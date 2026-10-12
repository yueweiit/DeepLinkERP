"""Display-only 52-line draft in the existing isolated QA database."""

import json

import frappe


def seed():
	if frappe.local.site != "po-grid-qa.localhost" or frappe.conf.db_name != "qa_procurement_5":
		raise RuntimeError("Only the existing isolated procurement QA database is allowed")
	frappe.set_user("Administrator")
	frappe.flags.mute_emails = True
	company = "QA Second Company"
	if frappe.db.get_value("Company", company, "custom_enable_crm_integration"):
		raise RuntimeError("Display fixture must not use an integration-enabled company")
	code = "QA-DETAIL-LONG-MATERIAL-CODE-20261012-0001"
	if not frappe.db.exists("Item", code):
		raise RuntimeError("Expected existing synthetic long-text procurement item")
	warehouse = frappe.db.get_value(
		"Warehouse", {"company": company, "warehouse_name": ["like", "QA明细长名称仓库%"]}, "name"
	)
	if not warehouse:
		raise RuntimeError("Expected existing synthetic warehouse")
	protected = [
		"GL Entry",
		"Stock Ledger Entry",
		"Payment Entry",
		"Sales Invoice",
		"Delivery Note",
		"Work Order",
		"Production Plan",
		"CRM Integration Log",
		"MES Integration Log",
	]
	before = {dt: frappe.db.count(dt) for dt in protected if frappe.db.exists("DocType", dt)}
	name = "QA-SALES-DETAIL-20261012"
	if not frappe.db.exists("Sales Order", name):
		items = [
			{
				"item_code": code,
				"warehouse": warehouse,
				"qty": 1234567.89 if index == 0 else index + 1,
				"rate": 9876.54 if index == 0 else 19,
				"delivery_date": "2026-10-31",
				"description": (
					"QA合成销售明细，仅用于三行文字、滚动和完整字段验收；"
					"Descripción larga para comprobar el diseño sin crear movimientos reales. " * 6
				),
				"custom_specifications": "QA长规格－sin truncar－" * 6,
			}
			for index in range(52)
		]
		frappe.get_doc(
			{
				"doctype": "Sales Order",
				"company": company,
				"customer": "QA Purchase Payments Customer",
				"currency": "CNY",
				"transaction_date": "2026-10-12",
				"delivery_date": "2026-10-31",
				"items": items,
			}
		).insert(set_name=name)
	doc = frappe.get_doc("Sales Order", name)
	if doc.docstatus != 0 or len(doc.items) != 52 or doc.company != company:
		raise RuntimeError("Display fixture must remain a 52-line synthetic draft")
	after = {dt: frappe.db.count(dt) for dt in before}
	if before != after:
		raise RuntimeError("Display draft must not create ledgers or downstream documents")
	return {"site": frappe.local.site, "name": name, "rows": len(doc.items), "protected_counts": after}


if __name__ == "__main__":
	frappe.init(site="po-grid-qa.localhost")
	frappe.connect()
	try:
		result = seed()
		frappe.db.commit()
		print(json.dumps(result, ensure_ascii=False))
	except Exception:
		frappe.db.rollback()
		raise
	finally:
		frappe.destroy()
