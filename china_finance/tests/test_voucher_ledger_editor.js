// Run with: node --test china_finance/tests/test_voucher_ledger_editor.js
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { test } = require("node:test");

const root = path.resolve(__dirname, "..");
const source = fs.readFileSync(
	path.join(root, "china_finance/report/china_voucher_ledger/china_voucher_ledger.js"),
	"utf8"
);

function inputHarness() {
	const handlers = {};
	return {
		handlers,
		value: "",
		on(event, handler) {
			handlers[event] = handler;
			return this;
		},
		attr() {
			return this;
		},
		select() {
			this.selected = true;
			return this;
		},
		val(value) {
			if (value === undefined) return this.value;
			this.value = value;
			return this;
		},
	};
}

function harness() {
	const controls = [];
	const timers = [];
	const context = vm.createContext({
		window: { setTimeout: (callback) => timers.push(callback) },
		document: {},
		china_finance: {},
		__: (text) => text,
		frappe: {
			query_reports: {},
			utils: {
				escape_html: (value) => String(value),
				icon: () => "",
			},
			ui: {
				form: {
					make_control({ df }) {
						const $input = inputHarness();
						const control = {
							df,
							$input,
							input: {},
							awesomplete: {},
							toggle_label() {},
							toggle_description() {},
							set_input_value(value) {
								$input.val(value);
							},
							set_focus() {
								this.focused = true;
							},
							get_value() {
								return $input.val();
							},
							set_value() {
								this.setValueCalls = (this.setValueCalls || 0) + 1;
							},
							on_input() {
								this.inputQueries = (this.inputQueries || 0) + 1;
							},
						};
						controls.push(control);
						return control;
					},
				},
			},
		},
	});
	context.window.window = context.window;
	vm.runInContext(source, context);
	return {
		context,
		controls,
		timers,
		accountEditor: vm.runInContext("create_inline_account_editor", context),
		summaryEditor: vm.runInContext("create_inline_summary_editor", context),
	};
}

function report() {
	return {
		get_filter_value: () => "测试公司",
		datatable: { cellmanager: { deactivateEditing() {} } },
	};
}

test("account editor focuses immediately without validating the existing account", () => {
	const h = harness();
	const editor = h.accountEditor(
		report(),
		"1001 - 库存现金 - 测试公司",
		{},
		{
			editable_account: true,
			edit_voucher_key: "Journal Entry:JV-1",
			edit_source_doctype: "Journal Entry",
			edit_source_name: "JV-1",
			edit_key: "je:row-1",
		}
	);
	editor.initValue("1001 - 库存现金 - 测试公司");
	const control = h.controls[0];
	assert.equal(control.focused, true);
	assert.equal(control.$input.value, "1001 - 库存现金 - 测试公司");
	assert.equal(control.setValueCalls, undefined);
	assert.equal(control.inputQueries, 1);
	control.df.change();
	assert.equal(h.timers.length, 1, "selecting a new account must finish cell editing");
});

test("summary editor stays active while typing and keeps space inside the input", () => {
	const h = harness();
	const editor = h.summaryEditor(
		report(),
		"原摘要",
		{},
		{
			editable_summary: true,
			edit_voucher_key: "Journal Entry:JV-1",
			summary_edit_key: "je-summary:row-1",
		}
	);
	editor.initValue("原摘要");
	const control = h.controls[0];
	assert.equal(control.focused, true);
	assert.equal(control.df.change, undefined, "typing must not deactivate the DataTable editor");
	assert.equal(
		typeof control.change,
		"function",
		"idle input must not rewrite the temporary value"
	);

	let propagationStopped = false;
	let defaultPrevented = false;
	control.$input.handlers["keydown.china_inline_voucher_editor"]({
		originalEvent: { key: " ", code: "Space", keyCode: 32 },
		stopPropagation() {
			propagationStopped = true;
		},
		preventDefault() {
			defaultPrevented = true;
		},
	});
	assert.equal(propagationStopped, true);
	assert.equal(defaultPrevented, false, "space must still be inserted into the input");
});
