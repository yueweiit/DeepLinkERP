const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const modulePath = path.join(__dirname, "../deeplinkerp_branding/public/js/purchase_source.js");
const create = fs.existsSync(modulePath) ? require(modulePath) : () => ({});
const projection = () => ({
	name: "OA/1", version: "current-source-and-cashier", target_company: "Company A", purchase_order: null,
	can_write: true, can_create: true,
	source: {
		eligible: true, business_id: "2026-审批1", oa_identity: { corp_id: "corp", process_instance_id: "instance" },
		currency: "CNY", requested_amount: "100.00", detail_total_amount: "100.00", payee: "付款对象",
		apply_date: "2026-10-01", schedule_date: "2026-10-08", issues: [],
		items: [{ item_code: "ITEM", item_name: "原物料", qty: "2.00001", uom: "Nos", amount: "100.00" }],
		original_fields: { description: "<img src=x onerror=write()>原文", payments: "计划支付100" },
		source_url: "https://aflow.dingtalk.com/dingtalk/mobile/homepage.htm?procInstId=instance",
	},
	cashier: {
		paid_amount: "25.12345", currency: "CNY", payment_evidence_status: "recorded", issues: [],
		payments: [{ source_id: "pay1", amount: "25.12345", currency: "CNY", payment_date: "2026-10-02", payer: "出纳", evidence_status: "recorded", remark: "证据" }],
		attachments: [{ attachment_id: "file/1", source_id: "file/1", version: "file-v1", filename: "凭证<1>.pdf", downloadable: true }, { attachment_id: "pending", version: "p1", filename: "待归档.pdf", downloadable: false }],
	},
});

// The installed ERPNext metadata has no Purchase Order.remarks/name DocField.
// Reject invented native fields instead of returning a permissive fake for every key.
const nativeFields = {
	"Purchase Order": { company: ["Link", "Company"], supplier: ["Link", "Supplier"], currency: ["Link", "Currency"], schedule_date: ["Date"], terms: ["Text Editor"], amended_from: ["Link", "Purchase Order"] },
	"Purchase Order Item": { item_code: ["Link", "Item"], qty: ["Float"], uom: ["Link", "UOM"], rate: ["Currency", "currency"] },
	"Payment Entry": { amended_from: ["Link", "Payment Entry"] },
};
function nativeField(doctype, fieldname) {
	const field = nativeFields[doctype]?.[fieldname];
	return field ? { fieldname, fieldtype: field[0], options: field[1] } : null;
}

