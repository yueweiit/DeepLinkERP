const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const modulePath = path.join(__dirname, "../deeplinkerp_branding/public/js/purchase_order_list.js");
const grid = fs.existsSync(modulePath) ? require(modulePath) : {};
function production(name) {
	assert.equal(typeof grid[name], "function", `${name} must be available`);
	return grid[name];
}
const fields = ["transaction_date", "supplier", "supplier_name", "status", "schedule_date", "company", "currency", "grand_total", "advance_paid", "party_account_currency", "advance_payment_status", "per_received", "per_billed", "project"];
const permitted = new Set(["name", "owner", "docstatus", ...fields]);

test("all query consumers use the same native, quick, and OR filters without mutating saved filters", () => {
	const native = { doctype: "Purchase Order", fields: ["name"], filters: [["Purchase Order", "project", "=", "P1"]], or_filters: [], order_by: "transaction_date desc", start: 100, page_length: 100 };
	const snapshot = JSON.stringify(native);
	const args = production("buildQuery")(native, { search: "供应商", from_date: "2026-01-01", to_date: "2026-01-31", company: "Company A", status: "Draft", advance_payment_status: "Initiated" }, permitted);
	const requests = production("buildRequests")(args, ["name", "advance_paid", "grand_total"], permitted);
	for (const request of [requests.count, requests.summary, requests.export]) {
		assert.deepEqual(request.filters, args.filters);
		assert.deepEqual(request.or_filters, args.or_filters);
	}
	assert.ok(args.filters.some((f) => f[1] === "transaction_date" && f[2] === ">="));
	assert.ok(args.or_filters.some((f) => f[1] === "name" && f[3] === "%供应商%"));
	assert.ok(args.or_filters.some((f) => f[1] === "supplier_name"));
	assert.equal(JSON.stringify(native), snapshot);
});

test("existing OR filters remain consistent and conflicting quick search is refused", () => {
	const native = { filters: [], or_filters: [["Purchase Order", "owner", "=", "buyer@example.com"]], fields: ["name"] };
	const query = production("buildQuery")(native, {}, permitted);
	const requests = production("buildRequests")(query, ["name"], permitted);
	for (const args of [requests.count, requests.summary, requests.export]) assert.deepEqual(args.or_filters, native.or_filters);
	assert.throws(() => production("buildQuery")(native, { search: "different buyer" }, permitted), /OR filters/);
});

test("design-specific header labels and widths keep the desktop table within 1700px", () => {
	const { list, env } = bareList();
	production("mount")(list, env);
	const header = list.get_header_html();
	for (const label of ["订单日期", "采购订单号", "供应商名称", "订单状态", "订单金额", "已预付", "创建人"]) assert.ok(header.includes(label));
	assert.ok(grid.COLUMNS.reduce((width, col) => width + col.width, 76) <= 1700);
});

test("export includes visible columns in order and account currency, without any page limit", () => {
	const requests = production("buildRequests")({ doctype: "Purchase Order", filters: [], or_filters: [], start: 500, page_length: 500, order_by: "name asc" }, ["supplier_name", "advance_paid", "name"], permitted);
	assert.deepEqual(requests.export.fields, ["supplier_name", "advance_paid", "party_account_currency", "name"]);
	assert.equal(requests.export.start, 0);
	assert.equal(requests.export.file_format_type, "Excel");
	assert.equal("page_length" in requests.export, false);
	assert.equal("limit_page_length" in requests.export, false);
	assert.equal(requests.count.limit, 0);
	assert.equal(requests.summary.group_by, "currency");
	assert.equal(requests.summary.aggregate_function, "sum");
	assert.equal(requests.summary.aggregate_on_field, "grand_total");
	assert.equal(requests.summary.limit_page_length, 0);
});

test("child-table filters retain native order grouping for both export and the summary read", () => {
	const query = { fields: ["name"], filters: [["Purchase Order Item", "item_code", "=", "ITEM-A"]], or_filters: [], group_by: "`tabPurchase Order`.`name`", order_by: "name asc", start: 100, page_length: 100 };
	const requests = production("buildRequests")(query, ["name", "grand_total"], permitted);
	assert.equal(requests.export.group_by, query.group_by);
	assert.equal(requests.summary.group_by, query.group_by);
	assert.deepEqual(requests.summary.filters, query.filters);
	assert.deepEqual(requests.summary.or_filters, query.or_filters);
	assert.deepEqual(requests.summary.fields, ["name", "currency", "grand_total", "party_account_currency", "advance_paid"]);
	assert.equal(requests.summary.limit_page_length, 0);
	assert.equal("aggregate_function" in requests.summary, false);
});

