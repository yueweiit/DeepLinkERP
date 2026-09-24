frappe.ui.form.on("Purchase Receipt", {
	refresh(frm) {
		frm.remove_custom_button(__("创建采购应付单"), __("创建"));
		frm.remove_custom_button(__("发起付款"), __("创建"));
		frm.remove_custom_button(__("查看采购应付单"), __("查看"));
		frm.dashboard.stats_area_row.find("[data-china-purchase-receipt-status]").remove();
		if (frm.doc.docstatus !== 1 || frm.doc.is_return || !frm.has_perm("read")) return;

		const summary_request = frappe.call({
			method: "china_finance.services.purchase_payables.get_receipt_payment_summary_for_user",
			args: { purchase_receipt: frm.doc.name },
		});
		summary_request.then((response) => {
			const summary = response.message || {};
			const invoices = summary.purchase_invoices || [];
			if (invoices.length) {
				frm.add_custom_button(
					__("查看采购应付单"),
					() => open_purchase_invoices(invoices),
					__("查看")
				);
			}
			const status = receipt_payment_status(summary);
			frm.dashboard
				.add_indicator(__("应付状态：{0}", [status.label]), status.color)
				.attr("data-china-purchase-receipt-status", "1");
		});

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
					const response = await summary_request;
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

function receipt_payment_status(summary) {
	if (!summary.purchase_invoices?.length) return { label: "未生成应付", color: "gray" };
	if (summary.payment_status === "全部付款") return { label: "全部付款", color: "green" };
	if (summary.payment_status === "部分付款") return { label: "部分付款", color: "orange" };
	return { label: "待付款", color: "orange" };
}

function open_purchase_invoices(names) {
	if (names.length === 1) {
		frappe.set_route("Form", "Purchase Invoice", names[0]);
		return;
	}
	frappe.route_options = { name: ["in", names] };
	frappe.set_route("List", "Purchase Invoice");
}

frappe.ui.form.on("Purchase Invoice", {
	refresh(frm) {
		frm.dashboard.stats_area_row.find("[data-china-purchase-payable-status]").remove();
		frm.remove_custom_button(__("发起付款"), __("创建"));
		if (frm.doc.docstatus !== 1 || frm.doc.is_return || !frm.has_perm("read")) return;

		frappe.call({
			method: "china_finance.services.purchase_payables.get_purchase_invoice_status_for_user",
			args: { purchase_invoice: frm.doc.name },
		}).then((response) => {
			const status = response.message;
			if (!status) return;
			const reconciliationIndicator = status.reconciliation_status === "Blocked" ? "orange" : "green";
			frm.dashboard
				.add_indicator(__("三单匹配：{0}", [status.reconciliation_status]), reconciliationIndicator)
				.attr("data-china-purchase-payable-status", "1");
			frm.dashboard
				.add_indicator(__("付款状态：{0}", [status.payment_status]), payment_status_indicator(status.payment_status))
				.attr("data-china-purchase-payable-status", "1");
			if (status.reconciliation_reason) {
				frm.dashboard
					.add_indicator(status.reconciliation_reason, "orange")
					.attr("data-china-purchase-payable-status", "1");
			}
			const taxInvoices = (status.tax_invoices || "").split(", ").filter(Boolean);
			frm.dashboard
				.add_indicator(
					__("进项税票：{0}", [taxInvoices.length ? taxInvoices.join(", ") : "未关联"]),
					taxInvoices.length ? "green" : "gray"
				)
				.attr("data-china-purchase-payable-status", "1");
			if (taxInvoices.length) {
				frm.add_custom_button(
					__("查看进项税票"),
					() => open_tax_invoices(taxInvoices),
					__("查看")
				);
			}
			if (frappe.model.can_create("Payment Entry") && status.outstanding_amount > 0) {
				frm.add_custom_button(
					__("发起付款"),
					async () => {
						const payment = await frappe.call({
							method: "erpnext.accounts.doctype.payment_entry.payment_entry.get_payment_entry",
							args: { dt: "Purchase Invoice", dn: frm.doc.name },
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
		});
	},
});

function payment_status_indicator(status) {
	if (status === "全部付款") return "green";
	if (status === "部分付款") return "orange";
	if (status === "异常" || status === "已取消") return "red";
	return "gray";
}

function open_tax_invoices(names) {
	if (names.length === 1) {
		frappe.set_route("Form", "China Tax Invoice", names[0]);
		return;
	}
	frappe.route_options = { name: ["in", names] };
	frappe.set_route("List", "China Tax Invoice");
}

frappe.ui.form.on("Purchase Order", {
	refresh(frm) {
		frm.dashboard.stats_area_row.find("[data-china-purchase-order-status]").remove();
		frm.remove_custom_button(__("发起预付款"), __("创建"));
		if (frm.doc.docstatus !== 1 || !frm.has_perm("read")) return;

		frappe.call({
			method: "china_finance.services.purchase_payables.get_purchase_order_status_for_user",
			args: { purchase_order: frm.doc.name },
		}).then((response) => {
			const status = response.message;
			if (!status) return;
			add_purchase_order_indicator(frm, `收货：${status.receive_status}`, status_color(status.receive_status));
			add_purchase_order_indicator(frm, `应付：${status.payable_status}`, status_color(status.payable_status));
			add_purchase_order_indicator(frm, `付款：${status.payment_status}`, payment_status_indicator(status.payment_status));
			if (status.order_amount > 0) {
				add_purchase_order_indicator(
					frm,
					`预付款：${status.advance_paid} / ${status.order_amount}`,
					status.advance_outstanding > 0 ? "orange" : "green"
				);
			}
			if (status.reconciliation_status === "Blocked") {
				add_purchase_order_indicator(frm, `三单匹配：${status.reconciliation_reason || "异常"}`, "orange");
			}
		});
		if (frappe.model.can_create("Payment Entry") && (frm.doc.grand_total || 0) > (frm.doc.advance_paid || 0)) {
			frm.add_custom_button(
				__("发起预付款"),
				async () => {
					const payment = await frappe.call({
						method: "erpnext.accounts.doctype.payment_entry.payment_entry.get_payment_entry",
						args: { dt: "Purchase Order", dn: frm.doc.name },
						freeze: true,
						freeze_message: __("正在创建预付款单草稿..."),
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

function add_purchase_order_indicator(frm, label, color) {
	frm.dashboard.add_indicator(__(label), color).attr("data-china-purchase-order-status", "1");
}

function status_color(status) {
	if (["全部收货", "全部应付"].includes(status)) return "green";
	if (["部分收货", "部分应付"].includes(status)) return "orange";
	if (["异常"].includes(status)) return "red";
	return "gray";
}
