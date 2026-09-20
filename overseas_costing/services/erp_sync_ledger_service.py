"""中文用途：将 ERP 同步预览保存为本地可审计的请求账本，不执行外部写入。"""

from __future__ import annotations

import json

from overseas_costing.services.erp_sync_service import classify_existing_request

try:
    import frappe
except ImportError:
    frappe = None


DOCTYPE = "Overseas Cost ERP Sync Request"
SUPERSEDEABLE_STATUSES = {"PENDING", "FAILED"}


def save_sync_request_specs(specs: dict, *, version: str = "") -> dict:
    """保存已通过路由校验的请求草稿；重复请求复用，绝不触发 ERP 接口。"""

    if not specs.get("ready"):
        return {"ok": False, "blocking": list(specs.get("blocking") or []), "requests": []}
    if frappe is None:
        raise RuntimeError("Frappe 运行环境不可用，无法保存同步请求账本。")

    saved = []
    for candidate in specs.get("requests") or []:
        existing = _latest_request(candidate.get("business_key"))
        action = classify_existing_request(existing, candidate)
        if action == "REUSE":
            saved.append({"name": existing["name"], "request_id": existing["request_id"], "action": "REUSE"})
            continue
        if action == "SUPERSEDE" and _text(existing.get("status")).upper() in SUPERSEDEABLE_STATUSES:
            frappe.db.set_value(DOCTYPE, existing["name"], "status", "SUPERSEDED", update_modified=True)

        values = _document_values(candidate, version=version)
        try:
            doc = frappe.get_doc({"doctype": DOCTYPE, **values}).insert(ignore_permissions=True)
        except frappe.DuplicateEntryError:
            duplicate = _request_by_id(candidate.get("request_id"))
            if not duplicate:
                raise
            saved.append({"name": duplicate["name"], "request_id": duplicate["request_id"], "action": "REUSE"})
            continue
        saved.append({"name": doc.name, "request_id": candidate["request_id"], "action": "CREATE"})

    return {"ok": True, "blocking": [], "requests": saved}


def list_sync_requests(batch: str, *, version: str = "", limit: int = 100) -> dict:
    """返回某批次的本地同步请求账本，不读取或调用目标 ERP。"""

    if frappe is None:
        raise RuntimeError("Frappe 运行环境不可用，无法读取同步请求账本。")

    filters = {"batch": _text(batch)}
    if _text(version):
        filters["version"] = _text(version)
    rows = frappe.get_all(
        DOCTYPE,
        filters=filters,
        fields=[
            "name", "request_id", "operation", "batch", "version", "site_code", "business_key",
            "cost_result_hash", "payload_hash", "status", "attempt_count", "error_code",
            "error_message", "creation", "modified",
        ],
        order_by="modified desc, name desc",
        limit_page_length=_limit(limit),
    )
    return {"ok": True, "items": [dict(row) for row in rows], "total": len(rows)}


def _latest_request(business_key: str) -> dict | None:
    rows = frappe.get_all(
        DOCTYPE,
        filters={"business_key": _text(business_key)},
        fields=["name", "request_id", "business_key", "payload_hash", "status"],
        order_by="modified desc, name desc",
        limit_page_length=1,
    )
    return dict(rows[0]) if rows else None


def _request_by_id(request_id: str) -> dict | None:
    rows = frappe.get_all(
        DOCTYPE,
        filters={"request_id": _text(request_id)},
        fields=["name", "request_id"],
        limit_page_length=1,
    )
    return dict(rows[0]) if rows else None


def _document_values(candidate: dict, *, version: str) -> dict:
    return {
        "request_id": _text(candidate.get("request_id")),
        "operation": _text(candidate.get("operation")) or "CREATE",
        "batch": _text(candidate.get("batch")),
        "version": _text(version),
        "cost_result_hash": _text(candidate.get("cost_result_hash")),
        "site_code": _text(candidate.get("site_code")),
        "business_key": _text(candidate.get("business_key")),
        "payload_hash": _text(candidate.get("payload_hash")),
        "status": "PENDING",
        "safe_payload_json": json.dumps(candidate.get("payload") or {}, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str),
    }


def _text(value) -> str:
    return str(value or "").strip()


def _limit(value) -> int:
    try:
        return max(1, min(int(value), 200))
    except (TypeError, ValueError):
        return 100
