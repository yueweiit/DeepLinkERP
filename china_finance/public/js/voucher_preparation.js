frappe.provide("china_finance.preparation");

(() => {
	const api = async (method, args) => (await frappe.call({method: `china_finance.services.voucher_preparation.${method}`, args, type: "POST", freeze: true})).message;
	const esc = value => frappe.utils.escape_html(String(value ?? ""));
	const money = (value, currency) => frappe.format(value, {fieldtype: "Currency", options: "currency"}, {only_value: true}, {currency});

	china_finance.preparation.edit = async (name, refresh) => {
		const result = await api("get_draft", {name});
		if (!result.can_edit) return frappe.msgprint(esc(result.reason));
		const doc = result.doc;
		const account_query = () => ({filters: {company: doc.company, is_group: 0, disabled: 0}});
		const fields = [
			{fieldname: "source_row", fieldtype: "Data", hidden: 1},
			{fieldname: "account", fieldtype: "Link", options: "Account", label: __("科目"), reqd: 1, in_list_view: 1, columns: 3, get_query: account_query},
			{fieldname: "user_remark", fieldtype: "Small Text", label: __("摘要"), in_list_view: 1, columns: 3},
			{fieldname: "debit_in_account_currency", fieldtype: "Float", precision: 2, label: __("借方（科目币种）"), in_list_view: 1, columns: 2},
			{fieldname: "credit_in_account_currency", fieldtype: "Float", precision: 2, label: __("贷方（科目币种）"), in_list_view: 1, columns: 2},
			{fieldname: "exchange_rate", fieldtype: "Float", label: __("汇率"), default: 1},
			{fieldname: "party_type", fieldtype: "Link", options: "DocType", label: __("往来类型"), get_query: () => ({filters: {name: ["in", ["Customer", "Supplier", "Employee", "Shareholder"]]}})},
			{fieldname: "party", fieldtype: "Dynamic Link", options: "party_type", label: __("往来单位")},
			{fieldname: "cost_center", fieldtype: "Link", options: "Cost Center", label: __("成本中心"), get_query: () => ({filters: {company: doc.company, is_group: 0}})},
			{fieldname: "project", fieldtype: "Link", options: "Project", label: __("项目")},
		];
		const dialog = new frappe.ui.Dialog({title: `${__("编辑未记账凭证")} · ${name}`, size: "extra-large", fields: [
			{fieldtype: "HTML", options: `<p>${esc(doc.company)} · ${esc(result.currency)} · ${__("保存后需要重新核对。银行收支必须与原回单一致。")}</p>`},
			{fieldname: "posting_date", fieldtype: "Date", label: __("凭证日期"), default: doc.posting_date, reqd: 1},
			{fieldname: "user_remark", fieldtype: "Small Text", label: __("凭证摘要"), default: doc.user_remark},
			{fieldname: "accounts", fieldtype: "Table", label: __("会计分录"), in_place_edit: true, fields,
				data: doc.accounts.map(row => ({...row, source_row: row.name}))},
			{fieldtype: "HTML", options: `${result.receipts.map(r => `<a href="${esc(r.source_file)}#page=${r.page_number}" target="_blank" rel="noopener">原回单：第 ${r.page_number} 页第 ${r.position} 张</a>`).join(" · ")}${result.cash.error ? `<p class="text-warning">${esc(result.cash.error)}</p>` : ""}`},
			{fieldname: "cash_flow_rows", fieldtype: "Table", label: __("现金流项目（按本位币核对）"), hidden: !result.cash.rows.length, cannot_add_rows: true, cannot_delete_rows: true, in_place_edit: true,
				data: result.cash.rows, fields: [
					{fieldname: "cash_account", fieldtype: "Data", label: __("现金或银行科目"), read_only: 1, in_list_view: 1, columns: 4},
					{fieldname: "direction", fieldtype: "Data", label: __("收付"), read_only: 1, in_list_view: 1, columns: 1},
					{fieldname: "amount", fieldtype: "Float", label: __("金额"), read_only: 1, in_list_view: 1, columns: 2},
					{fieldname: "row_code", fieldtype: "Select", label: __("现金流项目"), options: [{value: "", label: "请选择"}, ...result.cash.options], in_list_view: 1, columns: 3},
				]},
			{fieldname: "reason", fieldtype: "Small Text", label: __("修改说明（调整日期必填）")},
		], primary_action_label: __("保存草稿"), primary_action: async values => {
			dialog.get_primary_btn().prop("disabled", true);
			try {
				await api("save_draft", {name, modified: doc.modified, ...values});
				dialog.hide();
				frappe.show_alert({message: __("草稿已保存，请重新核对"), indicator: "green"});
				refresh?.();
			} finally { dialog.get_primary_btn().prop("disabled", false); }
		}});
		dialog.add_custom_action(__("原件与完整凭证"), () => frappe.set_route("Form", "Journal Entry", name));
		dialog.add_custom_action(__("预览打印（未记账）"), () => {
			const body = `<h3>未记账凭证 · ${esc(doc.posting_date)}</h3><p>${esc(doc.company)} · ${esc(result.currency)} · ${esc(name)}</p><table border="1" cellspacing="0" cellpadding="8"><tr><th>摘要</th><th>科目</th><th>借方</th><th>贷方</th></tr>${doc.accounts.map(r => `<tr><td>${esc(r.user_remark || doc.user_remark)}</td><td>${esc(r.account)}</td><td>${money(r.debit, result.currency)}</td><td>${money(r.credit, result.currency)}</td></tr>`).join("")}</table><p>未记账，仅供核对。此预览为打开时已保存的版本。</p>`;
			const win = window.open("", "_blank");
			if (win) { win.document.write(`<html><head><title>未记账凭证</title></head><body>${body}</body></html>`); win.document.close(); win.print(); }
		});
		dialog.show();
	};

	china_finance.preparation.trial = async (company, from_date, to_date) => {
		const result = await api("trial_balance", {company, from_date, to_date});
		const labels = {opening: "期初余额", posted_debit: "已记账借方", posted_credit: "已记账贷方", draft_debit: "草稿借方", draft_credit: "草稿贷方", expected_balance: "预计余额"};
		const dialog = new frappe.ui.Dialog({title: __("含未记账凭证的科目余额试算"), size: "extra-large", fields: [{fieldtype: "HTML", options: `
			<p>${esc(company)} · ${esc(from_date)} — ${esc(to_date)} · ${esc(result.currency)}</p><p>${esc(result.message)}</p>
			<p>本期草稿 ${result.draft_count} 张；更早期间草稿 ${result.earlier_drafts} 张。</p>
			${result.excluded.length ? `<div class="alert alert-warning">以下草稿未纳入，试算不完整：${result.excluded.map(r => `${esc(r.name)}：${esc(r.error)}`).join("<br>")}</div>` : ""}
			<div style="overflow:auto"><table class="table table-bordered"><thead><tr><th>科目</th>${Object.values(labels).map(label => `<th>${label}</th>`).join("")}</tr></thead><tbody>${result.rows.map(row => `<tr><td>${esc(row.account)}</td>${Object.keys(labels).map(key => `<td class="text-right">${money(row[key], result.currency)}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`}]});
		dialog.show();
	};

	china_finance.preparation.review = async names => {
		const preview = await api("review_preview", {names});
		const options = row => Object.fromEntries(row.cash.options.map(o => [o.value, o.label]));
		const body = preview.map(row => `<details open><summary>${esc(row.name)} · ${esc(row.posting_date)}</summary><table class="table table-bordered"><tr><th>摘要</th><th>科目</th><th>借方</th><th>贷方</th></tr>${row.accounts.map(r => `<tr><td>${esc(r.summary)}</td><td>${esc(r.account)}</td><td>${esc(r.debit)}</td><td>${esc(r.credit)}</td></tr>`).join("")}</table><p>${row.cash.rows.map(r => `${esc(r.cash_account)} ${esc(r.direction)} ${esc(r.amount)} → ${esc(options(row)[r.row_code] || "待选择现金流项目")}`).join("<br>")}${esc(row.cash.error)}</p></details>`).join("");
		return new Promise(resolve => {
			const dialog = new frappe.ui.Dialog({title: __("核对凭证与现金流项目"), size: "extra-large", fields: [{fieldtype: "HTML", options: body}], primary_action_label: __("核对完成，待记账"), primary_action: async () => {
				dialog.get_primary_btn().prop("disabled", true);
				try {
					const rows = await api("review_drafts", {names, versions: Object.fromEntries(preview.map(r => [r.name, r.modified])), cash_plans: Object.fromEntries(preview.map(r => [r.name, r.cash.rows]))});
					frappe.msgprint(rows.map(r => `${esc(r.name)}：${r.success ? "核对完成，待记账" : esc(r.error)}`).join("<br>"));
					dialog.hide(); resolve(rows);
				} finally { dialog.get_primary_btn().prop("disabled", false); }
			}});
			dialog.onhide = () => resolve([]);
			dialog.show();
		});
	};

	china_finance.preparation.bind_report = report => {
		report.page.add_menu_item(__("凭证准备模式设置"), () => frappe.set_route("Form", "China Finance Settings", report.get_filter_value("company")));
		report.page.add_inner_button(__("核对所选草稿"), async () => {
			const indices = report.datatable?.rowmanager.getCheckedRows() || [];
			const names = [...new Set(indices.map(i => report.data[i]?.draft_name).filter(Boolean))];
			if (!names.length) return frappe.msgprint(__("请勾选未记账凭证的分录行；同张凭证只处理一次"));
			await china_finance.preparation.review(names);
			report.refresh();
		});
		report.page.add_inner_button(__("未记账试算"), () => china_finance.preparation.trial(report.get_filter_value("company"), report.get_filter_value("from_date"), report.get_filter_value("to_date")));
		report.page.add_inner_button(__("月末处理"), () => frappe.new_doc("China Closing Run", {company: report.get_filter_value("company"), from_date: report.get_filter_value("from_date"), to_date: report.get_filter_value("to_date")}));
		report.page.add_inner_button(__("新增草稿"), () => frappe.new_doc("Journal Entry", {company: report.get_filter_value("company")}));
	};
})();
