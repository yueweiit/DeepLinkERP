"""Optional cost-source capability, trusted native provenance and cached comments.

List reads never reach upstream. Explicit refresh and the existing purchase
source timer reuse the cost app's current effective root and approval adapter.
"""
from __future__ import annotations

import time

import frappe

from . import purchase_fulfilment_contract as contract
from .purchase_payment_service import _read, _record_reader

BATCH = "Overseas Cost Batch"
BATCH_FIELDS = {"source_type", "source_data_id", "source_corp_id", "source_instance_id", "source_approval_status", "current_version", "extra_json"}
CAPABILITY_WARNING = "海外成本物流能力尚未安装或不可用，请先核对原生物流来源；可保留独立手工节点"
SOURCE_WARNING = "当前国际物流来源缺失、未批准或已变化，请核对来源"
LINK_REFRESH_WARNING = "部分物流关联已变化或缺失，请在原生单据重新核对；其余关联继续刷新"


def unavailable_snapshot(warning):
    return {"version": 1, "state": "unavailable", "warnings": [warning], "timeline": [], "quantities": [],
            "confirmed": False, "erp_received": False, "source_context": {}}


def _cost_modules():
    try:
        from overseas_costing.services import effective_logistics_source, dingtalk_approval_service
        return effective_logistics_source, dingtalk_approval_service
    except ImportError:
        return None


def _capability():
    reader = _record_reader.get()
    capability = getattr(reader, "fulfilment_cost_capability", None) if reader else None
    if capability is None:
        # Installed Python alone is insufficient: QA has the package, not its schema.
        schema = bool(frappe.db.exists("DocType", BATCH))
        capability = {"schema": schema, "installed": schema and "overseas_costing" in frappe.get_installed_apps()}
        if reader:
            reader.fulfilment_cost_capability = capability
    return capability


def cost_schema_exists():
    return _capability()["schema"]


def _available():
    capability = _capability()
    return capability["schema"] and capability["installed"]


def local_source(batch_name, required=False):
    """Permission-filtered local root metadata, memoized per bulk progress request."""
    reader = _record_reader.get()
    cache = getattr(reader, "fulfilment_cost_context", None) if reader else None
    if reader and cache is None:
        cache = reader.fulfilment_cost_context = {}
    if cache is not None and batch_name in cache:
        if required and cache[batch_name]["warning"]:
            frappe.throw(cache[batch_name]["warning"])
        return cache[batch_name]
    capability = _capability()
    if capability["schema"]:
        batch = _read(BATCH, batch_name, BATCH_FIELDS)
    # Overseas Cost Batch has no Company field. Never invent one or bypass its
    # native record/field permissions; the association separately guards companies.
    # An existing native model must pass record/field access even if its optional
    # Python/app capability is temporarily absent. Absence is not a permission bypass.
    modules = _cost_modules() if capability["schema"] and capability["installed"] else None
    if not modules:
        if required:
            frappe.throw(CAPABILITY_WARNING)
        result = {"context": {}, "warning": CAPABILITY_WARNING}
        if cache is not None:
            cache[batch_name] = result
        return result
    effective, _ = modules
    bundle = effective.current_source_bundle(batch_name)
    if bundle:
        context = dict(bundle["context"])
    else:
        # Existing installations without the settlement schema retain the native
        # DingTalk batch identity. The adapter verifies this again before use.
        from overseas_costing.scripts.import_oa_logistics import COMPLETED_APPROVAL_STATUSES, resolve_approval_decision
        decision = resolve_approval_decision(batch.source_approval_status)
        approved = str(batch.source_approval_status or "").upper() in {str(value).upper() for value in COMPLETED_APPROVAL_STATUSES}
        context = {"root_kind": "logistics" if batch.source_type == "oa_logistics" else "unclassified",
            "root_source_id": batch.source_data_id or contract.digest([batch.source_corp_id, batch.source_instance_id]),
            "corp_id": batch.source_corp_id or "", "instance_id": batch.source_instance_id or "",
            "source_snapshot": str(batch.modified), "available": bool(batch.source_instance_id),
            "approved": approved and not decision["excluded"], "invalid": bool(decision["excluded"]),
            "cost_version": batch.current_version or ""}
        context["fingerprint"] = contract.digest(context)
    result = {"context": context, "bundle": bundle, "warning": ""}
    if cache is not None:
        cache[batch_name] = result
    return result


