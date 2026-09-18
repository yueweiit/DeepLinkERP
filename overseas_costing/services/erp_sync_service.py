"""中文用途：ERP 分站点同步请求的身份、哈希和状态规则。

本模块只生成同步计划和状态判断，不读数据库、不保存回执、不发起网络请求。
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable


ALLOWED_TRANSITIONS = {
    "PENDING": {"RUNNING", "SUPERSEDED"},
    "RUNNING": {"SUCCESS", "FAILED", "UNCERTAIN", "MANUAL_REQUIRED"},
    "FAILED": {"RUNNING", "SUPERSEDED"},
    "UNCERTAIN": {"SUCCESS", "FAILED", "MANUAL_REQUIRED"},
    "SUCCESS": set(),
    "MANUAL_REQUIRED": set(),
    "SUPERSEDED": set(),
}


def purchase_business_key(*, batch: str, site: str, group: str, version: str = "") -> str:
    """生成稳定的采购业务身份；成本版本故意不参与身份。"""

    identity = "\x1f".join((_text(batch), _text(site), _text(group)))
    return _sha256(identity)


def payload_hash(payload: dict) -> str:
    """对结构化报文做稳定哈希，不依赖字典插入顺序。"""

    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return _sha256(encoded)


def build_sync_request_specs(
    *,
    batch: str,
    cost_result_hash: str,
    preview: dict,
    operation: str = "CREATE",
    client_intent_id: str = "",
) -> dict:
    """从分站点预览生成待保存的同步请求草稿。"""

    if not preview.get("ready", True):
        return {"ready": False, "blocking": list(preview.get("blocking") or []), "requests": []}

    requests = []
    for site in preview.get("sites") or []:
        for group in site.get("groups") or []:
            line_keys = sorted(
                _text(row.get("stable_line_key") or row.get("name"))
                for row in group.get("items") or []
            )
            group_identity = "\x1f".join(
                (
                    _text(site.get("site_code")),
                    _text(group.get("supplier")),
                    _text(group.get("purchase_currency")),
                    _text(group.get("erp_stock_uom")),
                    *line_keys,
                )
            )
            business_key = purchase_business_key(batch=batch, site=site.get("site_code", ""), group=group_identity)
            request_id = build_request_id(
                operation=operation,
                site=site.get("site_code", ""),
                business_key=business_key,
                cost_result_hash=cost_result_hash,
                client_intent_id=client_intent_id,
            )
            request_payload = {
                "target_system": "DeepLinkERP",
                "operation": operation,
                "business_key": business_key,
                "batch": _text(batch),
                "cost_result_hash": _text(cost_result_hash),
                "site_code": _text(site.get("site_code")),
                "supplier": _text(group.get("supplier")),
                "purchase_currency": _text(group.get("purchase_currency")),
                "erp_stock_uom": _text(group.get("erp_stock_uom")),
                "total_cost_rmb": _text(group.get("total_cost_rmb")),
                "allocated_fee_rmb": _text(group.get("allocated_fee_rmb")),
                "items": group.get("items") or [],
            }
            requests.append(
                {
                    "request_id": request_id,
                    "operation": operation,
                    "batch": _text(batch),
                    "site_code": _text(site.get("site_code")),
                    "business_key": business_key,
                    "cost_result_hash": _text(cost_result_hash),
                    "payload_hash": payload_hash(request_payload),
                    "status": "PENDING",
                    "payload": request_payload,
                }
            )

    return {"ready": True, "blocking": [], "requests": requests}


def build_site_sync_plan(
    *,
    batch: dict,
    version: dict,
    items: list[dict],
    routes: list[dict],
    site_configs: list[dict],
    client_intent_id: str = "",
) -> dict:
    """按物料项目归属生成分站点同步草稿，只计算预览，不保存也不推送。"""

    from overseas_costing.services.erp_routing_service import build_erp_push_state, resolve_item_routes

    route_result = resolve_item_routes(items, routes)
    routed_items = []
    for index, item in enumerate(items, start=1):
        row = dict(item)
        stable_line_key = _text(row.get("stable_line_key") or row.get("name") or row.get("row_no") or index)
        route = route_result["by_item"].get(stable_line_key) or {}
        row["stable_line_key"] = stable_line_key
        row["route_status"] = route.get("status") or "UNRESOLVED"
        row["erp_site_code"] = route.get("site_code") or ""
        row["subsidiary_code"] = route.get("subsidiary_code") or ""
        row["route_revision"] = route.get("route_revision") or 0
        routed_items.append(row)

    result = {
        "status": batch.get("confirm_status") or batch.get("status") or "",
        "total_cost_rmb": _sum_decimal_text(row.get("total_cost_rmb") for row in routed_items),
        "fee_total_rmb": _sum_decimal_text(row.get("allocated_fee_rmb") for row in routed_items),
        "items": routed_items,
    }
    push_state = build_erp_push_state(result, site_configs)
    cost_result_hash = payload_hash(
        {
            "batch": _text(batch.get("name") or batch.get("batch_no")),
            "version": _text(version.get("name") or version.get("version_code")),
            "items": [
                {
                    "stable_line_key": row["stable_line_key"],
                    "route_status": row["route_status"],
                    "site_code": row["erp_site_code"],
                    "total_cost_rmb": row.get("total_cost_rmb"),
                    "allocated_fee_rmb": row.get("allocated_fee_rmb"),
                }
                for row in routed_items
            ],
        }
    )
    specs = build_sync_request_specs(
        batch=_text(batch.get("name") or batch.get("batch_no")),
        cost_result_hash=cost_result_hash,
        preview=push_state["preview"],
        client_intent_id=client_intent_id,
    )
    blocking = list(push_state["blocking"])
    return {
        "ok": not blocking,
        "ready": not blocking,
        "blocking": blocking,
        "route_result": route_result,
        "push_state": push_state,
        "cost_result_hash": cost_result_hash,
        "request_specs": specs,
    }


def build_request_id(
    *,
    operation: str,
    site: str,
    business_key: str,
    cost_result_hash: str,
    client_intent_id: str = "",
) -> str:
    identity = "\x1f".join(
        (_text(operation).upper(), _text(site), _text(business_key), _text(cost_result_hash), _text(client_intent_id))
    )
    return _sha256(identity)


def classify_existing_request(existing: dict | None, candidate: dict) -> str:
    """比较本地账本中的请求，返回 REUSE、SUPERSEDE 或 CREATE。"""

    if not existing:
        return "CREATE"
    if _text(existing.get("request_id")) == _text(candidate.get("request_id")):
        return "REUSE"
    if (
        _text(existing.get("business_key")) == _text(candidate.get("business_key"))
        and _text(existing.get("payload_hash")) == _text(candidate.get("payload_hash"))
    ):
        return "REUSE"
    return "SUPERSEDE"


def can_transition(current: str, target: str) -> bool:
    return _text(target).upper() in ALLOWED_TRANSITIONS.get(_text(current).upper(), set())


def is_stale_cost_result(current_hash: str, incoming_hash: str) -> bool:
    return bool(_text(current_hash) and _text(incoming_hash) and _text(current_hash) != _text(incoming_hash))


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _text(value) -> str:
    return str(value or "").strip()


def _sum_decimal_text(values: Iterable) -> str:
    from decimal import Decimal, InvalidOperation

    total = Decimal("0")
    for value in values:
        try:
            total += Decimal(str(value or "0"))
        except (InvalidOperation, TypeError, ValueError):
            continue
    return format(total.quantize(Decimal("0.000001")).normalize(), "f")
