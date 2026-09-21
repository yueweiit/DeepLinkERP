// Run with: node --test china_finance/tests/test_company_context.js
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { test } = require("node:test");

const root = path.resolve(__dirname, "..");
const read = (file) => fs.readFileSync(path.join(root, file), "utf8");
const sidebar = JSON.parse(read("workspace_sidebar/china_finance.json"));
const tick = () => new Promise((resolve) => setImmediate(resolve));

function harness() {
	let route = ["desktop"];
	const events = {}, store = new Map(), dialogs = [], navigations = [], messages = [];
	const context = vm.createContext({
		URL, Promise, setTimeout: (fn) => setImmediate(fn),
		__: (text, values = []) => text.replace(/\{(\d+)\}/g, (_, i) => values[i]),
		document: { addEventListener: (event, fn) => { events[event] = fn; } },
		sessionStorage: { getItem: (key) => store.get(key), setItem: (key, value) => store.set(key, value) },
		$: () => ({ on: (event, fn) => { events[event] = fn; } }),
		china_finance: { company_context: {} },
		frappe: {
			provide() {}, session: { user: "test@example.com" },
			boot: { workspace_sidebar_item: { "china finance": sidebar } },
			defaults: { get_user_default: () => "默认公司" },
			get_route: () => route,
			router: { slug: (name) => name.toLowerCase().replaceAll(" ", "-"), on: (event, fn) => { events[event] = fn; } },
			after_ajax: (fn) => fn(),
			workspace: { is_read_only: true, page: { set_secondary_action: (label, fn) => { events.switch = fn; events.label = label; } } },
			model: { with_doctype: async () => {} },
			meta: { get_docfield: (dt) => dt !== "China Financial Statement Template" },
			db: { get_value: async (_dt, name) => ({ message: { name, is_group: 0 } }) },
			msgprint: (message) => messages.push(message),
			ui: { Dialog: class {
				constructor(options) { this.options = options; this.value = options.fields[0].default; dialogs.push(this); }
				set_primary_action(_label, fn) { this.submit = fn; }
				get_values() { return { company: this.value }; }
				get_primary_btn() { return { prop: (_key, value) => { this.disabled = value; } }; }
				show() { this.display = true; }
				hide() { this.display = false; this.onhide(); }
			} },
		},
	});
	context.window = context;
	context.location = { origin: "https://erp.example.com" };
	const frappe = context.frappe;
	frappe.set_route = async (pathname) => {
		navigations.push({ pathname, filters: { ...frappe.route_options } });
		route = pathname === "/desk/china-finance" ? ["Workspaces", "China Finance"] : [pathname];
		events.change?.();
	};
	vm.runInContext(read("public/js/company_context.js"), context);
	events.app_ready();
	return {
		context, frappe, events, dialogs, navigations, messages, store,
		company: context.china_finance.company_context,
		async select(value) {
			const done = this.company.select_company();
			dialogs.at(-1).value = value;
			await dialogs.at(-1).submit();
			return done;
		},
		async visit(value) { route = value; events.change(); await tick(); },
		click(href, { inSidebar = true, target = "", ...flags } = {}) {
			const link = { href, target, hasAttribute: () => false, closest: () => inSidebar };
			const event = { button: 0, target: { closest: () => link }, preventDefault() { this.prevented = true; }, stopImmediatePropagation() {}, ...flags };
			return { event, done: events.click(event) };
		},
	};
}

test("workspace entrance selects company and opens the workspace exactly once", async () => {
	const h = harness();
	const { event, done } = h.click("/desk/china-finance");
	assert.ok(event.prevented);
	assert.equal(h.navigations.length, 0);
	assert.equal(h.dialogs.length, 1);
	h.dialogs[0].value = "悦为智能（东莞）有限公司";
	await h.dialogs[0].submit();
	await done;
	await tick();
	assert.equal(h.navigations[0].pathname, "/desk/china-finance");
	assert.equal(h.dialogs.length, 1, "route change must not open another dialog");
	assert.equal(h.company.get_company(), "悦为智能（东莞）有限公司");
	assert.equal(h.frappe.defaults.get_user_default("Company"), "默认公司");
	assert.ok(h.events.label.includes("悦为智能"));
});

test("cancel keeps the previous company and does not navigate", async () => {
	const h = harness();
	await h.select("公司甲");
	const { done } = h.click("/desk/china-finance");
	h.dialogs.at(-1).hide();
	await done;
	assert.equal(h.company.get_company(), "公司甲");
	assert.equal(h.navigations.length, 0);
});

test("the workspace sidebar URL's native blank target still prompts in this tab", async () => {
	const h = harness();
	const { done, event } = h.click("/desk/china-finance", { target: "_blank" });
	assert.ok(event.prevented);
	assert.equal(h.dialogs.length, 1);
	h.dialogs[0].hide();
	await done;
});

test("app startup tolerates a route that is not initialized yet", async () => {
	const h = harness();
	await h.visit(null);
	assert.equal(h.dialogs.length, 0);
	await h.visit(["Workspaces", "China Finance"]);
	assert.equal(h.dialogs.length, 1);
	h.dialogs[0].hide();
});