// The real source controller runs against Frappe controls and the existing drawer shell boundary.
function host(detail = projection(), overrides = {}) {
	const surfaces = [], controls = new Map(), calls = [], confirmations = [], routes = [], handlers = new Map(), metadataReads = [];
	class Surface {
		constructor(markup = "", selector = "") {
			this.value = ""; this.markup = markup; this.selector = selector; this.handlers = new Map(); this.length = 1; surfaces.push(this);
			this.inputEvents = new Map(); this.node = { addEventListener: (event, callback) => this.inputEvents.set(event, callback), removeEventListener: event => this.inputEvents.delete(event) };
		}
		find(selector) { return new Surface("", selector); }
		html(value) { if (value === undefined) return this.value; this.value = value; return this; }
		text(value) { this.value = value; return this; }
		val(value) { if (value === undefined) return this.value; this.value = value; return this; }
		get() { return this.node; } dispatch(event) { this.inputEvents.get(event)?.(); }
		append(value) { this.value += value; return this; }
		appendTo() { return this; } prependTo() { return this; } remove() { return this; }
		addClass() { return this; } attr() { return this; } prop() { return this; } off() { return this; }
		on(event, handler) { this.handlers.set(event.split(".")[0], handler); return this; }
	}
	let alive = true;
	const drawer = { panel: new Surface(), controls: [], busy: false, loadId: 0, alive: () => alive,
		close() { alive = false; }, setBusy(value) { this.busy = value; }, error(error) { this.errorMessage = error.message; } };
	const root = {
		$: markup => new Surface(markup), document: { addEventListener: (event, fn) => handlers.set(event, fn) },
		DeepLinkERPCompactList: require("../deeplinkerp_branding/public/js/compact_list.js"),
		DeepLinkERPPurchasePayments: { createDrawer: () => drawer, disposeControls: owned => owned.splice(0), openNative: (type, name) => routes.push(["Form", type, name]) },
		frappe: {
			call: async request => { calls.push(request); return { message: request.method.endsWith("get_purchase_source_detail") ? detail : { name: "PO-DRAFT", doctype: "Purchase Order" } }; },
			model: { with_doctype: async () => {} }, meta: { get_docfield: (doctype, fieldname) => { metadataReads.push([doctype, fieldname]); return nativeField(doctype, fieldname); } },
			confirm: (message, yes, no) => confirmations.push({ message, yes, no }), show_alert() {}, msgprint() {},
			ui: { form: { make_control: ({ df }) => {
				const input = new Surface(), numeric = ["qty", "rate"].includes(df.fieldname.split("_")[0]);
				const control = { df, $input: input, get_value: () => numeric ? Number(input.val() || 0) : input.val(), get_precision() { return this.df.precision ?? 3; },
					format_for_input(value) { return value === null || value === undefined ? "" : Number(value).toFixed(this.get_precision()); },
					async set_value(value) { input.val(numeric ? this.format_for_input(value) : value); } };
				controls.set(df.fieldname, control); return control;
			} } },
			...overrides,
		},
	};
	const shellBoundary = root.DeepLinkERPPurchasePayments;
	vm.runInNewContext(fs.readFileSync(require.resolve("../deeplinkerp_branding/public/js/purchase_payments.js"), "utf8"), { globalThis: root, ...root });
	root.DeepLinkERPPurchasePayments = { ...root.DeepLinkERPPurchasePayments, ...shellBoundary };
	const api = create(root);
	const click = async className => {
		const surface = surfaces.findLast(s => s.markup.includes(className) && s.handlers.has("click"));
		assert.ok(surface, `${className} must be an available action`);
		return surface.handlers.get("click")({ preventDefault() {}, stopPropagation() {} });
	};
	return { api, root, drawer, controls, calls, confirmations, routes, click, metadataReads,
		html: () => surfaces.map(s => s.markup + s.value).join(""), input: async (field, value) => {
			assert.ok(controls.has(field), field); const control = controls.get(field);
			control.$input.val(value); control.$input.dispatch("input"); await control.set_value(value);
		} };
}

test("source drawer shows separate original, requested and actual paid evidence with protected file links", async () => {
	const h = host(); assert.equal(typeof h.api.open, "function"); await h.api.open("OA/1");
	const html = h.html();
	assert.match(html, /来源申请金额/); assert.match(html, /来源明细金额/); assert.match(html, /出纳实付（证据）/);
	assert.match(html, /25\.12345/); assert.match(html, /计划支付100/); assert.match(html, /&lt;img src=x onerror=write\(\)&gt;原文/);
	assert.doesNotMatch(html, /<img src=x/); assert.match(html, /get_purchase_source_detail|钉钉原单/);
	assert.match(html, /download_source_attachment\?name=OA%2F1&amp;attachment_id=file%2F1&amp;version=file-v1/);
	assert.match(html, /待归档|尚未归档/);
	assert.doesNotMatch(html, /attachment_id=pending/);
	assert.equal(h.calls.length, 1);
});

test("source facts and payment evidence reuse two-decimal display without changing exact original strings", async () => {
	const detail = projection(); detail.source.requested_amount = 100; detail.source.detail_total_amount = 100;
	detail.source.original_fields.original_amount = "100.00100";
	const original = JSON.stringify(detail), h = host(detail); await h.api.open("OA/1");
	assert.match(h.html(), /100\.00 CNY/); assert.match(h.html(), /25\.12 CNY/);
	assert.match(h.html(), /100\.00100/); assert.match(h.html(), /25\.12345/);
	assert.equal(JSON.stringify(detail), original);
});

