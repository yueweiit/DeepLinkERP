import json

import frappe
from pypika.terms import ExistsCriterion

from erpnext.selling.doctype.sales_order.sales_order import make_production_plan as native_make_production_plan


@frappe.whitelist()
def make_production_plan(source_name, target_doc=None):
	return native_make_production_plan(source_name, target_doc)


@frappe.whitelist()
def get_open_sales_orders(doc):
	frappe.has_permission("Production Plan", throw=True)

	if isinstance(doc, str):
		doc = json.loads(doc)

	production_plan = frappe.get_doc(doc)
	return get_sales_orders(production_plan)


@frappe.whitelist()
def sales_order_query(doctype=None, txt=None, searchfield=None, start=None, page_len=None, filters=None):
	frappe.has_permission("Production Plan", throw=True)
	filters = frappe._dict(filters or {})

	so_table = frappe.qb.DocType("Sales Order")
	table = frappe.qb.DocType("Sales Order Item")

	query = (
		frappe.qb.from_(so_table)
		.join(table)
		.on(table.parent == so_table.name)
		.select(table.parent)
		.distinct()
		.where(
			(table.qty > table.production_plan_qty)
			& (table.docstatus == 1)
		)
	)

	if filters.get("company"):
		query = query.where(so_table.company == filters.get("company"))

	query = query.where(so_table.status.notin(["Stopped", "Closed", "On Hold"]))

	if filters.get("sales_orders"):
		query = query.where(so_table.name.isin(filters.get("sales_orders")))

	if filters.get("item_code"):
		query = query.where(table.item_code == filters.get("item_code"))

	if txt:
		query = query.where(table.parent.like(f"%{txt}%"))

	if page_len:
		query = query.limit(page_len)

	if start:
		query = query.offset(start)

	return query.run()


def get_sales_orders(doc):
	bom = frappe.qb.DocType("BOM")
	pi = frappe.qb.DocType("Packed Item")
	so = frappe.qb.DocType("Sales Order")
	so_item = frappe.qb.DocType("Sales Order Item")

	open_so_subquery1 = frappe.qb.from_(bom).select(bom.name).where(bom.is_active == 1)

	open_so_subquery2 = (
		frappe.qb.from_(pi)
		.select(pi.name)
		.where(
			(pi.parent == so.name)
			& (pi.parent_item == so_item.item_code)
			& (
				ExistsCriterion(
					frappe.qb.from_(bom)
					.select(bom.name)
					.where((bom.item == pi.item_code) & (bom.is_active == 1))
				)
			)
		)
	)

	open_so_query = (
		frappe.qb.from_(so)
		.from_(so_item)
		.select(so.name, so.transaction_date, so.customer, so.base_grand_total)
		.distinct()
		.where(
			(so_item.parent == so.name)
			& (so.docstatus == 1)
			& (so.status.notin(["Stopped", "Closed"]))
			& (so.company == doc.company)
			& (so_item.qty > so_item.production_plan_qty)
		)
	)

	date_field_mapper = {
		"from_date": so.transaction_date >= doc.from_date,
		"to_date": so.transaction_date <= doc.to_date,
		"from_delivery_date": so_item.delivery_date >= doc.from_delivery_date,
		"to_delivery_date": so_item.delivery_date <= doc.to_delivery_date,
	}

	for field, value in date_field_mapper.items():
		if doc.get(field):
			open_so_query = open_so_query.where(value)

	for field in ("customer", "project", "sales_order_status"):
		if doc.get(field):
			so_field = "status" if field == "sales_order_status" else field
			open_so_query = open_so_query.where(so[so_field] == doc.get(field))

	if doc.item_code and frappe.db.exists("Item", doc.item_code):
		open_so_query = open_so_query.where(so_item.item_code == doc.item_code)
		open_so_subquery1 = open_so_subquery1.where(
			doc.get_bom_item_condition() or bom.item == so_item.item_code
		)

	open_so_query = open_so_query.where(
		ExistsCriterion(open_so_subquery1) | ExistsCriterion(open_so_subquery2)
	)

	return open_so_query.run(as_dict=True)

