"""中文用途：读取核算确认结果，生成或保存分站点 ERP 同步草稿。"""

from __future__ import annotations

import hashlib
import json

from overseas_costing.services import batch_service
from overseas_costing.services.erp_sync_service import build_site_sync_plan

try:
    import frappe
except ImportError:
    frappe = None


def preview_site_sync_plan(batch_name: str, version_name: str | None = None, client_intent_id: str = "") -> dict:
    """只读返回当前确认成本对应的分站点同步草稿。"""

    readiness = batch_service.check_writeback_ready(
        batch_name,
        version_name,
        require_batch_subsidiary=False,
    )
    if not readiness.get("ready"):
        return {
            "ok": False,
            "ready": False,
            "batch_name": readiness.get("batch_name") or batch_name,
            "version_name": readiness.get("version_name") or version_name,
            "blocking": _text_reasons(readiness.get("blocking_reasons")),
            "readiness": readiness,
        }

    remediation_gate = batch_service._build_review_remediation_gate(
        readiness.get("batch_name") or batch_name,
        for_update=False,
    )
    if remediation_gate.get("erp_blocked"):
        return {
            "ok": False,
            "ready": False,
            "batch_name": readiness.get("batch_name") or batch_name,
            "version_name": readiness.get("version_name") or version_name,
            "blocking": _text_reasons(remediation_gate.get("blocking_reasons")),
            "readiness": readiness,
            **remediation_gate,
        }

    context = batch_service._load_erp_push_context(batch_name, version_name)
    if not context.get("ok"):
        return {**context, "ready": False}
    plan = build_site_sync_plan(
        batch=context["batch"],
        version=context["version"],
        items=_prepared_items(context["items"]),
        routes=_active_routes(),
        site_configs=_enabled_sites(),
        active_supplier_names=_active_supplier_names(),
        client_intent_id=client_intent_id,
    )
    return {
        **plan,
        "batch_name": context["batch_doc_name"],
        "version_name": context["version_name"],
        "readiness": readiness,
    }


def save_site_sync_plan(batch_name: str, version_name: str | None = None, client_intent_id: str = "") -> dict:
    """重新生成当前草稿并保存到本地账本；不会发起 ERP HTTP 请求。"""

    from overseas_costing.services.erp_sync_ledger_service import save_sync_request_specs

    plan = preview_site_sync_plan(batch_name, version_name, client_intent_id)
    if not plan.get("ready"):
        return {**plan, "saved": False}
    saved = save_sync_request_specs(plan["request_specs"], version=plan.get("version_name") or "")
    if saved.get("ok"):
        _insert_plan_audit_log(plan, saved)
    return {**plan, "saved": bool(saved.get("ok")), "ledger": saved}


def execute_site_sync_plan(batch_name: str, version_name: str | None = None, client_intent_id: str = "") -> dict:
    """Server-recompute, persist and execute Company-scoped groups through one ledger."""

    from overseas_costing.services.erp_sync_ledger_service import execute_saved_sync_requests
    from overseas_costing.services.logistics_settlement.runtime import installed, lock_for_final_action

    resolved_batch = batch_service._resolve_batch_name(batch_name) or batch_name
    settlement_issues = lock_for_final_action(resolved_batch, version_name) if installed() else []
    if settlement_issues:
        return {
            "ok": False,
            "ready": False,
            "pushed": False,
            "queued": False,
            "blocking": _text_reasons(settlement_issues),
            "message": "；".join(settlement_issues),
        }
    if frappe is not None and callable(getattr(getattr(frappe, "db", None), "sql", None)):
        locked_version = batch_service._lock_confirmation_records(resolved_batch, version_name)
        remediation_gate = batch_service._build_review_remediation_gate(resolved_batch, for_update=True)
        if remediation_gate.get("erp_blocked"):
            return {
                "ok": False,
                "ready": False,
                "pushed": False,
                "queued": False,
                "version_name": locked_version,
                "blocking": _text_reasons(remediation_gate.get("blocking_reasons")),
                "message": "；".join(remediation_gate.get("blocking_reasons") or []),
                **remediation_gate,
            }

    saved_plan = save_site_sync_plan(batch_name, version_name, client_intent_id)
    if not saved_plan.get("saved"):
        return {**saved_plan, "pushed": False, "queued": False}
    execution = execute_saved_sync_requests((saved_plan.get("ledger") or {}).get("requests") or [])
    complete = saved_plan.get("complete", True) is not False
    successful = bool(execution.get("ok")) and complete
    status = "Success" if successful else "Failed"
    message = _execution_message(execution)
    if not complete:
        message += f"；另有 {len(saved_plan.get('blocking') or [])} 个物料组未推送，请修正后重试。"
    _record_execution_summary(saved_plan, execution, status=status, message=message)
    return {
        **saved_plan,
        "execution": execution,
        "ok": successful,
        "pushed": bool(execution.get("success_count")) and successful,
        "queued": bool(execution.get("failed_count") or execution.get("uncertain_count") or not complete),
        "retryable": bool(execution.get("failed_count") or not complete),
        "writeback_status": status,
        "message": message,
    }


