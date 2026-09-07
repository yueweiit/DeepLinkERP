"""中文用途：校验多站点 ERP 的安全配置。"""

from __future__ import annotations

import json

import frappe
from frappe.model.document import Document


class OverseasCostERPSite(Document):
    def validate(self) -> None:
        if not str(self.site_code or "").strip():
            frappe.throw("ERP 站点编码不能为空。")
        if self.cost_update_mode not in {"DISABLED", "MANUAL", "DRAFT_PURCHASE_ORDER"}:
            frappe.throw("ERP 成本更新模式不合法。")
        if self.capability_status not in {"UNVERIFIED", "VERIFIED", "FAILED"}:
            frappe.throw("ERP 能力状态不合法。")
        if self.capability_summary_json:
            try:
                parsed = json.loads(self.capability_summary_json)
            except (TypeError, ValueError) as exc:
                raise ValueError("ERP 能力摘要必须是 JSON。") from exc
            if not isinstance(parsed, dict):
                frappe.throw("ERP 能力摘要必须是 JSON 对象。")
