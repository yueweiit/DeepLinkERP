const china_voucher_title_field_doctypes = new Set(["Journal Entry", "Payment Entry"]);
const china_voucher_status_doctypes = new Set(["Journal Entry", "Payment Entry"]);
const native_list_setup_columns = frappe.views.ListView.prototype.setup_columns;

// A cancelled document can retain its last workflow state (for audit history).
// The standard indicator checks workflow state before docstatus, which made a
// cancelled voucher appear as the green “Posted” state in the source list.
const native_get_indicator = frappe.get_indicator;
if (!native_get_indicator.__china_voucher_docstatus_priority) {
	const get_indicator_with_docstatus_priority = function (doc, doctype, show_workflow_state) {
		const resolved_doctype = doctype || doc?.doctype;
		if (china_voucher_status_doctypes.has(resolved_doctype) && Number(doc?.docstatus) === 2) {
			return [__("已取消"), "red", "docstatus,=,2"];
		}
		return native_get_indicator(doc, doctype, show_workflow_state);
	};
	get_indicator_with_docstatus_priority.__china_voucher_docstatus_priority = true;
	frappe.get_indicator = get_indicator_with_docstatus_priority;
}

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
			"docstatus",
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

function delete_selected_journal_entry_drafts(listview) {
	const selected = listview.get_checked_items();
	if (!selected.length) {
		frappe.msgprint(__("请先勾选需要删除的凭证草稿"));
		return;
	}

	const submitted = selected.filter((doc) => Number(doc.docstatus) !== 0);
	const names = selected.map((doc) => doc.name);
	const message = submitted.length
		? __("已选择 {0} 张凭证，其中 {1} 张不是草稿。系统只会删除未记账草稿，其余记录会显示失败原因。", [selected.length, submitted.length])
		: __("确认删除选中的 {0} 张未记账凭证草稿？回单、银行交易和 PDF 原件会保留，可重新生成。", [selected.length]);

	frappe.confirm(message, () => {
		frappe.call({
			method: "china_finance.services.bank_receipt_import.delete_draft_vouchers",
			args: {names: JSON.stringify(names)},
			freeze: true,
			freeze_message: __("正在删除凭证草稿，请稍候…"),
		}).then((response) => {
			const result = response.message || {};
			const failed = result.failed || [];
			const details = failed.length
				? `<br><br><b>${__("未删除记录")}</b><br>${failed
					.map((row) => `${frappe.utils.escape_html(row.name)}：${frappe.utils.escape_html(row.error || "删除失败")}`)
					.join("<br>")}`
				: "";
			frappe.msgprint({
				title: failed.length ? __("凭证草稿删除完成（部分失败）") : __("凭证草稿已删除"),
				indicator: failed.length ? "orange" : "green",
				message: `${__("已删除 {0} 张草稿。", [result.deleted_count || 0])}${details}`,
			});
			listview.clear_checked_items();
			listview.refresh();
		});
	});
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
	listview.page.add_action_item(__("删除所选未记账草稿"), () => {
		delete_selected_journal_entry_drafts(listview);
	});
};
