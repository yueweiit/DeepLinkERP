frappe.query_reports["Inventory On Hand"] = {
	filters: [
		{
			fieldname: "company",
			label: __("公司"),
			fieldtype: "Link",
			options: "Company",
			default: "YW Fabricación MX 核心制造",
			reqd: 1,
		},
		{
			fieldname: "warehouse",
			label: __("仓库"),
			fieldtype: "Link",
			options: "Warehouse",
			get_query: () => ({
				filters: {
					company: frappe.query_report.get_filter_value("company"),
				},
			}),
		},
		{
			fieldname: "original_location",
			label: __("原始库位"),
			fieldtype: "Data",
		},
		{
			fieldname: "item_code",
			label: __("正式物料编码"),
			fieldtype: "Link",
			options: "Item",
			get_query: () => ({ query: "erpnext.controllers.queries.item_query" }),
		},
		{
			fieldname: "item_group",
			label: __("物料组"),
			fieldtype: "Link",
			options: "Item Group",
		},
	],

	formatter(value, row, column, data, default_formatter) {
		if (column.fieldname !== "actual_qty") {
			return default_formatter(value, row, column, data);
		}

		const formatted = default_formatter(
			value,
			row,
			Object.assign({}, column, { precision: data.quantity_precision ?? 2 }),
			data,
		);
		if (!data.quantity_warning) {
			return formatted;
		}

		const warning = frappe.utils.escape_html(data.quantity_warning);
		return `<span class="text-danger" title="${warning}">${formatted}</span>`;
	},
};
