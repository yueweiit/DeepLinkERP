frappe.listview_settings["Delivery Note"] = frappe.listview_settings["Delivery Note"] || {};

frappe.listview_settings["Delivery Note"].add_fields = [
	...(frappe.listview_settings["Delivery Note"].add_fields || []),
	"`tabDelivery Note`.`custom_delivery_readiness_status`",
];

frappe.listview_settings["Delivery Note"].formatters = {
	...(frappe.listview_settings["Delivery Note"].formatters || {}),
	custom_delivery_readiness_status: function(value) {
		if (!value) {
			return "";
		}

		const color_by_status = {
			"Ready to Deliver": "blue",
			"Delivered": "green",
			"Pending Release": "orange",
		};
		const color = color_by_status[value] || "gray";

		return `<span class="indicator-pill ${color} no-indicator-dot">${__(value)}</span>`;
	},
};
