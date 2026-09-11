const china_voucher_title_field_doctypes = new Set(["Journal Entry", "Payment Entry"]);
const native_list_setup_columns = frappe.views.ListView.prototype.setup_columns;

if (!frappe.views.ListView.prototype.__china_voucher_title_column_patched) {
	frappe.views.ListView.prototype.setup_columns = function () {
		if (!china_voucher_title_field_doctypes.has(this.doctype)) {
			return native_list_setup_columns.call(this);
		}
		const original_title_field = this.meta.title_field;
		this.meta.title_field = "custom_china_voucher_number";
		try {
			return native_list_setup_columns.call(this);
		} finally {
			this.meta.title_field = original_title_field;
		}
	};
	frappe.views.ListView.prototype.__china_voucher_title_column_patched = true;
}

function configure_china_voucher_number_list(doctype, fields, original_title_field) {
	frappe.listview_settings[doctype] = {
		add_fields: [
			"custom_china_voucher_number",
			...(doctype === "Journal Entry" ? ["custom_china_bank_transaction"] : []),
		],
		fields: JSON.stringify(fields.map((fieldname) => ({ fieldname }))),
		hide_name_column: false,
	};
}

function show_import_batch_posting_result(listview, result) {
	const rows = result?.results || [];
	const success_rows = rows.filter((row) => row.status === "success");
	const failed_rows = rows.filter((row) => row.status === "failed");
	const success_message = success_rows.length
		? `<p>${__("成功处理 {0} 张凭证", [success_rows.length])}</p>`
		: "";
	const failed_message = failed_rows.length
		? `<p><b>${__("失败 {0} 张", [failed_rows.length])}</b></p><ul>${failed_rows
			.map(
				(row) =>
					`<li>${frappe.utils.escape_html(row.name)}：${frappe.utils.escape_html(
						row.message || __("处理失败")
					)}</li>`
			)
			.join("")}</ul>`
		: "";

	frappe.msgprint({
		title: result?.failed_count ? __("批量处理完成（部分失败）") : __("批量处理完成"),
		message: `${success_message}${failed_message}<p>${__("处理批次")}: ${frappe.utils.escape_html(
			result?.batch_id || ""
		)}</p>`,
		indicator: result?.failed_count ? "orange" : "green",
	});
	listview.refresh();
}

function batch_post_selected_journal_entries(listview) {
	const docs = listview.get_checked_items();
	if (!docs.length) {
		frappe.msgprint(__("请先勾选需要处理的凭证"));
		return;
	}

	const batch_docs = docs.filter((doc) =>
		String(doc.title || "").trim().startsWith("Excel导入：") ||
		String(doc.custom_china_bank_transaction || "").trim()
	);
	if (batch_docs.length !== docs.length) {
		frappe.msgprint(
			__("批量审核并记账只支持 Excel 导入或银行流水生成的记账凭证，请不要同时勾选普通凭证。")
		);
		return;
	}

	const dialog = new frappe.ui.Dialog({
		title: __("批量审核并记账"),
		fields: [
			{
				fieldname: "reason",
				fieldtype: "Small Text",
				label: __("处理原因"),
				description: __("系统会记录批次、操作人和处理原因。"),
				reqd: 1,
			},
		],
		primary_action_label: __("确认批量审核并记账"),
		primary_action(values) {
			const reason = String(values.reason || "").trim();
			if (!reason) {
				frappe.msgprint(__("请填写处理原因"));
				return;
			}

			dialog.disable_primary_action();
			frappe.call({
				method: "china_finance.services.voucher.batch_post_imported_journal_entries",
				args: {
					names: JSON.stringify(batch_docs.map((doc) => doc.name)),
					reason,
				},
				freeze: true,
				freeze_message: __("正在批量审核并记账，请稍候…"),
			}).then((response) => {
				dialog.hide();
				show_import_batch_posting_result(listview, response.message || {});
			}).catch(() => {
				dialog.enable_primary_action();
			});
		},
	});
	dialog.show();
}

configure_china_voucher_number_list("Journal Entry", [
	"custom_china_voucher_number", "title", "status_field", "company", "total_debit", "name",
], "title");
configure_china_voucher_number_list("Payment Entry", [
	"custom_china_voucher_number", "party", "status_field", "company", "paid_amount", "name",
], "party");

frappe.listview_settings["Journal Entry"].onload = function (listview) {
	listview.page.add_action_item(__("批量审核并记账"), () => {
		batch_post_selected_journal_entries(listview);
	});
};
