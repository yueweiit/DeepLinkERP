"""中文用途：将 ERP 同步预览保存为本地可审计的请求账本，不执行外部写入。"""

from __future__ import annotations

import json
from datetime import datetime

from overseas_costing.services.erp_sync_service import classify_existing_request

try:
    import frappe
except ImportError:
    frappe = None


DOCTYPE = "Overseas Cost ERP Sync Request"
SUPERSEDEABLE_STATUSES = {"PENDING", "FAILED"}
EXECUTABLE_STATUSES = {"PENDING", "FAILED"}
RUNNING_STALE_SECONDS = 30 * 60


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


def execute_saved_sync_requests(saved_requests: list[dict]) -> dict:
    """执行本次保存/复用的可重试请求；成功组不会重复发送。"""

    if frappe is None:
        raise RuntimeError("Frappe 运行环境不可用，无法执行 ERP 同步请求。")
    names = [_text(row.get("name")) for row in saved_requests if _text(row.get("name"))]
    now_text = _now_text()
    results = []
    for name in names:
        claim = _claim_sync_request(name, now_text)
        if claim.get("action") != "CLAIM":
            results.append(claim)
            continue
        document = frappe.get_doc(DOCTYPE, name)
        executed = execute_request_documents(
            [document],
            push_payload=_push_payload,
            config_loader=_load_site_config,
            now_text=now_text,
            already_claimed=True,
        )
        results.extend(executed["results"])
    frappe.db.commit()
    return _summarize_results(results)


def execute_request_documents(
    documents: list,
    *,
    push_payload,
    config_loader,
    now_text: str,
    before_push=None,
    already_claimed: bool = False,
) -> dict:
    """可测试的逐组执行器：只执行 PENDING/FAILED，并保留部分成功结果。"""

    results = []
    for doc in documents:
        current_status = _text(_get(doc, "status")).upper()
        expected_statuses = {"RUNNING"} if already_claimed else EXECUTABLE_STATUSES
        if current_status not in expected_statuses:
            results.append({"name": _text(_get(doc, "name")), "status": current_status, "action": "SKIP"})
            continue

        attempt_count = int(_get(doc, "attempt_count") or 0)
        if not already_claimed:
            attempt_count += 1
            _set_values(doc, {"status": "RUNNING", "attempt_count": attempt_count, "started_at": now_text})
            if before_push:
                before_push()
        payload = _load_payload(_get(doc, "safe_payload_json"))
        try:
            response = push_payload(payload, config_loader(_text(_get(doc, "site_code")))) or {}
            status = "SUCCESS" if response.get("ok") else "FAILED"
            message = _text(response.get("message"))
            _set_values(
                doc,
                {
                    "status": status,
                    "safe_response_json": json.dumps(response, ensure_ascii=False, sort_keys=True, default=str),
                    "error_code": "" if status == "SUCCESS" else _text(response.get("error_code") or response.get("http_status")),
                    "error_message": "" if status == "SUCCESS" else (message or "ERP 返回失败。"),
                    "finished_at": now_text,
                },
            )
            results.append(
                {
                    "name": _text(_get(doc, "name")),
                    "status": status,
                    "attempt_count": attempt_count,
                    "erp_target_doc": _text(response.get("erp_target_doc")),
                    "message": message,
                }
            )
        except Exception as exc:  # 远端是否已接收无法确定，禁止自动重试
            _set_values(
                doc,
                {
                    "status": "UNCERTAIN",
                    "error_code": exc.__class__.__name__,
                    "error_message": _text(exc),
                    "finished_at": now_text,
                },
            )
            results.append({"name": _text(_get(doc, "name")), "status": "UNCERTAIN", "attempt_count": attempt_count, "message": _text(exc)})

    return _summarize_results(results)


def _summarize_results(results: list[dict]) -> dict:
    return {
        "ok": all(row["status"] in {"SUCCESS", "SUPERSEDED"} for row in results),
        "results": results,
        "success_count": sum(row["status"] == "SUCCESS" and row.get("action") != "SKIP" for row in results),
        "failed_count": sum(row["status"] == "FAILED" and row.get("action") != "SKIP" for row in results),
        "uncertain_count": sum(row["status"] == "UNCERTAIN" and row.get("action") != "SKIP" for row in results),
        "skipped_count": sum(row.get("action") == "SKIP" for row in results),
    }


