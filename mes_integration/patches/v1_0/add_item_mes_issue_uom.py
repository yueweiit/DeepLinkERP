import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
	create_custom_fields(
		{
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
	frappe.clear_cache(doctype="Item")