test("child-filter currency totals count each order once including zero values", () => {
	const totals = production("currencyTotals")([
		{ name: "PO-1", currency: "USD", grand_total: 120 },
		{ name: "PO-1", currency: "USD", grand_total: 120 },
		{ name: "PO-2", currency: "USD", grand_total: 0 },
		{ name: "PO-3", currency: "MXN", grand_total: "500.5" },
		{ name: "PO-4", currency: "USD", grand_total: 80 },
	]);
	assert.deepEqual(totals, [{ currency: "USD", _aggregate_column: 200 }, { currency: "MXN", _aggregate_column: 500.5 }]);
});

test("the summary uses distinct orders returned by a child-filter grouped query", async () => {
	const { list, env } = bareList();
	const requests = [];
	env.frappe.call = async (request) => {
		requests.push(request);
		return { message: request.method.endsWith("get_count") ? 2 : [{ name: "PO-1", currency: "USD", grand_total: 150 }, { name: "PO-1", currency: "USD", grand_total: 150 }, { name: "PO-2", currency: "USD", grand_total: 50 }] };
	};
	list.group_by = "`tabPurchase Order`.`name`";
	list.filters = [["Purchase Order Item", "item_code", "=", "ITEM-A"]];
	production("mount")(list, env);
	await list.render_count();
	assert.deepEqual(list.dlpPurchaseOrderGrid.summary, [{ currency: "USD", _aggregate_column: 200 }]);
	assert.deepEqual(requests[0].args.filters, requests[1].args.filters);
});

test("missing and forbidden metadata fields are omitted from query and export", () => {
	const meta = { fields: fields.map((fieldname) => ({ fieldname, permlevel: fieldname === "advance_paid" ? 1 : 0 })) };
	meta.fields.find((df) => df.fieldname === "project").is_virtual = 1;
	const allowed = production("allowedFields")(meta, (level) => level === 0, ["name", "owner", "docstatus"]);
	assert.equal(allowed.has("advance_paid"), false);
	assert.equal(allowed.has("project"), false);
	assert.equal(allowed.has("unknown_field"), false);
	const query = production("buildQuery")({ doctype: "Purchase Order", fields: ["name", "advance_paid", "unknown_field"] }, { advance_payment_status: "Initiated" }, allowed);
	assert.deepEqual(query.fields, ["name"]);
	assert.deepEqual(production("buildRequests")(query, ["name", "advance_paid"], allowed).export.fields, ["name"]);
	allowed.delete("grand_total");
	assert.equal(production("buildRequests")(query, ["name"], allowed).summary, null);
});

test("preferences are isolated by site and user and sanitize unknown or duplicate columns", () => {
	const key = production("preferenceKey");
	assert.notEqual(key("site-a", "buyer-a"), key("site-b", "buyer-a"));
	assert.notEqual(key("site-a", "buyer-a"), key("site-a", "buyer-b"));
	assert.match(key("site-a", "buyer-a"), /Purchase%20Order/);
	const prefs = production("normalizePreferences")({ density: "untrusted", columns: ["supplier_name", "name", "name", "secret", "advance_paid"] }, permitted);
	assert.equal(prefs.density, "tight");
	assert.deepEqual(prefs.columns, ["supplier_name", "name", "advance_paid"]);
	assert.deepEqual(production("normalizePreferences")({ columns: [] }, permitted).columns, ["name"]);
});

