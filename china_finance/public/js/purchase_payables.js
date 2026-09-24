frappe.ui.form.on("Purchase Receipt", {
	refresh(frm) {
		frm.remove_custom_button(__("创建采购应付单"), __("创建"));
		frm.remove_custom_button(__("发起付款"), __("创建"));
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

		if (frappe.model.can_create("Payment Entry")) {
			frm.add_custom_button(
				__("发起付款"),
				async () => {
					const response = await frappe.call({
						method: "china_finance.services.purchase_payables.get_receipt_payment_summary_for_user",
						args: { purchase_receipt: frm.doc.name },
						freeze: true,
						freeze_message: __("正在检查可付款的采购应付单..."),
					});
					const summary = response.message || {};
					const candidates = summary.payable_purchase_invoices || [];
					if (!candidates.length) {
						frappe.msgprint(__("该采购收货单没有可付款的已提交采购应付单。"));
						return;
					}
					if (candidates.length > 1) {
						frappe.new_doc("Payment Entry", {
							payment_type: "Pay",
							party_type: "Supplier",
							party: summary.supplier,
							company: summary.company,
						});
						frappe.show_alert({
							message: __("已带入供应商，请在付款单中选择本次核销的采购应付单。"),
							indicator: "blue",
						});
						return;
					}

					const payment = await frappe.call({
						method: "erpnext.accounts.doctype.payment_entry.payment_entry.get_payment_entry",
						args: { dt: "Purchase Invoice", dn: candidates[0] },
						freeze: true,
						freeze_message: __("正在创建付款单草稿..."),
					});
					if (!payment.message?.name) return;
					frappe.model.sync(payment.message);
					frappe.set_route("Form", "Payment Entry", payment.message.name);
				},
				__("创建")
			);
		}
	},
});
