(function (root, factory) {
	const api = factory(root, root.DeepLinkERPCompactList || (typeof require === "function" ? require("./compact_list.js") : null));
	if (typeof module === "object" && module.exports) module.exports = api;
	root.DeepLinkERPSalesWorkspace = api;
	if (root.frappe?.listview_settings) api.install(root);
})(typeof globalThis !== "undefined" ? globalThis : this, function (root, engine) {
	"use strict";
	const API = "deeplinkerp_branding.services.compact_sales_service.";
	const financialGroups = { pending: ["Pending Deposit Confirmation", "Deposit Confirmation Processing"], approved: ["Pending Production", "Pending Final Payment", "Deliverable", "Partially Delivered", "Completed"], rejected: ["Rejected"] };
	const financialLabels = { pending: "待财务审核", approved: "已放行生产", rejected: "已驳回" };
	const financialLabel = value => financialLabels[Object.keys(financialGroups).find(group => financialGroups[group].includes(value))] || "—";
	const statusLabels = { "Pending Confirmation": "待确认", "Pending Deposit Confirmation": "待财务放行", "Deposit Confirmation Processing": "CRM/MES 同步中", "Pending Production": "生产已放行", "Pending Final Payment": "待尾款确认", "Deliverable": "可发货", "Partially Delivered": "部分发货", "Completed": "已完成", "Rejected": "已驳回", "Cancelled": "已取消", "Closed": "已关闭" };
	const orderStatusLabels = { Draft: "草稿", "To Deliver and Bill": "待交付及开票", "To Bill": "待开票", "To Deliver": "待交付", Completed: "已完成", Cancelled: "已取消", Closed: "已关闭", "On Hold": "已暂停" };
	const COLUMNS = [
		["name", "CRM / ERP 订单号", 190], ["customer_name", "客户", 165], ["custom_process_status", "财务审核状态", 145], ["dlp_product", "产品", 170], ["dlp_quantity", "数量", 105], ["grand_total", "ERP 订单金额", 145], ["delivery_date", "预计交付日期", 110], ["transaction_date", "订单日期", 105],
		["title", "ERP 标题", 170], ["contact_display", "联系人", 160], ["contact_email", "联系人邮箱", 200], ["contact_mobile", "联系电话", 140], ["customer", "ERP 客户编码", 150], ["dlp_sales_person", "业务负责人", 155], ["dlp_rate", "ERP 单价", 125], ["custom_odt", "ODT", 130], ["custom_remark", "销售备注", 230], ["company", "公司", 180], ["currency", "币种", 70], ["status", "交付状态", 145], ["advance_paid", "ERP 预付款汇总", 150], ["owner", "ERP 创建人", 190], ["creation", "创建时间", 165], ["modified_by", "ERP 更新人", 190], ["modified", "更新时间", 165], ["per_delivered", "已交付", 85], ["per_billed", "已开票", 85], ["project", "项目", 130],
		["dlp_receipts", "关联收款记录", 290], ["dlp_sync", "财务确认 / 同步", 200], ["dlp_last_confirmation", "最近确认人 / 时间", 235], ["dlp_actions", "操作", 110],
	].map(([fieldname, label, width]) => ({ fieldname, label, width }));
	const presets = {
		main: ["name", "customer_name", "custom_process_status", "dlp_product", "dlp_quantity", "grand_total", "delivery_date", "dlp_actions"],
		middle: ["name", "title", "contact_display", "dlp_sales_person", "customer", "transaction_date", "delivery_date", "custom_remark", "dlp_actions"],
		tail: ["name", "custom_odt", "status", "per_delivered", "owner", "creation", "modified_by", "modified", "dlp_actions"],
		finance: ["name", "customer_name", "custom_process_status", "grand_total", "dlp_receipts", "dlp_last_confirmation", "dlp_actions"],
	};
	const itemColumns = [["idx", "序号"], ["item_code", "品目编码"], ["item_name", "品项名"], ["custom_specifications", "规格型号"], ["custom_version", "版本"], ["qty", "数量"], ["rate", "ERP 单价"], ["custom_item_tax_amount", "IVA 增值税"], ["amount", "ERP 明细金额"], ["delivery_date", "交付日期"], ["description", "摘要"], ["custom_product", "产品系列"], ["warehouse", "仓库"]];
	const esc = value => String(value ?? "").replace(/[&<>"']/g, ch => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[ch]);
	const t = (value, args) => (root.__ || ((x, values = []) => x.replace(/\{(\d+)\}/g, (_, i) => values[i] ?? "")))(value, args);
	const state = value => t(statusLabels[value] || value || "—");
	const money = (value, currency) => value === undefined || value === null ? "—" : `${Number(value).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })} ${esc(currency || "")}`;
	const call = async (method, args) => (await root.frappe.call({ method: API + method, args })).message;
	function itemTable(detail, full = true) {
		const permitted = new Set(detail.item_fields || []), currency = detail.header.currency;
		const columns = itemColumns.filter(([field]) => permitted.has(field));
		if (!columns.length) return `<p>${esc(t("无权查看产品明细"))}</p>`;
		return `<div class="dlp-sales-items-scroll"><table class="table dlp-sales-items ${full ? "" : "dlp-sales-items-overview"}"><thead><tr>${columns.map(([field, label], i) => `<th${i > 7 ? ' class="dlp-sales-extra-item"' : ""}>${esc(t(label))}</th>`).join("")}</tr></thead><tbody>${(detail.items || []).map(item => `<tr>${columns.map(([field], i) => {
			let value = item[field] ?? "—";
			if (["rate", "custom_item_tax_amount", "amount"].includes(field)) value = money(item[field], currency);
			else if (field === "qty") value = esc(item[field] ?? "—") + (permitted.has("uom") ? ` ${esc(item.uom)}` : "");
			else value = esc(value);
			return `<td${i > 7 ? ' class="dlp-sales-extra-item"' : ""}>${value}</td>`;
		}).join("")}</tr>`).join("")}</tbody></table></div>`;
	}
	function detailsHTML(detail) {
		const header = detail.header;
		const fields = [["custom_crm_order_no", "CRM 订单号"], ["name", "ERP 订单号"], ["customer_name", "客户"], ["customer", "ERP 客户编码"], ["title", "ERP 标题"], ["contact_display", "联系人"], ["contact_email", "联系人邮箱"], ["contact_mobile", "联系电话"], ["transaction_date", "订单日期"], ["delivery_date", "预计交付日期"], ["company", "公司"], ["custom_process_status", "ERP 业务状态"], ["grand_total", "ERP 订单金额"], ["advance_paid", "ERP 预付款汇总"], ["custom_odt", "ODT"], ["custom_remark", "销售备注"], ["owner", "ERP 创建人"], ["creation", "创建时间"], ["modified_by", "ERP 更新人"], ["modified", "更新时间"]].filter(([field]) => Object.hasOwn(header, field));
		return `<div class="dlp-sales-detail-layout"><section><h4>${esc(t("订单基本信息"))}</h4><dl>${fields.map(([field, label]) => `<dt>${esc(t(label))}</dt><dd>${field === "custom_process_status" ? esc(state(header[field])) : ["grand_total", "advance_paid"].includes(field) ? money(header[field], header[field === "advance_paid" ? "party_account_currency" : "currency"]) : esc(header[field] || "—")}</dd>`).join("")}</dl><p class="text-muted">${esc(t("显示 ERP 已同步字段；负责人来自销售团队，创建人是 ERP 账户。"))}</p><a class="btn btn-default btn-sm" href="/desk/sales-order/${encodeURIComponent(header.name)}">${esc(t(detail.can_edit ? "打开原生订单编辑" : "打开原生订单"))}</a></section><section><div class="dlp-sales-detail-heading"><h4>${esc(t("订单产品明细"))}</h4><button class="btn btn-default btn-sm dlp-sales-all-items" aria-expanded="false">${esc(t("显示全部明细字段"))}</button></div>${itemTable(detail, false)}<h4>${esc(t("订单附件"))}</h4>${(detail.attachments || []).filter(file => /^\/(private\/)?files\//.test(file.file_url)).map(file => `<p><a target="_blank" rel="noopener" href="${esc(file.file_url)}">${esc(file.file_name)}</a></p>`).join("") || `<p class="text-muted">${esc(t("没有可见附件"))}</p>`}<p class="text-muted">${esc(t("预计交付日期沿用 ERP 交期；CRM 未同步的源字段不作推断。"))}</p></section></div>`;
	}
	function renderValue(field, doc, formatters) {
		const tr = formatters.translate || t;
		if (field === "name") return `${esc(doc.custom_crm_order_no || doc.name)}${doc.custom_crm_order_no ? `<small class="dlp-sales-erp-number">ERP: ${esc(doc.name)}</small>` : ""}`;
		if (field === "custom_process_status") return `<span class="dlp-sales-state">${esc(tr(financialLabel(doc[field])))}</span>`;
		if (field === "status") return `<span class="dlp-sales-state">${esc(tr(orderStatusLabels[doc[field]] || doc[field] || "—"))}</span>`;
		if (field === "dlp_product") return esc(doc.dlp_product || "—") + (doc.dlp_item_count > 1 ? `<small> · ${doc.dlp_item_count} ${esc(tr("项"))}</small>` : "");
		if (field === "dlp_quantity") return doc.dlp_multiple_units ? esc(tr("多单位明细")) : doc.dlp_quantity == null ? "—" : `${esc(doc.dlp_quantity)} ${esc(doc.dlp_uom)}`;
		if (field === "dlp_rate") return doc.dlp_item_count > 1 ? esc(tr("多明细")) : money(doc.dlp_rate, doc.currency);
		if (field === "dlp_actions") return `<button type="button" class="btn btn-default btn-xs dlp-sales-detail" data-name="${esc(doc.name)}">${esc(tr("查看明细"))}</button>`;
		if (field === "dlp_receipts") return (doc.dlp_finance?.receipts || []).map(payment => `${esc(payment.name)} · ${esc(tr(payment.docstatus === 1 ? "已提交" : payment.docstatus === 2 ? "已取消" : "草稿"))}<br>${money(payment.allocated_amount, payment.currency)}`).join("<br>") || esc(tr("未找到可见的关联收款记录"));
		if (field === "dlp_sync") return doc.dlp_finance ? esc(tr(syncWarning(doc) || "—")) : esc(tr("正在核验订单…"));
		if (field === "dlp_last_confirmation") { const audit = doc.dlp_finance?.last_confirmation, warning = syncWarning(doc); return `${audit ? `${esc(audit.user)}<br>${esc(audit.creation)}` : "—"}${warning ? `<br><small class="text-warning">${esc(tr(warning))}</small>` : ""}`; }
	}
	function syncWarning(doc) {
		if ((doc.dlp_finance?.process_status || doc.custom_process_status) === "Deposit Confirmation Processing") return "CRM/MES 同步中";
		return doc.dlp_finance?.last_confirmation?.status === "Failed" ? "CRM/MES 同步失败" : "";
	}
	function transformQuery(args, controller) {
		if (controller.salesView === "finance" && ["approved", "rejected"].includes(controller.quick.financial_status) && controller.allowed.has("custom_process_status")) switchView(controller, "all");
		if (controller.salesView === "mine" && controller.allowed.has("owner")) args.filters.push(["Sales Order", "owner", "=", root.frappe.session.user]);
		if (controller.salesView === "finance") {
			if (!controller.allowed.has("custom_process_status")) { args.filters.push(["Sales Order", "name", "in", []]); controller.$salesNotice?.text(t("无权查看财务审核状态，请联系管理员。")); }
			else args.filters.push(["Sales Order", "custom_process_status", "in", financialGroups.pending], ["Sales Order", "docstatus", "=", 1], ["Sales Order", "status", "not in", ["Closed", "Cancelled", "Stopped", "On Hold"]]);
		}
		if (controller.quick.financial_status && financialGroups[controller.quick.financial_status]) {
			args.filters.push(controller.allowed.has("custom_process_status") ? ["Sales Order", "custom_process_status", "in", financialGroups[controller.quick.financial_status]] : ["Sales Order", "name", "in", []]);
		}
		if (controller.quick.product && controller.allowed.has("items")) args.filters.push(["Sales Order Item", "item_code", "=", controller.quick.product]);
		return args;
	}
	function switchView(controller, view) {
		controller.salesView = view;
		controller.$salesViewbar?.find("[data-sales-view]").attr("aria-pressed", "false");
		controller.$salesViewbar?.find(`[data-sales-view="${view}"]`).attr("aria-pressed", "true");
		controller.list.clear_checked_items?.(); controller.salesExpanded?.clear(); invalidateReleaseSelection(controller);
		controller.setPage?.(0);
		controller.$salesNotice?.text(t(view === "finance" ? "收款记录未录入不代表未收款；定金由财务按线下约定判断。" : "展开产品行或查看明细；左右滚动查看全部字段。"));
	}
	function invalidateExpandedDetails(controller) {
		for (const [name, detail] of controller.salesExpanded || []) { const row = controller.list.data.find(item => item.name === name); if (!row || (row.modified && row.modified !== detail.header.modified)) controller.salesExpanded.delete(name); }
	}
	async function onRows(controller) {
		if (!salesListActive(controller)) return;
		invalidateExpandedDetails(controller);
		const names = controller.list.data.map(row => row.name), generation = controller.requestId;
		try {
			const details = await call("get_sales_display_details", { sales_orders: names });
			if (generation !== controller.requestId || !salesListActive(controller)) return;
			controller.list.data.forEach(row => Object.assign(row, details[row.name] || {}));
			if (controller.salesView === "finance" || controller.preferences?.columns.some(field => ["dlp_receipts", "dlp_sync", "dlp_last_confirmation"].includes(field))) {
				const finance = [];
				for (let start = 0; start < names.length; start += 100) { const response = await root.frappe.call({ method: "crm_integration.crm_integration.finance_release.get_finance_release_review", args: { sales_orders: names.slice(start, start + 100) } }); if (generation !== controller.requestId || !salesListActive(controller)) return; finance.push(...response.message.orders); }
				controller.list.data.forEach(row => { row.dlp_finance = finance.find(item => item.name === row.name); });
			}
			controller.list.render_list(); controller.list.set_rows_as_checked?.(); controller.list.on_row_checked?.();
		} catch (_) { if (generation === controller.requestId && salesListActive(controller)) controller.$salesNotice?.text(t("补充信息读取失败；可打开原生订单核对。")); }
	}
	function migratePreferences(value, allowed) {
		if (!value?.columns || value.version === 3) return value;
		const columns = value.columns.filter(field => field !== "status");
		if (allowed.has("custom_process_status") && !columns.includes("custom_process_status")) columns.splice(Math.max(columns.indexOf("customer_name") + 1, 1), 0, "custom_process_status");
		return { ...value, columns };
	}
	function onColumnsChange(controller) {
		if (!salesListActive(controller) || !controller.preferences.columns.some(field => ["dlp_receipts", "dlp_sync", "dlp_last_confirmation"].includes(field)) || !controller.list.data.some(row => !row.dlp_finance)) return;
		const key = JSON.stringify([controller.requestId, controller.list.data.map(row => [row.name, row.modified])]);
		if (controller.salesColumnRead?.key === key) return controller.salesColumnRead.promise;
		const read = { key, promise: null };
		read.promise = onRows(controller).finally(() => { if (controller.salesColumnRead === read) controller.salesColumnRead = null; });
		controller.salesColumnRead = read;
		return read.promise;
	}
	function salesListActive(controller) {
		const route = controller.root.frappe.get_route?.() || [];
		return controller.salesRouteActive !== false && route[0] === "List" && route[1] === "Sales Order" && (!route[2] || route[2] === "List");
	}
	function releaseSelectionKey(controller) {
		return JSON.stringify([controller.requestId, (controller.list.get_checked_items?.() || []).map(row => typeof row === "string" ? row : [row.name, row.modified, row.status, row.custom_process_status])]);
	}
	function invalidateReleaseSelection(controller, label = t("正在刷新订单，请稍候…")) {
		controller.salesReleaseKey = null;
		controller.salesReleaseVersion = (controller.salesReleaseVersion || 0) + 1;
		controller.salesReleaseNames = [];
		controller.$salesViewbar?.find(".dlp-sales-selected").text(label);
		controller.$salesViewbar?.find(".dlp-sales-release").text(t("允许生产（{0}单）", [0])).prop("disabled", true);
	}
	function releaseSelectionCurrent(controller, version, key = controller.salesReleaseKey) {
		return salesListActive(controller) && controller.salesReleaseVersion === version && key === controller.salesReleaseKey && key === releaseSelectionKey(controller);
	}
	function updateReleaseSelection(controller, force = false) {
		if (!controller?.$salesViewbar) return Promise.resolve();
		if (controller.allowed && !controller.allowed.has("custom_process_status")) { invalidateReleaseSelection(controller, t("无权查看财务审核状态，请联系管理员。")); return Promise.resolve(); }
		if (!salesListActive(controller)) { invalidateReleaseSelection(controller, t("未选择订单")); return Promise.resolve(); }
		const selected = controller.list.get_checked_items?.() || [];
		const names = [...new Set(selected.map(row => typeof row === "string" ? row : row.name).filter(Boolean))];
		const key = releaseSelectionKey(controller);
		if (!force && controller.salesReleaseKey === key) return controller.salesReleasePromise || Promise.resolve();
		controller.salesReleaseKey = key;
		const version = controller.salesReleaseVersion = (controller.salesReleaseVersion || 0) + 1;
		controller.salesReleaseNames = [];
		const bar = controller.$salesViewbar;
		const paint = (label, eligible = []) => {
			controller.salesReleaseNames = eligible;
			bar.find(".dlp-sales-selected").text(label);
			bar.find(".dlp-sales-release").text(t("允许生产（{0}单）", [eligible.length])).prop("disabled", !eligible.length);
			controller.updateTableViewport?.();
		};
		paint(!names.length ? t("未选择订单") : names.length > 100 ? t("已选择：{0}；每次最多核验 100 单", [names.length]) : t("已选择：{0}；正在核验…", [names.length]));
		if (!names.length || names.length > 100) return Promise.resolve();
		const current = () => releaseSelectionCurrent(controller, version, key);
		const promise = (async () => {
			try {
				const response = await controller.root.frappe.call({ method: "crm_integration.crm_integration.finance_release.get_finance_release_review", args: { sales_orders: names } });
				if (!current()) return;
				const permitted = new Set((response.message?.orders || []).filter(row => row.can_release === true).map(row => row.name));
				const eligible = names.filter(name => permitted.has(name));
				paint(t("已选择：{0} · 可放行：{1} · 不可放行：{2}", [names.length, eligible.length, names.length - eligible.length]), eligible);
			} catch (_) {
				if (current()) paint(t("放行资格核验失败，请重新选择或刷新后重试。"));
			}
		})();
		controller.salesReleasePromise = promise;
		return promise;
	}
	function mountControls(controller) {
		controller.salesView = "finance"; controller.salesExpanded = new Map();
		if (!root.$ || !controller.$toolbar) return;
		dismissAutomaticOnboarding(controller);
		const bar = root.$(`<div class="dlp-sales-viewbar"><div class="dlp-sales-tabs">${[["all", "全部订单"], ["mine", "我的订单"], ["finance", "Pending financial approval"]].map(([value, label]) => `<button class="btn btn-default btn-sm" type="button" data-sales-view="${value}" aria-pressed="${value === "finance"}">${esc(t(label))}</button>`).join("")}</div><div class="dlp-sales-release-action"><span class="dlp-sales-selected" role="status">${esc(t("未选择订单"))}</span><button type="button" class="btn btn-primary dlp-sales-release" disabled>${esc(t("允许生产（{0}单）", [0]))}</button></div></div>`).insertBefore(controller.list.$frappe_list);
		controller.$salesViewbar = bar;
		controller.$salesNotice = root.$(`<p class="dlp-sales-notice text-muted">${esc(t("收款记录未录入不代表未收款；定金由财务按线下约定判断。"))}</p>`).insertAfter(bar);
		const updateSelection = () => updateReleaseSelection(controller);
		controller.updateSalesSelection = updateSelection;
		bar.find(".dlp-sales-release").on("click", async () => {
			const pending = updateReleaseSelection(controller, true), version = controller.salesReleaseVersion;
			await pending;
			if (!releaseSelectionCurrent(controller, version)) return;
			const names = [...controller.salesReleaseNames];
			if (!names.length) return;
			if (!root.CRMFinanceRelease) await root.frappe.require("/assets/crm_integration/js/finance_release.js");
			if (!releaseSelectionCurrent(controller, version)) return;
			root.CRMFinanceRelease.open(names, () => { controller.list.clear_checked_items?.(); updateSelection(); controller.refresh(); });
		});
		bar.find("[data-sales-view]").on("click", async event => {
			switchView(controller, event.currentTarget.dataset.salesView);
			if (controller.salesView === "finance") { controller.resetting = true; controller.quick.financial_status = ""; await controller.controls.financial_status?.set_value(""); controller.resetting = false; }
			controller.refresh();
			controller.$salesNotice.text(t(controller.salesView === "finance" ? "收款记录未录入不代表未收款；定金由财务按线下约定判断。" : "展开产品行或查看明细；左右滚动查看全部字段。"));
		});
		const select = root.$(`<select class="form-control input-xs dlp-sales-preset" aria-label="${esc(t("字段分组"))}">${[["main", "主要字段"], ["middle", "订单资料"], ["tail", "来源与进度"]].map(([value, label]) => `<option value="${value}">${esc(t(label))}</option>`).join("")}</select>`).prependTo(controller.$toolbar);
		select.on("change", event => controller.setColumns(presets[event.target.value]));
		controller.list.$result?.on("click.dlpSalesDetails", ".dlp-sales-detail,.dlp-sales-expand", async event => {
			event.preventDefault(); event.stopPropagation(); const button = root.$(event.currentTarget), name = button.attr("data-name");
			if (button.hasClass("dlp-sales-expand") && controller.salesExpanded.has(name)) { controller.salesExpanded.delete(name); controller.list.render_list(); controller.list.set_rows_as_checked?.(); return; }
			button.prop("disabled", true);
			try { const detail = await call("get_sales_order_details", { sales_order: name }); if (button.hasClass("dlp-sales-expand")) { controller.salesExpanded.set(name, detail); controller.list.render_list(); controller.list.set_rows_as_checked?.(); } else {
				const dialog = new root.frappe.ui.Dialog({ title: `${t("订单详情")} · ${name}`, size: "extra-large", fields: [{ fieldname: "details", fieldtype: "HTML", options: detailsHTML(detail) }] }); dialog.$wrapper.addClass("dlp-sales-detail-dialog"); dialog.show(); dialog.$wrapper.find(".dlp-sales-all-items").on("click", e => { const expanded = e.currentTarget.getAttribute("aria-expanded") !== "true"; e.currentTarget.setAttribute("aria-expanded", String(expanded)); e.currentTarget.textContent = t(expanded ? "收起额外字段" : "显示全部明细字段"); dialog.$wrapper.find(".dlp-sales-items").toggleClass("dlp-sales-items-overview", !expanded); });
			} } finally { button.prop("disabled", false); }
		});
		fitViewport(controller, true);
	}
	function fitViewport(controller, active) {
		if (!controller) return;
		return engine.fitViewport(controller, { active, root: controller.root,
			scrollElement: controller.list.$result?.parent(".result-container")?.[0], layoutTailElement: controller.list.$frappe_list?.[0],
			property: "--dlp-sales-result-max-height", headerSelector: ".dlp-po-grid-header", rowSelector: ".dlp-po-grid-row",
			observeTargets: [controller.$filters?.[0]?.parentElement, controller.$toolbar?.[0], controller.$salesViewbar?.[0], controller.$salesNotice?.[0], controller.$summary?.[0], controller.$paging?.[0], controller.list.page.wrapper?.find?.(".page-head")?.[0]],
		});
	}
	function dismissAutomaticOnboarding(controller) {
		return grid.dismissAutomaticOnboarding(controller, root);
	}
	const grid = engine.create({ doctype: "Sales Order", controllerKey: "dlpSalesOrderGrid", routeClass: "dlp-sales-order-grid-active", columns: COLUMNS, freezeUntil: "name", defaultColumns: presets.finance, preferenceVersion: 3, migratePreferences, keepColumnHeader: true, onSelectionChange: updateReleaseSelection,
		computedFields: ["dlp_product", "dlp_quantity", "dlp_rate", "dlp_sales_person", "dlp_receipts", "dlp_sync", "dlp_last_confirmation", "dlp_actions"], extraFields: ["customer", "custom_crm_order_no", "party_account_currency"],
		numbers: ["grand_total", "advance_paid", "per_delivered", "per_billed"], dates: ["transaction_date", "delivery_date"], moneySummary: true, quickFields: ["company", "customer"], searchFields: ["name", "custom_crm_order_no", "customer_name", "custom_odt"], optionLabels: { financial_status: financialLabels, custom_process_status: statusLabels, status: orderStatusLabels },
		controls: [{ fieldname: "search", fieldtype: "Data", label: "订单号 / 客户 / ODT" }, { fieldname: "customer", fieldtype: "Link", options: "Customer", label: "客户" }, { fieldname: "financial_status", permission_field: "custom_process_status", fieldtype: "Select", label: "财务审核状态", emptyLabel: "全部审核状态", options: "\npending\napproved\nrejected" }, { fieldname: "from_date", permission_field: "transaction_date", fieldtype: "Date", label: "开始日期" }, { fieldname: "to_date", permission_field: "transaction_date", fieldtype: "Date", label: "结束日期" }, { fieldname: "product", permission_field: "items", fieldtype: "Link", options: "Item", label: "品目编码" }, { fieldname: "company", fieldtype: "Link", options: "Company", label: "公司" }],
		exportOptions: args => ({ columnTransforms: Object.fromEntries(args.fields.flatMap((field, index) => field === "custom_process_status" ? [[index + 2, { header: t("财务审核状态"), value: value => t(financialLabel(value)) }]] : [])) }),
		searchConflictMessage: "现有 OR 筛选已保留；清除后可使用订单 / 客户搜索。",
		transformQuery, onRows, onColumnsChange, mountControls, renderValue, onRequestStart: invalidateReleaseSelection,
		onRouteChange: (controller, active) => { if (controller) controller.salesRouteActive = active; fitViewport(controller, active); if (!active && controller) { invalidateReleaseSelection(controller, t("未选择订单")); controller.stopInitialOnboarding?.(); } else controller?.updateSalesSelection?.(); },
		renderLink: (controller, doc, value) => `<button type="button" class="dlp-sales-name dlp-sales-detail" data-name="${esc(doc.name)}">${value}</button>`,
		renderSequence: (controller, doc, sequence) => `<button class="dlp-sales-expand" type="button" data-name="${esc(doc.name)}" aria-expanded="${controller.salesExpanded?.has(doc.name) || false}" aria-label="${esc(t("展开产品明细"))}">${controller.salesExpanded?.has(doc.name) ? "⌄" : "›"} ${sequence}</button>`,
		rowExtra: (controller, doc) => controller.salesExpanded?.has(doc.name) ? `<section class="dlp-sales-expanded"><strong>${esc(t("订单产品明细"))}</strong>${itemTable(controller.salesExpanded.get(doc.name))}</section>` : "",
		afterRender: controller => { controller.updateSalesSelection?.(); controller.updateTableViewport?.(); },
	});
	return { ...grid, COLUMNS, presets, itemTable, detailsHTML, transformQuery, financialLabel, statusLabels, orderStatusLabels, updateReleaseSelection, invalidateExpandedDetails, dismissAutomaticOnboarding, fitViewport };
});
