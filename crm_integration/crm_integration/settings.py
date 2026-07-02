import frappe


def is_crm_integration_enabled(company):
	if not company or not frappe.db.has_column("Company", "custom_enable_crm_integration"):
		return False

	return bool(frappe.db.get_value("Company", company, "custom_enable_crm_integration"))


def throw_crm_integration_disabled(company):
	frappe.throw(frappe._("公司 {0} 未启用 CRM 集成。").format(company or ""))
