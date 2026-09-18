# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt


import frappe
from frappe import _
from frappe.query_builder.functions import IfNull, Sum
from frappe.utils import flt, today
from frappe.utils.nestedset import get_descendants_of
from pypika.terms import ExistsCriterion

from erpnext.stock.utils import (
	is_reposting_item_valuation_in_progress,
	update_included_uom_in_report,
)


def execute(filters=None):
	is_reposting_item_valuation_in_progress()
	filters = frappe._dict(filters or {})
	include_uom = filters.get("include_uom")
	columns = get_columns()
	item_groups = get_item_groups(filters)
	bin_list = get_bin_list(filters)
	item_codes = {row.item_code for row in bin_list if row.item_code}
	item_map = get_item_map(
		filters.get("item_code"),
		include_uom,
		item_codes=item_codes,
		item_groups=item_groups,
		brand=filters.get("brand"),
	)

	warehouse_display = get_warehouse_display_map({row.warehouse for row in bin_list})
	pos_reserved_qty = get_pos_reserved_qty_map(
		{(row.item_code, row.warehouse) for row in bin_list}
	)
	data = []
	conversion_factors = []
	for bin in bin_list:
		item = item_map.get(bin.item_code)

		if not item:
			# likely an item that has reached its end of life
			continue

		warehouse = warehouse_display.get(bin.warehouse, {})
		company = warehouse.get("company")

		if filters.brand and filters.brand != item.brand:
			continue

		elif item_groups and item.item_group not in item_groups:
			continue

		elif filters.company and filters.company != company:
			continue

		re_order_level = re_order_qty = 0

		for d in item.get("reorder_levels"):
			if d.warehouse == bin.warehouse:
				re_order_level = d.warehouse_reorder_level
				re_order_qty = d.warehouse_reorder_qty

		shortage_qty = 0
		if (re_order_level or re_order_qty) and re_order_level > bin.projected_qty:
			shortage_qty = re_order_level - flt(bin.projected_qty)

		reserved_qty_for_pos = pos_reserved_qty.get((bin.item_code, bin.warehouse), 0)
		if reserved_qty_for_pos:
			bin.projected_qty -= reserved_qty_for_pos

		data.append(
			[
				item.name,
				item.item_name,
				item.description,
				item.item_group,
				item.brand,
				bin.warehouse,
				warehouse.get("warehouse_name", ""),
				warehouse.get("location_code", ""),
				item.stock_uom,
				bin.actual_qty,
				bin.planned_qty,
				bin.indented_qty,
				bin.ordered_qty,
				bin.reserved_qty,
				bin.reserved_qty_for_production,
				bin.reserved_qty_for_production_plan,
				bin.reserved_qty_for_sub_contract,
				reserved_qty_for_pos,
				bin.projected_qty,
				re_order_level,
				re_order_qty,
				shortage_qty,
			]
		)

		if include_uom:
			conversion_factors.append(item.conversion_factor)

	update_included_uom_in_report(columns, data, include_uom, conversion_factors)
	return columns, data


def get_columns():
	return [
		{
			"label": _("Item Code"),
			"fieldname": "item_code",
			"fieldtype": "Link",
			"options": "Item",
			"width": 140,
		},
		{"label": _("Item Name"), "fieldname": "item_name", "width": 100},
		{"label": _("Description"), "fieldname": "description", "width": 200},
		{
			"label": _("Item Group"),
			"fieldname": "item_group",
			"fieldtype": "Link",
			"options": "Item Group",
			"width": 100,
		},
		{
			"label": _("Brand"),
			"fieldname": "brand",
			"fieldtype": "Link",
			"options": "Brand",
			"width": 100,
		},
		{
			"label": _("Warehouse"),
			"fieldname": "warehouse",
			"fieldtype": "Link",
			"options": "Warehouse",
			"width": 120,
		},
		{
			"label": _("Warehouse Name"),
			"fieldname": "warehouse_name",
			"fieldtype": "Data",
			"width": 180,
		},
		{
			"label": _("Location Code"),
			"fieldname": "location_code",
			"fieldtype": "Data",
			"width": 110,
		},
		{
			"label": _("UOM"),
			"fieldname": "stock_uom",
			"fieldtype": "Link",
			"options": "UOM",
			"width": 100,
		},
		{
			"label": _("Actual Qty"),
			"fieldname": "actual_qty",
			"fieldtype": "Float",
			"width": 100,
			"convertible": "qty",
		},
		{
			"label": _("Planned Qty"),
			"fieldname": "planned_qty",
			"fieldtype": "Float",
			"width": 100,
			"convertible": "qty",
		},
		{
			"label": _("Requested Qty"),
			"fieldname": "indented_qty",
			"fieldtype": "Float",
			"width": 110,
			"convertible": "qty",
		},
		{
			"label": _("Ordered Qty"),
			"fieldname": "ordered_qty",
			"fieldtype": "Float",
			"width": 100,
			"convertible": "qty",
		},
		{
			"label": _("Reserved Qty"),
			"fieldname": "reserved_qty",
			"fieldtype": "Float",
			"width": 100,
			"convertible": "qty",
		},
		{
			"label": _("Reserved for Production"),
			"fieldname": "reserved_qty_for_production",
			"fieldtype": "Float",
			"width": 100,
			"convertible": "qty",
		},
		{
			"label": _("Reserved for Production Plan"),
			"fieldname": "reserved_qty_for_production_plan",
			"fieldtype": "Float",
			"width": 100,
			"convertible": "qty",
		},
		{
			"label": _("Reserved for Sub Contracting"),
			"fieldname": "reserved_qty_for_sub_contract",
			"fieldtype": "Float",
			"width": 100,
			"convertible": "qty",
		},
		{
			"label": _("Reserved for POS Transactions"),
			"fieldname": "reserved_qty_for_pos",
			"fieldtype": "Float",
			"width": 100,
			"convertible": "qty",
		},
		{
			"label": _("Projected Qty"),
			"fieldname": "projected_qty",
			"fieldtype": "Float",
			"width": 100,
			"convertible": "qty",
		},
		{
			"label": _("Reorder Level"),
			"fieldname": "re_order_level",
			"fieldtype": "Float",
			"width": 100,
			"convertible": "qty",
		},
		{
			"label": _("Reorder Qty"),
			"fieldname": "re_order_qty",
			"fieldtype": "Float",
			"width": 100,
			"convertible": "qty",
		},
		{
			"label": _("Shortage Qty"),
			"fieldname": "shortage_qty",
			"fieldtype": "Float",
			"width": 100,
			"convertible": "qty",
		},
	]


