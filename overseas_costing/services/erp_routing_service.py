"""ERP 行级路由、整柜快捷归属与费用范围冻结规则。"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal, InvalidOperation


READY_ROUTE_STATES = frozenset({"RESOLVED", "OVERRIDDEN"})


def normalize_project(value) -> str:
    return " ".join(str(value or "").split()).casefold()


def _date(value) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _route_is_active(route: dict, as_of: date | str | None = None) -> bool:
    if not int(route.get("enabled", 1) or 0):
        return False
    day = _date(as_of) or date.today()
    valid_from = _date(route.get("valid_from"))
    valid_to = _date(route.get("valid_to"))
    return not ((valid_from and valid_from > day) or (valid_to and valid_to < day))


def active_routes_by_project(routes: list[dict], *, as_of: date | str | None = None) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for route in routes or []:
        if _route_is_active(route, as_of):
            grouped[normalize_project(route.get("project_collection"))].append(route)
    return grouped


def _route_revision(route: dict) -> str:
    explicit = str(route.get("route_revision") or route.get("revision") or "").strip()
    if explicit:
        return explicit
    canonical = json.dumps(
        {
            "project": normalize_project(route.get("project_collection")),
            "subsidiary": str(route.get("subsidiary_code") or ""),
            "site": str(route.get("site_code") or route.get("erp_site_code") or route.get("erp_site") or ""),
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _route_state(status: str, code: str = "", route: dict | None = None, item: dict | None = None) -> dict:
    route = route or {}
    item = item or {}
    return {
        "status": status,
        "code": code,
        "project_collection": item.get("project_collection") or route.get("project_collection") or "",
        "subsidiary_code": route.get("subsidiary_code") or "",
        "site_code": route.get("site_code") or route.get("erp_site_code") or route.get("erp_site") or "",
        "route_revision": _route_revision(route) if route else "",
    }


def resolve_item_routes(
    items: list[dict],
    routes: list[dict],
    *,
    as_of: date | str | None = None,
) -> dict:
    by_project = active_routes_by_project(routes, as_of=as_of)
    result = {}
    for item in items or []:
        item_key = str(item.get("stable_line_key") or item.get("name") or "").strip()
        if not item_key:
            continue
        if str(item.get("route_status") or "").upper() == "OVERRIDDEN":
            result[item_key] = _route_state("OVERRIDDEN", route=item, item=item)
            continue
        project = str(item.get("project_collection") or "").strip()
        matches = by_project.get(normalize_project(project), [])
        if not project:
            resolved = _route_state("UNRESOLVED", "PROJECT_REQUIRED", item=item)
        elif not matches:
            resolved = _route_state("UNRESOLVED", "ROUTE_NOT_CONFIGURED", item=item)
        elif len(matches) != 1:
            resolved = _route_state("CONFLICT", "MULTIPLE_ACTIVE_ROUTES", item=item)
        else:
            resolved = _route_state("RESOLVED", route=matches[0], item=item)
        result[item_key] = resolved
    return {
        "by_item": result,
        "ready": bool(result) and all(row["status"] in READY_ROUTE_STATES for row in result.values()),
        "blocking": [
            {"stable_line_key": key, **row}
            for key, row in result.items()
            if row["status"] not in READY_ROUTE_STATES
        ],
    }


def _preview_revision(payload: dict) -> str:
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def preview_bulk_route(items: list[dict], *, target_site: str, target_subsidiary: str = "") -> dict:
    site = str(target_site or "").strip()
    subsidiary = str(target_subsidiary or "").strip()
    if not site:
        raise ValueError("TARGET_SITE_REQUIRED")
    changed = []
    updates = {}
    overwritten = []
    unchanged = []
    for item in items or []:
        key = str(item.get("stable_line_key") or item.get("name") or "").strip()
        if not key:
            continue
        current_site = str(item.get("erp_site_code") or item.get("site_code") or "").strip()
        current_subsidiary = str(item.get("subsidiary_code") or "").strip()
        if current_site == site and (not subsidiary or current_subsidiary == subsidiary):
            unchanged.append(key)
            continue
        changed.append(key)
        if current_site and current_site != site:
            overwritten.append(key)
        updates[key] = {
            "subsidiary_code": subsidiary,
            "erp_site_code": site,
            "route_status": "OVERRIDDEN",
        }
    body = {
        "target_site": site,
        "target_subsidiary": subsidiary,
        "changed_item_keys": sorted(changed),
        "overwritten_item_keys": sorted(overwritten),
        "unchanged_item_keys": sorted(unchanged),
        "updates": {key: updates[key] for key in sorted(updates)},
    }
    return {
        **body,
        "requires_confirmation": bool(overwritten),
        "preview_revision": _preview_revision(body),
    }


def resolve_subsidiary_scope(*, subsidiary_code: str, item_routes: dict[str, dict]) -> dict:
    target = str(subsidiary_code or "").strip()
    keys = sorted(
        key
        for key, route in (item_routes or {}).items()
        if route.get("status") in READY_ROUTE_STATES
        and str(route.get("subsidiary_code") or "").strip() == target
    )
    revisions = [str((item_routes.get(key) or {}).get("route_revision") or "") for key in keys]
    return {
        "scope_type": "ITEMS",
        "scope_item_keys": keys,
        "scope_revision": _preview_revision({"subsidiary_code": target, "items": list(zip(keys, revisions))}),
        "ready": bool(keys),
    }


def _decimal(value) -> Decimal:
    if value in (None, ""):
        return Decimal("0")
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal("0")


def _money(value) -> str:
    return format(_decimal(value).quantize(Decimal("0.01")), "f")


def normalize_currency(value) -> str:
    currency = str(value or "CNY").strip().upper()
    return "CNY" if currency == "RMB" else currency


def _allocated_fee(row: dict) -> Decimal:
    if row.get("allocated_fee_rmb") not in (None, ""):
        return _decimal(row.get("allocated_fee_rmb"))
    return sum(
        (_decimal(row.get(fieldname)) for fieldname in ("freight_alloc_rmb", "clearance_alloc_rmb", "tax_alloc_rmb", "other_alloc_rmb")),
        Decimal("0"),
    )


def _group_identity(row: dict) -> tuple[str, str, str, str]:
    return (
        str(row.get("erp_site_code") or row.get("site_code") or "").strip(),
        str(row.get("supplier") or "").strip(),
        normalize_currency(row.get("purchase_currency")),
        str(row.get("erp_stock_uom") or "").strip(),
    )


def build_site_payload_preview(result: dict) -> dict:
    """只对已确认的逐行金额做分组，不在此处重新分摊费用。"""

    grouped: dict[tuple[str, str, str, str], list[dict]] = defaultdict(list)
    for row in result.get("items") or []:
        grouped[_group_identity(row)].append(dict(row))

    sites_by_code: dict[str, dict] = {}
    for key in sorted(grouped):
        site_code, supplier, currency, stock_uom = key
        rows = sorted(grouped[key], key=lambda row: str(row.get("stable_line_key") or ""))
        goods_value = sum((_decimal(row.get("goods_value")) for row in rows), Decimal("0"))
        allocated_fee = sum((_allocated_fee(row) for row in rows), Decimal("0"))
        total_cost = sum((_decimal(row.get("total_cost_rmb")) for row in rows), Decimal("0"))
        group_identity = {
            "site_code": site_code,
            "supplier": supplier,
            "currency": currency,
            "stock_uom": stock_uom,
            "stable_line_keys": [str(row.get("stable_line_key") or "") for row in rows],
        }
        group = {
            **group_identity,
            "group_key": _preview_revision(group_identity),
            "item_count": len(rows),
            "total_quantity": _money(sum((_decimal(row.get("effective_shipped_qty") or row.get("actual_shipped_qty") or row.get("quantity")) for row in rows), Decimal("0"))),
            "goods_value_rmb": _money(goods_value),
            "allocated_fee_rmb": _money(allocated_fee),
            "total_cost_rmb": _money(total_cost),
            "estimated_fee_keys": sorted({key for row in rows for key in (row.get("estimated_fee_keys") or [])}),
            "items": rows,
        }
        site = sites_by_code.setdefault(
            site_code,
            {
                "site_code": site_code,
                "subsidiary_codes": set(),
                "groups": [],
                "estimated_fee_keys": set(),
                "goods_value_rmb": Decimal("0"),
                "allocated_fee_rmb": Decimal("0"),
                "total_cost_rmb": Decimal("0"),
            },
        )
        site["groups"].append(group)
        site["subsidiary_codes"].update(str(row.get("subsidiary_code") or "") for row in rows if row.get("subsidiary_code"))
        site["estimated_fee_keys"].update(group["estimated_fee_keys"])
        site["goods_value_rmb"] += goods_value
        site["allocated_fee_rmb"] += allocated_fee
        site["total_cost_rmb"] += total_cost

    sites = []
    for site_code in sorted(sites_by_code):
        site = sites_by_code[site_code]
        sites.append(
            {
                "site_code": site_code,
                "subsidiary_codes": sorted(site["subsidiary_codes"]),
                "group_count": len(site["groups"]),
                "groups": site["groups"],
                "estimated_fee_keys": sorted(site["estimated_fee_keys"]),
                "goods_value_rmb": _money(site["goods_value_rmb"]),
                "allocated_fee_rmb": _money(site["allocated_fee_rmb"]),
                "total_cost_rmb": _money(site["total_cost_rmb"]),
            }
        )
    allocated_total = sum((_decimal(site["allocated_fee_rmb"]) for site in sites), Decimal("0"))
    cost_total = sum((_decimal(site["total_cost_rmb"]) for site in sites), Decimal("0"))
    expected_fee_total = _decimal(result.get("fee_total_rmb")) if result.get("fee_total_rmb") not in (None, "") else allocated_total
    expected_cost_total = sum((_decimal(row.get("total_cost_rmb")) for row in result.get("items") or []), Decimal("0"))
    return {
        "cost_result_hash": str(result.get("cost_result_hash") or ""),
        "sites": sites,
        "site_count": len(sites),
        "group_count": sum(site["group_count"] for site in sites),
        "conservation": {
            "fee_matches": allocated_total.quantize(Decimal("0.01")) == expected_fee_total.quantize(Decimal("0.01")),
            "cost_matches": cost_total.quantize(Decimal("0.01")) == expected_cost_total.quantize(Decimal("0.01")),
            "allocated_fee_rmb": _money(allocated_total),
            "total_cost_rmb": _money(cost_total),
        },
    }


def _site_config_map(value) -> dict[str, dict]:
    if isinstance(value, dict):
        return {str(key): dict(row or {}) for key, row in value.items()}
    return {str(row.get("site_code") or ""): dict(row) for row in (value or []) if row.get("site_code")}


def build_erp_push_state(result: dict) -> dict:
    blocking = []
    if result.get("invalid_business"):
        blocking.append({"code": "INVALID_BUSINESS_STATE", "message": result.get("invalid_business_reason") or "当前审批已失效。"})
    if str(result.get("status") or "").upper() != "CONFIRMED" or not str(result.get("cost_result_hash") or "").strip():
        blocking.append({"code": "COST_RESULT_NOT_CONFIRMED", "message": "成本结果未确认或已失效。"})

    config_by_site = _site_config_map(result.get("site_configs"))
    configured_sites = set(config_by_site)
    referenced_sites = set()
    for item in result.get("items") or []:
        key = str(item.get("stable_line_key") or item.get("name") or "")
        route_status = str(item.get("route_status") or "").upper()
        site_code = str(item.get("erp_site_code") or item.get("site_code") or "").strip()
        if route_status not in READY_ROUTE_STATES or not site_code:
            blocking.append({"code": "ITEM_ROUTE_REQUIRED", "stable_line_key": key, "message": "物料行缺少明确 ERP 路由。"})
            continue
        referenced_sites.add(site_code)
        if not str(item.get("erp_stock_uom") or "").strip():
            blocking.append({"code": "ERP_UOM_REQUIRED", "stable_line_key": key, "site_code": site_code, "message": "物料行缺少 ERP 库存单位。"})

    if config_by_site or result.get("site_configs") is not None:
        for site_code in sorted(referenced_sites):
            config = config_by_site.get(site_code)
            if not config:
                blocking.append({"code": "ERP_SITE_CONFIG_REQUIRED", "site_code": site_code, "message": "ERP 站点未配置。"})
            elif not int(config.get("enabled", 1) or 0) or str(config.get("capability_status") or "UNVERIFIED").upper() != "VERIFIED":
                blocking.append({"code": "ERP_SITE_UNVERIFIED", "site_code": site_code, "message": "ERP 站点未通过能力核验。"})

    blocking_todos = {
        "AMOUNT_REQUIRED": "FEE_AMOUNT_REQUIRED",
        "ALLOCATION_REQUIRED": "FEE_ALLOCATION_REQUIRED",
        "RECALCULATE_REQUIRED": "FEE_RECALCULATION_REQUIRED",
    }
    for fee in result.get("fee_statuses") or []:
        for todo in fee.get("todos") or []:
            if todo.get("code") in blocking_todos:
                blocking.append({
                    "code": blocking_todos[todo["code"]],
                    "fee_key": fee.get("fee_key") or "",
                    "message": todo.get("label") or "费用尚未满足 ERP 推送要求。",
                })
    preview = build_site_payload_preview(result) if result.get("items") else {"sites": [], "site_count": 0, "group_count": 0}
    return {
        "ready": not blocking and bool(result.get("items")),
        "blocking": blocking,
        "preview": preview,
        "referenced_sites": sorted(referenced_sites),
        "configured_sites": sorted(configured_sites),
    }
