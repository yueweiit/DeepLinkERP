"""中文用途：校验可审计且不含密钥的 ERP 同步请求。"""

from __future__ import annotations

import json

import frappe
from frappe.model.document import Document


class OverseasCostERPSyncRequest(Document):
    def validate(self) -> None:
        if self.operation not in {"CREATE", "UPDATE_COST", "VERIFY"}:
            frappe.throw("ERP 同步操作不合法。")
        if self.status not in {"PENDING", "RUNNING", "SUCCESS", "FAILED", "UNCERTAIN", "MANUAL_REQUIRED", "SUPERSEDED"}:
            frappe.throw("ERP 同步请求状态不合法。")
        for fieldname in ("safe_payload_json", "safe_response_json"):
            value = getattr(self, fieldname, "")
            if not value:
                continue
            try:
                parsed = json.loads(value)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"{fieldname} 必须是 JSON。") from exc
            if not isinstance(parsed, (dict, list)):
                frappe.throw(f"{fieldname} 必须是 JSON 对象或数组。")