def get_bin_list(filters):
	bin = frappe.qb.DocType("Bin")
	query = (
		frappe.qb.from_(bin)
		.select(
			bin.item_code,
			bin.warehouse,
			bin.actual_qty,
			bin.planned_qty,
			bin.indented_qty,
			bin.ordered_qty,
			bin.reserved_qty,
			bin.reserved_qty_for_production,
			bin.reserved_qty_for_sub_contract,
			bin.reserved_qty_for_production_plan,
			bin.projected_qty,
		)
		.orderby(bin.item_code, bin.warehouse)
	)

	if filters.item_code:
		query = query.where(bin.item_code == filters.item_code)

	if filters.get("company"):
		company_warehouse = frappe.qb.DocType("Warehouse")
		query = query.join(company_warehouse).on(bin.warehouse == company_warehouse.name)
		query = query.where(company_warehouse.company == filters.company)

	if filters.warehouse:
		warehouse_details = frappe.db.get_value("Warehouse", filters.warehouse, ["lft", "rgt"], as_dict=1)

		if warehouse_details:
			wh = frappe.qb.DocType("Warehouse")
			query = query.where(
				ExistsCriterion(
					frappe.qb.from_(wh)
					.select(wh.name)
					.where(
						(wh.lft >= warehouse_details.lft)
						& (wh.rgt <= warehouse_details.rgt)
						& (bin.warehouse == wh.name)
					)
				)
			)

	warehouse_names = get_matching_warehouse_names(filters)
	if warehouse_names is not None:
		if not warehouse_names:
			return []

		query = query.where(bin.warehouse.isin(warehouse_names))

	bin_list = query.run(as_dict=True)

	return bin_list


def get_item_groups(filters):
	item_groups = []
	if filters.get("item_group"):
		item_groups.append(filters.item_group)
		item_groups.extend(get_descendants_of("Item Group", filters.item_group))
	return item_groups


def get_pos_reserved_qty_map(item_warehouse_pairs):
	"""Return POS reservations for all report rows using two grouped queries."""
	if not item_warehouse_pairs:
		return {}

	item_codes = sorted({item_code for item_code, _ in item_warehouse_pairs if item_code})
	warehouses = sorted({warehouse for _, warehouse in item_warehouse_pairs if warehouse})
	if not item_codes or not warehouses:
		return {}

	reserved_qty = {}
	for child_table, qty_column in (("POS Invoice Item", "stock_qty"), ("Packed Item", "qty")):
		pos_invoice = frappe.qb.DocType("POS Invoice")
		pos_item = frappe.qb.DocType(child_table)
		rows = (
			frappe.qb.from_(pos_invoice)
			.join(pos_item)
			.on(pos_invoice.name == pos_item.parent)
			.select(
				pos_item.item_code,
				pos_item.warehouse,
				Sum(pos_item[qty_column]).as_("reserved_qty"),
			)
			.where(
				(IfNull(pos_invoice.consolidated_invoice, "") == "")
				& (pos_item.docstatus == 1)
				& pos_item.item_code.isin(item_codes)
				& pos_item.warehouse.isin(warehouses)
			)
			.groupby(pos_item.item_code, pos_item.warehouse)
		).run(as_dict=True)

		for row in rows:
			key = (row.item_code, row.warehouse)
			reserved_qty[key] = reserved_qty.get(key, 0) + flt(row.reserved_qty)

	return reserved_qty