test("cells distinguish zero and missing values, escape labels, and render percentages numerically", () => {
	const cell = production("renderValue");
	for (const field of ["grand_total", "advance_paid"]) {
		assert.ok(grid.COLUMNS.find((column) => column.fieldname === field).width >= 140,
			`${field} must fit two-decimal amounts including their currency suffix`);
	}
	const configured = { frappe: { boot: { sysdefaults: { currency_precision: "3", float_precision: "8" } } } };
	assert.equal(production("formatNumber")(configured, 1.23456, "grand_total"), "1.235");
	assert.equal(production("formatNumber")(configured, 0, "advance_paid"), "0.000");
	assert.equal(production("formatNumber")({}, 1.23456, "grand_total"), "1.23");
	assert.equal(cell("grand_total", { grand_total: 0, currency: "USD" }), "0.00 USD");
	for (const [value, expected] of [[1.23456789, "1.23"], [-1.239, "-1.24"], [9.995, "10.00"]]) {
		assert.equal(cell("grand_total", { grand_total: value, currency: "USD" }), `${expected} USD`);
	}
	assert.equal(cell("grand_total", {}), "—");
	assert.equal(cell("per_received", { per_received: 0 }), "0%");
	assert.equal(cell("per_billed", { per_billed: 82.5 }), "82.5%");
	assert.equal(cell("supplier_name", { supplier_name: '<img src=x onerror="x">' }), "&lt;img src=x onerror=&quot;x&quot;&gt;");
	assert.equal(cell("advance_paid", { advance_paid: 100, currency: "MXN", party_account_currency: "USD" }), "100.00 USD");
	assert.equal(cell("advance_paid", { advance_paid: 0, currency: "MXN" }), "0.00");
	const padded = { number: (value) => value.toFixed(2) };
	for (const [field, doc, expected] of [
		["grand_total", { grand_total: 0, currency: "CNY" }, "0.00 CNY"],
		["advance_paid", { advance_paid: "0.000", currency: "MXN", party_account_currency: "USD" }, "0.00 USD"],
		["per_received", { per_received: 0 }, "0%"],
		["per_billed", { per_billed: "0.00" }, "0%"],
	]) assert.equal(cell(field, doc, padded), expected);
	assert.equal(cell("grand_total", { grand_total: 1, currency: "CNY" }, padded), "1.00 CNY");
});

function bareList() {
	let nativeLoads = 0;
	let nativeRefreshes = 0;
	const list = {
		doctype: "Purchase Order", view_name: "List", view: "List", meta: { fields: fields.map((fieldname) => ({ fieldname, permlevel: 0 })) }, fields: [["name", "Purchase Order"]], data: [], start: 0, page_length: 20,
		get_args() { return { doctype: this.doctype, filters: this.filters || [], or_filters: this.or_filters || [], fields: this.fields.map((f) => f[0]), start: this.start, page_length: this.page_length, order_by: "name asc", group_by: this.group_by || null }; },
		get_call_args() { return { method: "frappe.desk.reportview.get", args: this.get_args() }; },
		no_change(args) { const serialized = JSON.stringify(args); if (this.last_args === serialized) return true; this.last_args = serialized; return false; },
		prepare_data(response) { this.data = this.start ? this.data.concat(response.message) : response.message; },
		reset_defaults() { this.page_length += this.start; this.start = 0; },
		refresh() { nativeRefreshes++; return Promise.resolve(); },
		get_indicator_html(doc) { return `native:${doc.docstatus}`; },
		get_form_link(doc) { return `/desk/purchase-order/${encodeURIComponent(doc.name)}`; },
		get_header_html() { return "native header"; }, get_list_row_html() { return "native row"; }, render_list() {}, render_header() {}, render_count() {}, toggle_result_area() {}, on_filter_change() {},
		settings: { onload() { nativeLoads++; }, refresh() {}, get_indicator() { return ["Draft", "red"]; }, bulk_handler: () => "bulk" },
	};
	const env = { frappe: { listview_settings: { "Purchase Order": list.settings }, get_route: () => ["List", "Purchase Order", "List"], model: { std_fields_list: ["name", "owner", "docstatus"] }, perm: { has_perm: () => true }, session: { user: "buyer-a" }, boot: { sitename: "site-a" }, router: { on() {} } } };
	return { list, env, nativeLoads: () => nativeLoads, nativeRefreshes: () => nativeRefreshes };
}

function dispatch(list) {
	const call = list.get_call_args();
	assert.equal(list.no_change(call), false, "native BaseList gates dispatch with no_change");
	return call;
}

test("installation chains native settings and only mounts a native Purchase Order list once", () => {
	const { list, env, nativeLoads } = bareList();
	const indicator = list.settings.get_indicator;
	const bulk = list.settings.bulk_handler;
	production("install")(env);
	env.frappe.listview_settings["Purchase Order"].onload(list);
	const first = list.dlpPurchaseOrderGrid;
	env.frappe.listview_settings["Purchase Order"].onload(list);
	assert.equal(list.dlpPurchaseOrderGrid, first);
	assert.equal(nativeLoads(), 2);
	assert.equal(list.settings.get_indicator, indicator);
	assert.equal(list.settings.bulk_handler, bulk);
	assert.equal(list.page_length, 100);
	for (const other of [{ ...list, dlpPurchaseOrderGrid: undefined, doctype: "Sales Order" }, { ...list, dlpPurchaseOrderGrid: undefined, view_name: "Report" }, { ...list, dlpPurchaseOrderGrid: undefined, view_name: "Calendar" }]) {
		assert.equal(production("mount")(other, env), null);
	}
});

