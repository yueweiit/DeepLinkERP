function china_finance_can_direct_post(frm) {
	return Boolean(
		frm.__china_preparation_mode === false
		&& frm.is_new()
		&& frm.doc.docstatus === 0
		&& !frm.doc.custom_china_bank_transaction
		&& !String(frm.doc.title || "").trim().startsWith("Excel导入：")
		&& frm.perm?.[0]?.create
		&& frm.perm?.[0]?.submit
	);
}

function china_finance_set_direct_post_action(frm) {
	if (!china_finance_can_direct_post(frm)) return;

	frm.page.set_primary_action(
		__("保存并记账"),
		() => china_finance_save_and_post(frm),
		null,
		__("正在保存并记账...")
	);
	if (!frm.__china_finance_draft_save_button_added) {
		frm.add_custom_button(__("仅保存草稿"), () => frm.save("Save"), __("更多"));
		frm.__china_finance_draft_save_button_added = true;
	}
}

function china_finance_save_and_post(frm) {
	if (frm.__china_finance_direct_posting) return;
	frm.__china_finance_direct_posting = true;
	frm.page.btn_primary.prop("disabled", true);
	frappe.validated = true;

	let request = frm.script_manager.trigger("before_submit");
	request = request.then(() => {
		if (!frappe.validated) return null;
		frappe.validated = true;
		return frm.script_manager.trigger("validate");
	});
	request = request.then(() => {
		if (!frappe.validated) return null;
		return frm.script_manager.trigger("before_save");
	});
	request = request.then(() => {
		if (!frappe.validated) return null;
		return frappe.call({
			method: "china_finance.services.voucher.save_and_post_journal_entry",
			args: { doc: frm.doc },
			freeze: true,
			freeze_message: __("正在保存并记账..."),
		});
	});

	request
		.then((response) => {
			if (!response?.message) return;
			frappe.model.sync(response.message);
			frappe.show_alert({ message: __("凭证已保存并记账"), indicator: "green" });
			frappe.set_route("Form", "Journal Entry", response.message.name);
		})
		.catch((error) => console.error(error))
		.finally(() => {
			frm.__china_finance_direct_posting = false;
			frm.page.btn_primary.prop("disabled", false);
		});
}

frappe.ui.form.on("Journal Entry", {
	async refresh(frm) {
		$(frm.wrapper).off("dirty.china_finance_direct_post");
		if (frm.doc.company) {
			const response = await frappe.call({method: "china_finance.services.voucher_preparation.get_mode", args: {company: frm.doc.company, posting_date: frm.doc.posting_date}});
			frm.__china_preparation_mode = !!response.message?.enabled;
		}
		if (frm.__china_preparation_mode && frm.doc.docstatus === 0) {
			frm.page.set_primary_action(__("保存草稿"), () => frm.save());
			if (!frm.is_new()) frm.add_custom_button(__("核对完成，待记账"), async () => {
				if (frm.is_dirty()) await frm.save();
				await frappe.require("/assets/china_finance/js/voucher_preparation.js");
				await china_finance.preparation.review([frm.doc.name]);
				frm.reload_doc();
			});
			return;
		}
		if (!china_finance_can_direct_post(frm)) return;
		frm.__china_finance_draft_save_button_added = false;

		// The native dirty handler restores the primary button to “Save”. Reapply
		// our action after it runs so the behavior remains consistent while editing.
		$(frm.wrapper)
			.off("dirty.china_finance_direct_post")
			.on("dirty.china_finance_direct_post", () => {
				setTimeout(() => china_finance_set_direct_post_action(frm), 0);
			});
		china_finance_set_direct_post_action(frm);
	},
});
