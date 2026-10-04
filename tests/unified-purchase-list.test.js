const assert = require("node:assert/strict");
const test = require("node:test");
const fs = require("node:fs");
const path = require("node:path");
const engine = require("../deeplinkerp_branding/public/js/compact_list.js");
const adapterPath = path.join(__dirname, "../deeplinkerp_branding/public/js/unified_purchase_list.js");
const adapter = fs.existsSync(adapterPath) ? require(adapterPath) : {};

test('unified purchase view preserves freezing through supplier like native purchase list',()=>{
 assert.equal(adapter.configure([{fieldname:'name'},{fieldname:'supplier_name'}]).freezeUntil,'supplier_name');
});

function fixture(options={}) {
	const native = options.columns || [{ fieldname: "name", label: "采购订单号", width: 166 }];
	const provider = options.provider || {
		virtualFields: ["source"],
		columns: [...native, { fieldname: "source", label: "来源", width: 100 }],
		request: (c) => ({ method: "test.unified", args: { filters: JSON.stringify({ ...c.quick, scope: c.providerScope }), start: c.page * c.pageSize, page_length: c.pageSize, order_by: "transaction_date desc" } }),
		formLink: (doc) => `/desk/${doc.row_type === "oa_request" ? "oa-purchase-request" : "purchase-order"}/${encodeURIComponent(doc.name)}`,
		summary: () => "分别汇总",
		onActivate(c) { c.list.realtimeBindings ||= []; c.list.realtimeBindings.push("OA"); },
	};
	const grid = engine.create({ doctype: "Purchase Order", controllerKey: "grid", routeClass: "test", columns: native, provider });
	const list = {
		doctype: "Purchase Order", view_name: "List", meta: options.meta || { fields: [] }, fields: [["name", "Purchase Order"]], data: [],
		get_args() { return { filters: [], fields: ["name"], start: this.start, page_length: this.page_length }; },
		get_call_args() { return { method: "native", args: this.get_args() }; },
		no_change() { return false; }, prepare_data(r) { this.data = r.message; }, reset_defaults() {},
		refresh() { return Promise.resolve(); }, get_header_html() {}, get_list_row_html() {}, render_header() {}, render_list() {}, render_count() {}, toggle_result_area() {},
		get_form_link(d) { return `/desk/purchase-order/${d.name}`; }, get_checked_items() { return ["OLD-PO"]; },
		setup_realtime_updates() { this.realtimeBindings = ["Purchase Order"]; },
	};
	const root = { frappe: { model: { std_fields_list: ["name"] }, perm: { has_perm: () => true }, get_route: () => ["List", "Purchase Order", "List"], session: {}, boot: {} } };
	const controller = grid.mount(list, root);
	return { grid, list, controller };
}

test('real unified provider PO rows reuse native workflow indicator while OA rows keep their own status',()=>{
 const columns=[{fieldname:'name',label:'单据号',width:166},{fieldname:'supplier_name',label:'供应商',width:190},{fieldname:'status',label:'状态',width:120}];
 const {list,controller}=fixture({columns,provider:adapter.configure(columns),meta:{fields:[{fieldname:'status'},{fieldname:'supplier_name'}]}});
 const calls=[];list.workflow_state_fieldname='workflow_state';list.get_indicator_html=(doc,workflow)=>{calls.push([doc,workflow]);return '<span class="indicator-pill blue">待收货待开票</span>';};
 controller.setProviderScope('all',false);
 const po={name:'PO',row_type:'purchase_order',status:'To Receive and Bill',docstatus:1,supplier_name:'S'};
 const html=list.get_list_row_html(po);assert.match(html,/indicator-pill blue/);assert.match(html,/待收货待开票/);assert.equal(calls[0][0],po);assert.equal(calls[0][1],true);
 const oa=list.get_list_row_html({name:'OA',row_type:'oa_request',status:'OA 待办',supplier_name:'S'});assert.match(oa,/OA 待办/);assert.doesNotMatch(oa,/indicator-pill/);assert.equal(calls.length,1);
 assert.equal(controller.providerScope,'all');assert.equal(controller.list.data.length,0);
});

test("optional provider keeps OA rows outside native PO data and selection", () => {
	const { list, controller } = fixture();
	assert.equal(typeof controller.setProviderScope, "function");
	controller.setProviderScope("all", false);
	const call = list.get_call_args();
	assert.equal(call.method, "test.unified");
	list.no_change(call);
	const response = { message: { rows: [{ name: "SAME", row_key: "OA Purchase Request::SAME", row_type: "oa_request", source: "OA" }], total_count: 1 } };
	call.callback(response);
	list.prepare_data(response);
	assert.deepEqual(list.data, []);
	assert.equal(controller.providerRows.length, 1);
	assert.deepEqual(list.get_checked_items(true), []);
	const html = list.get_list_row_html(controller.providerRows[0]);
	assert.ok(html.includes("/desk/oa-purchase-request/SAME"));
	assert.ok(!html.includes("list-row-checkbox"));
	assert.ok(!html.includes('class="level list-row '));
	assert.ok(!list.get_header_html().includes("list-check-all"));
});