test("page responses replace rows, retain offset after native reset, and reset to zero on filter changes", () => {
	const { list, env } = bareList();
	const controller = production("mount")(list, env);
	list.data = [{ name: "PO-1" }];
	controller.setPage(1);
	const request = dispatch(list);
	const response = { message: [{ name: "PO-101" }] };
	request.callback(response);
	list.prepare_data(response);
	list.reset_defaults();
	assert.deepEqual(list.data, [{ name: "PO-101" }]);
	assert.equal(list.start, 100);
	assert.equal(list.page_length, 100);
	list.filters = [["Purchase Order", "company", "=", "Company B"]];
	assert.equal(list.get_args().start, 0);
	assert.equal(controller.page, 0);
});

test("a stale native response cannot overwrite a newer query page", () => {
	const { list, env } = bareList();
	const controller = production("mount")(list, env);
	const oldRequest = dispatch(list);
	controller.quick.search = "new";
	const newRequest = dispatch(list);
	const newer = { message: [{ name: "new" }] };
	newRequest.callback(newer);
	list.prepare_data(newer);
	const older = { message: [{ name: "old" }] };
	oldRequest.callback(older);
	list.prepare_data(older);
	assert.deepEqual(list.data, [{ name: "new" }]);
});

test("a repeated native no-change check does not invalidate the pending response", () => {
	const { list, env } = bareList();
	production("mount")(list, env);
	const pending = dispatch(list);
	// BaseList obtains args before its no_change guard, even when it will make no request.
	assert.equal(list.no_change(list.get_call_args()), true);
	const response = { message: [{ name: "PO-1" }] };
	pending.callback(response);
	list.prepare_data(response);
	assert.deepEqual(list.data, [{ name: "PO-1" }]);
});

test("changing page before its throttled request rejects an earlier page response", () => {
	const { list, env } = bareList();
	const controller = production("mount")(list, env);
	const pending = dispatch(list);
	controller.setPage(1);
	const response = { message: [{ name: "PO-1" }] };
	pending.callback(response);
	list.prepare_data(response);
	assert.deepEqual(list.data, []);
});

test("two actually dispatched requests with identical filters reject the older response", () => {
	const { list, env } = bareList();
	production("mount")(list, env);
	const oldRequest = dispatch(list);
	list.last_args = null; // Native forced refresh dispatches even though the query is identical.
	const newRequest = dispatch(list);
	assert.deepEqual(oldRequest.args, newRequest.args);
	const newer = { message: [{ name: "current" }] };
	newRequest.callback(newer);
	list.prepare_data(newer);
	const older = { message: [{ name: "outdated" }] };
	oldRequest.callback(older);
	list.prepare_data(older);
	assert.deepEqual(list.data, [{ name: "current" }]);
});

function nativeDebounce(func, wait) {
	let timeout;
	const debounced = function (...args) { clearTimeout(timeout); timeout = setTimeout(() => { timeout = null; func.apply(this, args); }, wait); };
	debounced.cancel = () => { if (!timeout) return false; clearTimeout(timeout); timeout = null; return true; };
	return debounced;
}

function realtimeList() {
	const fixture = bareList();
	const { list, env } = fixture;
	let unsubscribes = 0;
	list.pending_document_refreshes = [];
	list.filter_area = { is_being_edited: () => false };
	list.avoid_realtime_update = function () { return this.filter_area.is_being_edited() || this.disable_list_update; };
	list.disable_realtime_updates = () => { unsubscribes++; };
	// Native incremental updates bypass prepare_data and append matching names into the page.
	list.process_document_refreshes = function () { this.data.push(...this.pending_document_refreshes.map(({ name }) => ({ name }))); this.pending_document_refreshes = []; };
	env.cur_list = list;
	env.frappe.utils = { debounce: nativeDebounce };
	list.debounced_refresh = nativeDebounce(list.process_document_refreshes.bind(list), 2000);
	return { ...fixture, unsubscribes: () => unsubscribes };
}

function useNativeRefreshFlow(list, env) {
	list.refresh = async function () {
		const call = this.get_call_args();
		if (this.no_change(call)) return;
		const response = await env.frappe.call(call);
		call.callback(response);
		this.prepare_data(response);
		this.reset_defaults();
		await this.render_count();
	};
}

