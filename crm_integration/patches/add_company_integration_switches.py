import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


FIELDNAME = "custom_enable_crm_integration"


def execute():
	field_existed = frappe.db.has_column("Company", FIELDNAME)
	create_company_integration_switches()
	enable_existing_companies(field_existed)


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


def enable_existing_companies(field_existed):
	if not frappe.db.has_column("Company", FIELDNAME):
		return

	where_clause = f"WHERE `{FIELDNAME}` IS NULL" if field_existed else ""
	frappe.db.sql(f"UPDATE `tabCompany` SET `{FIELDNAME}` = 1 {where_clause}")
