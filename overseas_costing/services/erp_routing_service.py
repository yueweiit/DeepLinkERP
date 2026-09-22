"""中文用途：把物料行的项目归属解析为 ERP 业务主体和站点。

本模块只做纯规则解析，不读取数据库、不发起 ERP 请求，也不替用户选择冲突配置。
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation


DEFAULT_SITE_CODE = "DEEPLINKERP"


def resolve_item_routes(
    items: list[dict],
    routes: list[dict],
    *,
    as_of: date | None = None,
) -> dict:
    """解析每个物料行的 ERP 路由。

    同一项目存在多个有效且目标不同的路由时返回 ``CONFLICT``，不按列表顺序选第一条。
    """

    effective_date = as_of or date.today()
    active_routes = [route for route in routes if _route_is_active(route, effective_date)]
    by_project: dict[str, list[dict]] = {}
    for route in active_routes:
        project = _text(route.get("project_collection"))
        if project:
            by_project.setdefault(project, []).append(route)

    by_item: dict[str, dict] = {}
    blocking_reasons: list[str] = []
    for index, item in enumerate(items, start=1):
        item_key = _text(item.get("stable_line_key") or item.get("name") or item.get("row_no") or index)
        project = _text(item.get("project_collection"))
        if _text(item.get("route_status")) == "OVERRIDDEN":
            result = {
                "status": "OVERRIDDEN",
                "subsidiary_code": _text(item.get("subsidiary_code")),
                "site_code": _text(item.get("erp_site_code")) or DEFAULT_SITE_CODE,
                "route_revision": item.get("route_revision") or 1,
                "reason": "人工确认的 ERP 路由",
            }
            by_item[item_key] = {"stable_line_key": item_key, "project_collection": project, **result}
            continue
        candidates = by_project.get(project, []) if project else []
        targets = {_route_target(route) for route in candidates}

        if not project:
            result = {"status": "UNRESOLVED", "reason": "缺少项目归属"}
        elif not candidates:
            result = {"status": "UNRESOLVED", "reason": f"项目归属“{project}”没有有效 ERP 路由"}
        elif len(targets) > 1:
            result = {"status": "CONFLICT", "reason": f"项目归属“{project}”存在多个有效 ERP 路由"}
        else:
            route = candidates[0]
            subsidiary_code, site_code = _route_target(route)
            result = {
                "status": "RESOLVED",
                "subsidiary_code": subsidiary_code,
                "site_code": site_code,
                "route_revision": route.get("revision") or 1,
            }

        by_item[item_key] = {"stable_line_key": item_key, "project_collection": project, **result}
        if result["status"] != "RESOLVED":
            blocking_reasons.append(f"物料行 {item_key}：{result['reason']}。")

    return {
        "ok": not blocking_reasons,
        "ready": not blocking_reasons,
        "by_item": by_item,
        "blocking_reasons": blocking_reasons,
        "resolved_count": sum(row["status"] == "RESOLVED" for row in by_item.values()),
        "unresolved_count": sum(row["status"] != "RESOLVED" for row in by_item.values()),
    }


def build_site_payload_preview(result: dict) -> dict:
    """按 ERP 站点和目标单据约束生成只读报文预览。

    每行的分摊金额是唯一费用来源；本函数不重新分摊，也不把批次总额复制到站点。
    """

    groups: dict[tuple[str, str, str, str, str], dict] = {}
    blocking: list[dict] = []
    for index, item in enumerate(result.get("items") or [], start=1):
        item_key = _text(item.get("stable_line_key") or item.get("name") or item.get("row_no") or index)
        status = _text(item.get("route_status")).upper()
        site_code = _text(item.get("erp_site_code"))
        subsidiary_code = _text(item.get("subsidiary_code"))
        if status not in {"RESOLVED", "OVERRIDDEN"} or not site_code or not subsidiary_code:
            blocking.append({"code": "ITEM_ROUTE_REQUIRED", "stable_line_key": item_key})
            continue

        group_key = (
            site_code,
            subsidiary_code,
            _text(item.get("supplier")),
            normalize_currency(item.get("purchase_currency")),
            resolve_item_uom(item),
        )
        group = groups.setdefault(
            group_key,
            {
                "site_code": site_code,
                "subsidiary_code": subsidiary_code,
                "supplier": group_key[2],
                "purchase_currency": group_key[3],
                "erp_stock_uom": group_key[4],
                "items": [],
                "total_cost_rmb": Decimal("0"),
                "allocated_fee_rmb": Decimal("0"),
            },
        )
        group["items"].append(item)
        group["total_cost_rmb"] += _decimal(item.get("total_cost_rmb"))
        group["allocated_fee_rmb"] += _decimal(item.get("allocated_fee_rmb"))

    site_map: dict[str, dict] = {}
    for group in groups.values():
        site = site_map.setdefault(
            group["site_code"],
            {"site_code": group["site_code"], "groups": [], "items": [], "total_cost_rmb": Decimal("0"), "allocated_fee_rmb": Decimal("0")},
        )
        site["groups"].append(_serialise_group(group))
        site["items"].extend(group["items"])
        site["total_cost_rmb"] += group["total_cost_rmb"]
        site["allocated_fee_rmb"] += group["allocated_fee_rmb"]

    sites = [_serialise_site(site) for site in site_map.values()]
    return {
        "ready": not blocking,
        "blocking": blocking,
        "sites": sites,
        "source_total_cost_rmb": _decimal_text(result.get("total_cost_rmb")),
        "preview_total_cost_rmb": _decimal_text(sum((_decimal(site["total_cost_rmb"]) for site in sites), Decimal("0"))),
        "source_fee_total_rmb": _decimal_text(result.get("fee_total_rmb")),
        "preview_allocated_fee_rmb": _decimal_text(sum((_decimal(site["allocated_fee_rmb"]) for site in sites), Decimal("0"))),
    }


def build_erp_push_state(result: dict, site_configs: list[dict] | None = None) -> dict:
    """计算分站点 ERP 推送门槛，不执行网络请求。"""

    preview = build_site_payload_preview(result)
    blocking = list(preview["blocking"])
    status = _text(result.get("status") or result.get("confirm_status")).upper()
    if status != "CONFIRMED":
        blocking.append({"code": "CALCULATION_CONFIRMATION_REQUIRED", "message": "成本结果尚未人工确认"})

    configured_sites = { _text(row.get("site_code")): row for row in (site_configs or []) if row.get("enabled", 1) not in (0, False, "0") }
    if site_configs is not None:
        for site in preview["sites"]:
            config = configured_sites.get(site["site_code"])
            if site["site_code"] != DEFAULT_SITE_CODE and not config:
                blocking.append({"code": "ERP_SITE_CONFIG_REQUIRED", "site_code": site["site_code"]})

    source_total = _decimal(preview["source_total_cost_rmb"])
    preview_total = _decimal(preview["preview_total_cost_rmb"])
    if source_total and source_total != preview_total:
        blocking.append({"code": "SITE_TOTAL_MISMATCH", "source": _decimal_text(source_total), "preview": _decimal_text(preview_total)})

    return {"ready": not blocking, "blocking": blocking, "preview": preview}


def normalize_currency(value) -> str:
    text = _text(value).upper().replace("人民币", "CNY").replace("RMB", "CNY")
    text = text.replace("美元", "USD").replace("美金", "USD").replace("墨西哥比索", "MXN").replace("比索", "MXN")
    return text or "CNY"


def resolve_item_uom(item: dict, fallback: str = "") -> str:
    """Resolve the real material UOM used for ERP grouping and document rows."""

    return _text(
        item.get("erp_stock_uom")
        or item.get("stock_uom")
        or item.get("purchase_uom")
        or item.get("shipped_uom")
        or item.get("unit")
        or fallback
    )


def preview_bulk_route(items: list[dict], target_site: str, target_subsidiary: str | None = None) -> dict:
    """预览整柜统一归属会改变哪些已解析行，不直接写入物料。"""

    site = _text(target_site)
    subsidiary = _text(target_subsidiary)
    changed_item_keys = []
    for index, item in enumerate(items, start=1):
        item_key = _text(item.get("stable_line_key") or item.get("name") or item.get("row_no") or index)
        if _text(item.get("erp_site_code")) != site or (subsidiary and _text(item.get("subsidiary_code")) != subsidiary):
            changed_item_keys.append(item_key)

    return {
        "target_site": site,
        "target_subsidiary": subsidiary,
        "changed_item_keys": changed_item_keys,
        "requires_confirmation": bool(changed_item_keys),
    }


def list_unambiguous_project_routes(routes: list[dict], *, as_of: date | None = None) -> dict:
    """Return active projects that resolve to exactly one Company/site target."""

    effective_date = as_of or date.today()
    by_project: dict[str, set[tuple[str, str]]] = {}
    for route in routes:
        project = _text(route.get("project_collection"))
        if project and _route_is_active(route, effective_date):
            by_project.setdefault(project, set()).add(_route_target(route))
    options = []
    conflicts = []
    for project, targets in sorted(by_project.items()):
        if len(targets) != 1:
            conflicts.append(project)
            continue
        company, site_code = next(iter(targets))
        if company:
            options.append({"project_collection": project, "subsidiary_code": company, "site_code": site_code})
    return {"options": options, "conflicts": conflicts}


def _route_is_active(route: dict, as_of: date) -> bool:
    if route.get("enabled") in (0, False, "0"):
        return False
    valid_from = _parse_date(route.get("valid_from"))
    valid_to = _parse_date(route.get("valid_to"))
    return not (valid_from and as_of < valid_from or valid_to and as_of > valid_to)


def _route_target(route: dict) -> tuple[str, str]:
    return (
        _text(route.get("subsidiary_code")),
        _text(route.get("site_code") or route.get("erp_site")) or DEFAULT_SITE_CODE,
    )


def _parse_date(value) -> date | None:
    if isinstance(value, date):
        return value
    value = _text(value)
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def _text(value) -> str:
    return str(value or "").strip()


def _decimal(value) -> Decimal:
    try:
        return Decimal(str(value or "0")).quantize(Decimal("0.000001"))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal("0")


def _decimal_text(value) -> str:
    return format(_decimal(value).normalize(), "f")


def _serialise_group(group: dict) -> dict:
    return {
        "site_code": group["site_code"],
        "subsidiary_code": group["subsidiary_code"],
        "supplier": group["supplier"],
        "purchase_currency": group["purchase_currency"],
        "erp_stock_uom": group["erp_stock_uom"],
        "item_count": len(group["items"]),
        "items": group["items"],
        "total_cost_rmb": _decimal_text(group["total_cost_rmb"]),
        "allocated_fee_rmb": _decimal_text(group["allocated_fee_rmb"]),
    }


def _serialise_site(site: dict) -> dict:
    return {
        "site_code": site["site_code"],
        "groups": site["groups"],
        "items": site["items"],
        "item_count": len(site["items"]),
        "group_count": len(site["groups"]),
        "total_cost_rmb": _decimal_text(site["total_cost_rmb"]),
        "allocated_fee_rmb": _decimal_text(site["allocated_fee_rmb"]),
    }
