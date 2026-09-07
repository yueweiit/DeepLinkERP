"""中文用途：把已保存的运费比较保持为不可变审计记录。"""

from __future__ import annotations

import frappe
from frappe.model.document import Document


class OverseasFreightComparison(Document):
    def validate(self) -> None:
        if not self.batch or not self.packing_snapshot:
            frappe.throw("运费试算必须关联批次和已确认装箱快照。")

    def before_save(self) -> None:
        if self.get_doc_before_save():
            frappe.throw("不能修改已保存的运费试算；请基于当前报价另存一条比较记录。")

