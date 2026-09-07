"""中文用途：校验本地物料行与远端采购单行的稳定关联。"""

from __future__ import annotations

import frappe
from frappe.model.document import Document


class OverseasCostERPDocumentLink(Document):
    def validate(self) -> None:
        if not self.batch or not self.stable_line_key or not self.site_code or not self.business_key:
            frappe.throw("ERP 单据关联缺少批次、稳定行、站点或业务键。")
        if self.status not in {"UNVERIFIED", "VERIFIED", "SUCCESS", "FAILED", "MANUAL_REQUIRED"}:
            frappe.throw("ERP 单据关联状态不合法。")
