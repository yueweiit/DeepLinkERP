"""物料表格、可信 Excel 预览和数量来源的最小权限 API。"""

from __future__ import annotations

import json

import frappe

from overseas_costing.services import material_import_service, material_input_service, workbench_service
from overseas_costing.services.access_control import require_batch_permission


MAX_CHOICES_BYTES = 100_000
MAX_SOURCE_ID_LENGTH = 500
MAX_PREVIEW_REVISION_LENGTH = 10_000
USER_QUANTITY_MODES = {"DEFAULT_PURCHASE", "MANUAL_CONFIRMED"}


def _choices_payload(value) -> dict:
    if isinstance(value, dict):
        encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        payload = value
    else:
        encoded = str(value or "{}")
        if len(encoded.encode("utf-8")) > MAX_CHOICES_BYTES:
            raise ValueError("物料导入选择过大。")
        try:
            payload = json.loads(encoded)
        except (TypeError, ValueError) as error:
            raise ValueError("物料导入选择不是有效 JSON。") from error
    if len(encoded.encode("utf-8")) > MAX_CHOICES_BYTES:
        raise ValueError("物料导入选择过大。")
    if not isinstance(payload, dict):
        raise ValueError("物料导入选择必须是对象。")
    return payload


@frappe.whitelist()
def get_material_grid(batch_name, version_name=None, page=1, page_length=100):
    batch_name = require_batch_permission(batch_name, "read")
    return workbench_service.get_batch_items_page(
        batch_name=batch_name,
        version_name=version_name,
        page=page,
        page_length=page_length,
        field_group="all",
    )


@frappe.whitelist()
def preview_material_import(batch_name, source_kind, source_id, sheet_name=None):
    batch_name = require_batch_permission(batch_name, "read")
    normalized_source_id = str(source_id or "").strip()
    if not normalized_source_id or len(normalized_source_id) > MAX_SOURCE_ID_LENGTH:
        raise ValueError("物料来源 ID 不合法。")
    if "://" in normalized_source_id or normalized_source_id.startswith(("/", "~")):
        raise ValueError("物料来源只能使用系统内受控 ID。")
    return material_import_service.preview_material_import(
        batch_name,
        str(source_kind or "")[:40],
        normalized_source_id,
        sheet_name=str(sheet_name or "")[:200] or None,
    )


@frappe.whitelist()
def apply_material_import(
    batch_name,
    preview_revision,
    choices_json,
    edit_token,
    expected_modified,
):
    batch_name = require_batch_permission(batch_name, "write")
    choices = _choices_payload(choices_json)
    return material_import_service.apply_material_import(
        batch_name,
        str(preview_revision or "")[:MAX_PREVIEW_REVISION_LENGTH],
        choices,
        str(edit_token or "")[:200],
        str(expected_modified or "")[:200],
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