test("permission failure or group company cannot replace the selection", async () => {
	const h = harness();
	await h.select("公司甲");
	const pending = h.company.select_company();
	const dialog = h.dialogs.at(-1);
	dialog.value = "无权访问公司";
	h.frappe.db.get_value = async () => { throw new Error("Forbidden"); };
	await dialog.submit();
	assert.equal(h.company.get_company(), "公司甲");
	assert.equal(dialog.disabled, false);
	assert.ok(dialog.display);
	h.frappe.db.get_value = async () => ({ message: { name: "集团", is_group: 1 } });
	await dialog.submit();
	assert.equal(h.company.get_company(), "公司甲");
	assert.equal(h.messages.length, 2);
	dialog.hide();
	assert.equal(await pending, null);
});

test("closing a dialog during validation ignores its late response", async () => {
	const h = harness();
	await h.select("公司甲");
	let resolve;
	h.frappe.db.get_value = () => new Promise((done) => { resolve = done; });
	const pending = h.company.select_company();
	const dialog = h.dialogs.at(-1);
	dialog.value = "公司乙";
	const submitted = dialog.submit();
	dialog.hide();
	resolve({ message: { name: "公司乙" } });
	await submitted;
	assert.equal(await pending, null);
	assert.equal(h.company.get_company(), "公司甲");
});

test("switching company replaces old report/list/page filters before navigation", async () => {
	const h = harness();
	await h.select("公司甲");
	await h.click("/desk/journal-entry?company=old&docstatus=0").done;
	assert.deepEqual(Array.from(h.navigations.at(-1).filters.company), ["=", "公司甲"]);
	assert.equal(h.navigations.at(-1).filters.docstatus, 0);
	await h.select("公司乙 & 公司丙");
	for (const href of ["/desk/query-report/China%20Voucher%20Ledger?company=old", "/desk/journal-entry/view/list", "/desk/china-statement-mapping", "/desk/china-banking"]) {
		await h.click(href).done;
		const company = h.navigations.at(-1).filters.company;
		assert.equal(Array.isArray(company) ? company[1] : company, "公司乙 & 公司丙");
		assert.equal(h.navigations.at(-1).filters.sidebar, undefined);
		assert.ok(!h.navigations.at(-1).pathname.includes("?"));
	}
	assert.equal(h.dialogs.length, 2, "opening 查凭证 must not prompt again");
});

test("existing documents, foreign sites and other modules are not intercepted", async () => {
	const h = harness();
	await h.select("公司甲");
	for (const href of ["/desk/journal-entry/ACC-JV-0001", "https://other.example/desk/journal-entry", "/desk/customer"]) {
		assert.equal(await h.company.route_for_company(href), null);
		assert.equal(h.click(href).event.prevented, undefined);
	}
	assert.equal(h.click("/desk/journal-entry", { inSidebar: false }).event.prevented, undefined);
	assert.equal(await h.company.route_for_company("/desk/china-financial-statement-template"), null);
	assert.equal(h.click("/desk/china-finance", { ctrlKey: true }).event.prevented, undefined);
});

test("direct workspace entry prompts, and re-entering uses the previous choice", async () => {
	const h = harness();
	await h.visit(["Workspaces", "China Finance"]);
	assert.equal(h.dialogs.length, 1);
	h.dialogs[0].value = "公司甲";
	await h.dialogs[0].submit();
	await h.visit(["List", "Journal Entry"]);
	await h.visit(["Workspaces", "China Finance"]);
	assert.equal(h.dialogs.length, 2);
	assert.equal(h.dialogs.at(-1).value, "公司甲");
	h.dialogs.at(-1).hide();
});

test("cached banking page restores chosen company and reloads its iframe", () => {
	const h = harness();
	const storage = new Map();
	h.context.localStorage = { getItem: (k) => storage.get(k), setItem: (k, v) => storage.set(k, v) };
	h.frappe.pages = { "china-banking": {} };
	vm.runInContext(read("china_finance/page/china_banking/china_banking.js"), h.context);
	const page = vm.runInContext("Object.create(ChinaBankingPage.prototype)", h.context);
	let reloads = 0;
	page.$iframe = { attr(_key, value) { if (value) reloads++; return "/banking?embedded=1"; } };
	h.frappe.route_options = { company: "公司甲" };
	page.sync_company();
	page.sync_company();
	assert.equal(reloads, 1);
	storage.set("bank-rec-selected-company", JSON.stringify("公司乙"));
	page.sync_company();
	assert.equal(reloads, 2);
	assert.equal(JSON.parse(storage.get("bank-rec-selected-company")), "公司甲");
});

test("mapping console discards the previous company's slower response", async () => {
	const h = harness();
	h.frappe.pages = { "china-statement-mapping": {} };
	const requests = [];
	h.frappe.xcall = (_method, args) => new Promise((resolve) => requests.push({ args, resolve }));
	vm.runInContext(read("china_finance/page/china_statement_mapping/china_statement_mapping.js"), h.context);
	const page = vm.runInContext("Object.create(ChinaStatementMapping.prototype)", h.context);
	let company = "公司甲", renders = 0;
	Object.assign(page, {
		company: { get_value: () => company }, statement_type: { get_value: () => "Balance Sheet" },
		accounting_standard: { get_value: () => "跟随公司设置" },
		selected_accounts: new Set(), selected_rows: new Set(), collapsed_rows: new Set(),
		collapsed_accounts: new Set(), expanded_aggregates: new Set(),
		$rows: { html() {} }, $accounts: { empty() {} }, render_all: () => renders++,
	});
	const first = page.refresh();
	company = "公司乙";
	const second = page.refresh();
	requests[1].resolve({ company: "公司乙" });
	await second;
	requests[0].resolve({ company: "公司甲" });
	await first;
	assert.equal(page.data.company, "公司乙");
	assert.equal(renders, 1);
});
