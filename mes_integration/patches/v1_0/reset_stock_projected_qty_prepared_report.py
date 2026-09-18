import frappe


REPORT_NAME = "Stock Projected Qty"


def execute():
	prepared_report, disable_automation = frappe.db.get_value(
		"Report", REPORT_NAME, ["prepared_report", "disable_prepared_report_automation"]
	) or (0, 0)

	if prepared_report and not disable_automation:
		frappe.db.set_value("Report", REPORT_NAME, "prepared_report", 0, update_modified=False)
