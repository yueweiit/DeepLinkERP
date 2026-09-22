frappe.ui.form.on("China Bank Receipt Import", {
	async source_file(frm) {
		if (frm.doc.source_file && frm.doc.company && frm.doc.bank_account && !frm.doc.source_hash && !frm.__receipt_parsing) await frm.save();
	},
	async after_save(frm) {
		if (!frm.doc.source_file || frm.doc.source_hash || frm.__receipt_parsing || frm.doc.status === "已作废") return;
		frm.__receipt_parsing = true;
		try { await receipt_call("parse_import", {name: frm.doc.name}); await frm.reload_doc(); }
		finally { frm.__receipt_parsing = false; }
	},
	setup(frm) {
		frm.set_query("bank_account", () => ({ filters: { company: frm.doc.company, is_company_account: 1, disabled: 0 } }));
	},
	company(frm) { if (!frm.doc.source_hash) frm.set_value("bank_account", ""); },
	refresh(frm) {
		frm.set_df_property("source_file", "options", { restrictions: { allowed_file_types: [".pdf"], max_file_size: 20 * 1024 * 1024 }, make_attachments_public: false });
		if (frm.doc.company && frappe.model.can_create("China Bank Receipt Rule")) frm.add_custom_button(__("设置社保分摊规则"), async () => {
			const lookup = number => frappe.db.get_value("Account", { company: frm.doc.company, account_number: number, is_group: 0, disabled: 0 }, "name");
			const [expense, personal, accrual] = await Promise.all([lookup("660208"), lookup("122102"), lookup("221101")]);
			frappe.new_doc("China Bank Receipt Rule", { company: frm.doc.company, direction: "支出", rule_type: "社保分摊", account: expense.message?.name,
				personal_account: personal.message?.name, accrual_account: accrual.message?.name, injury_company_percent: 100, pension_company_percent: 66.67,
				medical_company_percent: 86.30, unemployment_company_percent: 80,
				notes: "按回单所属时期生成计提三行、支付两行。公司承担计入管理费用-社会保险费，个人承担计入其他应收款-社保；逐项四舍五入，个人承担取差额。使用前确认该所属期尚未计提。" });
		});
		if (frm.is_new()) return;
		const parsed = !!frm.doc.source_hash;
		for (const field of ["company", "bank_account", "mode", "source_file"]) frm.set_df_property(field, "read_only", parsed);
		if (parsed) frm.disable_save();
		if (!parsed && frm.doc.status !== "已作废") {
			frm.add_custom_button(__("识别回单"), async () => {
				if (frm.is_dirty()) await frm.save();
				await receipt_call("parse_import", { name: frm.doc.name });
				await frm.reload_doc();
			});
		}
		if (parsed && frm.doc.status !== "已作废") {
			frm.add_custom_button(__("刷新处理状态"), () => render_receipt_preview(frm));
			if (!(frm.doc.rows || []).some(r => r.receipt)) frm.add_custom_button(__("作废批次"), () => {
				frappe.prompt({ fieldname: "reason", label: __("作废原因"), fieldtype: "Small Text", reqd: 1 }, async ({ reason }) => {
					await receipt_call("abandon_import", { name: frm.doc.name, reason });
					frm.reload_doc();
				});
			});
		}
		if (parsed) {
			render_receipt_preview(frm);
			frm.add_custom_button(__("查看本批凭证"), () => {
				const dates = (frm.doc.rows || []).map(r => r.posting_date).filter(Boolean).sort();
				frappe.route_options = {company: frm.doc.company, receipt_import: frm.doc.name, from_date: dates[0], to_date: dates[dates.length - 1], period_preset: "", voucher_status: "全部有效凭证"};
				frappe.set_route("query-report", "China Voucher Ledger");
			});
		}
	},
});

async function receipt_call(method, args) {
	const response = await frappe.call({ method: `china_finance.services.bank_receipt_import.${method}`, args, freeze: true });
	return response.message;
}

function receipt_escape(value) { return frappe.utils.escape_html(String(value ?? "")); }

