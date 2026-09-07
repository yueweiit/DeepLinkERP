"""中文用途：装箱来源、缓存刷新、不可变确认和独立运费试算的最小权限 API。"""

from __future__ import annotations

import json
import re

import frappe

from overseas_costing.integrations.dingtalk_packing_source import get_packing_runtime_clients
from overseas_costing.services import freight_comparison_service, packing_snapshot_service
from overseas_costing.services.access_control import require_packing_workflow_permission


HASH_PATTERN = re.compile(r"^[0-9a-f]{64}$")


def _json_object(value, *, label: str, max_length: int) -> dict:
    if isinstance(value, dict):
        payload = value
        encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    else:
        encoded = str(value or "{}")
        if len(encoded.encode("utf-8")) > max_length:
            raise ValueError(f"{label}过大。")
        try:
            payload = json.loads(encoded)
        except (TypeError, ValueError) as error:
            raise ValueError(f"{label}不是有效 JSON。") from error
    if len(encoded.encode("utf-8")) > max_length:
        raise ValueError(f"{label}过大。")
    if not isinstance(payload, dict):
        raise ValueError(f"{label}必须是对象。")
    return payload


def _request_key(value: str) -> str:
    normalized = str(value or "").strip().lower()
    if not HASH_PATTERN.fullmatch(normalized):
        raise ValueError("请求 ID 必须是 64 位小写 SHA-256。")
    return normalized


@frappe.whitelist()
def list_packing_sources(batch_name):
    batch_name = require_packing_workflow_permission(batch_name, "read")
    return packing_snapshot_service.list_packing_sources(batch_name)


@frappe.whitelist()
def request_packing_workbook_refresh(batch_name, workbook_id, request_id):
    require_packing_workflow_permission(batch_name, "refresh")
    request_key = _request_key(request_id)
    request_number = get_packing_runtime_clients().submitter.request_workbook_index_refresh(
        str(workbook_id), request_key, str(frappe.session.user)
    )
    return {"ok": True, "request_id": request_number, "request_key": request_key}


@frappe.whitelist()
def request_packing_sheet_refresh(batch_name, workbook_id, sheet_id, request_id):
    require_packing_workflow_permission(batch_name, "refresh")
    request_key = _request_key(request_id)
    request_number = get_packing_runtime_clients().submitter.request_sheet_refresh(
        str(workbook_id), str(sheet_id), request_key, str(frappe.session.user)
    )
    return {"ok": True, "request_id": request_number, "request_key": request_key}


@frappe.whitelist()
def get_packing_refresh_status(batch_name, request_id):
    require_packing_workflow_permission(batch_name, "read")
    return get_packing_runtime_clients().catalog.get_refresh_status(_request_key(request_id)) or {
        "status": "not_found"
    }


@frappe.whitelist()
def preview_packing_source_v2(batch_name, source_kind, source_id, sheet_name=None):
    batch_name = require_packing_workflow_permission(batch_name, "preview")
    return packing_snapshot_service.preview_packing_source_v2(
        batch_name,
        str(source_kind)[:40],
        str(source_id)[:500],
        sheet_name=str(sheet_name)[:200] if sheet_name else None,
    )


@frappe.whitelist()
def confirm_packing_snapshot(batch_name, source_revision, resolutions_json=None):
    batch_name = require_packing_workflow_permission(batch_name, "confirm")
    resolutions = _json_object(resolutions_json, label="装箱确认内容", max_length=50000)
    return packing_snapshot_service.confirm_packing_snapshot(
        batch_name, str(source_revision)[:10000], resolutions
    )


@frappe.whitelist()
def get_current_packing_snapshot(batch_name):
    batch_name = require_packing_workflow_permission(batch_name, "read")
    return packing_snapshot_service.get_current_packing_snapshot(batch_name)


@frappe.whitelist()
def preview_freight_comparison(batch_name, snapshot_revision, quote_json):
    batch_name = require_packing_workflow_permission(batch_name, "preview")
    quote = _json_object(quote_json, label="报价内容", max_length=20000)
    return freight_comparison_service.preview_freight_comparison(
        batch_name, str(snapshot_revision)[:200], quote
    )


@frappe.whitelist()
def save_freight_comparison(batch_name, snapshot_revision, request_id, quote_json):
    batch_name = require_packing_workflow_permission(batch_name, "compare")
    request_key = _request_key(request_id)
    quote = _json_object(quote_json, label="报价内容", max_length=20000)
    return freight_comparison_service.save_freight_comparison(
        batch_name, str(snapshot_revision)[:200], request_key, quote
    )


@frappe.whitelist()
def list_freight_comparisons(batch_name):
    batch_name = require_packing_workflow_permission(batch_name, "read")
    return freight_comparison_service.list_freight_comparisons(batch_name)
