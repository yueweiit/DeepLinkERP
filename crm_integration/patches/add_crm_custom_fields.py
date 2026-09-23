import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


PROCESS_STATUS_OPTIONS = "\n".join(
	[
		"Pending Confirmation",
		"Pending Deposit Confirmation",
		"Pending Production",
		"Pending Final Payment",
		"Deliverable",
		"Partially Delivered",
		"Completed",
		"Rejected",
		"Cancelled",
	]
)


def execute():
	create_crm_custom_fields()
	clear_crm_custom_field_cache()


def create_crm_custom_fields():
	create_custom_fields(
		{
			"Item": [
				{
					"fieldname": "custom_specifications",
					"fieldtype": "Data",
					"label": "Specifications",
					"insert_after": "item_name",
				},
			],
			"Sales Order": [
				{
					"fieldname": "custom_process_status",
					"fieldtype": "Select",
					"label": "Process Status",
					"options": PROCESS_STATUS_OPTIONS,
					"default": "Pending Confirmation",
					"insert_after": "status",
					"in_list_view": 1,
					"allow_on_submit": 1,
					"read_only": 1,
					"no_copy": 1,
				},
				{
					"fieldname": "custom_crm_order_no",
					"fieldtype": "Data",
					"label": "CRM Order No",
					"insert_after": "po_no",
					"allow_on_submit": 1,
					"no_copy": 1,
				},
				{
					"fieldname": "custom_odt",
					"fieldtype": "Data",
					"label": "ODT",
					"insert_after": "custom_crm_order_no",
					"allow_on_submit": 1,
					"no_copy": 1,
				},
				{
					"fieldname": "custom_remark",
					"fieldtype": "Small Text",
					"label": "Remark",
					"insert_after": "custom_odt",
					"allow_on_submit": 1,
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
			"Sales Order Item": [
				{
					"fieldname": "custom_product",
					"fieldtype": "Data",
					"label": "Product",
					"insert_after": "item_name",
				},
				{
					"fieldname": "custom_specifications",
					"fieldtype": "Data",
					"label": "Specifications",
					"insert_after": "custom_product",
				},
				{
					"fieldname": "custom_version",
					"fieldtype": "Data",
					"label": "Version",
					"length": 64,
					"insert_after": "custom_specifications",
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


def clear_crm_custom_field_cache():
	for doctype in (
		"Item",
		"Sales Order",
		"Sales Order Item",
		"Delivery Note",
		"Delivery Note Item",
	):
		frappe.clear_cache(doctype=doctype)
