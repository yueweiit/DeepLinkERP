"""中文用途：校验项目到子公司和 ERP 站点的显式路由。"""

from __future__ import annotations

import frappe
from frappe.model.document import Document


class OverseasCostProjectRoute(Document):
    def validate(self) -> None:
        if not self.project_collection or not self.subsidiary_code or not self.erp_site:
            frappe.throw("项目路由必须包含项目、子公司和 ERP 站点。")
        if self.valid_from and self.valid_to and self.valid_from > self.valid_to:
            frappe.throw("路由生效日不能晚于失效日。")
