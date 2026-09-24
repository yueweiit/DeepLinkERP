// Run with: node --test china_finance/tests/test_closing_month.js
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { test } = require("node:test");
const vm = require("node:vm");

function harness(doc) {
	let handlers;
	const context = vm.createContext({
		frappe: { ui: { form: { on: (_doctype, events) => { handlers = events; } } } },
		__: (text) => text,
	});
	const source = path.resolve(__dirname, "../china_finance/doctype/china_closing_run/china_closing_run.js");
	vm.runInContext(fs.readFileSync(source, "utf8"), context);
	const changes = [];
	const frm = {
		doc: { docstatus: 0, ...doc },
		fields_dict: {},
		is_new: () => false,
		get_field: () => null,
		refresh_field() {},
		set_value(field, value) {
			changes.push([field, value]);
			this.doc[field] = value;
		},
	};
	return { handlers, frm, changes };
}

test("refresh preserves year-end dates with an empty or leftover closing month", async () => {
	for (const closing_month of [null, "2026-08"]) {
		const { handlers, frm, changes } = harness({
			closing_type: "Year End", closing_month,
			from_date: "2026-01-01", to_date: "2026-12-31",
		});
		await handlers.refresh(frm);
		assert.equal(frm.doc.from_date, "2026-01-01");
		assert.equal(frm.doc.to_date, "2026-12-31");
		assert.deepEqual(changes, []);
	}
});

test("selecting a month derives the whole calendar month including leap years", () => {
	for (const [closing_month, to_date] of [["2026-02", "2026-02-28"], ["2024-02", "2024-02-29"]]) {
		const { handlers, frm } = harness({ closing_type: "Monthly", closing_month });
		handlers.closing_month(frm);
		assert.equal(frm.doc.from_date, `${closing_month}-01`);
		assert.equal(frm.doc.to_date, to_date);
	}
});

test("clearing a monthly selection clears its derived dates", () => {
	const { handlers, frm } = harness({
		closing_type: "Monthly", closing_month: "",
		from_date: "2026-08-01", to_date: "2026-08-31",
	});
	handlers.closing_month(frm);
	assert.equal(frm.doc.from_date, null);
	assert.equal(frm.doc.to_date, null);
});

test("refresh infers the month on legacy monthly records without changing their dates", async () => {
	const { handlers, frm, changes } = harness({
		closing_type: "Monthly", closing_month: null,
		from_date: "2026-08-01", to_date: "2026-08-31",
	});
	await handlers.refresh(frm);
	assert.equal(frm.doc.closing_month, "2026-08");
	assert.deepEqual(changes, []);
});
