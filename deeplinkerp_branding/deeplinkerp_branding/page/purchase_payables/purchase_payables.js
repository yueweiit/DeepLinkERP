(function (root) {
	"use strict";
	const route = "purchase-payables",
		t = root.__ || ((text) => text);
	const columns = [
		["posting_date", "应付日期", 120],
		["name", "应付单号", 180],
		["supplier", "供应商", 160],
		["company", "公司", 150],
		["grand_total", "应付单整单金额", 160],
		["outstanding", "整单未付余额", 155],
		["status", "应付状态", 180],
		["orders", "采购订单", 200],
		["receipts", "采购入库", 200],
		["action", "办理", 240],
	].map(([fieldname, label, width]) => ({ fieldname, label, width }));
	const esc = root.DeepLinkERPCompactList.create({
		doctype: "Purchase Invoice",
		columns,
	}).escapeHTML;
	const money = (value, currency) =>
		value == null
			? "—"
			: `${esc(
					Number(value).toLocaleString(undefined, {
						minimumFractionDigits: 2,
						maximumFractionDigits: 2,
					})
			  )} ${esc(currency || "")}`;
	const api = (root.DeepLinkERPPurchasePayables = { controller: null });
	root.frappe.pages[route].on_page_load = (wrapper) => {
		const page = root.frappe.ui.make_app_page({
			parent: wrapper,
			title: t("采购应付"),
			single_column: true,
		});
		const actions = root.DeepLinkERPPurchasePayments;
		const provider = {
			columns,
			defaultColumns: columns.map((col) => col.fieldname),
			freezeUntil: "supplier",
			sortFields: [],
			summary: () => "",
			request: (c) => ({
				method: "deeplinkerp_branding.services.purchase_payment_service.get_purchase_payables",
				args: { ...c.quick, start: c.page * c.pageSize, page_length: c.pageSize },
			}),
			renderValue: (field, doc) => {
				if (field === "name")
					return actions.nativeAction("Purchase Invoice", doc.name, doc.name);
				if (field === "grand_total") return money(doc.grand_total, doc.invoice_currency);
				if (field === "outstanding") return money(doc.outstanding, doc.currency);
				if (field === "status")
					return `<div>${esc(
						t(
							doc.docstatus === 0
								? "草稿"
								: doc.docstatus === 2
								? "已取消"
								: doc.is_return
								? "退货应付"
								: doc.status
						)
					)}${
						doc.shared
							? `<div class="text-warning" title="${esc(
									t("共享 / 混合应付整单")
							  )}">${esc(t("共享 / 混合"))}</div>`
							: ""
					}</div>`;
				if (field === "orders" || field === "receipts")
					return doc[field]
						.map((name) =>
							actions.nativeAction(
								field === "orders" ? "Purchase Order" : "Purchase Receipt",
								name,
								name
							)
						)
						.join(" ");
				if (field === "action")
					return `${actions.nativeAction("Purchase Invoice", doc.name, "查看应付单")}${
						doc.can_pay
							? ` <button type="button" class="btn btn-default btn-xs dlp-payable-pay" data-name="${esc(
									doc.name
							  )}">${esc(t("付款 / 继续付款"))}</button>`
							: ""
					}`;
			},
			mountControls: (c) => {
				root.$(
					`<button type="button" class="btn btn-default btn-sm">${esc(
						t("清空筛选")
					)}</button>`
				)
					.appendTo(c.$toolbar)
					.on("click.dlpPayable", () => c.clearQuickFilters());
				c.list.$result.on("click.dlpPayable", ".dlp-payable-pay", (event) => {
					const row = c.providerRows.find(
						(doc) => doc.name === event.currentTarget.dataset.name
					);
					if (row?.can_pay) actions.pay(row.source_type, row.source_name, row.name);
				});
			},
			onPayload: (c) => {
				c.$providerNotice?.remove();
				c.$providerNotice = root
					.$('<p class="text-muted dlp-po-provider-notice"></p>')
					.text(t(c.providerPayload.notice || ""))
					.insertAfter(c.$filters);
			},
		};
		const grid = root.DeepLinkERPCompactList.create({
			doctype: "Purchase Invoice",
			pageRoute: route,
			dismissInitialOnboarding: true,
			routeClass: "dlp-purchase-payable-grid-active",
			columns,
			provider,
			renderLink: (_c, _doc, value) => value,
			emptyLabel: "没有符合条件的关联采购应付单",
			pageFieldMap: {
				orders: "items",
				receipts: "items",
				from_date: "posting_date",
				to_date: "posting_date",
			},
			dates: ["posting_date"],
			controls: [
				["search", "Data", null, "应付单号 / 供应商"],
				["company", "Link", "Company", "公司"],
				["supplier", "Link", "Supplier", "供应商"],
				["from_date", "Date", null, "应付开始日期"],
				["to_date", "Date", null, "应付结束日期"],
			].map(([fieldname, fieldtype, options, label]) => ({
				fieldname,
				fieldtype,
				options,
				label,
			})),
		});
		const ready = root.frappe.model
			.with_doctype("Purchase Invoice")
			.then(() => (api.controller = grid.mountPage(page, root)));
		wrapper.dlpLoad = async () => {
			const c = await ready;
			return c.refresh();
		};
		ready.catch(() =>
			page.main.append(
				`<p class="text-danger">${esc(t("应付元数据读取失败，请刷新或核对权限。"))}</p>`
			)
		);
		page.set_secondary_action(t("刷新"), () => wrapper.dlpLoad());
	};
	root.frappe.pages[route].on_page_show = (wrapper) => wrapper.dlpLoad?.();
})(globalThis);
