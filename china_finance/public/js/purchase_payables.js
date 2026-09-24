frappe.ui.form.on("Purchase Receipt", {
	refresh(frm) {
		frm.remove_custom_button(__("创建采购应付单"), __("创建"));
		if (frm.doc.docstatus !== 1 || frm.doc.is_return || !frm.has_perm("read")) return;

		frm.add_custom_button(
			__("创建采购应付单"),
			() => {
				frappe.call({
					method: "china_finance.services.purchase_payables.create_purchase_invoice_from_receipt",
					args: { purchase_receipt: frm.doc.name },
					freeze: true,
					freeze_message: __("正在创建采购应付单..."),
				}).then((response) => {
					const result = response.message;
					if (!result?.name) return;
					frappe.show_alert({
						message: result.created ? __("采购应付单 {0} 已创建", [result.name]) : __("已存在采购应付单 {0}", [result.name]),
						indicator: "green",
					});
					frappe.set_route("Form", "Purchase Invoice", result.name);
				});
			},
			__("创建")
		);
	},
});
