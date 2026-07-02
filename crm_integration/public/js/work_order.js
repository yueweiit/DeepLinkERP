frappe.ui.form.on("Work Order", {
	setup: function(frm) {
		set_sales_order_query(frm);
	},

	onload: function(frm) {
		set_sales_order_query(frm);
	},

	production_item: function(frm) {
		set_sales_order_query(frm);
	}
});

function set_sales_order_query(frm) {
	frm.set_query("sales_order", function() {
		if (frm.doc.production_item) {
			return {
				query: "crm_integration.crm_integration.work_order.query_sales_order",
				filters: {
					production_item: frm.doc.production_item,
					company: frm.doc.company
				}
			};
		}

		return {
			filters: {
				docstatus: 1,
				status: ["not in", ["Closed", "On Hold"]]
			}
		};
	});
}
