frappe.listview_settings["Stock Entry"] = frappe.listview_settings["Stock Entry"] || {};

const MES_DLM_STOCK_ENTRY_TYPES = [
	"Material Issue",
	"Material Transfer for Manufacture",
	"Injection Molding Issuance",
];

frappe.listview_settings["Stock Entry"].add_fields = [
	...(frappe.listview_settings["Stock Entry"].add_fields || []),
	"`tabStock Entry`.`stock_entry_type`",
	"`tabStock Entry`.`custom_mes_status`",
];

frappe.listview_settings["Stock Entry"].formatters = {
	...(frappe.listview_settings["Stock Entry"].formatters || {}),
	custom_mes_status: function(value, df, doc) {
		if (!doc || !MES_DLM_STOCK_ENTRY_TYPES.includes(doc.stock_entry_type)) {
			return "";
		}

		const status = value || "Unpushed";
		const color = status === "Pushed" ? "blue" : "red";

		return `<span class="indicator-pill ${color} no-indicator-dot">${__(status)}</span>`;
	},
};
