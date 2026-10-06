(function (root, factory) {
	const adapter = factory();
	if (typeof module === "object" && module.exports) module.exports = adapter;
	root.DeepLinkERPUnifiedPurchase = adapter;
	if (root.document && root.frappe) adapter.installNavigation(root);
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
	"use strict";
	const SERVICE = "deeplinkerp_branding.services.unified_purchase_service.";
	const virtualFields = ["row_type", "source", "oa_number", "approval_status", "oa_amount", "requested_amount", "cashier_paid_amount"];
	const additions = [
		["row_type", "单据类型", 104], ["source", "来源", 108], ["oa_number", "OA 来源单", 180],
		["approval_status", "审批状态", 120], ["oa_amount", "来源明细金额", 180],
		["requested_amount", "来源申请金额", 180], ["cashier_paid_amount", "出纳实付（证据）", 180],
	].map(([fieldname, label, width]) => ({ fieldname, label, width }));
	function filters(controller) {
		const quick = controller.quick || {}, result = { scope: controller.providerScope };
		for (const key of ["search", "from_date", "to_date", "company", "source", "approval_status", "status", "advance_payment_status"]) {
			if (quick[key] !== undefined && quick[key] !== null && quick[key] !== "") result[key] = quick[key];
		}
		if (quick.pending_company) result.company = "__unconfirmed__";
		return result;
	}
	function nativeSort(orderBy) {
		const primary = String(orderBy || "").split(",")[0].trim();
		const match = /^(?:`tabPurchase Order`\.)?`?([a-z_][a-z0-9_]*)`?\s+(asc|desc)$/i.exec(primary);
		return match ? `${match[1]} ${match[2].toLowerCase()}` : null;
	}
	function getArgs(controller, nativeArgs = controller.originals?.get_args?.call(controller.list) || {}) {
		const order = nativeSort(nativeArgs.order_by);
		if (order) {
			const changed = controller.providerNativeOrder !== undefined && controller.providerNativeOrder !== order;
			if (controller.providerSortSource !== "header" || changed) {
				controller.providerOrderBy = order; controller.providerSortSource = "native";
				if (changed) controller.setPage?.(0);
			}
			controller.providerNativeOrder = order;
		}
		return { filters: JSON.stringify(filters(controller)), native_filters: JSON.stringify(nativeArgs.filters || []), native_or_filters: JSON.stringify(nativeArgs.or_filters || []), start: controller.page * controller.pageSize, page_length: controller.pageSize, order_by: controller.providerOrderBy || "transaction_date desc" };
	}
	function request(controller, nativeArgs) { return { method: `${SERVICE}get_unified_purchase_list`, args: getArgs(controller, nativeArgs) }; }
	function formLink(doc) { return `/desk/${doc.row_type === "oa_request" ? "oa-purchase-request" : "purchase-order"}/${encodeURIComponent(doc.name)}`; }
	function exportColumns(columns) {
		const fields = columns.filter(field => !['receipt_action','order_settled','order_unpaid'].includes(field));
		for (const [amount, metadata] of [["grand_total", ["currency"]], ["oa_amount", ["oa_currency", "oa_amount_basis"]], ["requested_amount", ["oa_currency"]], ["cashier_paid_amount", ["cashier_currency"]], ["advance_paid", ["party_account_currency"]]]) {
			if (fields.includes(amount)) fields.splice(fields.indexOf(amount) + 1, 0, ...metadata.filter((field) => !fields.includes(field)));
		}
		for (const field of ["oa_warning", "oa_references"]) if (!fields.includes(field)) fields.push(field);
		return fields;
	}
	function renderValue(field, doc, formatters = {}, escape = String) {
		if (field === "name" && doc.row_type === "oa_request") return escape(`待完善 · ${doc.oa_number || doc.name}`);
		if (field === "receipt_action" && doc.row_type === "oa_request") return `<button type="button" class="btn btn-xs btn-default" data-purchase-source="${escape(doc.oa_name || doc.name)}">完善/关联</button>`;
		if (field === "row_type") return escape(doc.row_type === "oa_request" ? "待完善来源" : "采购订单");
		if (field === "source") return escape(["OA", "oa"].includes(doc.source) ? "钉钉" : ["non_oa", "未关联 OA"].includes(doc.source) ? "其他来源" : doc.source || "来源待确认");
		if (field === "company" && !doc.company) return doc.company_visibility === "hidden" ? "公司不可见" : "公司待确认";
		if (field === "oa_number") {
			if (doc.oa_references?.length) return doc.oa_references.map((ref) => {
				const title = [ref.approval_status, ref.amount == null ? "金额不可见" : `${ref.amount} ${ref.currency || "币种待确认"}`, ref.amount_basis, ref.company, ref.warning, doc.oa_warning].filter(Boolean).join("；");
				return `<a href="/desk/oa-purchase-request/${encodeURIComponent(ref.name)}" title="${escape(title)}">${escape(ref.number || ref.name)}</a>`;
			}).join("；");
			if (!doc.oa_name) return escape(doc.oa_warning || "—");
			return `<a href="/desk/oa-purchase-request/${encodeURIComponent(doc.oa_name)}" title="查看 OA 申请及钉钉原单">${escape(doc.oa_number || doc.oa_name)}</a>`;
		}
		if (["oa_amount", "requested_amount", "cashier_paid_amount"].includes(field)) {
			if (doc[field] === undefined || doc[field] === null || doc[field] === "") return escape(field === "oa_amount" ? doc.oa_warning || "—" : "—");
			const amount = Number(doc[field]);
			if (!Number.isFinite(amount)) return "—";
			const number = formatters.number ? formatters.number(amount, field) : amount.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
			const title = field === "cashier_paid_amount" ? "出纳实付证据；ERP 登记付款和核销另列" : [field === "oa_amount" ? doc.oa_amount_basis : "来源申请金额", doc.oa_warning].filter(Boolean).join("；");
			const currency = field === "cashier_paid_amount" ? doc.cashier_currency : doc.oa_currency;
			return `<span title="${escape(title)}">${escape(number)} ${escape(currency || "币种待确认")}${field !== "cashier_paid_amount" && doc.oa_warning ? " ⚠" : ""}</span>`;
		}
		if (field === "approval_status") return escape(doc.approval_status || [...new Set((doc.oa_references || []).map((ref) => ref.approval_status).filter(Boolean))].join("；") || "—");
	}
	function renderLink(controller, doc, value, escape = String) {
		if (doc.row_type === "oa_request") return `<button type="button" class="btn btn-link btn-xs" data-purchase-source="${escape(doc.oa_name || doc.name)}">${value}</button>`;
	}
	function summary(controller, escape = String) {
		const totals = controller.providerPayload?.totals;
		if (!totals) return "";
		const format = (rows) => (rows || []).map((r) => `${Number(r.amount).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })} ${r.currency}`).join(" · ") || "—";
		return escape(`订单金额：${format(totals.orders)} ｜ OA 申请金额：${format(totals.oa)}${totals.oa_unknown_currency_count ? ` ｜ ${totals.oa_unknown_currency_count} 条 OA 币种待确认（未计合计）` : ""}`);
	}
	async function exportCurrent(controller) {
		const { root } = controller;
		const args = { ...getArgs(controller), columns: JSON.stringify(exportColumns(controller.preferences.columns)) };
		delete args.start; delete args.page_length;
		if (!root.DeepLinkERPPurchaseOrderExport?.downloadWorkbook) await root.frappe.require("/assets/deeplinkerp_branding/js/purchase_order_export.js");
		const exporter = root.DeepLinkERPPurchaseOrderExport;
		if (!exporter?.downloadWorkbook) throw new Error("导出组件加载失败，请刷新重试。");
		const bytes = await exporter.fetchNativeWorkbook(root, args, `${SERVICE}export_unified_purchase_list`);
		exporter.downloadWorkbook(root, bytes, "统一采购列表");
	}
	function mountControls(controller) {
		const { root, list } = controller, $ = root.$;
		const sorter = list.sort_selector;
		if (sorter) {
			const change = sorter.onchange || sorter.change;
			sorter.onchange = function (...args) {
				if (controller.providerScope !== "orders") { controller.providerSortSource = "native"; controller.setPage(0); }
				return change?.apply(this, args);
			};
		}
		controller.$providerControls = $("<div class='dlp-po-provider-controls'><label>来源 <select class='form-control input-xs' data-filter='source' aria-label='来源'><option value=''>全部来源</option><option value='oa'>钉钉</option><option value='non_oa'>其他来源</option></select></label><label>审批状态 <input class='form-control input-xs' data-filter='approval_status' aria-label='审批状态' placeholder='审批状态（原值）'></label><label><input type='checkbox' data-filter='pending_company'> 公司待确认</label></div>").insertAfter(controller.$filters);
		if (root.frappe.session?.user === "Administrator" || root.frappe.user_roles?.includes("System Manager")) $("<button type='button' class='btn btn-default btn-sm dlp-source-sync'>同步钉钉</button>").appendTo(controller.$providerControls).on("click.dlpUnified", async event => {
			const button = $(event.currentTarget).prop("disabled", true);
			try {
				if (!root.deeplinkerp?.purchaseSource?.sync) await root.frappe.require("/assets/deeplinkerp_branding/js/purchase_source.js");
				await root.deeplinkerp.purchaseSource.sync(); await controller.refresh();
			} catch (error) { root.frappe.msgprint({ message: error.message || "采购来源同步失败，请核对系统提示。", indicator: "red" }); }
			finally { button.prop("disabled", false); }
		});
		controller.$providerControls.on("input.dlpUnified change.dlpUnified", "[data-filter]", (e) => {
			const field = e.target.dataset.filter, value = e.target.type === "checkbox" ? e.target.checked : e.target.value;
			if (controller.quick[field] === value) return;
			controller.quick[field] = value;
			controller.setPage(0); controller.refresh();
		});
		list.$result.on("click.dlpUnified", "[data-provider-sort]", (e) => {
			const field = e.currentTarget.dataset.providerSort, previous = controller.providerOrderBy.split(" ");
			controller.providerOrderBy = `${field} ${previous[0] === field && previous[1] === "asc" ? "desc" : "asc"}`;
			controller.providerSortSource = "header";
			if (sorter && controller.allowed?.has(field)) {
				sorter.set_value(field, controller.providerOrderBy.split(" ")[1]);
				controller.providerNativeOrder = nativeSort(sorter.get_sql_string());
			}
			controller.setPage(0); controller.refresh();
		});
		controller.setProviderScope("all", false);
		onActivate(controller);
	}
	function onActivate(controller) {
		const { root, list } = controller, realtime = root.frappe.realtime;
		if (!realtime?.on || !realtime?.off) return;
		controller.oaRealtimeListener ||= (data) => {
			if (data?.doctype === "OA Purchase Request" && controller.providerScope !== "orders" && root.cur_list === list && list.page.wrapper.is(":visible")) {
				if (controller.queueRealtimeRefresh) controller.queueRealtimeRefresh(data);
				else controller.refresh();
			}
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
				for (const link of links) if (['/desk/purchase-payables','/desk/purchase-payment-records'].includes(listPath(link.getAttribute('href')))) {
					const disabled=!root.frappe.model?.can_read?.('Payment Entry');
					link.setAttribute('aria-disabled',String(disabled));link.classList.toggle('dlp-finance-disabled',disabled);
				}
				for (const link of links) if (shouldHideOANavigation(link.getAttribute("href"), hrefs, canRead)) {
					const item = link.closest(".standard-sidebar-item, .sidebar-item");
					if (item) { item.hidden = true; item.dataset.dlpOaCompatibility = "true"; }
				}
			}
		};
		const start = () => {
			root.document.addEventListener('click',event=>{const link=event.target.closest?.('a.dlp-finance-disabled');if(link){event.preventDefault();event.stopPropagation();}},true);
			sync(); new root.MutationObserver(sync).observe(root.document.body, { childList: true, subtree: true });
			root.frappe.router?.on("change", sync);
		};
		if (root.document.readyState === "loading") root.document.addEventListener("DOMContentLoaded", start, { once: true }); else start();
	}
	function configure(nativeColumns) {
		const columns = [...nativeColumns];
		columns.splice(2, 0, ...additions.slice(0, 3));
		columns.splice(columns.findIndex((c) => c.fieldname === "grand_total") + 1, 0, additions[4]);
		columns.splice(columns.findIndex((c) => c.fieldname === "oa_amount") + 1, 0, ...additions.slice(5));
		columns.splice(columns.findIndex((c) => c.fieldname === "status") + 1, 0, additions[3]);
		return { columns: columns.map((c) => ({ ...c, label: c.fieldname === "transaction_date" ? "单据日期" : c.fieldname === "name" ? "采购订单号 / 待完善来源" : c.label })), freezeUntil: "supplier_name", virtualFields: [...virtualFields], newColumns: [...virtualFields], useNativeIndicator: doc => doc.row_type === "purchase_order", getArgs, request, formLink, renderLink, renderValue, summary, exportCurrent, mountControls, onActivate, onPayload, sortFields: ["transaction_date", "name", "company", "status", "grand_total", "oa_amount", "approval_status"] };
	}
	return { configure, getArgs, request, formLink, renderValue, summary, exportColumns, exportCurrent, shouldHideOANavigation, installNavigation };
});
