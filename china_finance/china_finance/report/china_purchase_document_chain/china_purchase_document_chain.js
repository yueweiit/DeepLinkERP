frappe.query_reports["China Purchase Document Chain"] = {
	onload(report) {
		if (!report.get_filter_value("company")) {
			report.set_filter_value("company", window.china_finance?.company_context?.default_company() || frappe.defaults.get_user_default("Company"));
		}
	},
};
