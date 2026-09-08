"""物料表格和发货数量来源的最小权限 API。"""

from __future__ import annotations

import json

import frappe

from overseas_costing.services import material_ai_fill_service, material_import_service, material_input_service
from overseas_costing.services.access_control import require_batch_permission


USER_QUANTITY_MODES = {"DEFAULT_PURCHASE", "MANUAL_CONFIRMED"}
MAX_CHOICES_BYTES = 100_000
MAX_SOURCE_ID_LENGTH = 500
MAX_PREVIEW_REVISION_LENGTH = 200_000
MAX_AI_UPDATES_BYTES = 1_000_000


def _choices_payload(value) -> dict:
    if isinstance(value, dict):
        payload = value
        encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
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


def _trusted_source_id(value) -> str:
    source_id = str(value or "").strip()
    if not source_id or len(source_id) > MAX_SOURCE_ID_LENGTH:
        raise ValueError("物料来源 ID 不合法。")
    if "://" in source_id or source_id.startswith(("/", "~")) or "\\" in source_id:
        raise ValueError("物料来源只能使用系统内受控 ID。")
    return source_id


def _ai_updates_payload(value) -> list:
    if isinstance(value, list):
        payload = value
        encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    else:
        encoded = str(value or "[]")
        if len(encoded.encode("utf-8")) > MAX_AI_UPDATES_BYTES:
            raise ValueError("AI 草稿更新内容过大。")
        try:
            payload = json.loads(encoded)
        except (TypeError, ValueError) as error:
            raise ValueError("AI 草稿更新不是有效 JSON。") from error
    if len(encoded.encode("utf-8")) > MAX_AI_UPDATES_BYTES:
        raise ValueError("AI 草稿更新内容过大。")
    if not isinstance(payload, list):
        raise ValueError("AI 草稿更新必须是数组。")
    return payload


def _ai_review_payload(value, expected_type, label):
    if isinstance(value, expected_type):
        payload = value
        encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    else:
        encoded = str(value or ("[]" if expected_type is list else "{}"))
        if len(encoded.encode("utf-8")) > MAX_AI_UPDATES_BYTES:
            raise ValueError(f"{label}内容过大。")
        try:
            payload = json.loads(encoded)
        except (TypeError, ValueError) as error:
            raise ValueError(f"{label}不是有效 JSON。") from error
    if len(encoded.encode("utf-8")) > MAX_AI_UPDATES_BYTES:
        raise ValueError(f"{label}内容过大。")
    if not isinstance(payload, expected_type):
        raise ValueError(f"{label}格式不正确。")
    return payload


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
def preview_material_import(batch_name, source_kind, source_id, sheet_name=None, merge_reviews_json=None):
    batch_name = require_batch_permission(batch_name, "read")
    return material_import_service.preview_material_import(
        batch_name,
        str(source_kind or "")[:40],
        _trusted_source_id(source_id),
        sheet_name=str(sheet_name or "")[:200] or None,
        **({"merge_reviews_json": _choices_payload(merge_reviews_json)} if merge_reviews_json is not None else {}),
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
    return material_import_service.apply_material_import(
        batch_name,
        str(preview_revision or "")[:MAX_PREVIEW_REVISION_LENGTH],
        _choices_payload(choices_json),
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


@frappe.whitelist()
def start_material_ai_fill(batch_name, version_name, edit_token, expected_modified):
    batch_name = require_batch_permission(batch_name, "write")
    return material_ai_fill_service.start_material_ai_fill(
        batch_name,
        str(version_name or "")[:200],
        str(edit_token or "")[:200],
        str(expected_modified or "")[:200],
    )


@frappe.whitelist()
def get_material_ai_fill_status(batch_name, run_id):
    batch_name = require_batch_permission(batch_name, "read")
    return material_ai_fill_service.get_material_ai_fill_status(
        batch_name,
        str(run_id or "")[:200],
    )


@frappe.whitelist()
def apply_material_ai_fill(batch_name, run_id, updates_json, edit_token, expected_modified):
    batch_name = require_batch_permission(batch_name, "write")
    return material_ai_fill_service.apply_material_ai_fill(
        batch_name,
        str(run_id or "")[:200],
        _ai_updates_payload(updates_json),
        str(edit_token or "")[:200],
        str(expected_modified or "")[:200],
    )


@frappe.whitelist()
def discard_material_ai_fill(batch_name, run_id):
    batch_name = require_batch_permission(batch_name, "write")
    return material_ai_fill_service.discard_material_ai_fill(
        batch_name,
        str(run_id or "")[:200],
    )


@frappe.whitelist()
def start_source_ai_review(batch_name, version_name, clarification_text=None, force=False):
    batch_name = require_batch_permission(batch_name, "write")
    return material_ai_fill_service.start_source_ai_review(
        batch_name,
        str(version_name or "")[:200],
        str(clarification_text or "")[:4000],
        force=str(force).strip().lower() in {"1", "true", "yes"},
    )


@frappe.whitelist()
def get_source_ai_review_status(batch_name, run_id=None, version_name=None):
    batch_name = require_batch_permission(batch_name, "read")
    return material_ai_fill_service.get_source_ai_review_status(
        batch_name,
        str(run_id or "")[:200],
        version_name=str(version_name or "")[:200],
    )


@frappe.whitelist()
def apply_source_ai_review(
    batch_name,
    run_id,
    selections_json,
    edits_json,
    edit_token,
    expected_modified,
    manual_updates_json=None,
):
    batch_name = require_batch_permission(batch_name, "write")
    return material_ai_fill_service.apply_source_ai_review(
        batch_name,
        str(run_id or "")[:200],
        _ai_review_payload(selections_json, list, "AI 草稿选择"),
        _ai_review_payload(edits_json, dict, "AI 草稿编辑"),
        str(edit_token or "")[:200],
        str(expected_modified or "")[:200],
        _ai_review_payload(manual_updates_json, list, "人工草稿更新"),
    )


@frappe.whitelist()
def discard_source_ai_review(batch_name, run_id):
    batch_name = require_batch_permission(batch_name, "write")
    return material_ai_fill_service.discard_source_ai_review(batch_name, str(run_id or "")[:200])
