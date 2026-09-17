function china_finance_is_amendment_draft(frm) {
	return Boolean(
		frm.doc.amended_from
		&& Number(frm.doc.docstatus) === 0
		&& !frm.is_new()
	);
}

function china_finance_set_amendment_save_action(frm) {
	if (!china_finance_is_amendment_draft(frm)) return;

	frm.page.set_primary_action(
		__("保存并记账"),
		() => china_finance_save_and_post_amendment(frm),
		null,
		__("正在保存并记账...")
	);
}

function china_finance_save_amendment(frm) {
	if (!frm.is_dirty()) return Promise.resolve();

	return new Promise((resolve, reject) => {
		let settled = false;
		const fail = (error) => {
			if (settled) return;
			settled = true;
			reject(error || new Error(__("凭证保存失败，请检查后重试")));
		};

		frm.save(
			"Save",
			(response) => {
				if (response?.exc) {
					fail(response);
					return;
				}
				settled = true;
				resolve(response);
			},
			null,
			() => fail(new Error(__("凭证保存失败，请检查必填项和校验提示")))
		);
	});
}

function china_finance_save_and_post_amendment(frm) {
	if (!china_finance_is_amendment_draft(frm) || frm.__china_finance_amendment_posting) {
		return;
	}

	frm.__china_finance_amendment_posting = true;
	frappe.ui.form.close_grid_form();
	return Promise.resolve()
		.then(() => (frm.is_dirty() ? china_finance_save_amendment(frm) : undefined))
		.then(() => {
			if (frm.is_dirty()) {
				throw new Error(__("凭证修改尚未保存，请检查保存提示后重试"));
			}
			return frappe.call({
				method: "china_finance.services.source_voucher_edit.complete_source_voucher_edit",
				args: {
					source_doctype: frm.doc.doctype,
					source_name: frm.doc.name,
				},
				freeze: true,
				freeze_message: __("正在自动审核并记账，请稍候…"),
			});
		})
		.then((response) => {
			const result = response.message || {};
			if (result.doc) frappe.model.sync(result.doc);
			china_finance_show_amendment_result(result);
			return frm.reload_doc();
		})
		.catch((error) => {
			frappe.msgprint({
				title: __("修订凭证自动记账失败"),
				message: error?.message || error?.exc || __("请检查凭证后重试"),
				indicator: "red",
			});
		})
		.finally(() => {
			frm.__china_finance_amendment_posting = false;
		});
}

function china_finance_show_amendment_result(result) {
	const reconciliation = result.bank_reconciliation || {};
	if (reconciliation.status !== "failed") {
		frappe.show_alert({
			message: result.message || __("修订凭证处理完成"),
			indicator: result.posted ? "green" : "orange",
		});
		return;
	}

	const bank_links = (reconciliation.failed || []).map((row) => {
		const name = row.name || "";
		const display_name = frappe.utils.escape_html(name);
		return frappe.utils.get_form_link("Bank Transaction", name, true, display_name);
	});
	frappe.msgprint({
		title: __("凭证已记账，银行对账未恢复"),
		indicator: "orange",
		message: [
			`<div>${frappe.utils.escape_html(result.message || __("修订凭证已记账"))}</div>`,
			bank_links.length
				? `<div class="mt-3"><b>${__("需要处理的银行流水")}</b>：${bank_links.join("、")}</div>`
				: "",
			`<div class="text-muted small mt-2">${__("请打开银行流水重新核销；凭证本身已经记账，无需重复提交。")}</div>`,
		].filter(Boolean).join(""),
	});
}

for (const doctype of ["Journal Entry", "Payment Entry"]) {
	frappe.ui.form.on(doctype, {
		refresh(frm) {
			if (!china_finance_is_amendment_draft(frm)) return;

			$(frm.wrapper)
				.off("dirty.china_finance_amendment")
				.on("dirty.china_finance_amendment", () => {
					setTimeout(() => china_finance_set_amendment_save_action(frm), 0);
				});
			china_finance_set_amendment_save_action(frm);
		},
	});
}
