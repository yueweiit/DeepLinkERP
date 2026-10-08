"""One local database boundary for explicit native procurement operations.

The Integration Request primary key is the lock and durable receipt. Nothing in
this module commits: Frappe commits the business documents and receipt together.
Redis is deliberately absent from this authority. External writes cannot join it.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from contextvars import ContextVar
from datetime import datetime, timezone

import frappe

SERVICE = "DeepLinkERP native procurement"
_active = ContextVar("purchase_operation", default=None)


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def identity(actor, request_id):
    return "DLP-PURCHASE-" + hashlib.sha256((actor + ":" + request_id).encode()).hexdigest()


def current():
    return _active.get()


def runtime_log(context, result, error=None):
    # Do not record exception text, payloads, remarks, accounts, or attachments.
    # This JSON file log survives a database rollback; it is not a business write.
    event = {key: context.get(key) for key in ("operation_id", "user", "documents", "amount", "currency", "quantity", "before", "after")}
    event.update(time=datetime.now(timezone.utc).isoformat(), elapsed_ms=round((time.monotonic() - context.get("started", time.monotonic())) * 1000),
        modules=context.get("modules", []), result=result, error=type(error).__name__ if error else None,
        error_code=error.args[0] if error and error.args and isinstance(error.args[0], int) else None,
        error_category="validation" if isinstance(error, frappe.ValidationError) else "permission" if isinstance(error, frappe.PermissionError) else "runtime" if error else None)
    logger = frappe.logger("purchase_operation", allow_site=True)
    (logger.error if error else logger.info)(encode(event))


def trace(context, module, action, *, source=None, target=None):
    started = time.monotonic()
    event = {"module": module, "source": source or context.get("documents", []),
        "target": target or context.get("documents", []), "result": "verified"}
    error = None
    try:
        return action()
    except Exception as caught:
        error = caught
        event.update(result="failed", error=type(caught).__name__,
            error_code=caught.args[0] if caught.args and isinstance(caught.args[0], int) else None)
        raise
    finally:
        event.update(elapsed_ms=round((time.monotonic() - started) * 1000),
            amount=context.get("amount"), currency=context.get("currency"), quantity=context.get("quantity"),
            before=context.get("before", {}), after=context.get("after", {}))
        context.setdefault("modules", []).append(event)
        logger = frappe.logger("purchase_operation", allow_site=True)
        (logger.error if error else logger.info)(encode({"operation_id": context["operation_id"],
            "user": context["user"], "time": datetime.now(timezone.utc).isoformat(), **event}))


def _existing(name):
    rows = frappe.db.get_values("Integration Request", {"name": name},
        ["name", "status", "data", "output"], as_dict=True, for_update=True)
    return rows[0] if rows else None


def _reserve(context):
    # System audit metadata has no native create permission, and must never use
    # IntegrationRequest.update_status(), which commits. db_insert is limited to
    # this audit record; all business documents retain normal controller ACLs.
    audit = frappe.get_doc({"doctype": "Integration Request", "name": context["operation_id"],
        "integration_request_service": SERVICE, "request_id": context["request_id"],
        "request_description": "Native procurement transaction", "is_remote_request": 0,
        "status": "Queued", "data": encode(context)})
    audit.db_insert()


def complete_audit(context, output):
    documents = output.get("documents") or [output.get("document", output)]
    receipts = []
    for document in documents:
        document = document.get("document", document)
        receipt = {"doctype": document.get("doctype", "Payment Entry"), "name": document.get("name"),
            "needs_review": bool(output.get("needs_review")), "permission": "read" if output.get("needs_review") else
                "submit" if document.get("docstatus") == 1 else "cancel" if document.get("docstatus") == 2 else "write"}
        receipts.append(receipt)
        identity = {key: receipt[key] for key in ("doctype", "name")}
        if identity not in context["documents"]:
            context["documents"].append(identity)
    document = documents[0].get("document", documents[0])
    context.update(amount=document.get("amount", document.get("grand_total")), currency=document.get("currency"),
        quantity=[{"key": row.get("key"), "qty": row.get("qty")} for row in document.get("items", [])])
    frappe.db.set_value("Integration Request", context["operation_id"], {
        "status": "Completed", "data": encode(context), "output": encode({"documents": receipts} if "documents" in output else receipts[0]),
        "reference_doctype": document.get("doctype", "Payment Entry"), "reference_docname": document.get("name")},
        update_modified=False)


def run(request_id, payload, operation, replay, *, digest=None, acknowledge_validation=False):
    """Run once, or re-read the acknowledged native documents under current ACLs."""
    if current() is not None:
        return operation()
    if not re.fullmatch(r"[a-zA-Z0-9-]{16,80}", str(request_id or "")):
        frappe.throw("缺少有效请求标识，请刷新抽屉")
    digest = digest or hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()
    context = {"operation_id": identity(frappe.session.user, request_id), "request_id": request_id,
        "user": frappe.session.user, "digest": digest, "before": {}, "after": {}, "documents": [],
        "amount": None, "currency": None, "quantity": [], "started": time.monotonic(),
        "started_at": datetime.now(timezone.utc).isoformat(), "modules": []}
    for attempt in range(3):
        previous = None
        reserved = False
        token = _active.set(context)
        try:
            previous = _existing(context["operation_id"])
            if previous:
                facts = json.loads(previous.data)
                if facts.get("digest") != digest or facts.get("user") != frappe.session.user:
                    frappe.throw("同一请求内容已改变，请刷新后重新核对")
                if previous.status != "Completed":
                    frappe.throw("上次请求尚未完成，请稍后重试")
                return replay(json.loads(previous.output))
            _reserve(context)
            reserved = True
            from .purchase_consistency import bind_operation
            bind_operation(context)
            result = trace(context, "native procurement controllers", operation)
            from .purchase_consistency import check_registered
            check_registered()
            complete_audit(context, result)
            runtime_log(context, "success_pending_commit")
            return result
        except Exception as error:
            frappe.db.rollback()  # including native ledgers, files and queued audit
            runtime_log(context, "rolled_back", error)
            # MariaDB 1205/1213 and PostgreSQL native equivalents only. Validation
            # errors are never retried; each retry rebuilds documents and callbacks.
            code = error.args[0] if error.args else None
            retry = isinstance(error, (frappe.QueryDeadlockError, frappe.QueryTimeoutError)) or code in (1205, 1213, "40P01", "55P03") or getattr(error, "pgcode", None) in ("40P01", "55P03")
            audit_collision = isinstance(error, frappe.DuplicateEntryError) and not reserved and previous is None
            if audit_collision:
                # Concurrent primary-key winner is visible only in a new/current read.
                retry = True
            if retry and attempt < 2 and (audit_collision or not isinstance(error, (frappe.ValidationError, frappe.PermissionError))):
                continue  # Frappe rollback starts a new transaction.
            if previous is None and acknowledge_validation and isinstance(error, (frappe.ValidationError, frappe.PermissionError)):
                return {"failed": True, "error": str(error)}
            raise
        finally:
            _active.reset(token)


def protect_audit(doc, method=None):
    if doc.get("integration_request_service") == SERVICE:
        frappe.throw("采购操作审计需永久保留，不能删除或改写", frappe.PermissionError)


class ProcurementAuditRetention:
    @staticmethod
    def clear_old_logs(days=30):
        # Native cleanup uses the resolved controller, so exclude this service
        # while retaining ordinary Integration Request cleanup behavior.
        from frappe.query_builder import Interval
        from frappe.query_builder.functions import Now

        table = frappe.qb.DocType("Integration Request")
        frappe.db.delete(table, filters=(table.creation < (Now() - Interval(days=days))) &
            ((table.integration_request_service != SERVICE) | table.integration_request_service.isnull()))