test("structured source detail and confirmation summary share formatted display with exact hover evidence", async () => {
	const detail = projection(); detail.source.items[0].amount = 100;
	const original = JSON.stringify(detail), h = host(detail); await h.api.open("OA/1");
	assert.match(h.html(), /<td[^>]*><span title="原值 · 2\.00001">2<\/span><\/td>/);
	assert.match(h.html(), /<td[^>]*><span title="原值 · 100">100\.00 CNY<\/span><\/td>/);
	await h.input("supplier", "SUPPLIER"); await h.input("rate_0", "49.99975000125");
	await h.click("dlp-source-create");
	assert.match(h.confirmations[0].message, /title="原值 · 2\.00001">2<\/span>/);
	assert.match(h.confirmations[0].message, /title="原值 · 49\.99975000125">50\.00 CNY<\/span>/);
	assert.equal(JSON.stringify(detail), original);
	await h.confirmations[0].yes();
	assert.deepEqual(JSON.parse(h.calls[1].args.items), [{ item_code: "ITEM", qty: "2.00001", uom: "Nos", rate: "49.99975000125" }]);
});

test("an old cached drawer shell missing shared formatters prompts a full refresh before loading source data", async () => {
	const h = host(); const messages = []; let required = 0;
	delete h.root.DeepLinkERPPurchasePayments.formatMoney;
	h.root.frappe.require = async () => { required++; }; h.root.frappe.msgprint = message => messages.push(message);
	await h.api.open("OA/1");
	assert.equal(required, 1); assert.equal(h.calls.length, 0); assert.equal(h.controls.size, 0);
	assert.match(String(messages[0]), /版本|整页刷新/);
});

test("source facts do not invent quantities, prices or supplier master data", async () => {
	const detail = projection(); detail.source.items[0].qty = null; detail.source.schedule_date = "10月8号";
	const h = host(detail); assert.equal(typeof h.api.open, "function"); await h.api.open("OA/1");
	assert.equal(h.controls.get("supplier").get_value(), "");
	assert.equal(h.controls.get("qty_0").$input.val(), "");
	assert.equal(h.controls.get("rate_0").$input.val(), "");
	assert.equal(h.controls.get("schedule_date").$input.val(), "");
	assert.equal(h.controls.get("item_code_0").df.options, "Item");
	assert.equal(h.controls.get("supplier").df.options, "Supplier");
	await h.click("dlp-source-create");
	assert.equal(h.confirmations.length, 0); assert.equal(h.calls.length, 1);
	assert.match(h.drawer.errorMessage, /公司|供应商|数量|单价/);
});

test("an unavailable source gives the shared drawer a visible error area without leaving a loading state", async () => {
	const h = host(projection(), { call: async () => { throw new Error("此申请尚未接入来源，请先同步核对"); } });
	await h.api.open("OA/1");
	assert.match(h.html(), /dlp-error/); assert.match(h.drawer.errorMessage, /同步核对/);
	assert.equal(h.controls.size, 0);
});

test("hidden cashier evidence is identified as unavailable and cannot render stale paid amounts or files", async () => {
	const detail = projection(); detail.cashier.payment_evidence_status = "hidden";
	const h = host(detail); await h.api.open("OA/1");
	assert.match(h.html(), /付款证据不可见/);
	assert.doesNotMatch(h.html(), /25\.12345|file%2F1/);
});

test("creating a draft requires confirmation and sends exact manual values and frozen source version", async () => {
	const h = host(); assert.equal(typeof h.api.open, "function"); await h.api.open("OA/1");
	for (const [field, value] of Object.entries({ company: "Company A", supplier: "SUPPLIER", currency: "CNY", schedule_date: "2026-10-08", item_code_0: "ITEM", qty_0: "2.00001", uom_0: "Nos", rate_0: "49.99975000125", correction_reason: "按原明细核对" })) await h.input(field, value);
	await h.click("dlp-source-create");
	assert.equal(h.calls.length, 1); assert.equal(h.confirmations.length, 1);
	assert.match(h.confirmations[0].message, /草稿/); assert.match(h.confirmations[0].message, /SUPPLIER/);
	await h.confirmations[0].yes();
	const request = h.calls[1];
	assert.equal(request.method, "deeplinkerp_branding.services.purchase_source_service.create_purchase_order_from_source");
	assert.equal(request.args.expected_version, "current-source-and-cashier");
	assert.deepEqual(JSON.parse(request.args.items), [{ item_code: "ITEM", qty: "2.00001", uom: "Nos", rate: "49.99975000125" }]);
	assert.equal(request.args.supplier, "SUPPLIER"); assert.equal(request.args.correction_reason, "按原明细核对");
	assert.equal(request.args.docstatus, undefined); assert.equal(request.args.paid_amount, undefined);
	assert.deepEqual(h.routes, [["Form", "Purchase Order", "PO-DRAFT"]]);
});

