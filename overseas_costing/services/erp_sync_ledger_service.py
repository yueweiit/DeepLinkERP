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
LINK_DOCTYPE = "Overseas Cost ERP Document Link"
SUPERSEDEABLE_STATUSES = {"PENDING", "FAILED"}
EXECUTABLE_STATUSES = {"PENDING", "FAILED"}
# 只有「远端结果未知」和「已确认失败」才需要回读核对；其余状态重读远端没有意义。
RECONCILABLE_STATUSES = {"FAILED", "UNCERTAIN"}
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


def find_batch_request_name(batch: str, request_id: str) -> str:
    """在指定批次内按请求幂等键定位账本请求，返回文档名；找不到返回空串。

    页面只持有 request_id，定位必须同时限定批次，否则会操作到其他批次的请求。
    """

    if frappe is None:
        raise RuntimeError("Frappe 运行环境不可用，无法读取同步请求账本。")

    request_id = _text(request_id)
    if not request_id:
        return ""
    return _text(
        frappe.db.get_value(DOCTYPE, {"batch": _text(batch), "request_id": request_id}, "name")
    )


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
            record_links=_record_success_links,
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
    record_links=None,
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
                    "error_code": "" if status == "SUCCESS" else _text(
                        response.get("error_code") or response.get("http_status") or "ERP_PUSH_FAILED"
                    ),
                    "error_message": "" if status == "SUCCESS" else (message or "ERP 返回失败。"),
                    "finished_at": now_text,
                },
            )
            row = {
                "name": _text(_get(doc, "name")),
                "status": status,
                "attempt_count": attempt_count,
                "erp_target_doc": _text(response.get("erp_target_doc")),
                "message": message,
            }
            if status == "SUCCESS" and record_links:
                # 远端已经成功，落关联失败只是本地善后没做完：如实记录，但绝不把已成功的
                # 推送改判成失败——重发会在远端重复创建采购单。
                try:
                    row["linked_row_count"] = int(record_links(doc, payload, response) or 0)
                except Exception as link_error:  # noqa: BLE001
                    row["link_error"] = _text(link_error)
                    _set_values(
                        doc,
                        {"error_message": f"推送已成功，但保存远端单据关联失败：{_text(link_error)}"},
                    )
            results.append(row)
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


def reconcile_sync_request(name: str, *, inspector=None, now_text: str | None = None) -> dict:
    """按稳定业务键只读回读远端，把「结果未知」的请求落到确定状态。

    远端超时或异常时无法判断采购单到底有没有建出来，这类请求停在 ``UNCERTAIN``
    永远不会再被执行。核对只做查询和状态判定，不发送任何写入请求；只有确认远端
    确实没有单据（或只有未提交的草稿）才会回到可重试的 ``FAILED``。
    """

    if frappe is None:
        raise RuntimeError("Frappe 运行环境不可用，无法核对 ERP 同步请求。")
    from overseas_costing.services.erp_sync_service import can_transition

    request_name = _text(name)
    now_text = now_text or _now_text()
    row = _locked_request_row(request_name)
    if not row:
        frappe.db.commit()
        return {"ok": False, "action": "MISSING", "name": request_name, "message": f"找不到同步请求 {request_name}。"}

    status = _text(row.get("status")).upper()
    if status not in RECONCILABLE_STATUSES:
        frappe.db.commit()
        return {
            "ok": False,
            "action": "SKIP",
            "name": request_name,
            "status": status,
            "message": f"当前状态 {status or '未知'} 不需要核对。",
        }

    payload = _load_payload(row.get("safe_payload_json"))
    inspect = inspector or _inspect_remote_purchase
    try:
        inspection = inspect(payload, _load_site_config(_text(row.get("site_code")))) or {}
    except Exception as exc:  # noqa: BLE001
        # 查不通远端时保持原状态：把「查不到」当成「没建出来」会重复创建采购单。
        frappe.db.commit()
        return {
            "ok": False,
            "action": "UNKNOWN",
            "name": request_name,
            "status": status,
            "message": f"远端核对失败，状态保持不变：{_text(exc)}",
        }

    target, error_code, message = _reconcile_target(inspection)
    # 核对结论与当前状态相同时是幂等重核（例如 FAILED 再次确认远端仍无单据），
    # 只刷新核对结论，不需要状态机批准。
    if target != status and not can_transition(status, target):
        frappe.db.commit()
        return {
            "ok": False,
            "action": "SKIP",
            "name": request_name,
            "status": status,
            "message": f"{status} 不能转为 {target}。",
        }

    _set_db_values(
        request_name,
        {
            "status": target,
            "error_code": error_code,
            "error_message": "" if target == "SUCCESS" else message,
            "finished_at": now_text,
        },
    )
    links = 0
    if target == "SUCCESS":
        links = _save_document_links(
            batch=_text(row.get("batch")),
            site_code=_text(row.get("site_code")),
            business_key=_text(row.get("business_key")),
            cost_result_hash=_text(row.get("cost_result_hash")),
            payload_hash=_text(row.get("payload_hash")),
            remote_document=_text(inspection.get("name")),
            remote_docstatus=inspection.get("docstatus"),
            payload=payload,
            lines=inspection.get("lines") or {},
            now_text=now_text,
        )
    frappe.db.commit()
    return {
        "ok": True,
        "action": target,
        "name": request_name,
        "request_id": _text(row.get("request_id")),
        "status": target,
        "previous_status": status,
        "erp_target_doc": _text(inspection.get("name")),
        "linked_row_count": links,
        "message": message,
    }


