const period_closing_voucher_doctype = "Period Closing Voucher";
const existing_period_closing_voucher_settings =
	frappe.listview_settings[period_closing_voucher_doctype] || {};
const original_period_closing_custom_filter_configs =
	existing_period_closing_voucher_settings.custom_filter_configs;

// Make the period and revision relationship visible in the list. These fields
// are intentionally enabled only for this list view, so the standard form
// layout and database schema remain unchanged.
const period_closing_voucher_meta = frappe.get_meta(period_closing_voucher_doctype);
const period_closing_voucher_list_fields = [
	"period_start_date",
	"period_end_date",
	"amended_from",
];

period_closing_voucher_meta?.fields
	.filter((df) => period_closing_voucher_list_fields.includes(df.fieldname))
	.forEach((df) => {
		df.in_list_view = 1;
	});

// A saved List View Settings record can explicitly limit the columns. Append
// these fields for this view as well, without changing the user's saved
// settings in the database.
const native_period_closing_setup_columns = frappe.views.ListView.prototype.setup_columns;
if (!frappe.views.ListView.prototype.__china_period_closing_columns_patched) {
	frappe.views.ListView.prototype.setup_columns = function () {
		if (this.doctype !== period_closing_voucher_doctype || !this.list_view_settings?.fields) {
			return native_period_closing_setup_columns.call(this);
		}

		let original_fields;
		try {
			original_fields = JSON.parse(this.list_view_settings.fields);
		} catch (error) {
			return native_period_closing_setup_columns.call(this);
		}

		if (!Array.isArray(original_fields)) {
			return native_period_closing_setup_columns.call(this);
		}

		const configured_fieldnames = new Set(
			original_fields.map((field) => field?.fieldname).filter(Boolean)
		);
		const fields_to_show = original_fields.concat(
			period_closing_voucher_list_fields
				.filter((fieldname) => !configured_fieldnames.has(fieldname))
				.map((fieldname) => ({ fieldname }))
		);

		this.list_view_settings.fields = JSON.stringify(fields_to_show);
		try {
			return native_period_closing_setup_columns.call(this);
		} finally {
			this.list_view_settings.fields = JSON.stringify(original_fields);
		}
	};
	frappe.views.ListView.prototype.__china_period_closing_columns_patched = true;
}

// A cancelled voucher may retain its last workflow state (Posted). Give
// docstatus priority so the original closing voucher is clearly shown as
// cancelled, while its amended replacement is identified as a revision.
const native_period_closing_get_indicator = frappe.get_indicator;
if (!native_period_closing_get_indicator.__china_period_closing_docstatus_priority) {
	const get_period_closing_indicator = function (doc, doctype, show_workflow_state) {
		const resolved_doctype = doctype || doc?.doctype;
		if (resolved_doctype === period_closing_voucher_doctype) {
			const docstatus = Number(doc?.docstatus);
			const has_amended_from = Boolean(String(doc?.amended_from || "").trim());

			if (docstatus === 2) {
				return [__("已冲销（原结账单）"), "red", "docstatus,=,2"];
			}
			if (docstatus === 1 && has_amended_from) {
				return [__("已记账（修订后）"), "green", "docstatus,=,1"];
			}
			if (docstatus === 1) {
				return [__("已记账"), "green", "docstatus,=,1"];
			}
			if (docstatus === 0 && has_amended_from) {
				return [__("草稿（待重新结账）"), "orange", "docstatus,=,0"];
			}
			if (docstatus === 0) {
				return [__("草稿"), "orange", "docstatus,=,0"];
			}
		}

		return native_period_closing_get_indicator(doc, doctype, show_workflow_state);
	};
	get_period_closing_indicator.__china_period_closing_docstatus_priority = true;
	frappe.get_indicator = get_period_closing_indicator;
}

frappe.listview_settings[period_closing_voucher_doctype] = {
	...existing_period_closing_voucher_settings,
	add_fields: [
		...new Set([
			...(existing_period_closing_voucher_settings.add_fields || []),
			"docstatus",
			"period_start_date",
			"period_end_date",
			"amended_from",
		]),
	],
	custom_filter_configs: async function () {
		let configs = [];
		if (typeof original_period_closing_custom_filter_configs === "function") {
			configs = await Promise.resolve(original_period_closing_custom_filter_configs());
		} else if (Array.isArray(original_period_closing_custom_filter_configs)) {
			configs = original_period_closing_custom_filter_configs;
		}
		if (!Array.isArray(configs)) {
			configs = [];
		}

		if (configs.some((config) => config.fieldname === "period_end_date")) {
			return configs;
		}

		return configs.concat({
			fieldtype: "Data",
			fieldname: "period_end_date",
			label: __("结账月份"),
			placeholder: __("例如 2026-05"),
			condition: "like",
			is_filter: 1,
		});
	},
};
