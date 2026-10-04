"""Explicitly authorized, isolated local PO display fixtures. Never run on a business site."""

import json
import os
import sys

import frappe


QA_SITE = "po-grid-qa.localhost"
QA_READER = "qa-po-reader@example.invalid"


def seed_finance_flow():
	"""Native, disposable browser fixtures; the old display-only seed is unchanged."""
	if frappe.local.site != QA_SITE:
		raise RuntimeError("Financial browser fixtures require the isolated QA site")
	frappe.set_user("Administrator")
	frappe.flags.in_test = True
	frappe.flags.mute_emails = True
	from erpnext.buying.doctype.purchase_order.purchase_order import make_purchase_receipt
	from erpnext.stock.doctype.purchase_receipt.purchase_receipt import make_purchase_invoice
	from frappe.utils import add_days, nowdate
	company = "QA Second Company"
	if not all(frappe.db.exists(doctype, name) for doctype, name in (
		("Company", company), ("Supplier", "QA Test Supplier"), ("Item", "QA-PO-ITEM"))):
		raise RuntimeError("Expected existing isolated QA master data")
	# Never turn the display-only 130 orders into native submitted transactions.
	def order(index, item_code="QA-PO-ITEM"):
		name = f"QA-FIN-PO-{index:02}"
		if frappe.db.exists("Purchase Order", name):
			return frappe.get_doc("Purchase Order", name)
		doc = frappe.get_doc({"doctype": "Purchase Order", "company": company,
			"supplier": "QA Test Supplier", "currency": "CNY", "schedule_date": add_days(nowdate(), 1),
			"items": [{"item_code": item_code, "qty": 10, "rate": 1000,
				"schedule_date": add_days(nowdate(), 1)}]}).insert(set_name=name)
		doc.submit()
		return doc
	def receipt(po, name, qty, submit=False):
		if frappe.db.exists("Purchase Receipt", name):
			return frappe.get_doc("Purchase Receipt", name)
		doc = make_purchase_receipt(po.name)
		doc.items[0].qty = qty
		doc.insert(set_name=name)
		if submit:
			doc.submit()
		return doc
	po = order(1)
	ready = receipt(po, "QA-FIN-PR-READY", 4, submit=True)
	# Real drafts give the 100-row pagination control a second page without posting.
	for index in range(1, 102):
		receipt(po, f"QA-FIN-PR-DRAFT-{index:03}", 1)
	shared_receipts = [receipt(order(index + 2), f"QA-FIN-PR-SHARED-{index + 1}", 1, submit=True)
		for index in range(2)]
	shared_name = "QA-FIN-PI-SHARED"
	if not frappe.db.exists("Purchase Invoice", shared_name):
		shared = make_purchase_invoice(shared_receipts[0].name)
		shared = make_purchase_invoice(shared_receipts[1].name, target_doc=shared)
		shared.insert(set_name=shared_name)
		shared.submit()
	pending_order = order(4)
	# Nos correctly rejects fractions. A separate non-stock material/UOM tests
	# display rounding without weakening any existing UOM or native validation.
	if not frappe.db.exists("UOM", "QA-FIN Fraction Unit"):
		frappe.get_doc({"doctype": "UOM", "uom_name": "QA-FIN Fraction Unit", "must_be_whole_number": 0}).insert()
	if not frappe.db.exists("Item", "QA-FIN-FRACTION-ITEM"):
		frappe.get_doc({"doctype": "Item", "item_code": "QA-FIN-FRACTION-ITEM",
			"item_name": "QA小数数量原生解析物料", "item_group": "Services",
			"stock_uom": "QA-FIN Fraction Unit", "is_stock_item": 0}).insert()
	fraction_receipt = receipt(order(5, "QA-FIN-FRACTION-ITEM"), "QA-FIN-PR-FRACTION", 4, submit=True)
	frappe.db.commit()
	return {"site": QA_SITE, "prefix": "QA-FIN-", "purchase_order": po.name,
		"pending_order": pending_order.name,
		"fraction_receipt": fraction_receipt.name,
		"ready_receipt": ready.name, "shared_receipts": [doc.name for doc in shared_receipts],
		"shared_invoice": shared_name, "draft_receipts": 101,
		"stock_item": bool(frappe.db.get_value("Item", "QA-PO-ITEM", "is_stock_item"))}


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
		if sys.argv[1:] == ["--finance-flow"]:
			print(json.dumps(seed_finance_flow(), ensure_ascii=False))
		elif not sys.argv[1:]:
			seed()
		else:
			raise RuntimeError("Unknown QA seed arguments")
	finally:
		frappe.db.rollback()
		frappe.destroy()