test("realtime updates reload the bounded second page and its filtered count and totals", async () => {
	const { list, env } = realtimeList();
	const calls = [];
	const page = Array.from({ length: 20 }, (_, index) => ({ name: `PO-${21 + index}` }));
	env.frappe.call = async (call) => {
		calls.push(call);
		if (call.method.endsWith("get_count")) return { message: 61 };
		if (call.method.endsWith("get_list")) return { message: [{ currency: "USD", _aggregate_column: 620 }] };
		return { message: page };
	};
	useNativeRefreshFlow(list, env);
	const controller = production("mount")(list, env);
	controller.quick.company = "A";
	list.get_args(); // Establish the query before navigating to page 2.
	controller.pageSize = 20;
	controller.setPage(1);
	list.data = page.map((row) => ({ ...row }));
	list.pending_document_refreshes = [{ name: "PO-NEW" }];
	await list.process_document_refreshes();
	assert.deepEqual(list.data.map((row) => row.name), page.map((row) => row.name));
	assert.equal(list.data.length, 20);
	assert.equal(controller.page, 1);
	assert.equal(calls[0].args.start, 20);
	assert.equal(calls[0].args.page_length, 20);
	assert.equal(calls.length, 3);
	for (const call of calls) assert.deepEqual(call.args.filters, [["Purchase Order", "company", "=", "A"]]);
	assert.equal(controller.total, 61);
	assert.deepEqual(controller.summary, [{ currency: "USD", _aggregate_column: 620 }]);
	assert.deepEqual(list.pending_document_refreshes, []);
});

test("a realtime refresh after a filter change cannot accept the old query response", async () => {
	const { list, env } = realtimeList();
	const reads = [];
	env.frappe.call = (call) => call.method === "frappe.desk.reportview.get" ? new Promise((resolve) => reads.push({ call, resolve })) : Promise.resolve({ message: call.method.endsWith("get_count") ? 1 : [] });
	useNativeRefreshFlow(list, env);
	const controller = production("mount")(list, env);
	const older = controller.refresh();
	controller.quick.company = "B";
	list.pending_document_refreshes = [{ name: "changed" }];
	const newer = list.process_document_refreshes();
	assert.equal(reads.length, 2);
	reads[1].resolve({ message: [{ name: "company B" }] });
	await newer;
	reads[0].resolve({ message: [{ name: "old query" }] });
	await older;
	assert.deepEqual(list.data, [{ name: "company B" }]);
});

test("pending realtime updates honor selection, editing and bulk guards", () => {
	for (const guard of ["selection", "editing", "bulk"]) {
		const { list, env, nativeRefreshes } = realtimeList();
		production("mount")(list, env);
		list.data = [{ name: "existing" }];
		list.pending_document_refreshes = [{ name: "new" }];
		if (guard === "selection") list.$checks = [{ name: "existing" }];
		if (guard === "editing") list.filter_area.is_being_edited = () => true;
		if (guard === "bulk") list.disable_list_update = true;
		list.process_document_refreshes();
		assert.deepEqual(list.data, [{ name: "existing" }], guard);
		assert.equal(nativeRefreshes(), 0, guard);
		assert.equal(list.pending_document_refreshes.length, 1, guard);
	}
});

test("pending realtime updates off the native PO route are cleared and unsubscribe", () => {
	for (const route of [["Form", "Purchase Order", "PO-1"], ["List", "Purchase Order", "Report"], ["List", "Sales Order", "List"]]) {
		const { list, env, nativeRefreshes, unsubscribes } = realtimeList();
		production("mount")(list, env);
		env.frappe.get_route = () => route;
		list.pending_document_refreshes = [{ name: "new" }];
		list.process_document_refreshes();
		assert.deepEqual(list.data, []);
		assert.deepEqual(list.pending_document_refreshes, []);
		assert.equal(nativeRefreshes(), 0);
		assert.equal(unsubscribes(), 1);
	}
});