def get_matching_warehouse_names(filters):
	"""Resolve the mobile-style warehouse name and location filters to leaf warehouses."""
	warehouse_name = str(filters.get("warehouse_name") or "").strip()
	location_code = str(filters.get("location_code") or "").strip()
	if not warehouse_name and not location_code:
		return None

	warehouse_filters = {"is_group": 0, "disabled": 0}
	if filters.get("company"):
		warehouse_filters["company"] = filters.company

	selected_warehouse = None
	if warehouse_name:
		selected_warehouse = frappe.db.get_value(
			"Warehouse", warehouse_name, ["lft", "rgt"], as_dict=True
		)
		if selected_warehouse:
			warehouse_filters["lft"] = [">=", selected_warehouse.lft]
			warehouse_filters["rgt"] = ["<=", selected_warehouse.rgt]

	warehouses = frappe.get_all(
		"Warehouse",
		filters=warehouse_filters,
		fields=["name", "warehouse_name", "parent_warehouse", "company"],
		limit_page_length=0,
	)
	return [
		row.get("name")
		for row in warehouses
		if matches_warehouse_display(
			row, "" if selected_warehouse else warehouse_name, location_code
		)
	]


def get_warehouse_display_map(warehouse_names):
	if not warehouse_names:
		return {}

	warehouses = frappe.get_all(
		"Warehouse",
		filters={"name": ["in", list(warehouse_names)]},
		fields=["name", "warehouse_name", "parent_warehouse", "company"],
		limit_page_length=0,
	)
	return {row.get("name"): get_warehouse_display(row) for row in warehouses}


def matches_warehouse_display(row, warehouse_name, location_code):
	display = get_warehouse_display(row)
	query_name = warehouse_name.casefold()
	query_location = location_code.casefold()

	if query_name:
		name_candidates = (
			row.get("name"),
			row.get("warehouse_name"),
			row.get("parent_warehouse"),
			display["warehouse_name"],
			display["parent_warehouse"],
			display["display_name"],
		)
		if not any(query_name in str(value or "").casefold() for value in name_candidates):
			return False

	if query_location:
		location_candidates = (row.get("name"), display["location_code"], display["display_name"])
		if not any(query_location in str(value or "").casefold() for value in location_candidates):
			return False

	return True


def get_warehouse_display(row):
	"""Keep desktop report warehouse labels consistent with the mobile inventory query."""
	raw_name = str(row.get("warehouse_name") or row.get("name") or "").strip()
	parent_name = str(row.get("parent_warehouse") or "").strip()
	company_suffix = get_warehouse_company_suffix(parent_name)
	display_name = (
		raw_name[: -len(company_suffix)].strip()
		if company_suffix and raw_name.endswith(company_suffix)
		else raw_name
	)
	parent_display = (
		parent_name[: -len(company_suffix)].strip()
		if company_suffix and parent_name.endswith(company_suffix)
		else parent_name
	)
	location_code = display_name.split(None, 1)[0] if display_name else ""
	warehouse_label = display_name[len(location_code) :].strip() if location_code else display_name

	return {
		"display_name": display_name,
		"location_code": location_code,
		"warehouse_name": warehouse_label or parent_display,
		"parent_warehouse": parent_display,
		"company": row.get("company"),
	}


def get_warehouse_company_suffix(parent_name):
	separator_index = parent_name.rfind(" - ")
	return parent_name[separator_index:] if separator_index >= 0 else ""


def get_item_map(item_code, include_uom, item_codes=None, item_groups=None, brand=None):
	"""Optimization: get only the item doc and re_order_levels table"""

	bin = frappe.qb.DocType("Bin")
	item = frappe.qb.DocType("Item")

	query = (
		frappe.qb.from_(item)
		.select(item.name, item.item_name, item.description, item.item_group, item.brand, item.stock_uom)
		.where(
			(item.is_stock_item == 1)
			& (item.disabled == 0)
			& (
				(item.end_of_life > today())
				| (item.end_of_life.isnull())
				| (item.end_of_life == "0000-00-00")
			)
			& (ExistsCriterion(frappe.qb.from_(bin).select(bin.name).where(bin.item_code == item.name)))
		)
	)

	if item_code:
		query = query.where(item.item_code == item_code)
	elif item_codes is not None:
		if not item_codes:
			return {}
		query = query.where(item.name.isin(sorted(item_codes)))

	if item_groups:
		query = query.where(item.item_group.isin(item_groups))

	if brand:
		query = query.where(item.brand == brand)

	if include_uom:
		ucd = frappe.qb.DocType("UOM Conversion Detail")
		query = query.select(ucd.conversion_factor)
		query = query.left_join(ucd).on((ucd.parent == item.name) & (ucd.uom == include_uom))

	items = query.run(as_dict=True)
	item_names = [row.name for row in items]
	if not item_names:
		return {}

	ir = frappe.qb.DocType("Item Reorder")
	query = frappe.qb.from_(ir).select("*")
	query = query.where(ir.parent.isin(item_names))

	reorder_levels = frappe._dict()
	for d in query.run(as_dict=True):
		if d.parent not in reorder_levels:
			reorder_levels[d.parent] = []

		reorder_levels[d.parent].append(d)

	item_map = frappe._dict()
	for item in items:
		item["reorder_levels"] = reorder_levels.get(item.name) or []
		item_map[item.name] = item

	return item_map
