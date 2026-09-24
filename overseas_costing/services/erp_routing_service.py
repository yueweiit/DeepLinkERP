"""中文用途：把物料行的项目归属解析为 ERP 业务主体和站点。

本模块只做纯规则解析，不读取数据库、不发起 ERP 请求，也不替用户选择冲突配置。
"""

from __future__ import annotations

import json
import unicodedata
from datetime import date
from decimal import Decimal, InvalidOperation


DEFAULT_SITE_CODE = "DEEPLINKERP"
LEGACY_PROJECT_IDENTITIES = {
    "yueweimx核心制造": "ywfabricacionmx核心制造",
}

# DeepLinkERP 计量单位词表快照（2026-09-24 线上实测导出，34 项）。
# 该站点把 ERPNext 默认单位换成了「中文：西语」命名，本地物料行只写冒号前的部分，
# 这里用于把本地自由文本补全成 ERP 实际存在的受控单位；运行时若读得到远端词表，
# 由 `erp_client._ensure_item` 再校验一次（见 `_load_remote_uom_names`）。
ERP_UOM_NAMES = (
    "g", "kg", "m²", "个：pieza", "付：par", "件：pieza", "份：porción", "包：paquete",
    "千克", "卷：rollo", "双：par", "台：unidad", "啤：vez", "块：pedazo", "套：conjunto",
    "对：par", "张：hoja", "把：puño", "支：ramo", "本：ejemplar", "条：barra", "根：raíz",
    "桶：barril", "片：hoja", "瓶：botella", "盒：caja", "码：yarda", "筒：tubo", "箱：caja",
    "米：metro", "罐：lata", "袋：bolsa", "辆：unidad", "颗：grano",
)

# 同一计量单位的其他写法（西语/英语/粘连写法）→ ERP 计量单位。
# 只收录有确定对应关系的写法；无法确定的（纯数字、人名等）一律不猜，交给下游阻断。
ERP_UOM_ALIASES = {
    "pcs": "个：pieza",
    "pc": "个：pieza",
    "pza": "个：pieza",
    "pzs": "个：pieza",
    "pieza": "个：pieza",
    "piezas": "个：pieza",
    "个pieza": "个：pieza",
    "set": "套：conjunto",
    "sets": "套：conjunto",
    "juego": "套：conjunto",
    "roll": "卷：rollo",
    "rolls": "卷：rollo",
    "rollo": "卷：rollo",
    "卷roll": "卷：rollo",
    "kgs": "kg",
    "kilogramo": "kg",
    "kilogramos": "kg",
    "m2": "m²",
    "par": "双：par",
    "pares": "双：par",
    "caja": "箱：caja",
    "cajas": "箱：caja",
    "bolsa": "袋：bolsa",
    "botella": "瓶：botella",
    "lata": "罐：lata",
    "metro": "米：metro",
    "metros": "米：metro",
    "hoja": "张：hoja",
    "hojas": "张：hoja",
}


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
            by_project.setdefault(project_route_identity(project), []).append(route)

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
                "warehouse": _route_warehouse(by_project.get(project_route_identity(project), []) if project else []),
                "route_revision": item.get("route_revision") or 1,
                "reason": "人工确认的 ERP 路由",
            }
            by_item[item_key] = {"stable_line_key": item_key, "project_collection": project, **result}
            continue
        candidates = by_project.get(project_route_identity(project), []) if project else []
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
                "warehouse": _text(route.get("warehouse")),
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


def build_site_payload_preview(
    result: dict,
    *,
    active_supplier_names: set[str] | None = None,
) -> dict:
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

        supplier_state = _supplier_push_state(item, active_supplier_names)
        if supplier_state["blocking"]:
            blocking.append(
                {
                    **supplier_state["blocking"],
                    "stable_line_key": item_key,
                }
            )
            continue

        warehouse = _text(item.get("erp_warehouse"))
        if not warehouse:
            blocking.append({"code": "ITEM_WAREHOUSE_REQUIRED", "stable_line_key": item_key})
            continue

        group_key = (
            site_code,
            subsidiary_code,
            warehouse,
            _text(item.get("supplier")),
            normalize_currency(item.get("purchase_currency")),
            resolve_item_uom(item),
        )
        group = groups.setdefault(
            group_key,
            {
                "site_code": site_code,
                "subsidiary_code": subsidiary_code,
                "warehouse": warehouse,
                "supplier": group_key[3],
                "purchase_currency": group_key[4],
                "erp_stock_uom": group_key[5],
                "warnings": [],
                "items": [],
                "total_cost_rmb": Decimal("0"),
                "allocated_fee_rmb": Decimal("0"),
            },
        )
        if supplier_state["warning"] and supplier_state["warning"] not in group["warnings"]:
            group["warnings"].append(supplier_state["warning"])
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


