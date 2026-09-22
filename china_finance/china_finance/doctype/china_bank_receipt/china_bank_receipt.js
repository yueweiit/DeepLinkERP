frappe.ui.form.on("China Bank Receipt", {
	refresh(frm) {
		frm.disable_save();
		frm.fields_dict.details.$wrapper.html(china_finance.bank_receipts.details_html(frm.doc.raw_data));
		if (frm.doc.source_file) frm.add_custom_button(__("查看原回单"), () => window.open(`${frm.doc.source_file}#page=${frm.doc.page_number}`, "_blank", "noopener"));
		if (frm.doc.bank_transaction && frm.doc.status === "已关联待核销") frm.add_custom_button(__("核销已关联凭证"), () => {
			frappe.confirm(__("确认核销该银行交易与已关联凭证？"), async () => {
				await frappe.call({ method: "china_finance.services.bank_receipt_import.reconcile_receipt", args: { name: frm.doc.name }, freeze: true });
				frm.reload_doc();
			});
		});
	},
});
