(function (root, factory) {
	const adapter = factory();
	if (typeof module === "object" && module.exports) module.exports = adapter;
	root.DeepLinkERPUnifiedPurchase = adapter;
	if (root.document && root.frappe) adapter.installNavigation(root);
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
	"use strict";
	const SERVICE = "deeplinkerp_branding.services.unified_purchase_service.";
	const virtualFields = ["row_type", "source", "oa_number", "approval_status", "oa_amount"];
	const additions = [
		["row_type", "单据类型", 104], ["source", "来源", 108], ["oa_number", "OA 来源单", 180],
		["approval_status", "审批状态", 120], ["oa_amount", "OA 申请金额", 180],
	].map(([fieldname, label, width]) => ({ fieldname, label, width }));
	function filters(controller) {
		const quick = controller.quick || {}, result = { scope: controller.providerScope };
		for (const key of ["search", "from_date", "to_date", "company", "source", "approval_status"]) {
			if (quick[key] !== undefined && quick[key] !== null && quick[key] !== "") result[key] = quick[key];
		}
		if (quick.pending_company) result.company = "__unconfirmed__";
		return result;
	}
	function request(controller) {
		return { method: `${SERVICE}get_unified_purchase_list`, args: { filters: JSON.stringify(filters(controller)), start: controller.page * controller.pageSize, page_length: controller.pageSize, order_by: controller.providerOrderBy || "transaction_date desc" } };
	}
	function formLink(doc) { return `/desk/${doc.row_type === "oa_request" ? "oa-purchase-request" : "purchase-order"}/${encodeURIComponent(doc.name)}`; }
	function exportColumns(columns) {
		const fields = [...columns];
		for (const [amount, metadata] of [["grand_total", ["currency"]], ["oa_amount", ["oa_currency", "oa_amount_basis"]], ["advance_paid", ["party_account_currency"]]]) {
			if (fields.includes(amount)) fields.splice(fields.indexOf(amount) + 1, 0, ...metadata.filter((field) => !fields.includes(field)));
		}
		for (const field of ["oa_warning", "oa_references"]) if (!fields.includes(field)) fields.push(field);
		return fields;
	}
	function renderValue(field, doc, formatters = {}, escape = String) {
		if (field === "row_type") return escape(doc.row_type === "oa_request" ? "OA 申请" : "采购订单");
		if (field === "source") return escape(doc.source || "来源待确认");
		if (field === "company" && !doc.company) return doc.company_visibility === "hidden" ? "公司不可见" : "公司待确认";
		if (field === "oa_number") {
			if (doc.oa_references?.length) return doc.oa_references.map((ref) => {
				const title = [ref.approval_status, ref.amount == null ? "金额不可见" : `${ref.amount} ${ref.currency || "币种待确认"}`, ref.amount_basis, ref.company, ref.warning, doc.oa_warning].filter(Boolean).join("；");
				return `<a href="/desk/oa-purchase-request/${encodeURIComponent(ref.name)}" title="${escape(title)}">${escape(ref.number || ref.name)}</a>`;
			}).join("；");
			if (!doc.oa_name) return escape(doc.oa_warning || "—");
			return `<a href="/desk/oa-purchase-request/${encodeURIComponent(doc.oa_name)}" title="查看 OA 申请及钉钉原单">${escape(doc.oa_number || doc.oa_name)}</a>`;
		}
		if (field === "oa_amount") {
			if (doc.oa_amount === undefined || doc.oa_amount === null) return escape(doc.oa_warning || "—");
			const amount = Number(doc.oa_amount);
			if (!Number.isFinite(amount)) return "—";
			const number = formatters.number ? formatters.number(amount, field) : amount.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
			const title = [doc.oa_amount_basis, doc.oa_warning].filter(Boolean).join("；");
			return `<span title="${escape(title)}">${escape(number)} ${escape(doc.oa_currency || "币种待确认")}${doc.oa_warning ? " ⚠" : ""}</span>`;
		}
		if (field === "approval_status") return escape(doc.approval_status || [...new Set((doc.oa_references || []).map((ref) => ref.approval_status).filter(Boolean))].join("；") || "—");
	}
	function summary(controller, escape = String) {
		const totals = controller.providerPayload?.totals;
		if (!totals) return "";
		const format = (rows) => (rows || []).map((r) => `${Number(r.amount).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })} ${r.currency}`).join(" · ") || "—";
		return escape(`订单金额：${format(totals.orders)} ｜ OA 申请金额：${format(totals.oa)}${totals.oa_unknown_currency_count ? ` ｜ ${totals.oa_unknown_currency_count} 条 OA 币种待确认（未计合计）` : ""}`);
	}
	async function exportCurrent(controller) {
		const { root } = controller;
		const args = { filters: JSON.stringify(filters(controller)), columns: JSON.stringify(exportColumns(controller.preferences.columns)), order_by: controller.providerOrderBy };
		if (!root.DeepLinkERPPurchaseOrderExport?.downloadWorkbook) await root.frappe.require("/assets/deeplinkerp_branding/js/purchase_order_export.js");
		const exporter = root.DeepLinkERPPurchaseOrderExport;
		if (!exporter?.downloadWorkbook) throw new Error("导出组件加载失败，请刷新重试。");
		const bytes = await exporter.fetchNativeWorkbook(root, args, `${SERVICE}export_unified_purchase_list`);
		exporter.downloadWorkbook(root, bytes, "统一采购列表");
	}
	function mountControls(controller) {
		const { root, list } = controller, $ = root.$;
		controller.$providerScope = $("<select class='form-control input-xs dlp-po-scope' aria-label='查看范围'><option value='all'>全部采购</option><option value='orders'>仅订单</option><option value='oa'>仅 OA</option></select>").prependTo(controller.$toolbar);
		controller.$providerScope.on("change.dlpUnified", (e) => controller.setProviderScope(e.target.value));
		controller.$providerControls = $("<div class='dlp-po-provider-controls'><label>来源 <select class='form-control input-xs' data-filter='source' aria-label='来源'><option value=''>全部来源</option><option value='OA'>OA</option><option value='non_oa'>未关联 OA</option></select></label><label>审批状态 <input class='form-control input-xs' data-filter='approval_status' aria-label='审批状态' placeholder='审批状态（原值）'></label><label><input type='checkbox' data-filter='pending_company'> 公司待确认</label><span class='text-muted'>统一视图仅查看；高级筛选和批量操作请切换“仅订单”。</span></div>").insertAfter(controller.$filters);
		controller.$providerControls.on("input.dlpUnified change.dlpUnified", "[data-filter]", (e) => {
			const field = e.target.dataset.filter, value = e.target.type === "checkbox" ? e.target.checked : e.target.value;
			if (controller.quick[field] === value) return;
			controller.quick[field] = value;
			controller.setPage(0); controller.refresh();
		});
		list.$result.on("click.dlpUnified", "[data-provider-sort]", (e) => {
			const field = e.currentTarget.dataset.providerSort, previous = controller.providerOrderBy.split(" ");
			controller.providerOrderBy = `${field} ${previous[0] === field && previous[1] === "asc" ? "desc" : "asc"}`;
			controller.setPage(0); controller.refresh();
		});
		controller.setProviderScope("all", false);
		onActivate(controller);
	}
	function onActivate(controller) {
		const { root, list } = controller, realtime = root.frappe.realtime;
		if (!realtime?.on || !realtime?.off) return;
		controller.oaRealtimeListener ||= (data) => {
			if (data?.doctype === "OA Purchase Request" && controller.providerScope !== "orders" && root.cur_list === list && list.page.wrapper.is(":visible")) controller.refresh();
		};
		// Native ListView initialization clears list_update listeners, including cached adapters.
		realtime.off("list_update", controller.oaRealtimeListener);
		realtime.on("list_update", controller.oaRealtimeListener);
	}
	function onPayload(controller) {
		onActivate(controller);
		if (controller.providerPayload?.capabilities?.oa_request && !controller.oaSubscribed) {
			controller.root.frappe.realtime?.doctype_subscribe?.("OA Purchase Request"); controller.oaSubscribed = true;
		}
		controller.$providerNotice?.remove();
		const warnings = controller.providerPayload?.warnings || [];
		if (warnings.length) controller.$providerNotice = controller.root.$("<div class='text-muted dlp-po-provider-notice'></div>").text(warnings.join("；")).insertAfter(controller.$providerControls);
	}
	function listPath(href) { try { return new URL(href, "https://local.invalid").pathname.replace(/\/$/, ""); } catch (_) { return ""; } }
	function shouldHideOANavigation(href, availableHrefs, canReadPO) {
		return Boolean(canReadPO && ["/desk/oa-purchase-request", "/app/oa-purchase-request"].includes(listPath(href)) && availableHrefs.some((value) => ["/desk/purchase-order", "/app/purchase-order"].includes(listPath(value))));
	}
	function installNavigation(root) {
		const sync = () => {
			const canRead = Boolean(root.frappe.model?.can_read?.("Purchase Order"));
			for (const container of root.document.querySelectorAll(".body-sidebar-container")) {
				const links = [...container.querySelectorAll("a[href]")], hrefs = links.map((link) => link.getAttribute("href"));
				for (const link of links) if (shouldHideOANavigation(link.getAttribute("href"), hrefs, canRead)) {
					const item = link.closest(".standard-sidebar-item, .sidebar-item");
					if (item) { item.hidden = true; item.dataset.dlpOaCompatibility = "true"; }
				}
			}
		};
		const start = () => {
			sync(); new root.MutationObserver(sync).observe(root.document.body, { childList: true, subtree: true });
			root.frappe.router?.on("change", sync);
		};
		if (root.document.readyState === "loading") root.document.addEventListener("DOMContentLoaded", start, { once: true }); else start();
	}
	function configure(nativeColumns) {
		const columns = [...nativeColumns];
		columns.splice(2, 0, ...additions.slice(0, 3));
		columns.splice(columns.findIndex((c) => c.fieldname === "grand_total") + 1, 0, additions[4]);
		columns.splice(columns.findIndex((c) => c.fieldname === "status") + 1, 0, additions[3]);
		return { columns: columns.map((c) => ({ ...c, label: c.fieldname === "transaction_date" ? "单据日期" : c.fieldname === "name" ? "单据编号" : c.label })), freezeUntil: "name", virtualFields, newColumns: virtualFields, request, formLink, renderValue, summary, exportCurrent, mountControls, onActivate, onPayload, sortFields: ["transaction_date", "name", "company", "status", "grand_total", "oa_amount", "approval_status"] };
	}
	return { configure, request, formLink, renderValue, summary, exportColumns, exportCurrent, shouldHideOANavigation, installNavigation };
});
