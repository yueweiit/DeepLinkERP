frappe.query_reports["China Purchase Receipt Payment"] = {
	onload(report) {
		if (!report.get_filter_value("company")) {
			report.set_filter_value("company", window.china_finance?.company_context?.default_company() || frappe.defaults.get_user_default("Company"));
		}
	},
	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		if (column.fieldname === "payment_status" && data.payment_status) {
			const color = ["全部付款"].includes(data.payment_status) ? "green" : ["异常", "已取消"].includes(data.payment_status) ? "red" : "orange";
			return `<span class="indicator-pill ${color} no-indicator-dot ellipsis"><span class="ellipsis">${frappe.utils.escape_html(data.payment_status)}</span></span>`;
		}
		return value;
	},
};
