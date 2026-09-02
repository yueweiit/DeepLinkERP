frappe.query_reports["China Voucher Ledger"] = {
	filters: [
		{
			fieldname: "company",
			label: __("公司"),
			fieldtype: "Link",
			options: "Company",
			default: frappe.defaults.get_user_default("Company"),
			reqd: 1,
		},
		{
			fieldname: "period_preset",
			label: __("凭证日期"),
			fieldtype: "Select",
			options: ["", __("本月凭证"), __("上月凭证"), __("近三个月"), __("本年凭证")],
			default: __("本月凭证"),
			on_change: (report) => {
				const preset = report.get_filter_value("period_preset");
				if (preset) set_quick_period(report, preset);
			},
		},
		{ fieldname: "from_date", label: __("起始日期"), fieldtype: "Date", reqd: 1 },
		{ fieldname: "to_date", label: __("截止日期"), fieldtype: "Date", reqd: 1 },
		{ fieldname: "voucher_word", label: __("凭证字号"), fieldtype: "Data" },
		{ fieldname: "accounting_period", label: __("会计期间"), fieldtype: "Data" },
		{
			fieldname: "source_doctype",
			label: __("来源类型"),
			fieldtype: "Select",
			options: ["", "Journal Entry", "Payment Entry"],
		},
		{ fieldname: "source_name", label: __("来源单据"), fieldtype: "Data" },
		{ fieldname: "voucher_number", label: __("凭证编号"), fieldtype: "Data" },
		{ fieldname: "account", label: __("科目"), fieldtype: "Link", options: "Account" },
		{
			fieldname: "party_type",
			label: __("往来类型"),
			fieldtype: "Select",
			options: ["", "Customer", "Supplier", "Employee", "Shareholder"],
		},
		{ fieldname: "party", label: __("往来单位"), fieldtype: "Data" },
		{ fieldname: "search_text", label: __("关键词"), fieldtype: "Data" },
	],
	tree: false,
	formatter(value, row, column, data, default_formatter) {
		const formatted = default_formatter(value, row, column, data);
		if (column.fieldname === "voucher_status" && data?.voucher_status !== undefined && data?.voucher_status !== null) {
			const status = {
				0: [__("草稿"), "orange"],
				1: [__("已提交"), "green"],
				2: [__("已取消"), "red"],
			}[data.voucher_status];
			if (!status) return "";
			return `<span class="china-voucher-status-text ${status[1]}">${status[0]}</span>`;
		}
		if (column.fieldname === "statutory_number" && data?.source_doctype && data?.source_name) {
			const route = frappe.utils.get_form_link(data.source_doctype, data.source_name);
			return `<a href="${route}" class="china-voucher-link" data-source-doctype="${encodeURIComponent(data.source_doctype)}" data-source-name="${encodeURIComponent(data.source_name)}">${formatted}</a>`;
		}
		if (!data || !["posting_date", "statutory_number", "accounting_period", "remarks"].includes(column.fieldname)) {
			return formatted;
		}
		const index = Number.isInteger(row?._index) ? row._index : frappe.query_report.data?.indexOf(data);
		const previous = index > 0 ? frappe.query_report.data?.[index - 1] : null;
		if (previous && previous.voucher_snapshot === data.voucher_snapshot) return "";
		return formatted;
	},
	onload(report) {
		report.page.wrapper.addClass("china-voucher-ledger-report");
		ensure_voucher_ledger_styles();
		report.page.wrapper.on("click", ".china-voucher-link", (event) => {
			event.preventDefault();
			const source_doctype = decodeURIComponent(event.currentTarget.dataset.sourceDoctype);
			const source_name = decodeURIComponent(event.currentTarget.dataset.sourceName);
			frappe.set_route("Form", source_doctype, source_name);
		});
		report.page.wrapper.on("click", ".china-voucher-snapshot-link", (event) => {
			event.preventDefault();
			const snapshot_name = decodeURIComponent(event.currentTarget.dataset.snapshotName);
			frappe.set_route("Form", "China Accounting Voucher", snapshot_name);
		});
		if (!report.get_filter_value("company")) {
			report.set_filter_value("company", frappe.defaults.get_user_default("Company"));
		}
		if (!report.get_filter_value("from_date") || !report.get_filter_value("to_date")) {
			const today = frappe.datetime.get_today();
			report.set_filter_value({
				period_preset: __("本月凭证"),
				from_date: frappe.datetime.month_start(today),
				to_date: frappe.datetime.month_end(today),
			});
		}
	},
};

function ensure_voucher_ledger_styles() {
	if (document.getElementById("china-voucher-ledger-inline-style")) return;
	$("<style>")
		.attr("id", "china-voucher-ledger-inline-style")
		.text(`
			.china-voucher-ledger-report .dt-header,
			.china-voucher-ledger-report .dt-scrollable { max-width: none; }
			.china-voucher-ledger-report .dt-row {
				min-width: 100%;
				width: max-content;
			}
			.china-voucher-ledger-report .dt-cell { flex: 0 0 auto; }
			.china-voucher-ledger-report .dt-scrollable { overflow-x: auto; }
			.china-voucher-ledger-report .dt-cell__content {
				line-height: 24px;
				padding-left: 6px;
				padding-right: 6px;
				white-space: nowrap;
				overflow: hidden;
				text-overflow: ellipsis;
			}
			.china-voucher-ledger-report .dt-row { min-height: 28px; }
		`)
		.appendTo(document.head);
}

function set_quick_period(report, period) {
	const today = frappe.datetime.get_today();
	// Select values may be translated, so compare the selected option's index
	// instead of comparing translated labels directly.
	const period_control = report.get_filter("period_preset");
	const selected_index = Number(period_control.$input?.prop("selectedIndex"));
	const raw_options = period_control.df.options || [];
	const options = Array.isArray(raw_options) ? raw_options : raw_options.split("\n");
	const period_index = Number.isInteger(selected_index) && selected_index >= 0
		? selected_index
		: options.indexOf(period);
	const period_text = String(period || "");
	let from_date;
	let to_date;
	if (period_text.includes("近三") || period_index === 3) {
		from_date = moment(today).subtract(2, "months").startOf("month").format("YYYY-MM-DD");
		to_date = today;
	} else if (period_text.includes("本年") || period_index === 4) {
		from_date = `${today.slice(0, 4)}-01-01`;
		to_date = today;
	} else if (period_text.includes("本月") || period_index === 1) {
		from_date = moment(today).startOf("month").format("YYYY-MM-DD");
		to_date = moment(today).endOf("month").format("YYYY-MM-DD");
	} else if (period_text.includes("上月") || period_index === 2) {
		const previous = moment(today).subtract(1, "month");
		from_date = previous.clone().startOf("month").format("YYYY-MM-DD");
		to_date = previous.clone().endOf("month").format("YYYY-MM-DD");
	} else {
		from_date = moment(today).startOf("month").format("YYYY-MM-DD");
		to_date = moment(today).endOf("month").format("YYYY-MM-DD");
	}
	report.set_filter_value("from_date", from_date);
	report.set_filter_value("to_date", to_date);
	report.refresh();
}
