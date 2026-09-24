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
			open_invoice_selector(frm, "Purchase Invoice", "supplier", "Supplier");
		});
	}
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