test("the rebound realtime debounce cancels old pending work and keeps native 2s/15s delays", (context) => {
	context.mock.timers.enable({ apis: ["setTimeout"] });
	for (const delay of [2000, 15000]) {
		const { list, env, nativeRefreshes } = realtimeList();
		list.is_large_table = delay === 15000;
		list.pending_document_refreshes = [{ name: "new" }];
		list.debounced_refresh(); // Constructor's bound native function must not fire after mounting.
		production("mount")(list, env);
		const rebound = list.debounced_refresh;
		production("mount")(list, env);
		assert.equal(list.debounced_refresh, rebound);
		list.debounced_refresh();
		context.mock.timers.tick(delay - 1);
		assert.equal(nativeRefreshes(), 0);
		assert.deepEqual(list.data, []);
		context.mock.timers.tick(1);
		assert.equal(nativeRefreshes(), 1);
		assert.deepEqual(list.data, []);
	}
});

test("old totals cannot replace the totals of the current filtered query", async () => {
	const { list, env } = bareList();
	const pending = [];
	env.frappe.call = (args) => new Promise((resolve) => pending.push({ args, resolve }));
	production("mount")(list, env);
	const before = list.render_count();
	list.dlpPurchaseOrderGrid.quick.company = "Company B";
	const after = list.render_count();
	pending[2].resolve({ message: 3 });
	pending[3].resolve({ message: [{ currency: "USD", _aggregate_column: 400 }] });
	await after;
	pending[0].resolve({ message: 30 });
	pending[1].resolve({ message: [{ currency: "USD", _aggregate_column: 9000 }] });
	await before;
	assert.equal(list.total_count, 3);
	assert.deepEqual(list.dlpPurchaseOrderGrid.summary, [{ currency: "USD", _aggregate_column: 400 }]);
	assert.deepEqual(pending[2].args.args.filters, pending[3].args.args.filters);
});

test("the cached list activates on return and removes its body class on forms or other views", () => {
	const { list, env } = bareList();
	const classes = new Set();
	const listeners = [];
	let route = ["List", "Purchase Order", "List"];
	env.document = { body: { classList: { toggle(name, enabled) { if (enabled) classes.add(name); else classes.delete(name); } } } };
	env.frappe.get_route = () => route;
	env.frappe.router.on = (event, callback) => listeners.push(callback);
	env.cur_list = list;
	production("install")(env);
	production("install")(env);
	env.frappe.listview_settings["Purchase Order"].onload(list);
	const controller = list.dlpPurchaseOrderGrid;
	assert.ok(classes.has("dlp-purchase-order-grid-active"));
	for (const next of [["Form", "Purchase Order", "PO-1"], ["List", "Purchase Order", "Report"], ["List", "Sales Order", "List"]]) {
		route = next;
		listeners[0]();
		assert.equal(classes.has("dlp-purchase-order-grid-active"), false);
	}
	route = ["List", "Purchase Order", "List"];
	listeners[0]();
	assert.equal(classes.has("dlp-purchase-order-grid-active"), true);
	assert.equal(list.dlpPurchaseOrderGrid, controller);
	assert.equal(listeners.length, 1);
});

test("native OR filters that appear while quick search is active keep the query valid and show a notice", () => {
	const { list, env } = bareList();
	const notices = [];
	env.frappe.show_alert = (notice) => notices.push(notice);
	const controller = production("mount")(list, env);
	controller.quick.search = "buyer";
	list.or_filters = [["Purchase Order", "owner", "=", "other buyer"]];
	const args = list.get_args();
	assert.deepEqual(args.or_filters, list.or_filters);
	assert.equal(controller.quick.search, "");
	assert.equal(notices.length, 1);
});

test("rendered rows retain native selection hooks, native indicator, and escaped order and supplier links", () => {
	const { list, env } = bareList();
	env.__ = (label) => ({ "Partially Paid": "部分已付", "Supplier <A>": "must not translate business name" })[label] || label;
	env.frappe.boot.sysdefaults = { currency_precision: "2", float_precision: "8" };
	env.format_number = (value, _format, precision) => {
		assert.equal(precision, 2, "list display must override native global precision without changing data");
		return value.toFixed(precision);
	};
	production("mount")(list, env);
	const doc = { name: 'PO/"1', supplier: "SUP/1", supplier_name: "Supplier <A>", grand_total: 123.456789, currency: "MXN", advance_paid: 5.6789, party_account_currency: "CNY", advance_payment_status: "Partially Paid", docstatus: 2, _idx: 0 };
	const html = list.get_list_row_html(doc);
	assert.match(html, /list-row-container/);
	assert.match(html, /list-row-checkbox/);
	const rowClasses = html.match(/class="([^"]*\bdlp-po-grid-row\b[^"]*)"/)[1].split(/\s+/);
	assert.ok(rowClasses.includes("level"), "native drag selection delegates to .level.list-row");
	assert.ok(rowClasses.includes("list-row"));
	assert.match(html, /data-name="PO\/&quot;1"/);
	assert.match(html, /native:2/);
	assert.match(html, /purchase-order\/PO%2F%221/);
	assert.match(html, /supplier\/SUP%2F1/);
	assert.match(html, /Supplier &lt;A&gt;/);
	assert.match(html, />123\.46 MXN<\/div>/);
	assert.match(html, />5\.68 CNY<\/div>/);
	assert.equal(doc.grand_total, 123.456789, "display rounding must not alter source amounts or export values");
	assert.match(html, />部分已付<\/div>/);
	assert.equal(doc.advance_payment_status, "Partially Paid", "display translation must not alter the query/export field value");
});