test("numeric input presentation has at most two decimals while confirmation retains original and manual precision", async () => {
	const h = host(); await h.api.open("OA/1");
	assert.equal(h.controls.get("qty_0").$input.val(), "2.00");
	assert.equal(h.controls.get("qty_0").get_precision(), 3);
	assert.equal(h.controls.get("rate_0").$input.val(), "");
	await h.input("supplier", "SUPPLIER"); await h.input("rate_0", "49.99975000125");
	assert.equal(h.controls.get("rate_0").$input.val(), "50.00");
	await h.click("dlp-source-create"); await h.confirmations[0].yes();
	assert.deepEqual(JSON.parse(h.calls[1].args.items), [{ item_code: "ITEM", qty: "2.00001", uom: "Nos", rate: "49.99975000125" }]);
});

test("correction explanation is a dialog-only field without depending on or writing native terms", async () => {
	const h = host(); await h.api.open("OA/1");
	assert.equal(h.drawer.errorMessage, undefined);
	assert.equal(h.controls.get("correction_reason")?.df.fieldtype, "Small Text");
	assert.equal(h.controls.get("correction_reason")?.$input.val(), "");
	assert.equal(h.metadataReads.some(([, field]) => ["remarks", "terms", "correction_reason"].includes(field)), false);
	assert.match(h.html(), /dlp-source-create/); assert.match(h.html(), /dlp-source-associate/);
	await h.input("correction_reason", "保留临时说明"); await h.input("purchase_order", "PO-EXISTING");
	await h.click("dlp-source-associate"); await h.confirmations[0].yes();
	assert.equal(h.calls[1].args.correction_reason, "保留临时说明");
	assert.equal(h.calls[1].args.terms, undefined); assert.equal(h.calls[1].args.remarks, undefined);
});

test("association explicitly chooses an existing order and does not use create-draft mapping fields", async () => {
	const h = host(); assert.equal(typeof h.api.open, "function"); await h.api.open("OA/1");
	await h.input("purchase_order", "PO-EXISTING"); await h.input("correction_reason", "核对已有订单");
	assert.equal(h.controls.get("purchase_order").df.options, "Purchase Order");
	await h.click("dlp-source-associate"); assert.equal(h.calls.length, 1);
	await h.confirmations[0].yes();
	assert.equal(h.calls[1].method, "deeplinkerp_branding.services.purchase_source_service.associate_purchase_order");
	assert.equal(h.calls[1].args.purchase_order, "PO-EXISTING");
	assert.equal(h.calls[1].args.expected_version, "current-source-and-cashier");
	assert.equal(h.calls[1].args.items, undefined); assert.equal(h.calls[1].args.correction_reason, "核对已有订单");
});

test("a linked source rechecks only its fixed existing order after an explicit fresh read", async () => {
	const cached = projection(); cached.purchase_order = "PO-EXISTING";
	const fresh = structuredClone(cached); fresh.version = "fresh-source-and-cashier";
	const h = host(cached);
	h.root.frappe.call = async request => { h.calls.push(request); return { message: request.method.endsWith("get_purchase_source_detail") ? request.args.fresh ? fresh : cached : { name: "PO-EXISTING", doctype: "Purchase Order" } }; };
	await h.api.open("OA/1");
	assert.equal(h.calls[0].args.fresh, undefined); assert.doesNotMatch(h.html(), /class='[^']*dlp-source-review'/);
	await h.click("dlp-source-reload");
	assert.equal(h.calls[1].args.fresh, 1); assert.match(h.html(), /复核现有关联/);
	assert.equal(h.controls.has("purchase_order"), false); assert.equal(h.controls.has("supplier"), false);
	assert.doesNotMatch(h.html(), /class='[^']*dlp-source-create|class='[^']*dlp-source-associate/);
	await h.input("correction_reason", "原单更新，已核对现有订单"); await h.click("dlp-source-review");
	assert.equal(h.calls.length, 2); assert.match(h.confirmations[0].message, /PO-EXISTING/); assert.match(h.confirmations[0].message, /复核/);
	await h.confirmations[0].yes();
	assert.equal(h.calls[2].method, "deeplinkerp_branding.services.purchase_source_service.associate_purchase_order");
	assert.deepEqual(h.calls[2].args, { name: "OA/1", expected_version: "fresh-source-and-cashier", purchase_order: "PO-EXISTING", correction_reason: "原单更新，已核对现有订单" });
	assert.deepEqual(h.routes, [["Form", "Purchase Order", "PO-EXISTING"]]);
});