test("returning to orders restores native query, links, preferences and selection", () => {
	const { list, controller } = fixture();
	assert.equal(typeof controller.setProviderScope, "function");
	controller.setProviderScope("all", false);
	assert.ok(controller.preferences.columns.includes("source"));
	controller.setProviderScope("orders", false);
	assert.equal(list.get_call_args().method, "native");
	assert.deepEqual(controller.preferences.columns, ["name"]);
	assert.deepEqual(list.get_checked_items(true), ["OLD-PO"]);
});

test("switching scope invalidates an old response before a new request is dispatched", () => {
	const { list, controller } = fixture();
	assert.equal(typeof controller.setProviderScope, "function");
	controller.setProviderScope("all", false);
	const old = list.get_call_args(); list.no_change(old);
	controller.setProviderScope("oa", false);
	const response = { message: { rows: [{ name: "old" }], total_count: 1 } };
	old.callback(response); list.prepare_data(response);
	assert.deepEqual(controller.providerRows, []);
});

test("OA realtime binding follows the native setup which clears event listeners", () => {
	const { list, controller } = fixture();
	controller.setProviderScope("all", false);
	list.setup_realtime_updates();
	assert.deepEqual(list.realtimeBindings, ["Purchase Order", "OA"]);
});

test("provider request omits native advanced filters and explicitly filters unknown company", () => {
	assert.equal(typeof adapter.request, "function");
	const request = adapter.request({ providerScope: "all", quick: { search: "A", pending_company: 1, company: "Known", status: "Draft" }, page: 2, pageSize: 100, providerOrderBy: "oa_amount asc" });
	assert.deepEqual(JSON.parse(request.args.filters), { scope: "all", search: "A", company: "__unconfirmed__" });
	assert.equal(request.args.start, 200);
	assert.equal(request.args.order_by, "oa_amount asc");
});

test("hidden company is not presented as a pending company assignment", () => {
	assert.equal(adapter.renderValue("company", { company: null, company_visibility: "hidden" }), "公司不可见");
	assert.equal(adapter.renderValue("company", { company: null, company_visibility: "pending" }), "公司待确认");
});

test("OA amount renders its own currency and basis without rounding the source", () => {
	assert.equal(typeof adapter.renderValue, "function");
	const escape = (v) => String(v).replaceAll("<", "&lt;");
	const doc = { oa_amount: 123.45678, currency: "USD", oa_currency: "MXN", oa_amount_basis: "付款申请金额", oa_warning: "<需核对>" };
	const value = adapter.renderValue("oa_amount", doc, { number: (v) => v.toFixed(2) }, escape);
	assert.ok(value.includes("123.46 MXN"));
	assert.ok(value.includes("付款申请金额"));
	assert.ok(value.includes("&lt;需核对>"));
	assert.equal(doc.oa_amount, 123.45678);
	assert.ok(adapter.renderValue("oa_amount", { oa_amount: 0 }, {}, escape).includes("币种待确认"));
});

test("navigation hides only an OA list duplicate when a PO entry exists", () => {
	assert.equal(typeof adapter.shouldHideOANavigation, "function");
	assert.equal(adapter.shouldHideOANavigation("/desk/oa-purchase-request", ["/desk/purchase-order"], true), true);
	assert.equal(adapter.shouldHideOANavigation("/desk/oa-purchase-request", [], true), false);
	assert.equal(adapter.shouldHideOANavigation("/desk/oa-purchase-request", ["/desk/purchase-order"], false), false);
	assert.equal(adapter.shouldHideOANavigation("/desk/oa-purchase-request/ABC", ["/desk/purchase-order"], true), false);
});

test("conflicting OA references keep individual source links and readable original evidence", () => {
	const escape = (v) => String(v).replaceAll("<", "&lt;").replaceAll('"', "&quot;");
	const doc = { oa_warning: "OA关联冲突", oa_references: [
		{ name: "OA/1", number: "审批<1>", approval_status: "通过", amount: 15.12345, currency: "CNY", amount_basis: "采购明细合计", company: "A" },
		{ name: "OA-2", number: "审批2", approval_status: "撤销", amount: 20, currency: "MXN", amount_basis: "付款申请金额", company: "B" },
	] };
	const value = adapter.renderValue("oa_number", doc, {}, escape);
	assert.ok(value.includes("/desk/oa-purchase-request/OA%2F1"));
	assert.ok(value.includes("/desk/oa-purchase-request/OA-2"));
	assert.ok(value.includes("审批&lt;1>"));
	assert.ok(value.includes("15.12345 CNY"));
	assert.ok(value.includes("付款申请金额"));
	assert.equal(adapter.renderValue("approval_status", doc, {}, escape), "通过；撤销");
});

