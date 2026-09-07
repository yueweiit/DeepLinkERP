"""中文用途：保存只追加的费用已齐确认和失效历史。"""

from __future__ import annotations

import frappe
from frappe.model.document import Document


COMPLETION_STATUSES = {"CONFIRMED", "INVALIDATED"}


class OverseasCostFeeCompletion(Document):
    def validate(self) -> None:
        if not self.batch or not self.version or not self.input_hash:
            frappe.throw("费用完结记录必须包含批次、版本和输入哈希。")
        if self.status not in COMPLETION_STATUSES:
            frappe.throw("费用完结状态不合法。")

    def before_save(self) -> None:
        if not self.is_new():
            frappe.throw("不能覆盖原费用完结记录；请追加新的失效或确认记录。")