async function render_receipt_preview(frm) {
	const data = await receipt_call("preview_import", { name: frm.doc.name });
	frm.receipt_preview = data;
	const e = receipt_escape;
	const amount = value => frappe.format(value, { fieldtype: "Currency", options: "currency" }, { only_value: true }, { currency: "CNY" });
	const blocked = data.errors.length || ["已作废", "识别失败"].includes(data.status);
	const $wrapper = frm.fields_dict.preview.$wrapper;
	$wrapper.html(`
		<p>${e(data.mode)} · ${data.rows.length} 张回单 / ${data.transaction_count ?? data.rows.length} 笔交易 · 收入 ${amount(data.deposit_total)} · 支出 ${amount(data.withdrawal_total)}（按流水号去重合计）</p>
		<p class="text-muted">历史补回单只关联已有凭证。新业务仅生成草稿，审核记账后才进入报表。原件页码及页内位置可用于逐笔核对。</p>
		${data.errors.length ? `<div class="alert alert-danger">${data.errors.map(x => `第 ${e(x.page)} 页：${e(x.message)}`).join("<br>")}<br>请作废本批次并重新上传完整、正确的回单。</div>` : ""}
		${!blocked && data.mode === "新业务制证" ? '<button class="btn btn-default btn-sm receipt-batch">确认导入并生成所选草稿</button>' : ""}
		<div style="overflow:auto;margin-top:12px"><table class="table table-bordered"><thead><tr>
		<th>选择</th><th>日期 / 原件</th><th>收支 / 金额</th><th>对方 / 摘要</th><th>建议科目 / 依据</th><th>状态 / 已有凭证</th><th>操作</th>
		</tr></thead><tbody>${data.rows.map((r, index) => `<tr>
		<td>${!blocked && data.mode === "新业务制证" && !r.receipt && !r.candidates.length && (r.suggestion.account || r.suggestion.allocations) && !r.suggestion.blocked && r.status !== "冲突" ? `<input type="checkbox" class="receipt-selected" checked data-index="${index}">` : ""}</td>
		<td>${e(r.posting_date)}<br><a href="${e(data.source_file)}#page=${r.page_number}" target="_blank" rel="noopener">第 ${r.page_number} 页第 ${r.position} 张</a><br>${e(r.transaction_id)}</td>
		<td>${e(r.direction)}<br>${amount(r.amount)}</td><td>${e(r.counterparty)}<br>${e(r.summary)}</td>
		<td>${r.suggestion.allocations ? r.suggestion.allocations.map(a => `${e(a.account)}：${amount(a.amount)}`).join("<br>") : e(r.suggestion.account || "待人工分类")}<br><small>${e(r.suggestion.reason)}</small>${r.suggestion.allocations && !r.receipt ? `<br><label><input type="checkbox" class="receipt-social-confirm" data-index="${index}"> 已核对所属期，该期社保尚未计提</label>` : ""}</td>
		<td>${e(r.status)}${r.message ? `<br><small>${e(r.message)}</small>` : ""}${r.voucher_name ? `<br>${frappe.utils.get_form_link(r.voucher_type, r.voucher_name, true)}` : ""}
		${r.candidates.map(c => c.restricted ? '<br>存在需管理员核对的凭证' : `<br>${frappe.utils.get_form_link(c.doctype, c.name, true)} ${e(c.posting_date || "")}`).join("")}</td>
		<td>${r.receipt ? `${frappe.utils.get_form_link("China Bank Receipt", r.receipt, true, "查看回单记录")}${r.status === "已关联待核销" ? `<br><button class="btn btn-xs btn-default receipt-reconcile" data-index="${index}">核销</button>` : ""}${r.status === "凭证已取消或缺失" ? `<br><button class="btn btn-xs btn-default receipt-process" data-index="${index}">关联修订凭证</button>` : ""}` : !blocked && r.status !== "冲突" ? `<button class="btn btn-xs btn-default receipt-process" data-index="${index}">核对处理</button>` : ""}</td>
		</tr>`).join("")}</tbody></table></div>`);
	$wrapper.find(".receipt-process").on("click", event => receipt_dialog(frm, data.rows[event.currentTarget.dataset.index]));
	$wrapper.find(".receipt-reconcile").on("click", event => {
		const row = data.rows[event.currentTarget.dataset.index];
		frappe.confirm(__("确认将这笔回单对应银行交易与已关联凭证核销？"), async () => {
			await receipt_call("reconcile_receipt", { name: row.receipt });
			await frm.reload_doc();
		});
	});
	$wrapper.find(".receipt-batch").on("click", () => {
		const selected = $wrapper.find(".receipt-selected:checked").map((_, el) => data.rows[el.dataset.index]).get();
		if (!selected.length) return frappe.msgprint(__("请勾选已核对的回单"));
		frappe.confirm(__("已核对这 {0} 笔业务尚未记账，建议科目及业务依据正确，确认生成凭证草稿？", [selected.length]), async () => {
			const result = await receipt_call("process_import_batch", {name: frm.doc.name, confirmed: 1, rows: selected.map(row => ({
				name: row.name, account: row.suggestion.account, decision_hash: row.suggestion.decision_hash,
				social_not_accrued: $wrapper.find(`.receipt-social-confirm[data-index="${data.rows.indexOf(row)}"]`).is(":checked") ? 1 : 0,
			}))});
			await frm.reload_doc();
			frappe.msgprint(`新增草稿 ${result.created} 张，复用 ${result.reused} 笔，待处理 ${result.failed} 笔。<br>` + result.results.filter(r => r.error).map(r => `${e(r.name)}：${e(r.error)}`).join("<br>"));
		});
	});
}

