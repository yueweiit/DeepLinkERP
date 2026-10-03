(function (root) {
 const engine = typeof module === "object" && module.exports ? require("./compact_list.js") : root.DeepLinkERPCompactList;
	const COLUMNS = [
		["transaction_date", "订单日期", 96], ["name", "采购订单号", 166],
		["supplier_name", "供应商名称", 205], ["status", "订单状态", 120],
		["schedule_date", "需求日期", 96], ["company", "公司", 100],
		["currency", "币种", 56], ["grand_total", "订单金额", 140],
		["advance_paid", "已预付", 140], ["advance_payment_status", "预付款状态", 94],
		["per_received", "已收货%", 70], ["per_billed", "已开票%", 70],
		["project", "项目", 96], ["owner", "创建人", 96],
	].map(([fieldname, label, width]) => ({ fieldname, label, width }));

 const grid = engine.create({ doctype: "Purchase Order", columns: COLUMNS, controllerKey: "dlpPurchaseOrderGrid", routeClass: "dlp-purchase-order-grid-active", freezeUntil: "supplier_name", moneySummary: true, numbers: ["grand_total", "advance_paid", "per_received", "per_billed"], dates: ["transaction_date", "schedule_date"], quickFields: ["company", "status", "advance_payment_status"], searchFields: ["name", "supplier_name"], extraFields: ["supplier", "party_account_currency"], controls: [
 {fieldname:"search",fieldtype:"Data",label:"采购订单号 / 供应商名称"},
 {fieldname:"from_date",fieldtype:"Date",label:"订单开始日期",permission_field:"transaction_date"},
 {fieldname:"to_date",fieldtype:"Date",label:"订单结束日期",permission_field:"transaction_date"},
 {fieldname:"company",fieldtype:"Link",options:"Company",label:"公司"},
 {fieldname:"status",fieldtype:"Select",label:"订单状态"},
 {fieldname:"advance_payment_status",fieldtype:"Select",label:"预付款状态"}
 ]});
 if (typeof module === "object" && module.exports) module.exports = grid;
 root.DeepLinkERPPurchaseOrderGrid = grid;
 grid.install(root);
})(typeof globalThis !== "undefined" ? globalThis : this);
