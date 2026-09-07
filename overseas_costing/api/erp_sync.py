"""Permission-bounded multi-site ERP routing and synchronization API."""

from __future__ import annotations

import json

import frappe

from overseas_costing.services import erp_sync_service
from overseas_costing.services.access_control import require_erp_sync_permission


MAX_TEXT_LENGTH = 500
MAX_SITE_SELECTION_BYTES = 20_000


def _text(value, *, maximum: int = MAX_TEXT_LENGTH) -> str:
    result = str(value or "").strip()
    if len(result) > maximum:
        raise ValueError("参数过长。")
    return result


def _site_codes(value) -> list[str]:
    if isinstance(value, list):
        encoded = json.dumps(value, ensure_ascii=False)
        payload = value
    else:
        encoded = str(value or "[]")
        if len(encoded.encode("utf-8")) > MAX_SITE_SELECTION_BYTES:
            raise ValueError("站点选择参数过大。")
        try:
            payload = json.loads(encoded)
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError("站点选择必须是 JSON 数组。") from exc
    if len(encoded.encode("utf-8")) > MAX_SITE_SELECTION_BYTES:
        raise ValueError("站点选择参数过大。")
    if not isinstance(payload, list):
        raise ValueError("站点选择必须是 JSON 数组。")
    result = []
    for value in payload:
        site_code = _text(value, maximum=100)
        if not site_code:
            raise ValueError("站点编码不能为空。")
        if site_code not in result:
            result.append(site_code)
    return result


@frappe.whitelist()
def get_route_preview(batch_name, version_name=None):
    batch_name = require_erp_sync_permission(batch_name, "read")
    return erp_sync_service.get_route_preview(batch_name, _text(version_name) or None)


@frappe.whitelist()
def preview_bulk_route(batch_name, target_site_code):
    batch_name = require_erp_sync_permission(batch_name, "read")
    return erp_sync_service.preview_bulk_route(batch_name, _text(target_site_code, maximum=100))


@frappe.whitelist()
def apply_bulk_route(batch_name, preview_revision, edit_token, expected_modified):
    batch_name = require_erp_sync_permission(batch_name, "write")
    return erp_sync_service.apply_bulk_route(
        batch_name=batch_name,
        preview_revision=_text(preview_revision, maximum=500),
        edit_token=_text(edit_token, maximum=200),
        expected_modified=_text(expected_modified, maximum=200),
    )


@frappe.whitelist()
def preview_erp_sync(batch_name, version_name=None):
    batch_name = require_erp_sync_permission(batch_name, "read")
    return erp_sync_service.preview_erp_sync(batch_name, _text(version_name) or None)


@frappe.whitelist()
def start_erp_create(batch_name, cost_result_hash, request_key):
    batch_name = require_erp_sync_permission(batch_name, "write")
    return erp_sync_service.start_erp_create(
        batch_name=batch_name,
        cost_result_hash=_text(cost_result_hash, maximum=128),
        request_key=_text(request_key, maximum=200),
    )


@frappe.whitelist()
def preview_erp_updates(batch_name, from_hash, to_hash):
    # 历史批次在此操作中可能根据 GET-only 远端核验建立本地 link，因此要求写权限。
    batch_name = require_erp_sync_permission(batch_name, "write")
    return erp_sync_service.preview_erp_updates(
        batch_name=batch_name,
        from_hash=_text(from_hash, maximum=128),
        to_hash=_text(to_hash, maximum=128),
    )


@frappe.whitelist()
def start_erp_updates(batch_name, to_hash, accepted_site_codes_json, request_key):
    batch_name = require_erp_sync_permission(batch_name, "write")
    return erp_sync_service.start_erp_updates(
        batch_name=batch_name,
        to_hash=_text(to_hash, maximum=128),
        accepted_site_codes=_site_codes(accepted_site_codes_json),
        request_key=_text(request_key, maximum=200),
    )


@frappe.whitelist()
def get_erp_sync_status(batch_name):
    batch_name = require_erp_sync_permission(batch_name, "read")
    return erp_sync_service.get_erp_sync_status(batch_name)


@frappe.whitelist()
def retry_erp_request(batch_name, request_id):
    batch_name = require_erp_sync_permission(batch_name, "retry")
    return erp_sync_service.retry_erp_request(
        batch_name=batch_name,
        request_id=_text(request_id, maximum=128),
    )
