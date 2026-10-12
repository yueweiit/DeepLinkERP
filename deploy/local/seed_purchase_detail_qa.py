"""Synthetic display-only drafts for long procurement detail browser acceptance."""

import json

import frappe


def seed():
	if frappe.local.site != "po-grid-qa.localhost" or frappe.conf.db_name != "qa_procurement_5":
		raise RuntimeError("Only the existing isolated procurement QA database is allowed")
	from deeplinkerp_branding.services.purchase_repost_boundary import initialize

	initialize()
	if not frappe.db.exists("Purchase Order", "QA-PO-001"):
		raise RuntimeError("Expected existing synthetic procurement fixtures")
	frappe.set_user("Administrator")
	frappe.flags.mute_emails = True
	company, supplier = "QA Second Company", "QA Test Supplier"
	before = {dt: frappe.db.count(dt) for dt in ("GL Entry", "Stock Ledger Entry", "Payment Entry")}
	uom = "QA 单位：unidad de prueba larga"
	if not frappe.db.exists("UOM", uom):
		frappe.get_doc({"doctype": "UOM", "uom_name": uom, "must_be_whole_number": 0}).insert()
	warehouse_label = "QA明细长名称仓库－仅合成测试－almacén de materiales para comprobar texto completo"
	warehouse = frappe.db.get_value(
		"Warehouse", {"warehouse_name": warehouse_label, "company": company}, "name"
	)
	if not warehouse:
		warehouse = (
			frappe.get_doc(
				{"doctype": "Warehouse", "warehouse_name": warehouse_label, "company": company, "is_group": 0}
			)
			.insert()
			.name
		)
	code = "QA-DETAIL-LONG-MATERIAL-CODE-20261012-0001"
	label = (
		"QA长名称物料仅用于明细换行验收；Material de prueba con nombre bilingüe completo，禁止当作真实采购。"
		* 2
	)
	if not frappe.db.exists("Item", code):
		frappe.get_doc(
			{
				"doctype": "Item",
				"item_code": code,
				"item_name": label[:140],
				"item_group": "Services",
				"stock_uom": uom,
				"is_stock_item": 0,
			}
		).insert()
	names = {"Purchase Order": "QA-DETAIL-PO-20261012", "Purchase Receipt": "QA-DETAIL-PR-20261012"}
	for dt, name in names.items():
		if not frappe.db.exists(dt, name):
			items = [
				{
					"item_code": code,
					"warehouse": warehouse,
					"qty": qty,
					"rate": rate,
					"schedule_date": "2026-10-31",
				}
				for qty, rate in ((1234567.89, 9876.54), (2.25, 0))
			]
			frappe.get_doc(
				{
					"doctype": dt,
					"company": company,
					"supplier": supplier,
					"currency": "CNY",
					"schedule_date": "2026-10-31",
					"items": items,
				}
			).insert(set_name=name)
		if frappe.db.get_value(dt, name, "docstatus") != 0:
			raise RuntimeError("Display fixture must remain a draft")
	if before != {dt: frappe.db.count(dt) for dt in before}:
		raise RuntimeError("Display drafts must not create ledger or payment records")
	return {
		"site": frappe.local.site,
		"documents": names,
		"item_code": code,
		"warehouse": warehouse,
		"ledger_counts_unchanged": before,
	}


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
