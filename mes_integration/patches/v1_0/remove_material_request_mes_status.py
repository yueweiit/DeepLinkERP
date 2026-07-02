import frappe


def execute():
	field_name = "Material Request-custom_mes_status"
	if frappe.db.exists("Custom Field", field_name):
		frappe.delete_doc("Custom Field", field_name, ignore_permissions=True, force=True)

	frappe.clear_cache(doctype="Material Request")
