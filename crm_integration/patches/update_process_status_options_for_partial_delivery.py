import frappe


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
	custom_field = frappe.db.get_value(
		"Custom Field",
		{"dt": "Sales Order", "fieldname": "custom_process_status"},
		"name",
	)
	if not custom_field:
		return

	frappe.db.set_value("Custom Field", custom_field, "options", PROCESS_STATUS_OPTIONS)
	frappe.clear_cache(doctype="Sales Order")