def build_erp_push_state(
    result: dict,
    site_configs: list[dict] | None = None,
    *,
    active_supplier_names: set[str] | None = None,
) -> dict:
    """计算分站点 ERP 推送门槛，不执行网络请求。"""

    preview = build_site_payload_preview(result, active_supplier_names=active_supplier_names)
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
    # Row-scoped blockers deliberately remove those rows from the executable
    # preview, so a lower preview total is expected. A mismatch without such a
    # blocker still indicates data loss and remains a global stop condition.
    if source_total and source_total != preview_total and not preview["blocking"]:
        blocking.append({"code": "SITE_TOTAL_MISMATCH", "source": _decimal_text(source_total), "preview": _decimal_text(preview_total)})

    return {"ready": not blocking, "blocking": blocking, "preview": preview}


def normalize_currency(value) -> str:
    text = _text(value).upper().replace("人民币", "CNY").replace("RMB", "CNY")
    text = text.replace("美元", "USD").replace("美金", "USD").replace("墨西哥比索", "MXN").replace("比索", "MXN")
    return text or "CNY"


def project_route_identity(value) -> str:
    """Match harmless spelling changes and named legacy departments without rewriting stored history."""

    normalized = unicodedata.normalize("NFKD", _text(value))
    identity = "".join(
        character.lower()
        for character in normalized
        if not unicodedata.combining(character) and character.isalnum()
    )
    return LEGACY_PROJECT_IDENTITIES.get(identity, identity)


def _uom_key(value) -> str:
    """单位比较键：忽略大小写、空白与全角冒号差异。"""

    return _text(value).replace(" ", "").replace("：", ":").lower()


def normalize_erp_uom(unit) -> str:
    """把本地自由文本单位翻译成 DeepLinkERP 计量单位表的写法。

    依次尝试「本身就是 ERP 单位 → 已知别名 → 补全中文冒号前缀」；
    都译不出时返回空串，由调用方决定阻断，绝不猜一个单位出来。
    """

    key = _uom_key(unit)
    if not key:
        return ""
    for name in ERP_UOM_NAMES:
        if _uom_key(name) == key:
            return name
    alias = ERP_UOM_ALIASES.get(key)
    if alias:
        alias_key = _uom_key(alias)
        for name in ERP_UOM_NAMES:
            if _uom_key(name) == alias_key:
                return name
    for name in ERP_UOM_NAMES:
        head, separator, _tail = name.partition("：")
        if separator and _uom_key(head) == key:
            return name
    return ""


def raw_item_uom(item: dict, fallback: str = "") -> str:
    """取本地行上的单位原文，不做 ERP 词表翻译。"""

    return _text(
        item.get("erp_stock_uom")
        or item.get("stock_uom")
        or item.get("purchase_uom")
        or item.get("shipped_uom")
        or item.get("unit")
        or fallback
    )


def resolve_item_uom(item: dict, fallback: str = "") -> str:
    """Resolve the real material UOM used for ERP grouping and document rows.

    取到本地写法后统一翻译成 ERP 计量单位；译不出时保留原样，
    让 ``erp_client._ensure_item`` 在新建物料前报出明确原因。
    """

    raw = raw_item_uom(item, fallback)
    if not raw:
        return ""
    return normalize_erp_uom(raw) or raw


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
    by_project: dict[str, list[dict]] = {}
    for route in routes:
        project = _text(route.get("project_collection"))
        if project and _route_is_active(route, effective_date):
            by_project.setdefault(project_route_identity(project), []).append(route)
    options = []
    conflicts = []
    for _identity, project_routes in sorted(by_project.items()):
        selected = min(
            project_routes,
            key=lambda route: (
                -_route_revision(route),
                _text(route.get("project_collection")).casefold(),
                _text(route.get("project_collection")),
                _text(route.get("ai_match_hint")),
            ),
        )
        project = _text(selected.get("project_collection"))
        targets = {_route_target(route) for route in project_routes}
        if len(targets) != 1:
            conflicts.append(project)
            continue
        company, site_code = next(iter(targets))
        if company:
            options.append(
                {
                    "project_collection": project,
                    "subsidiary_code": company,
                    "site_code": site_code,
                    "revision": _route_revision(selected),
                    "ai_match_hint": _text(selected.get("ai_match_hint")),
                }
            )
    return {"options": options, "conflicts": conflicts}