def _claim_sync_request(name: str, now_text: str) -> dict:
    """Atomically claim one request before any remote write.

    The row lock prevents two workers from sending the same group. A stale
    RUNNING row is moved to UNCERTAIN for manual reconciliation and is never
    automatically resent because the prior remote outcome is unknowable.
    """

    rows = frappe.db.sql(
        f"""
        SELECT name, status, attempt_count, site_code, safe_payload_json, started_at
        FROM `tab{DOCTYPE}`
        WHERE name = %s
        FOR UPDATE
        """,
        (name,),
        as_dict=True,
    )
    if not rows:
        frappe.db.commit()
        return {"name": _text(name), "status": "MISSING", "action": "SKIP", "attempt_count": 0}

    row = dict(rows[0])
    status = _text(row.get("status")).upper()
    attempt_count = int(row.get("attempt_count") or 0)
    if status == "RUNNING" and _running_is_stale(row.get("started_at"), now_text):
        _set_db_values(
            name,
            {
                "status": "UNCERTAIN",
                "error_code": "STALE_RUNNING",
                "error_message": "ERP 请求执行超时，远端结果未知，请人工核对后处理。",
                "finished_at": now_text,
            },
        )
        frappe.db.commit()
        return {"name": _text(name), "status": "UNCERTAIN", "action": "STALE", "attempt_count": attempt_count}

    if status not in EXECUTABLE_STATUSES:
        frappe.db.commit()
        return {"name": _text(name), "status": status, "action": "SKIP", "attempt_count": attempt_count}

    attempt_count += 1
    _set_db_values(
        name,
        {
            "status": "RUNNING",
            "attempt_count": attempt_count,
            "started_at": now_text,
            "finished_at": None,
            "error_code": "",
            "error_message": "",
        },
    )
    # Commit the claimed state before the irreversible remote request.
    frappe.db.commit()
    return {"name": _text(name), "status": "RUNNING", "action": "CLAIM", "attempt_count": attempt_count}


def _set_db_values(name: str, values: dict) -> None:
    for fieldname, value in values.items():
        frappe.db.set_value(DOCTYPE, name, fieldname, value, update_modified=False)


def _running_is_stale(started_at, now_text: str) -> bool:
    started_timestamp = _datetime_timestamp(started_at)
    now_timestamp = _datetime_timestamp(now_text)
    if started_timestamp is None:
        return True
    if now_timestamp is None:
        return False
    return now_timestamp - started_timestamp >= RUNNING_STALE_SECONDS


def _datetime_timestamp(value) -> float | None:
    if isinstance(value, datetime):
        return value.timestamp()
    text = _text(value)
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


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


def _load_site_config(site_code: str) -> dict:
    from overseas_costing.services import erp_client
    from overseas_costing.services.erp_routing_service import DEFAULT_SITE_CODE

    if site_code == DEFAULT_SITE_CODE:
        return erp_client.get_erp_push_config()
    from overseas_costing.services.erp_site_service import get_site_push_config

    return get_site_push_config(site_code)


def _push_payload(payload: dict, config: dict) -> dict:
    from overseas_costing.services.erp_client import push_overseas_cost_payload_with_config

    return push_overseas_cost_payload_with_config(payload, config)


def _load_payload(value) -> dict:
    if isinstance(value, dict):
        return dict(value)
    try:
        loaded = json.loads(value or "{}")
    except (TypeError, ValueError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _get(doc, fieldname: str):
    return doc.get(fieldname) if hasattr(doc, "get") else getattr(doc, fieldname, None)


def _set_values(doc, values: dict) -> None:
    if isinstance(doc, dict):
        doc.update(values)
        return
    for fieldname, value in values.items():
        doc.db_set(fieldname, value, update_modified=False)


def _now_text() -> str:
    if frappe is not None and getattr(frappe, "utils", None):
        return str(frappe.utils.now_datetime())
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _text(value) -> str:
    return str(value or "").strip()


def _limit(value) -> int:
    try:
        return max(1, min(int(value), 200))
    except (TypeError, ValueError):
        return 100