function selectionList() {
	const { list, env } = bareList();
	const rows = new Map();
	let appended = 0;
	list.data = [{ name: "PO-1" }, { name: "PO-2" }];
	list.$result = {
		find(selector) {
			if (selector === ".list-row-container") return { remove() { rows.clear(); appended = 0; } };
			if (selector === ".list-row-checkbox:checked") return [...rows.values()].filter((row) => row.checked);
			const name = selector.match(/data-name='([^']+)'/)?.[1];
			return { prop(property, value) { const row = rows.get(name); if (row) row[property] = value; } };
		},
		append() { const doc = list.data[appended++]; rows.set(doc.name, { name: doc.name, checked: false }); },
	};
	// These dependencies follow ListView.set_rows_as_checked/on_row_checked's live DOM contract.
	list.on_row_checked = function () { this.$checks = this.$result.find(".list-row-checkbox:checked"); this.actionsVisible = this.$checks.length > 0; };
	list.set_rows_as_checked = function () {
		if (!this.$checks || !this.$checks.length) return;
		for (const check of this.$checks) this.$result.find(`.list-row-checkbox[data-name='${check.name}']`).prop("checked", true);
		this.on_row_checked();
	};
	production("mount")(list, env);
	return { list, env, rows };
}

test("native selection survives replacement rendering until the native restoration step", () => {
	const { list, rows } = selectionList();
	const oldSelection = [{ name: "PO-2", checked: true }];
	list.$checks = oldSelection;
	list.render_list();
	assert.equal(list.$checks, oldSelection, "render_list must leave the old checked elements for native restoration");
	assert.equal(rows.get("PO-2").checked, false);
	list.set_rows_as_checked();
	assert.equal(rows.get("PO-2").checked, true);
	assert.deepEqual(list.$checks.map((check) => check.name), ["PO-2"]);
	assert.equal(list.actionsVisible, true);
});

test("saving visible columns restores selected rows and resets empty selection actions", () => {
	const { list, rows } = selectionList();
	list.$checks = [{ name: "PO-2", checked: true }];
	const controller = list.dlpPurchaseOrderGrid;
	assert.equal(typeof controller.setColumns, "function");
	controller.setColumns(["name", "supplier_name"]);
	assert.deepEqual(controller.preferences.columns, ["name", "supplier_name"]);
	assert.equal(rows.get("PO-2").checked, true);
	assert.deepEqual(list.$checks.map((check) => check.name), ["PO-2"]);
	assert.equal(list.actionsVisible, true);
	list.$checks = [];
	controller.setColumns(["name"]);
	assert.equal(rows.get("PO-2").checked, false);
	assert.equal(list.actionsVisible, false);
});

test("clearing quick filters resets all controls and page with one adapter refresh", async () => {
	const { list, env, nativeRefreshes } = bareList();
	const controller = production("mount")(list, env);
	controller.quick = { search: "supplier", from_date: "2026-01-01", to_date: "2026-02-01", company: "A", status: "Draft", advance_payment_status: "Initiated" };
	controller.setPage(3);
	const values = { ...controller.quick };
	controller.controls = Object.fromEntries(Object.keys(values).map((field) => [field, { async set_value(value) { values[field] = value; if (!controller.resetting) await controller.refresh(); } }]));
	assert.equal(typeof controller.clearQuickFilters, "function");
	await controller.clearQuickFilters();
	assert.deepEqual(controller.quick, {});
	assert.ok(Object.values(values).every((value) => value === ""));
	assert.equal(controller.page, 0);
	assert.equal(controller.resetting, false);
	assert.equal(nativeRefreshes(), 1);
});

