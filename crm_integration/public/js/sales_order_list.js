(function() {
frappe.listview_settings["Sales Order"] = frappe.listview_settings["Sales Order"] || {};

const sales_order_list_settings = frappe.listview_settings["Sales Order"];
const sales_order_list_onload = sales_order_list_settings.onload;
const sales_order_list_before_render = sales_order_list_settings.before_render;
const sales_order_list_refresh = sales_order_list_settings.refresh;

sales_order_list_settings.add_fields = [
	...(sales_order_list_settings.add_fields || []),
	"`tabSales Order`.`custom_process_status`",
];

sales_order_list_settings.onload = function(listview) {
	if (sales_order_list_onload) {
		sales_order_list_onload(listview);
	}

	if (!listview._crm_integration_setup_columns) {
		listview._crm_integration_setup_columns = listview.setup_columns.bind(listview);
		listview.setup_columns = function() {
			this._crm_integration_setup_columns();
			add_sales_order_extra_columns(this);
		};
	}

	add_sales_order_extra_columns(listview);
	listview.render_header(true);
};

sales_order_list_settings.before_render = function() {
	if (sales_order_list_before_render) {
		sales_order_list_before_render();
	}

	const listview = sales_order_list_settings._listview;
	if (listview) {
		load_sales_order_extra_columns(listview);
	}
};

sales_order_list_settings.formatters = {
	...(sales_order_list_settings.formatters || {}),
	custom_process_status: function(value) {
		const status = value || "Pending Confirmation";
		const colors = {
			"Pending Confirmation": "orange",
			"Rejected": "red",
			"Pending Deposit Confirmation": "yellow",
			"Pending Production": "blue",
			"Pending Final Payment": "yellow",
			"Deliverable": "blue",
			"Partially Delivered": "orange",
			"Completed": "green",
			"Closed": "green",
			"Cancelled": "red",
		};

		return `<span class="indicator-pill ${colors[status] || "gray"} no-indicator-dot">${__(status)}</span>`;
	},
	custom_first_sales_person: function(value) {
		return sales_order_list_text(value);
	},
	custom_first_product: function(value) {
		return sales_order_list_text(value);
	},
};

function add_sales_order_extra_columns(listview) {
	sales_order_list_settings._listview = listview;

	const extra_columns = [
		{
			after: "customer_name",
			column: {
				type: "Field",
				df: {
					label: __("业务员"),
					fieldname: "custom_first_sales_person",
					fieldtype: "Data",
				},
			},
		},
		{
			after: "custom_first_sales_person",
			column: {
				type: "Field",
				df: {
					label: __("产品"),
					fieldname: "custom_first_product",
					fieldtype: "Data",
				},
			},
		},
	];

	for (const { after, before, column } of extra_columns) {
		remove_sales_order_column(listview, column.df.fieldname);
		insert_sales_order_column(listview, column, { after, before });
	}
}

function insert_sales_order_column(listview, column, { after, before }) {
	const columns = listview.columns || [];
	const target_fieldname = after || before;
	const target_index = columns.findIndex((col) => col.df?.fieldname === target_fieldname);
	const fallback_index = columns.findIndex((col) => col.type === "Status");
	let insert_index = columns.length;

	if (target_index !== -1) {
		insert_index = before ? target_index : target_index + 1;
	} else if (fallback_index !== -1) {
		insert_index = fallback_index + 1;
	}

	columns.splice(insert_index, 0, column);
}

function remove_sales_order_column(listview, fieldname) {
	const index = (listview.columns || []).findIndex((col) => col.df?.fieldname === fieldname);
	if (index !== -1) {
		listview.columns.splice(index, 1);
	}
}

function load_sales_order_extra_columns(listview) {
	const names = (listview.data || []).map((doc) => doc.name).filter(Boolean);
	if (!names.length) {
		return;
	}

	const cache_key = names.join("\n");
	if (listview._sales_order_extra_columns_cache_key === cache_key) {
		apply_sales_order_extra_details(
			listview,
			listview._sales_order_extra_columns_details || {}
		);
		return;
	}

	listview._sales_order_extra_columns_cache_key = cache_key;

	frappe.call({
		method: "crm_integration.crm_integration.sales_order.get_sales_order_list_details",
		args: { sales_orders: names },
		callback: function(response) {
			if (listview._sales_order_extra_columns_cache_key !== cache_key) {
				return;
			}

			const details = response.message || {};
			listview._sales_order_extra_columns_details = details;
			apply_sales_order_extra_details(listview, details);
			listview.render();
		},
	});
}

function apply_sales_order_extra_details(listview, details) {
	for (const doc of listview.data || []) {
		const row = details[doc.name] || {};
		doc.custom_first_sales_person = row.sales_person || "";
		doc.custom_first_product = row.product || "";
	}
}

function sales_order_list_text(value) {
	const text = value || "-";
	return `<span class="ellipsis" title="${frappe.utils.escape_html(text)}">${frappe.utils.escape_html(text)}</span>`;
}

})();
