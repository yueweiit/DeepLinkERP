import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
	create_custom_fields(
		{
			"Sales Order Item": [
				{
					"fieldname": "custom_item_tax_amount",
					"fieldtype": "Currency",
					"label": "Item Tax Amount",
					"insert_after": "item_tax_template",
					"allow_on_submit": 1,
					"no_copy": 1,
				},
			],
		},
		update=True,
	)
	frappe.clear_cache(doctype="Sales Order Item")
