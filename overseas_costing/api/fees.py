"""费用与凭证工作台的最小权限 API。"""

from __future__ import annotations

import json

import frappe

from overseas_costing.services import fee_service
from overseas_costing.services.access_control import require_batch_permission


MAX_FEE_PAYLOAD_BYTES = 100_000
MAX_IDENTIFIER_LENGTH = 300
MAX_REMARK_LENGTH = 2_000


def _bounded_json_object(value) -> dict:
    if isinstance(value, dict):
        encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        payload = value
    else:
        encoded = str(value or "{}")
        if len(encoded.encode("utf-8")) > MAX_FEE_PAYLOAD_BYTES:
            raise ValueError("费用参数过大。")
        try:
            payload = json.loads(encoded)
        except (TypeError, ValueError, json.JSONDecodeError) as error:
            raise ValueError("费用参数不是有效 JSON。") from error
    if len(encoded.encode("utf-8")) > MAX_FEE_PAYLOAD_BYTES:
        raise ValueError("费用参数过大。")
    if not isinstance(payload, dict):
        raise ValueError("费用参数必须是 JSON 对象。")
    return payload


def _identifier(value) -> str:
    normalized = str(value or "").strip()
    if not normalized or len(normalized) > MAX_IDENTIFIER_LENGTH:
        raise ValueError("记录标识不合法。")
    return normalized


@frappe.whitelist()
def get_fee_worklist(batch_name, version_name=None):
    batch_name = require_batch_permission(batch_name, "read")
    return fee_service.get_fee_worklist(batch_name, str(version_name or "") or None)


@frappe.whitelist()
def save_fee(batch_name, version_name, fee_payload, edit_token, expected_modified):
    batch_name = require_batch_permission(batch_name, "write")
    return fee_service.save_fee(
        batch_name=batch_name,
        version_name=_identifier(version_name),
        fee_payload=_bounded_json_object(fee_payload),
        edit_token=str(edit_token or "")[:MAX_IDENTIFIER_LENGTH],
        expected_modified=str(expected_modified or "")[:MAX_IDENTIFIER_LENGTH],
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
    batch_name = require_batch_permission(batch_name, "write")
    return fee_service.link_fee_evidence(
        batch_name=batch_name,
        fee_rule=_identifier(fee_rule),
        attachment=_identifier(attachment),
        evidence_role=str(evidence_role or "")[:MAX_IDENTIFIER_LENGTH],
        edit_token=str(edit_token or "")[:MAX_IDENTIFIER_LENGTH],
        expected_modified=str(expected_modified or "")[:MAX_IDENTIFIER_LENGTH],
    )


@frappe.whitelist()
def set_fee_evidence_status(
    batch_name,
    evidence_name,
    status,
    remark=None,
    edit_token=None,
    expected_modified=None,
):
    batch_name = require_batch_permission(batch_name, "write")
    return fee_service.set_fee_evidence_status(
        batch_name=batch_name,
        evidence_name=_identifier(evidence_name),
        status=str(status or "")[:40],
        remark=str(remark or "")[:MAX_REMARK_LENGTH],
        edit_token=str(edit_token or "")[:MAX_IDENTIFIER_LENGTH],
        expected_modified=str(expected_modified or "")[:MAX_IDENTIFIER_LENGTH],
    )