test("a fresh withdrawn or readonly linked source never offers association recheck", async () => {
	for (const change of [source => source.source.eligible = false, source => source.can_write = false]) {
		const cached = projection(); cached.purchase_order = "PO-EXISTING";
		const fresh = structuredClone(cached); fresh.version = "fresh-version"; change(fresh);
		const h = host(cached); h.root.frappe.call = async request => { h.calls.push(request); return { message: request.args.fresh ? fresh : cached }; };
		await h.api.open("OA/1"); await h.click("dlp-source-reload");
		assert.equal(h.calls[1].args.fresh, 1); assert.doesNotMatch(h.html(), /class='[^']*dlp-source-review'/); assert.equal(h.calls.length, 2);
		assert.match(h.html(), /来源审批未满足办理条件|当前没有办理权限/);
	}
});

test("a failed fresh read blocks the previous linked-source recheck without losing the manual reason", async () => {
	const detail = projection(); detail.purchase_order = "PO-EXISTING";
	const h = host(detail); let fail = false;
	h.root.frappe.call = async request => { h.calls.push(request); if (fail) throw new Error("原单暂不可读取"); return { message: detail }; };
	await h.api.open("OA/1"); await h.click("dlp-source-reload"); await h.input("correction_reason", "待复核说明");
	fail = true; await h.click("dlp-source-reload"); await h.click("dlp-source-review");
	assert.equal(h.calls.length, 3); assert.equal(h.confirmations.length, 0); assert.match(h.drawer.errorMessage, /原单暂不可读取/);
	assert.equal(h.controls.get("correction_reason").get_value(), "待复核说明");
});

test("withdrawn, readonly and already linked sources remain evidence without actionable create buttons", async () => {
	for (const change of [d => d.source.eligible = false, d => d.can_write = false, d => d.purchase_order = "ALREADY-PO"]) {
		const detail = projection(); change(detail);
		const h = host(detail); assert.equal(typeof h.api.open, "function"); await h.api.open("OA/1");
		assert.doesNotMatch(h.html(), /class="[^"]*dlp-source-create|class="[^"]*dlp-source-associate/);
		assert.equal(h.calls.length, 1); assert.match(h.html(), /审批|权限|已关联/);
	}
});

test("a cancelled load cannot populate or write a departed source drawer", async () => {
	let resolve; const pending = new Promise(done => resolve = done);
	const h = host(projection(), { call: () => pending }); assert.equal(typeof h.api.open, "function");
	const opening = h.api.open("OA/1"); h.drawer.close(); resolve({ message: projection() }); await opening;
	assert.equal(h.controls.size, 0); assert.equal(h.confirmations.length, 0);
});

test("missing native metadata explains setup failure and offers no write action", async () => {
	const h = host(projection(), { model: { with_doctype: async () => { throw new Error("missing"); } } });
	assert.equal(typeof h.api.open, "function"); await h.api.open("OA/1");
	assert.equal(h.controls.size, 0); assert.match(h.drawer.errorMessage, /字段|元数据|安装/);
	assert.doesNotMatch(h.html(), /class="[^"]*dlp-source-create/);
});

test("association uses a real native Link field and removes inherited readonly and permission bypass settings", async () => {
	const h = host(projection(), { meta: { get_docfield: (doctype, fieldname) => nativeField(doctype, fieldname) && ({ ...nativeField(doctype, fieldname), read_only: 1, hidden: 1, ignore_user_permissions: 1 }) } });
	await h.api.open("OA/1");
	assert.ok(h.controls.has("purchase_order"), "standard document name is not a native DocField");
	const df = h.controls.get("purchase_order").df;
	assert.equal(df.only_select, 1); assert.equal(df.read_only, 0); assert.equal(df.hidden, 0); assert.equal(df.ignore_user_permissions, 0);
});

