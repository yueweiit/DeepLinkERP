from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

from crm_integration.patches.add_crm_custom_fields import clear_crm_custom_field_cache


def execute():
	create_custom_fields(
		{
			"Sales Order Item": [
				{
					"fieldname": "custom_version",
					"fieldtype": "Data",
					"label": "Version",
					"length": 64,
					"insert_after": "custom_specifications",
				},
			],
			"Delivery Note": [
				{
					"fieldname": "custom_crm_shipment_no",
					"fieldtype": "Data",
					"label": "CRM Shipment No",
					"length": 140,
					"insert_after": "customer",
					"read_only": 1,
					"in_list_view": 1,
					"in_standard_filter": 1,
					"unique": 1,
					"allow_on_submit": 1,
					"no_copy": 1,
				},
			],
			"Delivery Note Item": [
				{
					"fieldname": "custom_version",
					"fieldtype": "Data",
					"label": "Version",
					"length": 64,
					"insert_after": "description",
					"read_only": 1,
				},
			],
		},
		update=True,
	)
	clear_crm_custom_field_cache()
