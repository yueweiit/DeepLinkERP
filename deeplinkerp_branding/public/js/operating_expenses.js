(function (root, factory) {
	if (typeof module === "object" && module.exports) module.exports = factory;
	root.DeepLinkERPOperatingExpenses = factory(root);
})(typeof globalThis !== "undefined" ? globalThis : this, function (root) {
	"use strict";
	const API = "deeplinkerp_branding.services.operating_expenses.",
		route = "operating-expenses";
	const t = (value) => (root.__ || ((text) => text))(value);
	const esc = (value) =>
		String(value ?? "").replace(
			/[&<>"']/g,
			(char) =>
				({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[char])
		);
	const columns = [
		["request_date", "申请日期", 110],
		["source_id", "申请编号 / 摘要", 240],
		["effective_application_type", "申请类型", 115],
		["payee_name", "收款人", 170],
		["applicant", "申请人", 110],
		["company", "法律公司", 170],
		["summary", "摘要", 250],
		["currency", "币种", 75],
		["amount", "申请金额", 125],
		["paid_amount", "累计已付", 125],
		["pending_amount", "剩余待付", 125],
		["source_status", "付款状态", 120],
		["approval_state", "来源审批", 125],
		["finance_status", "凭证状态", 135],
		["actions", "操作", 85],
	].map(([fieldname, label, width]) => ({ fieldname, label, width }));
	const defaultColumns = ["request_date","source_id","effective_application_type","payee_name","company","approval_state","amount","paid_amount","pending_amount","finance_status","actions"];
	const sortFields = ["request_date", "amount", "applicant", "source_id", "company", "modified"];
	const filterFields = [
		"keyword",
		"company",
		"application_type",
		"applicant",
		"source_status",
		"approval_state",
		"date_from",
		"date_to",
	];
	const exportFields = new Set([
		"company",
		"source_id",
		"approval_no",
		"effective_application_type",
		"application_type_raw",
		"applicant",
		"payee_name",
		"summary",
		"request_date",
		"currency",
		"amount",
		"paid_amount",
		"pending_amount",
		"source_status",
		"approval_state",
		"finance_status",
		"issues",
		"source_company",
		"source_sheet",
	]);
	function filters(values = {}) {
		const result = {};
		for (const field of filterFields)
			if (values[field] !== undefined && values[field] !== null && values[field] !== "")
				result[field] = String(values[field]);
		for (const [field, allowed, label] of [
			["application_type", ["payment", "reimbursement", "unclassified"], "申请类型"],
			["source_status", ["未付款", "部分付款", "已付款", "付款待核对"], "来源付款状态"],
			["approval_state", ["eligible", "blocked"], "来源审批状态"],
		]) {
			if (result[field] && !allowed.includes(result[field]))
				throw new Error(t(`${label}无效`));
		}
		return result;
	}
	function orderBy(value = "request_date desc") {
		const match = /^([a-z_]+) (asc|desc)$/.exec(value);
		if (!match || !sortFields.includes(match[1])) throw new Error(t("排序字段无效"));
		return value;
	}
	function request(c) {
		return {
			method: API + "get_operating_expenses",
			args: {
				filters: JSON.stringify(filters(c.quick)),
				order_by: orderBy(c.providerOrderBy),
				start: c.page * c.pageSize,
				page_length: c.pageSize,
			},
		};
	}
	// Display rounds decimal text without changing the exact text used by financial controls.
	function money(value) {
		if (value == null || value === "" || !["string", "number"].includes(typeof value))
			return "—";
		const match = /^([+-]?)(\d+)(?:\.(\d+))?$/.exec(String(value));
		if (!match) return "—";
		const fraction = (match[3] || "").padEnd(3, "0");
		let cents = BigInt(match[2]) * 100n + BigInt(fraction.slice(0, 2));
		if (fraction[2] >= "5") cents++;
		return `${
			match[1] === "-" && cents ? "-" : ""
		}${String(cents / 100n).replace(/\B(?=(\d{3})+(?!\d))/g, ",")}.${String(cents % 100n).padStart(2, "0")}`;
	}
	const typeLabel = (value) =>
		t(
			{ payment: "付款申请", reimbursement: "费用报销", unclassified: "待分类" }[value] ||
				"待分类"
		);
	const approvalLabel = (value) => t(value === "eligible" ? "来源审批通过" : "需复核");
	function summary(c) {
		const totals = c.providerPayload?.currency_totals || {};
		return Object.entries(totals)
			.map(
				([currency, row]) =>
					`${esc(currency || t("币种未明确"))} · ${esc(t("申请金额"))} ${money(
						row.amount
					)} · ${esc(t("累计已付"))} ${money(row.paid_amount)} · ${esc(
						t("剩余待付")
					)} ${money(row.pending_amount)}${
						row.incomplete
							? ` <span class="text-warning">${esc(t("金额不完整，需复核"))}</span>`
							: ""
					}`
			)
			.join("<br>");
	}
	function renderValue(field, doc) {
		if (field === "source_id") return `<div class="dlp-operating-identity"><span class="dlp-operating-ellipsis" title="${esc(doc.source_id)}">${esc(doc.approval_no || doc.source_id || "—")}</span><small class="dlp-operating-ellipsis text-muted" title="${esc(doc.summary||"")}">${esc(doc.summary||"—")}</small></div>`;
		if (["amount", "paid_amount", "pending_amount"].includes(field)) return money(doc[field])+(doc.currency?` <small class="text-muted">${esc(doc.currency)}</small>`:"");
		if (field === "effective_application_type") return esc(typeLabel(doc[field]));
		if (field === "approval_state")
			return `<span class="${
				doc[field] === "eligible" ? "text-success" : "text-warning"
			}">${esc(approvalLabel(doc[field]))}</span>`;
		if (field === "finance_status") return esc(t(doc[field] || "未确认"));
		if (field === "actions")
			return `<button type="button" class="btn btn-default btn-xs dlp-operating-open" data-source="${esc(
				doc.source_id || doc.name
			)}">${esc(t(doc.finance_status === "关联已记账" ? "查看" : "办理"))}</button>`;
		return `<span class="dlp-operating-ellipsis" title="${esc(
			doc[field] ?? ""
		)}">${esc(doc[field] ?? "—")}</span>`;
	}
	async function exportCurrent(c) {
		const args = {
			filters: JSON.stringify(filters(c.quick)),
			order_by: orderBy(c.providerOrderBy),
			columns: JSON.stringify([
				...new Set([
					...c.preferences.columns.flatMap(field=>field==="source_id"?["display_source_id","summary"]:exportFields.has(field)?[field]:[]),
					"currency",
					"approval_no",
					"source_id",
				]),
			]),
		};
		if (!root.DeepLinkERPPurchaseOrderExport?.downloadWorkbook)
			await root.frappe.require("/assets/deeplinkerp_branding/js/purchase_order_export.js");
		const exporter = root.DeepLinkERPPurchaseOrderExport;
		if (!exporter) throw new Error(t("导出组件加载失败，请刷新。"));
		exporter.downloadWorkbook(
			root,
			await exporter.fetchNativeWorkbook(root, args, API + "export_operating_expenses"),
			t("运营支出")
		);
	}
	function fit(c, active = true) {
		return root.DeepLinkERPCompactList.fitViewport(c, {
			active,
			root,
			scrollElement: c.list.$result.parent(".result-container")[0],
			layoutTailElement: c.list.$frappe_list[0],
			property: "--dlp-operating-result-max-height",
			headerSelector: ".dlp-po-grid-header",
			rowSelector: ".dlp-po-grid-row",
			observeTargets: [
				c.$filters?.[0]?.parentElement,
				c.$toolbar?.[0],
				c.$summary?.[0],
				c.$paging?.[0],
			],
		});
	}
	function mountControls(c) {
		const tabs=root.$('<div class="dlp-operating-list-tabs"></div>').insertBefore(c.$toolbar);
		for(const [field,choices] of [["application_type",[["","全部申请"],["payment","付款申请"],["reimbursement","费用报销"]]],["source_status",[["","全部付款状态"],["未付款","未付款"],["部分付款","部分付款"],["已付款","已付款"],["付款待核对","待核对"]]]]) {
			if(!c.controls[field])continue;
			const group=root.$('<div role="group"></div>').appendTo(tabs);
			const mark=()=>group.find("button").each((_i,node)=>root.$(node).toggleClass("active",node.dataset.value===(c.controls[field].get_value()||"")));
			for(const [value,label] of choices) root.$(`<button type="button" class="btn btn-default btn-sm" data-value="${esc(value)}">${esc(t(label))}</button>`).appendTo(group).on("click.dlpOperating",async()=>{c.resetting=true;try{c.quick[field]=value;await c.controls[field].set_value(value);}finally{c.resetting=false;}mark();c.setPage(0);await c.refresh();});
			c.controls[field].$input?.on("change.dlpOperating",mark);
			mark();
		}
		root.$(`<button type="button" class="btn btn-default btn-sm">${esc(t("恢复推荐列"))}</button>`).appendTo(c.$toolbar).on("click.dlpOperating",()=>c.setColumns(defaultColumns));
		root.$(
			`<button type="button" class="btn btn-default btn-sm">${esc(t("清空筛选"))}</button>`
		)
			.appendTo(c.$toolbar)
			.on("click.dlpOperating", () => c.clearQuickFilters());
		if (root.DeepLinkERPOperatingExpenseDrawer.isManager())
			root.$(
				`<button type="button" class="btn btn-default btn-sm">${esc(
					t("同步设置")
				)}</button>`
			)
				.appendTo(c.$toolbar)
				.on("click.dlpOperating", () =>
					root.DeepLinkERPOperatingExpenseDrawer.openSettings(() => c.refresh())
				);
		c.list.$result
			.off(".dlpOperating")
			.on("click.dlpOperating", ".dlp-operating-open", (event) =>
				root.DeepLinkERPOperatingExpenseDrawer.open(
					event.currentTarget.dataset.source,
					() => c.refresh()
				)
			)
			.on("click.dlpOperating", "[data-provider-sort]", (event) => {
				const field = event.currentTarget.dataset.providerSort;
				if (!sortFields.includes(field)) return;
				const [previous, direction] = c.providerOrderBy.split(" ");
				c.providerOrderBy = `${field} ${
					previous === field && direction === "asc" ? "desc" : "asc"
				}`;
				c.setPage(0);
				c.refresh();
			});
		c.$operatingNotice = root
			.$('<p class="text-muted dlp-operating-notice"></p>')
			.text(t("历史付款 + ERP 登记汇总；审批、付款、凭证状态分别展示。登记不转账，凭证仅保存草稿。"))
			.insertAfter(c.$filters);
	}
	function grid() {
		const pageFieldMap = Object.fromEntries(
			columns.map((col) => [col.fieldname, col.fieldname])
		);
		Object.assign(pageFieldMap, {
			finance_status: "issues",
			actions: "source_id",
			keyword: "source_id",
			date_from: "request_date",
			date_to: "request_date",
			application_type: "effective_application_type",
		});
		const controls = [
			["keyword", "Data", null, "申请编号 / 摘要 / 收款人"],
			["company", "Link", "Company", "法律公司"],
			["application_type", "Select", "\npayment\nreimbursement\nunclassified", "申请类型"],
			["applicant", "Data", null, "申请人"],
			["source_status", "Select", "\n未付款\n部分付款\n已付款\n付款待核对", "来源付款状态"],
			["approval_state", "Select", "\neligible\nblocked", "来源审批"],
			["date_from", "Date", null, "申请开始日期"],
			["date_to", "Date", null, "申请结束日期"],
		].map(([fieldname, fieldtype, options, label]) => ({
			fieldname,
			fieldtype,
			options,
			label,
			permission_field: pageFieldMap[fieldname] || fieldname,
		}));
		return root.DeepLinkERPCompactList.create({
			doctype: "Operating Expense Source",
			pageRoute: route,
			routeClass: "dlp-operating-expense-grid-active",
			columns,
			defaultColumns,
			defaultSort: "request_date desc",
			pageFieldMap,
			controls,
			numbers: ["amount", "paid_amount", "pending_amount"],
			dates: ["request_date"],
			dismissInitialOnboarding: true,
			optionLabels: {
				application_type: {
					payment: "付款申请",
					reimbursement: "费用报销",
					unclassified: "待分类",
				},
				approval_state: { eligible: "来源审批通过", blocked: "需复核" },
			},
			provider: {
				columns,
				defaultColumns,
				freezeUntil: "source_id",
				sortFields,
				request,
				renderValue,
				summary,
				exportCurrent,
				mountControls,
				onPayload: (c) => fit(c),
			},
			afterRender: (c) => fit(c),
			emptyLabel: "没有符合条件的运营支出来源",
		});
	}
	const api = {
		API,
		route,
		columns,
		defaultColumns,
		sortFields,
		filters,
		orderBy,
		request,
		money,
		typeLabel,
		approvalLabel,
		summary,
		renderValue,
		exportCurrent,
		esc,
		grid,
		fit,
		controller: null,
	};
	api.onPageLoad = (wrapper) => {
		const page = root.frappe.ui.make_app_page({
			parent: wrapper,
			title: t("运营支出"),
			single_column: true,
		});
		const ready = root.frappe.model.with_doctype("Operating Expense Source").then(() => {
			const c = grid().mountPage(page, root);
			api.controller = c;
			wrapper.dlpOperatingController = c;
			root.frappe.router?.on("change", () =>
				fit(c, (root.frappe.get_route?.() || [])[0] === route)
			);
			return c;
		});
		wrapper.dlpLoad = async () => {
			const c = await ready;
			c.activate();
			fit(c, (root.frappe.get_route?.() || [])[0] === route);
			return c.refresh();
		};
		ready.catch(() =>
			page.main.append(
				`<p class="text-danger">${esc(t("来源元数据读取失败，请刷新或核对权限。"))}</p>`
			)
		);
		page.set_secondary_action(t("刷新"), () => wrapper.dlpLoad());
	};
	api.onPageShow = (wrapper) => wrapper.dlpLoad?.();
	return api;
});
