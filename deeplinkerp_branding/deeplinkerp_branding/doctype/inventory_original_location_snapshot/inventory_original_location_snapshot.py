"""库存原始库位快照行。"""

from __future__ import annotations

import frappe
from frappe.model.document import Document


class InventoryOriginalLocationSnapshot(Document):
	def validate(self) -> None:
		required = (
			"snapshot_key",
			"snapshot_date",
			"company",
			"item_code",
			"warehouse",
			"original_location",
			"stock_uom",
			"idempotency_key",
		)
		missing = [fieldname for fieldname in required if not self.get(fieldname)]
		if missing:
			frappe.throw("库存库位快照缺少必填字段：" + "、".join(missing))
