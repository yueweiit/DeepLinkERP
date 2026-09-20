// Run with: node --test china_finance/tests/test_bank_account.js
// Exercise the installed Frappe control implementation, including its async lock.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { test } = require("node:test");
const vm = require("node:vm");

const controls = path.resolve(__dirname, "../../../frappe/frappe/public/js/frappe/form/controls");
const patch = path.resolve(__dirname, "../public/js/bank_account.js");
const oldAccount = "100201 - 银行存款－基本存款账户 - YC";
const newAccount = "100201 - 银行存款－基本存款账户 - 悦为智能";
const title = "银行存款－基本存款账户";
const tick = () => new Promise((resolve) => setImmediate(resolve));

function harness(patched = true) {
	let handlers;
	const titles = {};
	const context = vm.createContext({
		frappe: {
			ui: { form: { on: (_doctype, events) => { handlers = events; } } },
			provide() {},
			boot: { link_title_doctypes: ["Account"] },
			utils: {
				get_link_title: (_doctype, name) => titles[name],
				add_link_title: (_doctype, name, label) => { titles[name] = label; },
				fetch_link_title: async () => title,
			},
			run_serially: async (steps) => { for (const step of steps) await step(); },
		},
		Awesomplete: function () {},
		strip_html: (value) => value,
		__: (value) => value,
	});
	for (const file of ["base_control", "base_input", "data", "link"]) {
		const source = fs.readFileSync(path.join(controls, `${file}.js`), "utf8")
			.replace(/^import .*;\n/gm, "");
		vm.runInContext(source, context);
	}
	const control = Object.create(context.frappe.ui.form.ControlLink.prototype);
	let input = "";
	const requests = [];
	Object.assign(control, {
		df: { options: "Account", fieldname: "account" },
		doc: { account: "" },
		$input: {
			cache: { Account: { "": [{ value: oldAccount }] } },
			val(value) { if (arguments.length) input = value; return input; },
		},
		set_mandatory() {},
		set_invalid() {},
		validate(value) {
			if (!value) return "";
			return new Promise((resolve, reject) => requests.push({ value, resolve, reject }));
		},
		async set_model_value(value) {
			this.doc.account = value;
			this.last_value = value;
			this.set_formatted_input(value);
		},
	});
	const frm = { fields_dict: { account: control } };
	if (patched) {
		vm.runInContext(fs.readFileSync(patch, "utf8"), context);
		handlers.refresh(frm);
	}
	return { control, requests, frm, handlers };
}

test("native control drops selection while an invalid old account is being validated", async () => {
	const { control, requests } = harness(false);
	const old = control.parse_validate_and_set_in_model(oldAccount);
	await control.parse_validate_and_set_in_model(newAccount, null, title);
	assert.equal(requests.length, 1);
	requests.shift().resolve(undefined);
	await old;
	assert.equal(control.doc.account, undefined);
});

test("new selection survives old failed validation and Save waits for it", async () => {
	const { control, requests, handlers, frm } = harness();
	const old = control.parse_validate_and_set_in_model(oldAccount);
	const selected = control.parse_validate_and_set_in_model(newAccount, null, title);
	control.$input.val(title); // Awesomplete replaces the input immediately.
	assert.equal(control.get_input_value(), newAccount);
	let saved = false;
	const save = handlers.before_save(frm).then(() => { saved = true; });
	requests.shift().resolve(undefined);
	await old;
	await tick();
	assert.equal(saved, false);
	assert.equal(requests[0].value, newAccount);
	requests.shift().resolve(newAccount);
	await Promise.all([selected, save]);
	assert.equal(control.doc.account, newAccount);
	assert.equal(control.get_input_value(), newAccount);
	assert.equal(control.$input.val(), title);
});

test("same title in different companies resolves to the last selection on blur", async () => {
	const { control, requests } = harness();
	control.doc.account = oldAccount;
	control.set_formatted_input(oldAccount);
	await tick();
	const selected = control.parse_validate_and_set_in_model(newAccount, null, title);
	control.$input.val(title);
	const blur = control.parse_validate_and_set_in_model(control.get_input_value(), null, title);
	requests.shift().resolve(newAccount);
	await Promise.all([selected, blur]);
	assert.equal(control.doc.account, newAccount);
	assert.equal(requests.length, 0);
});

test("changing company clears the old account and cached suggestions even during validation", async () => {
	const { control, requests, handlers, frm } = harness();
	const selected = control.parse_validate_and_set_in_model(oldAccount, null, title);
	const changed = handlers.company(frm);
	assert.equal(Object.keys(control.$input.cache).length, 0);
	requests.shift().resolve(oldAccount);
	await Promise.all([selected, changed]);
	assert.equal(control.doc.account, "");
	assert.equal(control.get_input_value(), "");
});

test("an invalid final selection remains invalid", async () => {
	const { control, requests, handlers, frm } = harness();
	const selected = control.parse_validate_and_set_in_model("missing-account", null, title);
	requests.shift().resolve(undefined);
	await selected;
	await handlers.before_save(frm);
	assert.equal(control.doc.account, undefined);
});

test("a failed network request does not lock out the next selection", async () => {
	const { control, requests } = harness();
	const old = control.parse_validate_and_set_in_model(oldAccount);
	const rejected = assert.rejects(old, /network error/);
	const selected = control.parse_validate_and_set_in_model(newAccount, null, title);
	requests.shift().reject(new Error("network error"));
	await rejected;
	await tick();
	assert.equal(requests[0].value, newAccount);
	requests.shift().resolve(newAccount);
	await selected;
	assert.equal(control.doc.account, newAccount);
});

test("company defaults can change before the account input is rendered", async () => {
	const { handlers } = harness();
	let cleared;
	await handlers.company({
		fields_dict: { account: {} },
		set_value: (field, value) => { cleared = { field, value }; },
	});
	assert.deepEqual(cleared, { field: "account", value: "" });
});
