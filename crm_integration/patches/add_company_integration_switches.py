import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


FIELDNAME = "custom_enable_crm_integration"


def execute():
	create_company_integration_switches()


def create_company_integration_switches():
	create_custom_fields(
		{
			"Company": [
				{
					"fieldname": FIELDNAME,
					"fieldtype": "Check",
					"insert_after": "parent_company",
					"label": "启用 CRM 集成",
					"default": "0",
				},
			]
		},
		update=True,
	)
	frappe.clear_cache(doctype="Company")