def get_site_sync_requests(batch_name: str, version_name: str | None = None, limit: int = 100) -> dict:
    """读取当前批次的本地分站点同步请求账本。"""

    from overseas_costing.services.erp_sync_ledger_service import list_sync_requests

    context = batch_service._load_erp_push_context(batch_name, version_name)
    if not context.get("ok"):
        return {**context, "items": [], "total": 0}
    return {
        **list_sync_requests(context["batch_doc_name"], version=context["version_name"] or "", limit=limit),
        "batch_name": context["batch_doc_name"],
        "version_name": context["version_name"],
    }


def list_project_route_options(batch_name: str = "") -> dict:
    """List unambiguous active project-to-Company routes for material editing."""

    from overseas_costing.services.erp_routing_service import (
        list_unambiguous_project_routes,
        project_route_identity,
    )

    result = list_unambiguous_project_routes(_active_routes())
    candidates = _batch_project_candidate_names(batch_name) if batch_name else []
    candidate_order = {
        project_route_identity(name): index for index, name in enumerate(candidates)
    }
    options = [
        {
            **option,
            "is_approval_candidate": (
                project_route_identity(option.get("project_collection")) in candidate_order
            ),
        }
        for option in result["options"]
    ]
    options.sort(
        key=lambda option: (
            0 if option["is_approval_candidate"] else 1,
            candidate_order.get(
                project_route_identity(option.get("project_collection")),
                len(candidate_order),
            ),
            str(option.get("project_collection") or ""),
        )
    )
    revision_payload = {
        "options": options,
        "conflicts": result["conflicts"],
        "approval_candidates": candidates,
    }
    return {
        "ok": True,
        "options": options,
        "conflicts": result["conflicts"],
        "route_revision": hashlib.sha256(
            json.dumps(
                revision_payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest(),
    }


def _batch_project_candidate_names(batch_name: str) -> list[str]:
    """Return first-seen DingTalk candidates from the current material version."""

    from overseas_costing.services.erp_routing_service import (
        project_candidate_names,
        project_route_identity,
    )

    _require_frappe()
    resolved = batch_service._resolve_batch_name(batch_name) or str(batch_name or "")
    version = frappe.db.get_value("Overseas Cost Batch", resolved, "current_version")
    if not resolved or not version:
        return []
    items = frappe.get_all(
        "Overseas Cost Item",
        filters={"batch": resolved, "version": version, "is_excluded": 0},
        fields=["extra_json"],
        order_by="row_no asc, name asc",
        limit_page_length=10000,
    )
    names = []
    seen = set()
    for item in items:
        for name in project_candidate_names(item):
            identity = project_route_identity(name)
            if identity not in seen:
                seen.add(identity)
                names.append(name)
    return names


def _prepared_items(items: list[dict]) -> list[dict]:
    """把物料行补齐成 ERP 报文形态。

    行级报文字段口径复用 ``batch_service.build_erp_payload_item``：
    分组/路由需要的原始列（``stable_line_key``、``erp_stock_uom`` 等）保留，
    同时带上 ``erp_client`` 组装采购单时要读的 ``cost_formula`` 等字段。
    """

    prepared = []
    for item in items:
        row = dict(item)
        payload_item = batch_service.build_erp_payload_item(row)
        formula = payload_item["cost_formula"]
        prepared.append(
            {
                **row,
                **payload_item,
                "total_cost_rmb": formula["total_cost"],
                "allocated_fee_rmb": formula["allocated_total_cost"],
            }
        )
    return prepared


def _active_routes() -> list[dict]:
    _require_frappe()
    return frappe.get_all(
        "Overseas Cost Project Route",
        filters={"enabled": 1},
        fields=["project_collection", "subsidiary_code", "erp_site", "enabled", "valid_from", "valid_to", "revision", "ai_match_hint"],
        limit_page_length=1000,
    )


def _enabled_sites() -> list[dict]:
    _require_frappe()
    return frappe.get_all(
        "Overseas Cost ERP Site",
        filters={"enabled": 1},
        fields=["site_code", "enabled", "subsidiary_code", "capability_status", "cost_update_mode"],
        limit_page_length=1000,
    )


def _active_supplier_names() -> set[str]:
    """Load active canonical Supplier names once for the complete ERP preview."""

    _require_frappe()
    rows = frappe.get_all(
        "Supplier",
        filters={"disabled": 0},
        fields=["name"],
        limit_page_length=10000,
    )
    return {str(row.get("name") or "").strip() for row in rows if row.get("name")}


def _insert_plan_audit_log(plan: dict, saved: dict) -> None:
    requests = saved.get("requests") or []
    sites = sorted(
        {
            str(row.get("site_code") or "")
            for row in (plan.get("request_specs") or {}).get("requests") or []
            if row.get("site_code")
        }
    )
    batch_service._insert_batch_audit_log(
        batch_doc_name=plan["batch_name"],
        version_name=plan.get("version_name"),
        action_type="WRITEBACK",
        field_name="erp_site_sync_plan",
        new_value=json.dumps(
            {
                "request_count": len(requests),
                "created_count": sum(row.get("action") == "CREATE" for row in requests),
                "reused_count": sum(row.get("action") == "REUSE" for row in requests),
                "sites": sites,
            },
            ensure_ascii=False,
            sort_keys=True,
        ),
        action_remark="已生成分站点 ERP 同步草稿，尚未发送至 ERP。",
    )


def _record_execution_summary(
    plan: dict,
    execution: dict,
    *,
    status: str | None = None,
    message: str | None = None,
) -> None:
    status = status or ("Success" if execution.get("ok") else "Failed")
    message = message or _execution_message(execution)
    values = {
        "writeback_status": status,
        "writeback_time": frappe.utils.now_datetime(),
        "writeback_message": message,
    }
    frappe.db.set_value("Overseas Cost Batch", plan["batch_name"], values, update_modified=True)
    batch_service._insert_batch_audit_log(
        batch_doc_name=plan["batch_name"],
        version_name=plan.get("version_name"),
        action_type="WRITEBACK",
        field_name="erp_company_sync_execution",
        new_value=json.dumps(
            {
                "success_count": execution.get("success_count", 0),
                "failed_count": execution.get("failed_count", 0),
                "uncertain_count": execution.get("uncertain_count", 0),
                "skipped_count": execution.get("skipped_count", 0),
            },
            ensure_ascii=False,
            sort_keys=True,
        ),
        action_remark=message,
    )
    frappe.db.commit()


def _execution_message(execution: dict) -> str:
    return (
        f"ERP 分组同步：成功 {execution.get('success_count', 0)} 组，"
        f"失败 {execution.get('failed_count', 0)} 组，"
        f"状态待确认 {execution.get('uncertain_count', 0)} 组。"
    )


def _require_frappe() -> None:
    if frappe is None:
        raise RuntimeError("Frappe 运行环境不可用，无法读取 ERP 路由配置。")


def _text_reasons(reasons) -> list[dict]:
    return [{"code": "WRITEBACK_READINESS_REQUIRED", "message": str(reason)} for reason in reasons or []]
