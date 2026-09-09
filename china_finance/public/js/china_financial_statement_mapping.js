frappe.ui.form.on("China Financial Statement Mapping", {
	refresh(frm) {
		frm.set_query("account", () => ({
			filters: { company: frm.doc.company, is_group: 0, disabled: 0 },
		}));
		load_statement_row_options(frm);
		add_review_actions(frm);
		load_review_context(frm);
	},
	template(frm) {
		["row_code", "cash_inflow_row_code", "cash_outflow_row_code"].forEach((fieldname) => frm.set_value(fieldname, ""));
		load_statement_row_options(frm);
		load_review_context(frm);
	},
	row_code(frm) {
		load_review_context(frm);
	},
	cash_inflow_row_code(frm) {
		load_review_context(frm);
	},
	cash_outflow_row_code(frm) {
		load_review_context(frm);
	},
});

function load_statement_row_options(frm) {
	const fieldnames = ["row_code", "cash_inflow_row_code", "cash_outflow_row_code"];
	fieldnames.forEach((fieldname) => frm.get_field(fieldname)?.set_data([]));
	if (!frm.doc.template) return;

	const templateName = frm.doc.template;
	frappe.db.get_doc("China Financial Statement Template", templateName).then((template) => {
		if (frm.doc.template !== templateName) return;
		const options = (template.rows || []).map((row) => ({
			value: row.row_code,
			label: `${row.row_code} | ${row.label}`,
			description: row.row_type === "Formula" ? __("公式汇总项目") : __("列报项目"),
		}));
		fieldnames.forEach((fieldname) => {
			const field = frm.get_field(fieldname);
			if (field) {
				field.set_data(options);
				field.refresh_input();
			}
		});
		frm.__statement_rows = Object.fromEntries((template.rows || []).map((row) => [row.row_code, row]));
		render_local_context(frm);
	});
}

function add_review_actions(frm) {
	if (frm.is_new()) return;
	if (frm.doc.reviewed) {
		frm.add_custom_button(__("撤销复核"), () => update_review_status(frm, false), __("复核"));
		frm.set_intro(__("已复核。修改归类、科目、期间或金额方向后，系统会自动要求重新复核。"), "green");
		return;
	}
	frm.add_custom_button(__("确认本条映射正确"), () => {
		frappe.prompt(
			[{ fieldname: "review_notes", fieldtype: "Small Text", label: __("复核说明"), description: __("可选，例如：已按 2026 年会计政策复核。") }],
			(values) => update_review_status(frm, true, values.review_notes),
			__("确认映射复核"),
			__("确认"),
		);
	}, __("复核"));
	frm.set_intro(__("待复核：先确认科目性质和归入项目；现金流量表还需确认收款、付款两个方向。"), "orange");
}

function update_review_status(frm, reviewed, reviewNotes = null) {
	frappe.call({
		method: "china_finance.services.statement_mapping_review.set_mapping_reviewed",
		args: { name: frm.doc.name, reviewed: reviewed ? 1 : 0, review_notes: reviewNotes },
		freeze: true,
		freeze_message: reviewed ? __("正在保存复核结果") : __("正在撤销复核"),
		callback: () => frm.reload_doc(),
	});
}

function load_review_context(frm) {
	if (frm.is_new()) {
		render_local_context(frm);
		return;
	}
	frappe.call({
		method: "china_finance.services.statement_mapping_review.get_mapping_review_context",
		args: { name: frm.doc.name },
		callback: (response) => render_review_context(frm, response.message),
	});
}

function render_local_context(frm) {
	const rows = frm.__statement_rows || {};
	const render = (account = {}) => render_review_context(frm, {
		mapping_source: frm.doc.mapping_source,
		reviewed: Boolean(frm.doc.reviewed),
		statement_type: frm.doc.template?.includes("Cash Flow") ? "Cash Flow" : null,
		account: { name: frm.doc.account, ...account },
		row: row_context(rows, frm.doc.row_code),
		cash_inflow_row: row_context(rows, frm.doc.cash_inflow_row_code),
		cash_outflow_row: row_context(rows, frm.doc.cash_outflow_row_code),
		guidance: __("保存后可查看完整科目性质和复核提示。"),
	});
	if (!frm.doc.account) {
		render();
		return;
	}
	const account_name = frm.doc.account;
	frappe.db.get_value(
		"Account",
		account_name,
		["account_name", "account_number", "root_type", "account_type"],
	).then((response) => {
		if (frm.doc.account !== account_name) return;
		const account = response.message || {};
		account.account_label = [account.account_number, account.account_name].filter(Boolean).join(" - ");
		render(account);
	}).catch(() => {
		if (frm.doc.account === account_name) render();
	});
}

function row_context(rows, rowCode) {
	if (!rowCode || !rows[rowCode]) return null;
	return { row_code: rowCode, label: rows[rowCode].label, display: `${rowCode} | ${rows[rowCode].label}` };
}

function render_review_context(frm, context) {
	frm.dashboard.parent.find(".china-finance-mapping-context").closest(".form-dashboard-section").remove();
	if (!context) return;
	const escape = frappe.utils.escape_html;
	const item = (label, value) => `<div class="mb-2"><span class="text-muted">${escape(label)}</span><div class="font-weight-bold">${escape(value || __("未选择"))}</div></div>`;
	const account = context.account || {};
	const accountLabel = account.account_label || [account.account_number, account.account_name].filter(Boolean).join(" | ");
	const nature = [account.root_type, account.account_type].filter(Boolean).join(" / ");
	const sections = [
		item(__("会计科目"), accountLabel),
		item(__("科目性质"), nature),
		item(__("归入报表项目"), context.row?.display),
	];
	if (context.statement_type === "Cash Flow") {
		sections.push(item(__("收到现金时归入"), context.cash_inflow_row?.display));
		sections.push(item(__("支付现金时归入"), context.cash_outflow_row?.display));
	}
	const source = context.mapping_source === "Automatic" ? __("系统建议，待复核") : __("人工维护");
	const status = context.reviewed ? `<span class="text-success">${__("已复核")}</span>` : `<span class="text-warning">${__("待复核")}</span>`;
	const html = `<div class="china-finance-mapping-context">
		<div class="d-flex justify-content-between mb-3"><strong>${__("复核指引")}</strong><span>${status}</span></div>
		<div class="row">${sections.map((content) => `<div class="col-sm-6">${content}</div>`).join("")}</div>
		<div class="small text-muted mt-2">${__("映射来源")}：${escape(source)}。${escape(context.guidance || "")}</div>
	</div>`;
	frm.dashboard.add_section(html, __("映射复核"));
	frm.dashboard.show();
}