def project_candidate_names(item: dict) -> list[str]:
    """Read the importer-owned DingTalk project candidate structure once."""

    value = item.get("extra_json")
    if isinstance(value, dict):
        metadata = value
    else:
        try:
            metadata = json.loads(str(value or "{}"))
        except (TypeError, ValueError):
            metadata = {}
    if not isinstance(metadata, dict):
        return []
    names = []
    seen = set()
    for candidate in metadata.get("project_candidates") or []:
        name = _text(candidate.get("name") if isinstance(candidate, dict) else candidate)
        identity = project_route_identity(name)
        if name and identity not in seen:
            seen.add(identity)
            names.append(name)
    return names


def item_project_route_policy(item: dict, route_options: list[dict]) -> dict:
    """Intersect DingTalk-selected projects with active unambiguous routes."""

    candidates = project_candidate_names(item)
    candidate_identities = {project_route_identity(name) for name in candidates}
    allowed_routes = [
        {
            key: option.get(key)
            for key in (
                "project_collection",
                "subsidiary_code",
                "site_code",
                "revision",
                "ai_match_hint",
            )
        }
        for option in route_options or []
        if project_route_identity(option.get("project_collection")) in candidate_identities
    ]
    return {
        "approval_candidates": candidates,
        "allowed_projects": [route["project_collection"] for route in allowed_routes],
        "routes": allowed_routes,
    }


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


def _route_warehouse(routes: list[dict]) -> str:
    """只在候选路由给出同一个收货仓库时返回，避免猜测。"""

    warehouses = {_text(route.get("warehouse")) for route in routes if _text(route.get("warehouse"))}
    return next(iter(warehouses)) if len(warehouses) == 1 else ""


def _route_revision(route: dict) -> int:
    try:
        return max(1, int(route.get("revision") or 1))
    except (TypeError, ValueError):
        return 1


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


def _supplier_push_state(item: dict, active_supplier_names: set[str] | None) -> dict:
    """Apply new-template supplier rules while retaining the documented legacy fallback."""

    from overseas_costing.services.supplier_resolution_service import supplier_provenance_state

    state = supplier_provenance_state(item)
    item_key = _text(item.get("stable_line_key") or item.get("name") or item.get("row_no"))
    if state["requires_explicit_supplier"]:
        return {
            "warning": None,
            "blocking": {
                "code": "ITEM_SUPPLIER_REQUIRED",
                "raw_value": state["raw_value"],
                "match_status": state["match_status"],
                "message": f"物料行 {item_key}：供应商尚未匹配并确认。",
            },
        }
    if (
        state["supplier"]
        and active_supplier_names is not None
        and state["supplier"] not in active_supplier_names
    ):
        return {
            "warning": None,
            "blocking": {
                "code": "ITEM_SUPPLIER_INACTIVE",
                "supplier": state["supplier"],
                "message": f"物料行 {item_key}：供应商已失效或不在 ERP 有效供应商列表。",
            },
        }
    warning = None
    if state["legacy_default_allowed"]:
        warning = {"code": "LEGACY_DEFAULT_SUPPLIER", "message": state["warning"]}
    return {"warning": warning, "blocking": None}


def _serialise_group(group: dict) -> dict:
    return {
        "site_code": group["site_code"],
        "subsidiary_code": group["subsidiary_code"],
        "warehouse": group["warehouse"],
        "supplier": group["supplier"],
        "purchase_currency": group["purchase_currency"],
        "erp_stock_uom": group["erp_stock_uom"],
        "warnings": list(group.get("warnings") or []),
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