test("source numeric controls retain native currency context and precision without a default price", async () => {
	const h = host(projection(), { meta: { get_docfield: (doctype, fieldname) => nativeField(doctype, fieldname) && ({ ...nativeField(doctype, fieldname), ...(fieldname === "rate" ? { precision: 6, default: "0" } : {}) }) } });
	await h.api.open("OA/1");
	const rate = h.controls.get("rate_0");
	assert.equal(rate.df.options, "currency"); assert.equal(rate.df.precision, 6);
	assert.equal(rate.$input.val(), ""); assert.equal(rate.df.default, null);
	assert.equal(rate.get_doc().currency, "CNY");
});

test("manager source synchronization uses a POST cache sync while ordinary buyers cannot invoke it", async () => {
	const h = host(); assert.equal(typeof h.api.sync, "function");
	await assert.rejects(h.api.sync(), /管理员|权限/); assert.equal(h.calls.length, 0);
	h.root.frappe.user_roles = ["System Manager"];
	await h.api.sync();
	assert.equal(h.calls[0].method, "deeplinkerp_branding.services.purchase_source_service.sync_purchase_sources");
	assert.equal(h.calls[0].type, "POST"); assert.equal(h.calls[0].args.items, undefined);
});

test("historical payment reconciliation selects existing native payments with an explicit confirmation", async () => {
	const detail = projection(); detail.purchase_order = "PO-1"; detail.can_reconcile = true;
	const h = host(detail); await h.api.open("OA/1");
	assert.ok(h.controls.has("payment_entry_0"));
	assert.equal(h.controls.get("payment_entry_0").df.options, "Payment Entry");
	assert.equal(h.controls.get("payment_entry_0").df.only_select, 1);
	assert.deepEqual(h.controls.get("payment_entry_0").get_query().filters, { docstatus: 1, payment_type: "Pay", company: "Company A" });
	await h.input("payment_entry_0", "PE-OLD");
	await h.click("dlp-source-reconcile"); assert.equal(h.calls.length, 1);
	assert.match(h.confirmations[0].message, /核对历史付款/); await h.confirmations[0].yes();
	assert.equal(h.calls[1].method, "deeplinkerp_branding.services.purchase_source_service.confirm_historical_payments");
	assert.deepEqual(JSON.parse(h.calls[1].args.payment_entries), ["PE-OLD"]);
	assert.equal(h.calls[1].args.expected_version, "current-source-and-cashier");
	assert.equal(h.calls[1].args.docstatus, undefined); assert.equal(h.calls[1].args.posting_date, undefined);
	assert.equal(h.routes.length, 0); assert.equal(h.calls[2].method, "deeplinkerp_branding.services.purchase_source_service.get_purchase_source_detail");
});

test("unknown or hidden actual-payment evidence offers no reconciliation action even with finance capability", async () => {
	for (const status of ["unknown", "hidden"]) {
		const detail = projection(); detail.purchase_order = "PO-1"; detail.can_reconcile = true;
		detail.cashier.payment_evidence_status = status; detail.cashier.paid_amount = null;
		const h = host(detail); await h.api.open("OA/1");
		assert.doesNotMatch(h.html(), /class="[^"]*dlp-source-reconcile/);
		assert.equal(h.controls.has("payment_entry_0"), false);
	}
});

test("OA legacy form removes unsafe generate action before adding the safe manual source drawer", () => {
	const formPath = path.join(__dirname, "../deeplinkerp_branding/public/js/oa_purchase_request.js");
	assert.ok(fs.existsSync(formPath), "OA form script is required");
	let settings, opened, action; const removed = [];
	vm.runInNewContext(fs.readFileSync(formPath, "utf8"), { frappe: { ui: { form: { on: (doctype, value) => { assert.equal(doctype, "OA Purchase Request"); settings = value; } } } }, deeplinkerp: { purchaseSource: { open: name => opened = name } }, __: value => value });
	settings.refresh({ doc: { name: "OA-1" }, is_new: () => false, remove_custom_button: label => removed.push(label), add_custom_button: (label, callback) => action = callback });
	assert.ok(removed.includes("生成采购订单")); assert.ok(removed.includes("Generate Purchase Order"));
	action(); assert.equal(opened, "OA-1");
});
