"""
中文用途：ERP 回写相关 API。

一期先占住接口，不急着做深度 ERP 集成：
1. 检查是否满足回写条件
2. 执行回写
"""

from __future__ import annotations

import frappe

from overseas_costing.services import batch_service
from overseas_costing.services.access_control import require_batch_permission


@frappe.whitelist()
def check_writeback_ready(batch_name: str, version_name: str | None = None) -> dict:
    """检查当前批次/版本是否可回写 ERP。"""

    batch_name = require_batch_permission(batch_name, "read")
    return batch_service.check_writeback_ready(batch_name=batch_name, version_name=version_name)


@frappe.whitelist()
def confirm_calculation_result(batch_name: str, version_name: str | None = None, remark: str | None = None) -> dict:
    """人工确认当前计算结果，通过后才允许组织 ERP 推送报文。"""

    batch_name = require_batch_permission(batch_name, "write")
    return batch_service.confirm_calculation_result(
        batch_name=batch_name,
        version_name=version_name,
        remark=remark,
    )


@frappe.whitelist()
def preview_erp_payload(batch_name: str, version_name: str | None = None) -> dict:
    """预览当前批次将推送给 DeepLinkERP 的报文。"""

    batch_name = require_batch_permission(batch_name, "read")
    return batch_service.preview_erp_payload(batch_name=batch_name, version_name=version_name)


@frappe.whitelist()
def preview_site_sync_plan(batch_name: str, version_name: str | None = None, client_intent_id: str = "") -> dict:
    """预览按项目归属拆分的 ERP 站点同步草稿，不执行外部写入。"""

    from overseas_costing.services.erp_sync_plan_service import preview_site_sync_plan as preview

    batch_name = require_batch_permission(batch_name, "read")
    return preview(batch_name=batch_name, version_name=version_name, client_intent_id=client_intent_id)


@frappe.whitelist()
def save_site_sync_plan(batch_name: str, version_name: str | None = None, client_intent_id: str = "") -> dict:
    """保存分站点同步请求到本地账本，不执行外部写入。"""

    from overseas_costing.services.erp_sync_plan_service import save_site_sync_plan as save

    batch_name = require_batch_permission(batch_name, "write")
    return save(batch_name=batch_name, version_name=version_name, client_intent_id=client_intent_id)


@frappe.whitelist()
def get_site_sync_requests(batch_name: str, version_name: str | None = None, limit: int = 100) -> dict:
    """读取当前批次的本地 ERP 同步草稿和执行状态，不读取目标 ERP。"""

    from overseas_costing.services.erp_sync_plan_service import get_site_sync_requests as get_requests

    batch_name = require_batch_permission(batch_name, "read")
    return get_requests(batch_name=batch_name, version_name=version_name, limit=limit)


@frappe.whitelist()
def verify_erp_site_capability(site_code: str) -> dict:
    """管理员手动核验指定 ERP 站点的字段合同；仅执行远端只读请求。"""

    from overseas_costing.services.erp_site_service import verify_and_record_site_capability

    frappe.only_for("System Manager")
    return verify_and_record_site_capability(site_code)


@frappe.whitelist()
def writeback_to_erp(batch_name: str, version_name: str | None = None) -> dict:
    """执行回写 ERP。"""

    batch_name = require_batch_permission(batch_name, "write")
    return batch_service.writeback_to_erp(batch_name=batch_name, version_name=version_name)