function receipt_dialog(frm, row) {
	const can_create = frm.doc.mode === "新业务制证" && !row.receipt && !row.candidates.length && !row.suggestion.blocked;
	const create_label = row.suggestion.allocations ? "按社保计提及支付生成草稿" : "生成凭证草稿";
	const candidate = row.candidates.find(c => !c.restricted);
	const dialog = new frappe.ui.Dialog({ title: __("核对回单"), fields: [
		{ fieldtype: "HTML", options: `<p>${receipt_escape(row.posting_date)} · ${receipt_escape(row.direction)} ${receipt_escape(row.amount)} CNY</p><p>${receipt_escape(row.summary)}</p><p>${receipt_escape(row.suggestion.reason)}</p>${china_finance.bank_receipts.allocation_html(row.suggestion, {account: frm.receipt_preview.bank_gl_account, amount: row.amount})}<details><summary>收付款方及费用明细</summary>${china_finance.bank_receipts.details_html(row.raw_data)}</details>` },
		{ fieldname: "action", label: "处理方式", fieldtype: "Select", options: can_create ? `关联已有凭证\n${create_label}` : "关联已有凭证", default: can_create ? create_label : "关联已有凭证" },
		{ fieldname: "social_not_accrued", label: "已核对回单所属时期，该期社保尚未计提，同意生成计提及支付分录；已计提时应手工冲应付科目后关联", fieldtype: "Check", depends_on: 'eval:doc.action=="按社保计提及支付生成草稿"' },
		{ fieldname: "account", label: "对方科目", fieldtype: "Link", options: "Account", default: row.suggestion.account,
			depends_on: 'eval:doc.action=="生成凭证草稿"', get_query: () => ({ filters: { company: frm.doc.company, is_group: 0, disabled: 0 } }) },
		{ fieldname: "party_type", label: "往来单位类型", fieldtype: "Select", options: "\nCustomer\nSupplier\nEmployee\nShareholder", depends_on: 'eval:doc.action=="生成凭证草稿"' },
		{ fieldname: "party", label: "往来单位", fieldtype: "Dynamic Link", options: "party_type", depends_on: 'eval:doc.action=="生成凭证草稿"' },
		{ fieldname: "voucher_type", label: "凭证类型", fieldtype: "Select", options: "Journal Entry\nPayment Entry", default: candidate?.doctype || "Journal Entry", depends_on: 'eval:doc.action=="关联已有凭证"' },
		{ fieldname: "voucher_name", label: "已有凭证", fieldtype: "Dynamic Link", options: "voucher_type", default: candidate?.name, depends_on: 'eval:doc.action=="关联已有凭证"', get_query: () => ({ filters: { company: frm.doc.company, docstatus: ["!=", 2] } }) },
		{ fieldname: "create_bank_transaction", label: "同时补建银行交易（用于后续核销）", fieldtype: "Check", default: 0, depends_on: 'eval:doc.action=="关联已有凭证"' },
		{ fieldname: "notes", label: "核对说明", fieldtype: "Small Text" },
		{ fieldname: "confirmed", label: "已核对原回单、业务依据及重复记账情况", fieldtype: "Check", reqd: 1 },
	], primary_action_label: __("确认处理"), primary_action: async values => {
		if (!values.confirmed) return frappe.msgprint(__("请先核对并勾选确认"));
		dialog.get_primary_btn().prop("disabled", true);
		try {
			const result = await receipt_call("process_receipt", { ...values, decision_hash: row.suggestion.decision_hash, action: values.action === "按社保计提及支付生成草稿" ? "create_social" : values.action === "生成凭证草稿" ? "create" : "link", name: frm.doc.name, row_name: row.name });
			if (result.error) { frappe.msgprint(receipt_escape(result.error)); return; }
			dialog.hide();
			await frm.reload_doc();
		} finally { dialog.get_primary_btn().prop("disabled", false); }
	} });
	dialog.show();
}
