"""海外成本工作台只读 API。"""

from __future__ import annotations

import json

import frappe

from overseas_costing.services import workbench_service
from overseas_costing.services import dingtalk_approval_service
from overseas_costing.services.access_control import require_batch_permission, require_overseas_cost_access


def _filters(value: str | dict | None) -> dict:
    if isinstance(value, dict):
        return value
    return json.loads(value or "{}")


@frappe.whitelist()
def get_batches(filters_json=None, task="pending", page=1, page_length=30) -> dict:
    require_overseas_cost_access()
    return workbench_service.get_workbench_batches(
        _filters(filters_json), task=task, page=page, page_length=page_length
    )


@frappe.whitelist()
def get_summary(filters_json=None) -> dict:
    require_overseas_cost_access()
    return workbench_service.get_workbench_summary(_filters(filters_json))


@frappe.whitelist()
def get_batch_items_page(
    batch_name,
    version_name=None,
    keyword="",
    page=1,
    page_length=50,
    field_group="basic",
    sort_by="row_no",
    sort_order="asc",
) -> dict:
    batch_name = require_batch_permission(batch_name, "read")
    return workbench_service.get_batch_items_page(
        batch_name=batch_name,
        version_name=version_name,
        keyword=keyword,
        page=page,
        page_length=page_length,
        field_group=field_group,
        sort_by=sort_by,
        sort_order=sort_order,
    )


@frappe.whitelist()
def get_batch_result_preview(batch_name, page=1, page_length=20) -> dict:
    """返回工作台批次行内展开所需的精简核算结果。"""

    batch_name = require_batch_permission(batch_name, "read")
    return workbench_service.get_batch_result_preview(
        batch_name=batch_name,
        page=page,
        page_length=page_length,
    )


@frappe.whitelist()
def locate_batch_item(batch_name, item_name, version_name=None, page_length=50) -> dict:
    """返回某个 SKU 在未筛选批次明细中的服务端页码。"""

    batch_name = require_batch_permission(batch_name, "read")
    return workbench_service.locate_batch_item(
        batch_name=batch_name,
        item_name=item_name,
        version_name=version_name,
        page_length=page_length,
    )


@frappe.whitelist()
def get_batch_dingtalk_approval_detail(batch_name) -> dict:
    """返回当前批次的物流审批、关联采购、评论及附件。"""

    batch_name = require_batch_permission(batch_name, "read")
    return dingtalk_approval_service.get_batch_dingtalk_approval_detail(batch_name)
