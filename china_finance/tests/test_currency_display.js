// Exercise Frappe's real currency resolver and formatter with USD system defaults.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { test } = require("node:test");
const vm = require("node:vm");

const frappeJs = path.resolve(__dirname, "../../../frappe/frappe/public/js/frappe");
const doctypes = path.resolve(__dirname, "../china_finance/doctype");
function field(doctype, fieldname) {
	return JSON.parse(fs.readFileSync(path.join(doctypes, doctype, doctype + ".json"))).fields
		.find((df) => df.fieldname === fieldname);
}

function harness() {
	const context = vm.createContext({
		$: { extend: Object.assign }, locals: {}, cur_frm: { doc: { currency: "CNY" } },
		__: (value) => value, cstr: String, cint: (value) => parseInt(value || 0),
		in_list: (items, value) => items.includes(value),
		replace_all: (value, search, replacement) => value.split(search).join(replacement),
		frappe: {
			meta: {}, form: {}, utils: {}, defaults: {},
			boot: { sysdefaults: { currency: "USD", currency_precision: 2 } },
			model: { get_value: (doctype, name, key) => doctype === ":Currency" && key === "symbol"
				? ({ CNY: "¥", USD: "$", EUR: "€" })[name] : undefined },
		},
	});
	context.window = context;
	context.frappe.provide = (name) => {
		let target = context;
		for (const part of name.split(".")) target = target[part] ||= {};
	};
	for (const file of ["model/meta.js", "utils/number_format.js", "form/formatters.js"]) {
		const source = fs.readFileSync(path.join(frappeJs, file), "utf8").replace('import "./datatype";', "");
		vm.runInContext(source, context, { filename: file });
	}
	return context;
}

test("voucher grid distinguishes company amounts from account amounts despite USD defaults", () => {
	const ctx = harness();
	const format = ctx.frappe.form.formatters.Currency;
	const row = { account_currency: "USD" };
	assert.equal(format(700, field("china_accounting_voucher_entry", "debit"), { only_value: true }, row), "¥ 700.00");
	assert.equal(format(100, field("china_accounting_voucher_entry", "debit_in_account_currency"), { only_value: true }, row), "$ 100.00");
	// The former missing-options metadata reproduces the user's screenshot.
	assert.equal(format(700, { fieldtype: "Currency" }, { only_value: true }, row), "$ 700.00");
});

test("totals, tax rows and sales settlements use the actual parent currency", () => {
	const ctx = harness();
	const format = ctx.frappe.form.formatters.Currency;
	assert.equal(format(700, field("china_accounting_voucher", "total_debit"), { only_value: true }, { currency: "CNY" }), "¥ 700.00");
	ctx.cur_frm.doc.currency = "EUR";
	for (const [doctype, name] of [["china_tax_invoice_item", "tax_amount"], ["china_sales_settlement_item", "settlement_amount"]]) {
		assert.equal(format(100, field(doctype, name), { only_value: true }, {}), "€ 100.00");
	}
});

test("report and bank rows retain their own currency when another form remains active", () => {
	const ctx = harness();
	ctx.cur_frm.doc.currency = "USD";
	const format = ctx.frappe.form.formatters.Currency;
	assert.equal(format(500, { fieldtype: "Currency", options: "currency" }, { only_value: true }, { currency: "CNY" }), "¥ 500.00");
	assert.equal(format(100, field("china_reconciliation_line", "debit"), { only_value: true }, { currency: "EUR" }), "€ 100.00");
});

function reconciliationHarness(doctype) {
	const ctx = harness();
	let events;
	ctx.frappe.ui = { form: { on: (name, handlers) => { events = handlers; } } };
	ctx.frappe.db = { get_value: async (type) => ({ message: {
		Company: { default_currency: "CNY" }, Account: { account_currency: "USD" },
		"Bank Account": { account: "USD bank" },
	}[type] }) };
	vm.runInContext(fs.readFileSync(path.join(doctypes, doctype, doctype + ".js"), "utf8"), ctx);
	const frm = { doc: { company: "Company", docstatus: 0 }, refresh_field: () => {},
		set_value: async (field, value) => Object.assign(frm.doc, typeof field === "string" ? { [field]: value } : field) };
	return { events, frm };
}

test("new bank statements resolve base and bank currencies before saving", async () => {
	const { events, frm } = reconciliationHarness("china_reconciliation_statement");
	Object.assign(frm.doc, { statement_type: "Bank", account: "USD bank", lines: [
		{ line_source: "Ledger" }, { line_source: "Bank Transaction" },
	] });
	await events.onload(frm);
	assert.equal(frm.doc.currency, "CNY");
	assert.equal(frm.doc.bank_currency, "USD");
	assert.deepEqual(frm.doc.lines.map((row) => row.currency), ["CNY", "USD"]);
	frm.doc.statement_type = "Customer";
	await events.statement_type(frm);
	assert.equal(frm.doc.bank_currency, "CNY");
});

test("new reconciliation scopes follow the selected bank currency and reset for a customer", async () => {
	const { events, frm } = reconciliationHarness("china_reconciliation_scope");
	Object.assign(frm.doc, { scope_type: "Bank", reference_name: "Foreign Bank" });
	await events.onload(frm);
	assert.equal(frm.doc.currency, "USD");
	frm.doc.scope_type = "Customer";
	await events.scope_type(frm);
	assert.equal(frm.doc.currency, "CNY");
});
