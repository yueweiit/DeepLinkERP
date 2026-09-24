frappe.ui.form.on("Payment Entry", {
	refresh(frm) {
		update_invoice_selector_button(frm);
	},

	payment_type(frm) {
		update_invoice_selector_button(frm);
	},
});

function update_invoice_selector_button(frm) {
	frm.remove_custom_button(__("选销售应收单"));
	frm.remove_custom_button(__("选采购应付单"));

	if (!frm.is_new() || frm.doc.payment_type === "Internal Transfer") return;

	if (frm.doc.payment_type === "Receive") {
		frm.add_custom_button(__("选销售应收单"), () => {
			open_invoice_selector(frm, "Sales Invoice", "customer", "Customer");
		});
	} else if (frm.doc.payment_type === "Pay") {
		frm.add_custom_button(__("选采购应付单"), () => {
			open_purchase_invoice_selector(frm);
		});
	}
}

function open_purchase_invoice_selector(frm) {
	if (!frm.doc.company) {
		frappe.msgprint(__("请先选择公司"));
		return;
	}

	const dialog = new frappe.ui.Dialog({
		title: __("选择采购应付单"),
		fields: [
			{
				fieldname: "search",
				label: __("搜索采购应付单"),
				fieldtype: "Data",
				placeholder: __("输入采购应付单号"),
			},
			{ fieldname: "invoice_table", fieldtype: "HTML" },
		],
		primary_action_label: __("添加到付款单"),
		primary_action() {
			const names = dialog.$wrapper
				.find(".china-purchase-invoice-option:checked")
				.map((_index, element) => element.dataset.name)
				.get();
			if (!names.length) {
				frappe.msgprint(__("请选择至少一张采购应付单"));
				return;
			}
			dialog.hide();
			load_selected_invoices(frm, "Purchase Invoice", "supplier", "Supplier", names);
		},
	});

	let search_timeout;
	dialog.show();
	dialog.get_field("search").$input.on("input", () => {
		clearTimeout(search_timeout);
		search_timeout = setTimeout(
			() => load_purchase_invoice_candidates(frm, dialog),
			250
		);
	});
	load_purchase_invoice_candidates(frm, dialog);
}

async function load_purchase_invoice_candidates(frm, dialog) {
	const response = await frappe.call({
		method: "china_finance.services.purchase_payables.get_purchase_payment_candidates",
		args: {
			company: frm.doc.company,
			supplier: frm.doc.party || "",
			txt: dialog.get_value("search") || "",
		},
	});
	const rows = response.message || [];
	const table = rows.length
		? `<div class="table-responsive"><table class="table table-bordered table-hover">
			<thead><tr>
				<th style="width: 32px"><input type="checkbox" class="china-purchase-invoice-select-all"></th>
				<th>${__("采购应付单")}</th><th>${__("采购订单")}</th><th>${__("采购收货单")}</th>
				<th>${__("到期日")}</th><th class="text-right">${__("未付金额")}</th>
			</tr></thead><tbody>
			${rows.map(purchase_invoice_selection_row).join("")}
			</tbody></table></div>`
		: `<div class="text-muted text-center p-4">${__("没有可付款的采购应付单")}</div>`;
	dialog.get_field("invoice_table").$wrapper.html(table);
	dialog.get_field("invoice_table").$wrapper.find(".china-purchase-invoice-select-all").on("change", (event) => {
		dialog
			.get_field("invoice_table")
			.$wrapper
			.find(".china-purchase-invoice-option")
			.prop("checked", event.currentTarget.checked);
	});
}

function purchase_invoice_selection_row(row) {
	const escape = (value) => frappe.utils.escape_html(String(value || ""));
	const amount = format_currency(row.outstanding_amount || 0, row.currency);
	return `<tr>
		<td><input type="checkbox" class="china-purchase-invoice-option" data-name="${escape(row.name)}"></td>
		<td><a href="/app/purchase-invoice/${encodeURIComponent(row.name)}" target="_blank">${escape(row.name)}</a><br><small class="text-muted">${escape(row.supplier)}</small></td>
		<td>${escape(row.purchase_orders) || "-"}</td>
		<td>${escape(row.purchase_receipts) || "-"}</td>
		<td>${escape(row.due_date) || "-"}</td>
		<td class="text-right">${escape(amount)}</td>
	</tr>`;
}

function open_invoice_selector(frm, doctype, party_field, party_type) {
	const setters = { company: frm.doc.company };
	setters[party_field] = frm.doc.party || null;

	const dialog = new frappe.ui.form.MultiSelectDialog({
		doctype,
		target: frm,
		setters,
		add_filters_group: 1,
		get_query() {
			const filters = {
				company: frm.doc.company,
				docstatus: 1,
				outstanding_amount: [">", 0],
			};
			if (frm.doc.party) filters[party_field] = frm.doc.party;
			return { filters };
		},
		action(selections) {
			if (!selections.length) {
				frappe.msgprint(__("请选择至少一张单据"));
				return;
			}

			dialog.dialog.hide();
			load_selected_invoices(frm, doctype, party_field, party_type, selections);
		},
	});
}

async function load_selected_invoices(frm, doctype, party_field, party_type, names) {
	const fields = [
		"name",
		party_field,
		"company",
		"posting_date",
		"due_date",
		"grand_total",
		"outstanding_amount",
		"currency",
	];
	fields.push(doctype === "Sales Invoice" ? "debit_to" : "credit_to");
	if (doctype === "Purchase Invoice") fields.push("bill_no");
	const invoices = await frappe.db.get_list(doctype, {
		filters: { name: ["in", names], docstatus: 1, outstanding_amount: [">", 0] },
		fields,
		limit: names.length,
	});

	const parties = [...new Set(invoices.map((invoice) => invoice[party_field]).filter(Boolean))];
	if (parties.length > 1 || (frm.doc.party && parties.some((party) => party !== frm.doc.party))) {
		frappe.throw(__("选择的单据必须属于同一个往来单位"));
	}

	if (!frm.doc.party && parties[0]) {
		await frm.set_value("party_type", party_type);
		await frm.set_value("party", parties[0]);
	}

	const existing = new Set(
		(frm.doc.references || [])
			.filter((row) => row.reference_doctype === doctype)
			.map((row) => row.reference_name)
	);

	for (const invoice of invoices) {
		if (existing.has(invoice.name)) continue;
		const row = frm.add_child("references");
		row.reference_doctype = doctype;
		row.reference_name = invoice.name;
		row.due_date = invoice.due_date;
		row.total_amount = invoice.grand_total;
		row.outstanding_amount = invoice.outstanding_amount;
		row.allocated_amount = 0;
		row.bill_no = invoice.bill_no;
		row.account = invoice.debit_to || invoice.credit_to;
		row.exchange_rate = 1;
	}

	frm.refresh_field("references");
	frm.events.set_unallocated_amount(frm);
}