function savedFilterPage() {
	const groups = [];
	const collection = (matches) => ({
		length: matches.length,
		attr(name, value) { if (name === "data-label") matches.forEach((group) => { group.identity = value; }); return this; },
		find(selector) {
			assert.equal(selector, "button");
			return { contents() { return { first() { return matches[0] ? [matches[0].label] : []; } }; } };
		},
	});
	const toolbar = {
		find(selector) {
			const identity = selector.match(/data-label="([^"]+)"/)?.[1];
			return collection(groups.filter((group) => group.identity === identity));
		},
	};
	// Native Page stores encoded group labels; ListFilter later looks up the English key.
	const page = {
		inner_toolbar: toolbar,
		get_inner_group_button(label) { return toolbar.find(`.inner-group-button[data-label="${encodeURIComponent(label)}"]`); },
		get_or_add_inner_group_button(label) {
			let result = this.get_inner_group_button(label);
			if (!result.length) {
				groups.push({ identity: encodeURIComponent(label), label: { textContent: label }, dropdown: [] });
				result = this.get_inner_group_button(label);
			}
			return result;
		},
	};
	return { page, groups, nativeUpdate(label) {
		toolbar.find('.inner-group-button[data-label="Saved%20Filters"]').find("button").contents().first()[0].textContent = label;
	} };
}

test("localized native saved-filter group keeps its button and handlers when clear updates the label", async () => {
	const { list, env } = bareList();
	const { page, groups, nativeUpdate } = savedFilterPage();
	const translated = "已保存的筛选器";
	env.__ = (label) => label === "Saved Filters" ? translated : label;
	page.get_or_add_inner_group_button(translated);
	const saved = groups[0];
	const nativeAction = () => "existing saved filter";
	saved.dropdown.push(nativeAction);
	list.page = page;
	const controller = production("mount")(list, env);
	assert.doesNotThrow(() => nativeUpdate("Saved Filters"));
	await controller.clearQuickFilters();
	assert.equal(saved.label.textContent.trim(), translated);
	assert.equal(saved.dropdown[0], nativeAction);
	assert.equal(groups.length, 1);
});

test("PO page saved-filter group creation and lookup are localized, idempotent and leave other groups alone", () => {
	const { list, env } = bareList();
	const { page, groups } = savedFilterPage();
	const translated = "已保存的筛选器";
	env.__ = (label) => label === "Saved Filters" ? translated : label;
	list.page = page;
	production("mount")(list, env);
	const create = page.get_or_add_inner_group_button;
	page.get_or_add_inner_group_button(translated);
	const saved = groups[0];
	assert.equal(saved.identity, "Saved%20Filters");
	assert.equal(saved.label.textContent.trim(), translated);
	assert.equal(page.get_inner_group_button(translated).length, 1);
	assert.equal(page.get_inner_group_button("Saved Filters").length, 1);
	page.get_or_add_inner_group_button(translated);
	production("mount")(list, env);
	assert.equal(page.get_or_add_inner_group_button, create);
	assert.equal(groups.length, 1);
	page.get_or_add_inner_group_button("工作流");
	assert.equal(groups[1].identity, encodeURIComponent("工作流"));
	assert.equal(groups[1].label.textContent, "工作流");
});

test("Excel adapter is loaded only on export and receives the unpaginated filtered native request", async () => {
	const { list, env } = bareList();
	const loaded = [], exports = [];
	env.frappe.model.can_export = () => true;
	env.frappe.require = async (asset) => { loaded.push(asset); env.DeepLinkERPPurchaseOrderExport = { async exportExcel(root, args) { exports.push(args); } }; };
	const controller = production("mount")(list, env);
	assert.equal(loaded.length, 0);
	controller.quick.company = "A";
	controller.setPage(3);
	assert.equal(typeof controller.exportCurrent, "function");
	await controller.exportCurrent();
	await controller.exportCurrent();
	assert.equal(loaded.length, 1);
	assert.ok(loaded[0].includes("purchase_order_export.js"));
	assert.equal(new URL(loaded[0], "http://erp.localhost").search, "", "Frappe AssetManager requires the extension before adding its own version suffix");
	assert.equal(exports[0].start, 0);
	assert.equal("page_length" in exports[0], false);
	assert.ok(exports[0].fields.includes("party_account_currency"));
	assert.deepEqual(exports[0].filters, [["Purchase Order", "company", "=", "A"]]);
	env.frappe.model.can_export = () => false;
	await assert.rejects(() => controller.exportCurrent(), /权限/);
	assert.equal(exports.length, 2);
});