def retry_sync_request(name: str, *, inspector=None, now_text: str | None = None) -> dict:
    """先核对再重试：只有确认远端还没有单据时才重发，避免重复创建采购单。"""

    reconciled = reconcile_sync_request(name, inspector=inspector, now_text=now_text)
    if reconciled.get("status") != "FAILED":
        return {**reconciled, "executed": False}
    execution = execute_saved_sync_requests([{"name": _text(name)}])
    return {**reconciled, "executed": True, "execution": execution, "status": _retried_status(execution)}


def _retried_status(execution: dict) -> str:
    if execution.get("success_count"):
        return "SUCCESS"
    if execution.get("uncertain_count"):
        return "UNCERTAIN"
    return "FAILED"


def _summarize_results(results: list[dict]) -> dict:
    return {
        "ok": all(row["status"] in {"SUCCESS", "SUPERSEDED"} for row in results),
        "results": results,
        "success_count": sum(row["status"] == "SUCCESS" and row.get("action") != "SKIP" for row in results),
        "failed_count": sum(row["status"] == "FAILED" and row.get("action") != "SKIP" for row in results),
        "uncertain_count": sum(row["status"] == "UNCERTAIN" and row.get("action") != "SKIP" for row in results),
        "skipped_count": sum(row.get("action") == "SKIP" for row in results),
    }


def _locked_request_row(name: str) -> dict:
    """在行锁内读取一条请求；调用方负责 commit 以释放锁。"""

    rows = frappe.db.sql(
        f"""
        SELECT name, request_id, status, attempt_count, batch, site_code, business_key,
               cost_result_hash, payload_hash, safe_payload_json, started_at
        FROM `tab{DOCTYPE}`
        WHERE name = %s
        FOR UPDATE
        """,
        (name,),
        as_dict=True,
    )
    return dict(rows[0]) if rows else {}


def _inspect_remote_purchase(payload: dict, config: dict) -> dict:
    from overseas_costing.services import erp_client

    return erp_client.inspect_remote_purchase(payload, config)


