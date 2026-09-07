"""物料表格和发货数量来源的最小权限 API。"""

from __future__ import annotations

import frappe

from overseas_costing.services import material_input_service
from overseas_costing.services.access_control import require_batch_permission


USER_QUANTITY_MODES = {"DEFAULT_PURCHASE", "MANUAL_CONFIRMED"}


@frappe.whitelist()
def get_material_grid(batch_name, version_name=None, page=1, page_length=100):
    batch_name = require_batch_permission(batch_name, "read")
    return material_input_service.get_material_grid(
        batch_name=batch_name,
        version_name=version_name,
        page=page,
        page_length=page_length,
    )


@frappe.whitelist()
def set_shipping_quantity(
    batch_name,
    item_name,
    mode,
    value,
    uom,
    edit_token,
    expected_modified,
):
    batch_name = require_batch_permission(batch_name, "write")
    normalized_mode = str(mode or "").strip()
    if normalized_mode not in USER_QUANTITY_MODES:
        raise ValueError("发货数量来源状态不合法。")
    return material_input_service.set_shipping_quantity(
        batch_name=batch_name,
        item_name=str(item_name or "")[:200],
        mode=normalized_mode,
        value=value,
        uom=str(uom or "")[:100],
        edit_token=str(edit_token or "")[:200],
        expected_modified=str(expected_modified or "")[:200],
    )
