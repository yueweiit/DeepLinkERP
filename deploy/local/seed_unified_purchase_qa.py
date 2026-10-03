"""Add identifiable draft fixtures ONLY to the existing isolated local QA site."""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def seed():
	if frappe.local.site != "po-grid-qa.localhost":
		raise RuntimeError("Unified purchase fixtures are restricted to po-grid-qa.localhost")
	frappe.set_user("Administrator")
	frappe.flags.mute_emails = True
	if frappe.db.sql("select count(*) from `tabPurchase Order` where name not like 'QA-%'")[0][0]:
		raise RuntimeError("QA site contains non-fixture purchase orders; refusing to seed")
	create_custom_fields({"Purchase Order": [{"fieldname": "custom_oa_purchase_expense", "label": "OA来源单", "fieldtype": "Data", "insert_after": "supplier"}]})
	if not frappe.get_meta("OA Purchase Request").has_field("target_company"):
		create_custom_fields({"OA Purchase Request": [{"fieldname": "target_company", "label": "公司", "fieldtype": "Link", "options": "Company"}]})
	for index, amount in ((1, 25.12345), (2, 0)):
		name = f"QA-UP-PO-{index:02}"
		if not frappe.db.exists("Purchase Order", name):
			frappe.get_doc({
				"doctype": "Purchase Order", "company": "Yuewei", "supplier": "QA Test Supplier",
				"transaction_date": "2026-10-02", "schedule_date": "2026-10-31",
				"currency": "CNY", "conversion_rate": 1,
				"custom_oa_purchase_expense": "QA-UP-OA-01" if index == 1 else None,
				"items": [{"item_code": "QA-PO-ITEM", "qty": 1, "rate": amount, "schedule_date": "2026-10-31"}],
			}).insert(set_name=name)
	for index, currency, amount, approval in ((1, "人民币RMB", 25.12345, "通过"), (2, None, 500, "审批中"), (3, "比索Peso", 35, "撤销")):
		name = f"QA-UP-OA-{index:02}"
		if not frappe.db.exists("OA Purchase Request", name):
			frappe.get_doc({
				"doctype": "OA Purchase Request", "oa_code": name, "apply_date": "2026-10-03",
				"currency": currency, "detail_total_amount": amount, "approval_status": approval,
				"target_company": "Yuewei" if index == 1 else None,
				"purchase_order": "QA-UP-PO-01" if index == 1 else None,
				"items": [{"item_name": "QA测试申请", "qty": 1, "amount": amount}],
			}).insert(set_name=name)
	frappe.db.set_value("OA Purchase Request", "QA-UP-OA-01", "target_company", "Yuewei", update_modified=False)
	frappe.db.commit()
	return {"site": frappe.local.site, "purchase_orders": frappe.db.count("Purchase Order"), "oa_requests": frappe.db.count("OA Purchase Request"), "gl_entries": frappe.db.count("GL Entry"), "stock_entries": frappe.db.count("Stock Ledger Entry")}


if __name__ == "__main__":
	frappe.init(site="po-grid-qa.localhost", sites_path="/home/frappe/frappe-bench/sites")
	frappe.connect()
	try:
		print(frappe.as_json(seed()))
	finally:
		frappe.destroy()