def _reconcile_target(inspection: dict) -> tuple[str, str, str]:
    """把远端回读结果翻译成（目标状态、错误编码、给用户的说明）。"""

    if inspection.get("ambiguous"):
        return (
            "MANUAL_REQUIRED",
            "AMBIGUOUS_REMOTE_BUSINESS_KEY",
            "稳定业务键在远端命中多张采购单，请人工核对后处理。",
        )
    if inspection.get("found"):
        remote_document = _text(inspection.get("name"))
        if inspection.get("docstatus") == 1:
            return "SUCCESS", "", f"远端采购单 {remote_document} 已提交，上次推送实际已成功。"
        return (
            "FAILED",
            "REMOTE_DOCUMENT_NOT_SUBMITTED",
            f"远端采购单 {remote_document} 尚未提交，可重试补齐提交。",
        )
    return "FAILED", "REMOTE_DOCUMENT_ABSENT", "远端没有对应采购单，可安全重试。"


def _record_success_links(doc, payload: dict, response: dict) -> int:
    """推送成功后保存远端单据与行级关联，供追溯和后续成本更新使用。

    远端单号直接取本次推送的响应，不再按业务键重查一次，省掉一次跨网往返。
    """

    from overseas_costing.services import erp_client

    business_key = _text(payload.get("business_key"))
    remote_document = _text(response.get("erp_target_doc"))
    if not business_key or not remote_document:
        return 0
    state = erp_client.read_remote_purchase_state(
        remote_document, _load_site_config(_text(_get(doc, "site_code")))
    )
    return _save_document_links(
        batch=_text(_get(doc, "batch")),
        site_code=_text(_get(doc, "site_code")),
        business_key=business_key,
        cost_result_hash=_text(_get(doc, "cost_result_hash")),
        payload_hash=_text(_get(doc, "payload_hash")),
        remote_document=remote_document,
        remote_docstatus=state.get("docstatus"),
        payload=payload,
        lines=state.get("lines") or {},
    )


def _save_document_links(
    *,
    batch: str,
    site_code: str,
    business_key: str,
    cost_result_hash: str,
    payload_hash: str,
    remote_document: str,
    remote_docstatus,
    payload: dict,
    lines: dict,
    now_text: str | None = None,
) -> int:
    """按物料行保存远端单据关联；同一业务键与行键重复写时原地更新。"""

    if not business_key or not remote_document:
        return 0
    verified_at = now_text or _now_text()
    docstatus = remote_docstatus if isinstance(remote_docstatus, int) else 0
    saved = 0
    for item in payload.get("items") or []:
        if not isinstance(item, dict):
            continue
        line_key = _text(item.get("stable_line_key"))
        if not line_key:
            continue
        remote_row = _text(lines.get(line_key))
        values = {
            "batch": batch,
            "stable_line_key": line_key,
            "site_code": site_code,
            "business_key": business_key,
            "remote_doctype": "Purchase Order",
            "remote_document": remote_document,
            "remote_row": remote_row,
            "remote_docstatus": docstatus,
            # 远端单据里找不到对应行时不能谎称已关联，交人工确认。
            "status": "ACTIVE" if remote_row else "MANUAL_REQUIRED",
            "last_cost_result_hash": cost_result_hash,
            "last_payload_hash": payload_hash,
            "verified_at": verified_at,
        }
        existing = frappe.db.get_value(
            LINK_DOCTYPE, {"business_key": business_key, "stable_line_key": line_key}, "name"
        )
        if existing:
            for fieldname, value in values.items():
                frappe.db.set_value(LINK_DOCTYPE, existing, fieldname, value, update_modified=True)
        else:
            frappe.get_doc({"doctype": LINK_DOCTYPE, **values}).insert(ignore_permissions=True)
        saved += 1
    return saved


def _claim_sync_request(name: str, now_text: str) -> dict:
    """Atomically claim one request before any remote write.

    The row lock prevents two workers from sending the same group. A stale
    RUNNING row is moved to UNCERTAIN for manual reconciliation and is never
    automatically resent because the prior remote outcome is unknowable.
    """

    row = _locked_request_row(name)
    if not row:
        frappe.db.commit()
        return {"name": _text(name), "status": "MISSING", "action": "SKIP", "attempt_count": 0}

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
