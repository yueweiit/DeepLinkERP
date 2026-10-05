const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const listPath = "../deeplinkerp_branding/public/js/operating_expenses.js";
const create = fs.existsSync(require("node:path").join(__dirname, listPath))
	? require(listPath)
	: () => ({});
const api = create({});

test("operating filters retain only the exact backend predicates without type inference", () => {
	assert.equal(typeof api.filters, "function");
	assert.deepEqual(
		api.filters({
			keyword: "编号",
			company: "Legal",
			application_type: "payment",
			applicant: "A",
			source_status: "部分付款",
			approval_state: "eligible",
			date_from: "2026-10-01",
			date_to: "2026-10-06",
			injected: "x",
		}),
		{
			keyword: "编号",
			company: "Legal",
			application_type: "payment",
			applicant: "A",
			source_status: "部分付款",
			approval_state: "eligible",
			date_from: "2026-10-01",
			date_to: "2026-10-06",
		}
	);
	assert.throws(() => api.filters({ application_type: "报销付款混合" }), /类型/);
	assert.throws(() => api.filters({ source_status: "partially_paid" }), /状态/);
	assert.throws(() => api.filters({ source_status: "partial" }), /状态/);
});
test("operating provider requests a stable whitelisted sort and the selected page only", () => {
	assert.equal(typeof api.request, "function");
	const req = api.request({
		quick: { company: "C" },
		providerOrderBy: "amount asc",
		page: 2,
		pageSize: 500,
	});
	assert.equal(
		req.method,
		"deeplinkerp_branding.services.operating_expenses.get_operating_expenses"
	);
	assert.deepEqual(JSON.parse(req.args.filters), { company: "C" });
	assert.equal(req.args.start, 1000);
	assert.equal(req.args.page_length, 500);
	assert.equal(req.args.order_by, "amount asc");
	assert.throws(
		() =>
			api.request({
				quick: {},
				providerOrderBy: "amount asc; delete",
				page: 0,
				pageSize: 100,
			}),
		/排序/
	);
});
test("operating amount rendering distinguishes missing, malformed, exact zero, and decimal rounding", () => {
	assert.equal(typeof api.money, "function");
	assert.equal(api.money(null), "—");
	assert.equal(api.money(""), "—");
	assert.equal(api.money("NaN"), "—");
	assert.equal(api.money(Infinity), "—");
	assert.equal(api.money("0"), "0.00");
	assert.equal(api.money("12.345"), "12.35");
	assert.equal(api.money("9007199254740993.01"), "9,007,199,254,740,993.01");
});
test("source classification and approval display never imply native posting", () => {
	assert.equal(typeof api.typeLabel, "function");
	assert.equal(api.typeLabel("unclassified"), "待分类");
	assert.equal(api.typeLabel("unknown reimbursement"), "待分类");
	assert.equal(api.typeLabel("payment"), "付款申请");
	assert.equal(api.typeLabel("reimbursement"), "费用报销");
	assert.equal(api.approvalLabel("eligible"), "来源审批通过");
	assert.equal(api.approvalLabel("agree"), "需复核");
});
test("summary renders every server currency separately and calls out unknown or incomplete values", () => {
	assert.equal(typeof api.summary, "function");
	const html = api.summary({
		providerPayload: {
			currency_totals: {
				CNY: { amount: "10", paid_amount: "2", pending_amount: "8" },
				USD: { amount: "3", paid_amount: "0", pending_amount: "3", incomplete: true },
				"": { amount: "0", incomplete: true },
			},
		},
	});
	assert.match(html, /CNY.*10\.00.*出纳已付.*2\.00.*出纳待付.*8\.00/);
	assert.match(html, /USD.*3\.00/);
	assert.match(html, /不完整/);
	assert.match(html, /币种未明确/);
});
test("full-filter Excel snapshots filters, sort and ordered supported columns before lazy loading", async () => {
	let resume, args, method, downloaded;
	const root = { frappe: { require: () => new Promise((resolve) => (resume = resolve)) } };
	const exportAPI = create(root);
	assert.equal(typeof exportAPI.exportCurrent, "function");
	const c = {
		quick: { company: "C", keyword: "old" },
		providerOrderBy: "source_id asc",
		page: 4,
		pageSize: 20,
		preferences: { columns: ["summary", "actions", "finance_status", "amount"] },
	};
	const pending = exportAPI.exportCurrent(c);
	c.quick.keyword = "new";
	c.providerOrderBy = "amount desc";
	c.preferences.columns = ["payee_name"];
	root.DeepLinkERPPurchaseOrderExport = {
		fetchNativeWorkbook: async (_root, value, cmd) => {
			args = value;
			method = cmd;
			return new Uint8Array([1]);
		},
		downloadWorkbook: (_root, _bytes, title) => (downloaded = title),
	};
	resume();
	await pending;
	assert.deepEqual(JSON.parse(args.filters), { company: "C", keyword: "old" });
	assert.equal(args.order_by, "source_id asc");
	assert.deepEqual(JSON.parse(args.columns), ["summary", "amount", "currency", "source_id"]);
	assert.equal(args.start, undefined);
	assert.equal(args.page_length, undefined);
	assert.equal(
		method,
		"deeplinkerp_branding.services.operating_expenses.export_operating_expenses"
	);
	assert.equal(downloaded, "运营费用");
});
test("list opens source drawer directly and preserves raw backend finance status", () => {
	assert.equal(typeof api.renderValue, "function");
	assert.match(api.renderValue("actions", { source_id: "A<&" }), /dlp-operating-open/);
	assert.doesNotMatch(api.renderValue("actions", { source_id: "A<&" }), /data-source="A<&"/);
	assert.match(
		api.renderValue("finance_status", { finance_status: "草稿已生成" }),
		/草稿已生成/
	);
	assert.equal(api.renderValue("amount", { amount: "0" }), "0.00");
});
test("operating Page reuses the shared readonly engine with scalar permission aliases and fixed source filters", () => {
	let config;
	const root = {
		DeepLinkERPCompactList: {
			create: (value) => {
				config = value;
				return { mountPage() {} };
			},
		},
	};
	const a = create(root);
	assert.equal(typeof a.grid, "function");
	a.grid();
	assert.equal(config.doctype, "Operating Expense Source");
	assert.equal(config.pageRoute, "operating-expenses");
	assert.equal(config.defaultSort, "request_date desc");
	assert.equal(config.provider.freezeUntil, "source_id");
	assert.equal(config.pageFieldMap.finance_status, "issues");
	assert.equal(config.pageFieldMap.actions, "source_id");
	assert.equal(
		config.controls.find((c) => c.fieldname === "source_status").options,
		"\n未付款\n部分付款\n已付款"
	);
	assert.equal(config.controls.find((c) => c.fieldname === "company").fieldtype, "Link");
	assert.ok(config.controls.every((c) => c.permission_field));
	assert.ok(config.provider.exportCurrent);
});
test("shared column settings opens for a provider whose primary identifier is source_id and virtual columns are permission aliases", () => {
	const shared = require("../deeplinkerp_branding/public/js/compact_list.js"),
		handlers = new Map();
	let dialogHTML = "",
		shown = 0;
	class Surface {
		constructor(key = "") {
			this.key = key;
			this.length = 1;
		}
		find(key) {
			return new Surface(key);
		}
		first() {
			return this;
		}
		parent() {
			return this;
		}
		html(value) {
			if (this.key === "dialog") dialogHTML = value;
			return this;
		}
		text() {
			return this;
		}
		append() {
			return this;
		}
		appendTo() {
			return this;
		}
		prependTo() {
			return this;
		}
		insertBefore() {
			return this;
		}
		insertAfter() {
			return this;
		}
		addClass() {
			return this;
		}
		removeClass() {
			return this;
		}
		toggleClass() {
			return this;
		}
		hide() {
			return this;
		}
		show() {
			return this;
		}
		remove() {
			return this;
		}
		off() {
			return this;
		}
		on(name, ...args) {
			handlers.set(this.key + ":" + name, args.at(-1));
			return this;
		}
		attr() {
			return this;
		}
		prop() {
			return this;
		}
		val() {
			return this;
		}
	}
	const root = {
		$: () => new Surface(),
		DeepLinkERPCompactList: shared,
		DeepLinkERPOperatingExpenseDrawer: { isManager: () => false },
		document: { body: { classList: { toggle() {} } } },
		frappe: {
			get_route: () => ["operating-expenses"],
			session: { user: "finance" },
			router: { on() {} },
			get_meta: () => ({ fields: [{ fieldname: "source_id" }, { fieldname: "issues" }] }),
			model: { can_export: () => false },
			ui: {
				Dialog: class {
					constructor() {
						this.fields_dict = { columns: { $wrapper: new Surface("dialog") } };
					}
					show() {
						shown++;
					}
					hide() {}
				},
				form: { make_control: () => ({ get_value: () => "", set_value: async () => {} }) },
			},
		},
	};
	const c = create(root).grid().mountPage({ main: new Surface(), wrapper: new Surface() }, root);
	assert.doesNotThrow(() => handlers.get(".dlp-po-columns:click.dlpPO")());
	assert.equal(shown, 1);
	assert.match(dialogHTML, /申请编号/);
	assert.match(dialogHTML, /财务状态/);
	assert.match(dialogHTML, /操作/);
	assert.doesNotMatch(dialogHTML, /data-field="name"/);
	assert.deepEqual(c.preferences.columns, ["source_id", "finance_status", "actions"]);
});
