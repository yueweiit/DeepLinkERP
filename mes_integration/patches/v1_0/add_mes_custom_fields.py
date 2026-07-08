import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
	create_custom_fields(
		{
			"Stock Entry": [
				{
					"fieldname": "custom_material_request_no",
					"fieldtype": "Data",
					"insert_after": "stock_entry_type",
					"label": "Material Request No",
					"read_only": 1,
				},
				{
					"fieldname": "custom_stock_entry_no",
					"fieldtype": "Data",
					"insert_after": "custom_material_request_no",
					"label": "Stock Entry No",
					"read_only": 1,
				},
				{
					"fieldname": "custom_mes_status",
					"fieldtype": "Select",
					"insert_after": "tab_connections",
					"label": "MES Status",
					"options": "\nPushed\nUnpushed",
					"read_only": 1,
					"in_list_view": 1,
				},
			],
			"Material Request": [
				{
					"fieldname": "custom_material_request_no",
					"fieldtype": "Data",
					"insert_after": "material_request_type",
					"label": "Material Request No",
					"read_only": 1,
					"in_list_view": 1,
				},
				{
					"fieldname": "custom_stock_entry_no",
					"fieldtype": "Data",
					"insert_after": "custom_material_request_no",
					"label": "Stock Entry No",
					"read_only": 1,
					"in_list_view": 1,
				},
				{
					"fieldname": "custom_odt",
					"fieldtype": "Data",
					"insert_after": "auto_created_via_reorder",
					"label": "odt",
					"read_only": 1,
				},
			],
			"Material Request Item": [
				{
					"fieldname": "custom_recycled_material_weight",
					"fieldtype": "Data",
					"insert_after": "custom_transferred_qty",
					"label": "recycled material weight",
				},
				{
					"fieldname": "custom_new_material_weight",
					"fieldtype": "Data",
					"insert_after": "custom_recycled_material_weight",
					"label": "new material weight",
				},
			],
			"Item": [
				{
					"fieldname": "custom_mes_issue_uom",
					"fieldtype": "Link",
					"insert_after": "stock_uom",
					"label": "MES Default Issue UOM",
					"options": "UOM",
					"description": "Default UOM used by the MES Material Request issue dialog. It must exist in the item's UOM Conversion Details or match the stock UOM.",
				},
			],
		},
		update=True,
	)

	for doctype in ("Stock Entry", "Material Request", "Material Request Item", "Item"):
		frappe.clear_cache(doctype=doctype)
