import frappe


def is_mes_integration_enabled(company):
	if not company or not frappe.db.has_column("Company", "custom_enable_mes_integration"):
		return False

	return bool(frappe.db.get_value("Company", company, "custom_enable_mes_integration"))


def throw_mes_integration_disabled(company):
	frappe.throw(frappe._("公司 {0} 未启用 MES 集成。").format(company or ""))
