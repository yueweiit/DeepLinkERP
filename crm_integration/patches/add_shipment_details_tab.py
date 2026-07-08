import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
	create_custom_fields(
		{
			"Sales Order": [
				{
					"fieldname": "custom_shipment_details_tab",
					"fieldtype": "Tab Break",
					"label": "出货详情",
					"insert_after": "pricing_rules",
				},
				{
					"fieldname": "custom_shipment_details_html",
					"fieldtype": "HTML",
					"label": "出货详情报表",
					"insert_after": "custom_shipment_details_tab",
				},
			]
		},
		update=True,
	)
	frappe.clear_cache(doctype="Sales Order")
