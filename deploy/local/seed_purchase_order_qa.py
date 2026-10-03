"""Explicitly authorized, isolated local PO display fixtures. Never run on a business site."""

import json
import os

import frappe


QA_SITE = "po-grid-qa.localhost"
QA_READER = "qa-po-reader@example.invalid"


def seed():
	if frappe.local.site != QA_SITE:
		raise RuntimeError("QA fixtures are permitted only on po-grid-qa.localhost")
	frappe.set_user("Administrator")
	frappe.flags.mute_emails = True
	if frappe.db.count("Purchase Order") and not frappe.db.exists("Purchase Order", "QA-PO-001"):
		raise RuntimeError("Expected an empty isolated test site's Purchase Orders")
	if not frappe.db.exists("Company", "QA Second Company"):
		frappe.get_doc({"doctype": "Company", "company_name": "QA Second Company", "abbr": "QAB", "default_currency": "CNY", "country": "China"}).insert()
	for name in ["QA Test Supplier", "QA测试供应商（仅用于长名称和悬停验收）" * 4]:
		if not frappe.db.exists("Supplier", name):
			frappe.get_doc({"doctype": "Supplier", "supplier_name": name, "supplier_group": "All Supplier Groups", "supplier_type": "Company"}).insert()
	if not frappe.db.exists("Item", "QA-PO-ITEM"):
		frappe.get_doc({"doctype": "Item", "item_code": "QA-PO-ITEM", "item_name": "QA采购列表测试物料", "item_group": "Services", "stock_uom": "Nos", "is_stock_item": 0}).insert()
	project = frappe.db.get_value("Project", {"project_name": "QA Purchase Grid Project"}, "name")
	if not project:
		project = frappe.get_doc({"doctype": "Project", "project_name": "QA Purchase Grid Project", "company": "Yuewei"}).insert().name
	states = [
		(0, "Draft", 0, 0), (1, "To Receive", 0, 100), (1, "To Bill", 100, 20),
		(1, "Completed", 100, 100), (1, "Closed", 10, 10),
		(1, "To Receive and Bill", 25, 10), (1, "On Hold", 0, 0), (2, "Cancelled", 0, 0),
	]
	for index in range(1, 131):
		name = f"QA-PO-{index:03d}"
		if frappe.db.exists("Purchase Order", name):
			continue
		currency = ["CNY", "USD", "EUR"][(index - 1) % 3]
		company = "Yuewei" if index <= 120 else "QA Second Company"
		po = frappe.get_doc({
			"doctype": "Purchase Order", "company": company,
			"supplier": "QA测试供应商（仅用于长名称和悬停验收）" * 4 if index == 2 else "QA Test Supplier",
			"transaction_date": "2026-10-01", "schedule_date": "2026-10-31",
			"currency": currency, "conversion_rate": {"CNY": 1, "USD": 7, "EUR": 8}[currency],
			"project": project if index == 2 else None,
			"items": [{"item_code": "QA-PO-ITEM", "qty": 1, "rate": 0 if index == 1 else index * 10, "schedule_date": "2026-10-31"}],
		})
		po.insert(set_name=name)
		# Display-state fixtures only: never submit, pay, post GL, or update real stock.
		docstatus, status, received, billed = states[index - 1] if index <= len(states) else states[0]
		frappe.db.set_value("Purchase Order", name, {
			"docstatus": docstatus, "status": status, "per_received": received, "per_billed": billed,
			"advance_paid": 5 if index == 2 else 0,
			"party_account_currency": "CNY",
			"advance_payment_status": "Partially Paid" if index == 2 else "Not Initiated",
		}, update_modified=False)
	if not frappe.db.exists("User", QA_READER):
		frappe.get_doc({"doctype": "User", "email": QA_READER, "first_name": "QA Restricted Reader", "send_welcome_email": 0, "new_password": os.environ["QA_PASSWORD"], "roles": [{"role": "Purchase User"}]}).insert()
	if not frappe.db.exists("User Permission", {"user": QA_READER, "allow": "Company", "for_value": "Yuewei"}):
		frappe.get_doc({"doctype": "User Permission", "user": QA_READER, "allow": "Company", "for_value": "Yuewei", "apply_to_all_doctypes": 1}).insert()
	frappe.db.commit()
	print(json.dumps({"site": QA_SITE, "count": frappe.db.count("Purchase Order"), "gl_entries": frappe.db.count("GL Entry"), "stock_ledger_entries": frappe.db.count("Stock Ledger Entry"), "totals": frappe.db.sql("select currency, sum(grand_total) total from `tabPurchase Order` group by currency order by currency", as_dict=True)}, ensure_ascii=False, default=str))


if __name__ == "__main__":
	frappe.init(site=QA_SITE, sites_path=".")
	frappe.connect()
	try:
		seed()
	finally:
		frappe.db.rollback()
		frappe.destroy()
