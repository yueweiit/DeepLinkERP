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

    readiness = batch_service.check_writeback_ready(batch_name, version_name)
    if not readiness.get("ready"):
        return {
            "ok": False,
            "ready": False,
            "batch_name": readiness.get("batch_name") or batch_name,
            "version_name": readiness.get("version_name") or version_name,
            "blocking": _text_reasons(readiness.get("blocking_reasons")),
            "readiness": readiness,
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


def _require_frappe() -> None:
    if frappe is None:
        raise RuntimeError("Frappe 运行环境不可用，无法读取 ERP 路由配置。")


def _text_reasons(reasons) -> list[dict]:
    return [{"code": "WRITEBACK_READINESS_REQUIRED", "message": str(reason)} for reason in reasons or []]
