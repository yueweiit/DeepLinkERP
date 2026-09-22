"""中文用途：读取核算确认结果，生成或保存分站点 ERP 同步草稿。"""

from __future__ import annotations

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
    _record_execution_summary(saved_plan, execution)
    return {
        **saved_plan,
        "execution": execution,
        "ok": bool(execution.get("ok")),
        "pushed": bool(execution.get("success_count")) and not execution.get("failed_count") and not execution.get("uncertain_count"),
        "queued": bool(execution.get("failed_count") or execution.get("uncertain_count")),
        "retryable": bool(execution.get("failed_count")),
        "writeback_status": "Success" if execution.get("ok") else "Failed",
        "message": _execution_message(execution),
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


def list_project_route_options() -> dict:
    """List unambiguous active project-to-Company routes for material editing."""

    from overseas_costing.services.erp_routing_service import list_unambiguous_project_routes

    return {"ok": True, **list_unambiguous_project_routes(_active_routes())}


def _prepared_items(items: list[dict]) -> list[dict]:
    prepared = []
    for item in items:
        row = batch_service._effective_calculated_item(dict(item))
        formula = batch_service._build_cost_formula(row)
        row["total_cost_rmb"] = formula["total_cost"]
        row["allocated_fee_rmb"] = formula["allocated_total_cost"]
        prepared.append(row)
    return prepared


def _active_routes() -> list[dict]:
    _require_frappe()
    return frappe.get_all(
        "Overseas Cost Project Route",
        filters={"enabled": 1},
        fields=["project_collection", "subsidiary_code", "erp_site", "enabled", "valid_from", "valid_to", "revision"],
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


def _record_execution_summary(plan: dict, execution: dict) -> None:
    status = "Success" if execution.get("ok") else "Failed"
    message = _execution_message(execution)
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
