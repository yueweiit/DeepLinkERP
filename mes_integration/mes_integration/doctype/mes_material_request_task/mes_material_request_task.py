import frappe
from frappe.model.document import Document


class MESMaterialRequestTask(Document):
	@staticmethod
	def clear_old_logs(days=30):
		from frappe.query_builder import Interval
		from frappe.query_builder.functions import Now

		table = frappe.qb.DocType("MES Material Request Task")
		frappe.db.delete(
			table,
			filters=(
				(table.creation < (Now() - Interval(days=days)))
				& table.status.isin(["Success", "Failed"])
			),
		)
