"""费用待办、凭证关联和最终确认的最小权限 API。"""

from __future__ import annotations

import json
import re

import frappe

from overseas_costing.services import fee_service
from overseas_costing.services.access_control import (
    require_attachment_permission,
    require_fee_workflow_permission,
)


MAX_FEE_JSON_BYTES = 50_000
MAX_TEXT_LENGTH = 500
ALLOWED_FEE_FIELDS = frozenset({*fee_service.FEE_FIELDS, "scope_item_keys"})
ALLOWED_EVIDENCE_ROLES = frozenset(
    {
        "freight_invoice",
        "tax_certificate",
        "customs_declaration",
        "payment_voucher",
        "expense_invoice",
        "other_final",
    }
)
ALLOWED_EVIDENCE_STATUSES = frozenset({"PENDING", "VALID", "INVALID", "UNLINKED"})


def _text(value, *, maximum: int = MAX_TEXT_LENGTH) -> str:
    normalized = str(value or "").strip()
    if len(normalized) > maximum:
        raise ValueError("参数过长。")
    return normalized


def _fee_payload(value) -> dict:
    if isinstance(value, dict):
        payload = dict(value)
        encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    else:
        encoded = str(value or "{}")
        if len(encoded.encode("utf-8")) > MAX_FEE_JSON_BYTES:
            raise ValueError("费用参数过大。")
        try:
            payload = json.loads(encoded)
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError("费用参数不是有效 JSON。") from exc
    if len(encoded.encode("utf-8")) > MAX_FEE_JSON_BYTES:
        raise ValueError("费用参数过大。")
    if not isinstance(payload, dict):
        raise ValueError("费用参数必须是 JSON 对象。")
    forbidden = sorted(set(payload) - ALLOWED_FEE_FIELDS)
    if forbidden:
        raise ValueError(f"费用参数包含不允许字段：{'、'.join(forbidden)}")
    return payload


@frappe.whitelist()
def get_fee_worklist(batch_name, version_name=None):
    batch_name = require_fee_workflow_permission(batch_name, "read")
    return fee_service.get_fee_worklist(batch_name, _text(version_name) or None)


@frappe.whitelist()
def save_fee(batch_name, version_name, fee_json, edit_token, expected_modified):
    batch_name = require_fee_workflow_permission(batch_name, "write")
    payload = _fee_payload(fee_json)
    return fee_service.save_fee(
        batch_name,
        _text(version_name),
        payload,
        _text(edit_token, maximum=200),
        _text(expected_modified, maximum=200),
    )


@frappe.whitelist()
def link_fee_evidence(
    batch_name,
    fee_rule,
    attachment,
    evidence_role,
    edit_token,
    expected_modified,
):
    batch_name = require_fee_workflow_permission(batch_name, "write")
    attachment = require_attachment_permission(_text(attachment), "read")
    role = _text(evidence_role, maximum=100)
    if role not in ALLOWED_EVIDENCE_ROLES:
        raise ValueError("凭证角色不合法。")
    return fee_service.link_fee_evidence(
        batch_name,
        _text(fee_rule),
        attachment,
        role,
        _text(edit_token, maximum=200),
        _text(expected_modified, maximum=200),
    )


@frappe.whitelist()
def set_fee_evidence_status(
    batch_name,
    evidence_name,
    status,
    remark,
    edit_token,
    expected_modified,
):
    batch_name = require_fee_workflow_permission(batch_name, "write")
    normalized_status = _text(status, maximum=30).upper()
    if normalized_status not in ALLOWED_EVIDENCE_STATUSES:
        raise ValueError("费用凭证状态不合法。")
    return fee_service.set_fee_evidence_status(
        batch_name,
        _text(evidence_name),
        normalized_status,
        _text(remark, maximum=2000),
        _text(edit_token, maximum=200),
        _text(expected_modified, maximum=200),
    )


@frappe.whitelist()
def confirm_all_fees_complete(
    batch_name,
    version_name,
    expected_input_hash,
    edit_token,
    expected_modified,
):
    batch_name = require_fee_workflow_permission(batch_name, "write")
    input_hash = _text(expected_input_hash, maximum=64).lower()
    if not re.fullmatch(r"[0-9a-f]{64}", input_hash):
        raise ValueError("费用输入哈希必须是 64 位 SHA-256。")
    return fee_service.confirm_all_fees_complete(
        batch_name,
        _text(version_name),
        input_hash,
        _text(edit_token, maximum=200),
        _text(expected_modified, maximum=200),
    )
