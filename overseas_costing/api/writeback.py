"""
中文用途：ERP 回写相关 API。

一期先占住接口，不急着做深度 ERP 集成：
1. 检查是否满足回写条件
2. 执行回写
"""

from __future__ import annotations

import frappe

from overseas_costing.services import batch_service, erp_sync_service
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
    return erp_sync_service.preview_erp_sync(batch_name=batch_name, version_name=version_name)


@frappe.whitelist()
def writeback_to_erp(batch_name: str, version_name: str | None = None) -> dict:
    """执行回写 ERP。"""

    batch_name = require_batch_permission(batch_name, "write")
    preview = erp_sync_service.preview_erp_sync(batch_name=batch_name, version_name=version_name)
    push = preview.get("erp_push") or {}
    return erp_sync_service.start_erp_create(
        batch_name=batch_name,
        cost_result_hash=str(push.get("cost_result_hash") or ""),
        request_key=f"legacy:{frappe.generate_hash(length=20)}",
    )