def _fresh_snapshot(batch_name):
    local = local_source(batch_name)
    if local["warning"]:
        return unavailable_snapshot(local["warning"])
    context = local["context"]
    effective, approval = _cost_modules()
    # Expense comments belong to the adopted expense root; they must never be
    # relabelled as international shipping comments from another approval.
    if context.get("root_kind") != "logistics":
        detail = effective.approval_detail_for_bundle(local["bundle"]) if local["bundle"] else {"ok": False}
    else:
        detail = approval.get_batch_dingtalk_approval_detail(batch_name)
    main = detail.get("main_approval") or {}
    from overseas_costing.scripts.import_oa_logistics import COMPLETED_APPROVAL_STATUSES
    approved = {str(value).strip().upper() for value in COMPLETED_APPROVAL_STATUSES}
    if main and (str(main.get("effective_status") or "").strip().upper() not in approved or
                 main.get("excluded") or main.get("analysis_only") or
                 (main.get("instance_id") and main["instance_id"] != context.get("instance_id")) or
                 (main.get("corp_id") and main["corp_id"] != context.get("corp_id"))):
        context = {**context, "available": False, "approved": False}
    return contract.logistics_snapshot(context, detail, None)


def _bound_snapshot(snapshot, bound):
    return contract.validate_snapshot_context(snapshot, snapshot.get("source_context", {}), bound)


def refresh_source(batch_name, bound):
    """Read current comments even for completed approvals; no status shortcut."""
    return _bound_snapshot(_fresh_snapshot(batch_name), bound)


def refresh_cached_logistics(*, deadline, max_batches=8):
    """Bounded addition to the existing 300-second purchase timer, no new jobs.

Each distinct batch's comments are fetched/parsed once. Per-link snapshot JSON
serialization counts its actual output bytes; manual nodes are never rewritten.

Only pre-save native allocation/CAS conflicts or missing records are skipped.
These branches register no post-save/after-commit callbacks. Permission errors,
DB failures (including whole-transaction deadlocks), and save failures propagate.
"""
    from . import purchase_fulfilment_service as service
    with service._request_reader():
        if not _available() or not frappe.db.exists("DocType", service.DOCTYPE):
            return {"batches": 0, "links": 0, "warnings": [CAPABILITY_WARNING]}
        rows = frappe.get_all(service.DOCTYPE, filters={"active": 1, "cost_batch": ["!=", ""]},
            fields=["name", "modified", "cost_batch"], order_by="snapshot_refreshed_on asc", limit_page_length=100)
        batches = {}; count = 0; warnings = []
        max_batches = min(8, max(0, int(max_batches)))
        for index, row in enumerate(rows):
            if time.monotonic() + 10 >= deadline:
                break
            if row.cost_batch not in batches:
                if len(batches) >= max_batches:
                    continue
                try:
                    batches[row.cost_batch] = _fresh_snapshot(row.cost_batch)
                except frappe.DoesNotExistError:
                    # A local optional source may have disappeared. No managed
                    # write/callback has run; never confuse permission/DB failure.
                    batches[row.cost_batch] = None
            if batches[row.cost_batch] is None:
                if LINK_REFRESH_WARNING not in warnings:
                    warnings.append(LINK_REFRESH_WARNING)
                continue
            if CAPABILITY_WARNING in batches[row.cost_batch].get("warnings", []):
                if CAPABILITY_WARNING not in warnings:
                    warnings.append(CAPABILITY_WARNING)
                continue  # Keep old private evidence until the capability returns.
            # The timer uses native authorization and the same sorted parents ->
            # current Link -> current allocations locking protocol as user actions.
            savepoint = "purchase_fulfilment_refresh_" + str(index)
            frappe.db.savepoint(savepoint)
            try:
                doc, _, _, _ = service._locked_link(row.name, str(row.modified))
            except (service.LinkStateConflict, frappe.DoesNotExistError):
                frappe.db.rollback(save_point=savepoint)
                frappe.db.release_savepoint(savepoint)
                if LINK_REFRESH_WARNING not in warnings:
                    warnings.append(LINK_REFRESH_WARNING)
                continue
            bound = service._json(doc.get("source_versions_json")).get("logistics", {})
            snapshot = _bound_snapshot(batches[row.cost_batch], bound)
            doc.snapshot_json = service._dump(snapshot)
            doc.snapshot_refreshed_on = frappe.utils.now_datetime()
            service._audit(doc, "refresh_logistics", {"source_context": snapshot.get("source_context"), "state": snapshot["state"]})
            service._save(doc)
            frappe.db.release_savepoint(savepoint)
            count += 1
        return {"batches": len(batches), "links": count, "warnings": warnings}