test("unified exports always retain selected amount currencies and provenance", () => {
	assert.deepEqual(adapter.exportColumns(["name", "oa_amount", "advance_paid"]),
		["name", "oa_amount", "oa_currency", "oa_amount_basis", "advance_paid", "party_account_currency", "oa_warning", "oa_references"]);
	assert.deepEqual(adapter.exportColumns(["name", "grand_total"]),
		["name", "grand_total", "currency", "oa_warning", "oa_references"]);
});

test("Excel transport reuses same-origin CSRF download for the unified endpoint", async () => {
	const exporter = require("../deeplinkerp_branding/public/js/purchase_order_export.js");
	assert.equal(typeof exporter.downloadWorkbook, "function");
	let body;
	const root = { frappe: { csrf_token: "test", request: { url: "/" } }, location: { href: "https://erp.test/desk/purchase-order", origin: "https://erp.test" }, fetch: async (_, options) => {
		body = new URLSearchParams(options.body);
		return new Response(Uint8Array.of(0x50, 0x4b, 0, 0), { headers: { "content-type": "application/octet-stream" } });
	} };
	await exporter.fetchNativeWorkbook(root, { filters: "{}", columns: '["name"]' }, "deeplinkerp_branding.services.unified_purchase_service.export_unified_purchase_list");
	assert.equal(body.get("cmd"), "deeplinkerp_branding.services.unified_purchase_service.export_unified_purchase_list");
	assert.equal(body.has("file_format_type"), false);
});

test("cached unified list reinstalls only its own OA realtime listener after native navigation", () => {
	const { EventEmitter } = require("node:events"), realtime = new EventEmitter();
	realtime.doctype_subscribe = () => {};
	const element = { prependTo() { return this; }, insertAfter() { return this; }, on() { return this; } };
	const list = { $result: element, page: { wrapper: { is: () => true } } };
	const root = { $: () => element, cur_list: list, frappe: { realtime } };
	let refreshed = 0;
	const controller = { root, list, $toolbar: element, $filters: element, providerPayload: { capabilities: { oa_request: true } }, setProviderScope(scope) { this.providerScope = scope; }, refresh() { refreshed++; } };
	const provider = adapter.configure([]);
	provider.mountControls(controller);
	realtime.emit("list_update", { doctype: "OA Purchase Request" });
	assert.equal(refreshed, 1);
	realtime.removeAllListeners("list_update");
	let nativeEvents = 0;
	realtime.on("list_update", () => nativeEvents++);
	provider.onActivate(controller);
	provider.onActivate(controller);
	realtime.emit("list_update", { doctype: "OA Purchase Request" });
	assert.equal(refreshed, 2);
	assert.equal(nativeEvents, 1);
});

test("provider text filters react to typing without duplicate refresh on blur", () => {
	const handlers = new Map();
	const element = { prependTo() { return this; }, insertAfter() { return this; }, on(events, selector, handler) {
		if (selector === "[data-filter]") for (const event of events.split(" ")) handlers.set(event.split(".")[0], handler);
		return this;
	} };
	let refreshed = 0, pageResets = 0;
	const controller = { root: { $: () => element, frappe: {} }, list: { $result: element }, quick: {},
		$toolbar: element, $filters: element, setProviderScope() {}, setPage(page) { assert.equal(page, 0); pageResets++; }, refresh() { refreshed++; } };
	adapter.configure([]).mountControls(controller);
	assert.equal(typeof handlers.get("input"), "function");
	const event = { target: { dataset: { filter: "approval_status" }, type: "text", value: "审批中" } };
	handlers.get("input")(event); handlers.get("change")(event);
	assert.equal(controller.quick.approval_status, "审批中");
	assert.equal(refreshed, 1); assert.equal(pageResets, 1);
	event.target.value = ""; handlers.get("input")(event);
	assert.equal(refreshed, 2);
});

test("export captures the clicked scope, filters and columns before lazy library loading", async () => {
	let resolve, captured;
	const root = { frappe: { require: () => new Promise((done) => { resolve = done; }) } };
	const controller = { root, providerScope: "all", quick: { company: "A" }, preferences: { columns: ["name", "oa_amount"] }, providerOrderBy: "name asc" };
	const downloading = adapter.exportCurrent(controller);
	controller.providerScope = "oa"; controller.quick.company = "B"; controller.preferences.columns = ["name", "grand_total"];
	root.DeepLinkERPPurchaseOrderExport = { fetchNativeWorkbook: async (_, args) => { captured = args; return new Uint8Array(); }, downloadWorkbook() {} };
	resolve(); await downloading;
	assert.deepEqual(JSON.parse(captured.filters), { scope: "all", company: "A" });
	assert.ok(JSON.parse(captured.columns).includes("oa_amount"));
	assert.ok(!JSON.parse(captured.columns).includes("grand_total"));
});
