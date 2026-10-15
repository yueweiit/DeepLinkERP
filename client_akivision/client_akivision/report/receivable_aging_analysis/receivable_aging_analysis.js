frappe.query_reports["Receivable Aging Analysis"] = {
	filters: [
		{ fieldname: "company", label: __("Company"), fieldtype: "Link", options: "Company", default: frappe.defaults.get_user_default("Company"), reqd: 1 },
		{ fieldname: "from_date", label: __("From Date"), fieldtype: "Date", default: frappe.datetime.year_start(), reqd: 1 },
		{ fieldname: "to_date", label: __("To Date"), fieldtype: "Date", default: frappe.datetime.get_today(), reqd: 1 },
		{ fieldname: "customer", label: __("Customer"), fieldtype: "Link", options: "Customer" },
	],
	formatter(value, row, column, data, default_formatter) {
		const formatted = default_formatter(value, row, column, data);
		if (!data) {
			return formatted;
		}

		if (column.fieldname === "aging_label") {
			return frappe.utils.escape_html(__(data.aging_label || ""));
		}

		if (column.fieldname === "risk_level") {
			const color = { "低风险": "green", "中风险": "orange", "高风险": "red" }[data.risk_level] || "gray";
			return `<span class="indicator-pill ${color}">${frappe.utils.escape_html(__(data.risk_level || ""))}</span>`;
		}

		if (column.fieldname === "status") {
			const color = data.status === "已结清" ? "green" : data.status === "未结清" ? "orange" : "gray";
			return `<span class="indicator-pill ${color}">${frappe.utils.escape_html(__(data.status || ""))}</span>`;
		}

		return formatted;
	},
	get_datatable_options(options) {
		return {
			...options,
			cellHeight: 38,
			dynamicRowHeight: false,
		};
	},
};
