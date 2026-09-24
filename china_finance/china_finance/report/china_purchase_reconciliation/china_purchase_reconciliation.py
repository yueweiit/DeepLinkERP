import frappe
from frappe import _

from china_finance.services.currency_context import currency_report_result

from china_finance.services.purchase_reconciliation import (
	evaluate_purchase_invoice,
	get_purchase_invoice_payment_summary,
	get_purchase_order_reconciliation_rows,
)
from china_finance.services.purchase_payables import (
	PAYMENT_STATUS_CANCELLED,
	PAYMENT_STATUS_EXCEPTION,
	get_purchase_payment_status,
)


def execute(filters=None):
	filters = frappe._dict(filters or {})
	if filters.get("view_mode") == "Purchase Order":
		data = get_purchase_order_reconciliation_rows(
			filters.company, filters.from_date, filters.to_date, filters.supplier, filters.purchase_order
		)
		if any("," in (row.get(field) or "") for row in data for field in ("currency", "party_account_currency")):
			frappe.throw(_("采购订单关联了不同币种的发票，不能直接合计；请切换采购发票视图逐张核对"))
		if filters.get("reconciliation_status"):
			data = [row for row in data if row.reconciliation_status == filters.reconciliation_status]
		if filters.get("exception_only"):
			data = [
				row
				for row in data
				if row.reconciliation_status == "Blocked"
				or row.payment_status in (PAYMENT_STATUS_CANCELLED, PAYMENT_STATUS_EXCEPTION)
			]
		if filters.get("payment_status"):
			data = [row for row in data if row.payment_status == filters.payment_status]
		return currency_report_result(get_purchase_order_columns(), data, filters.company)

	conditions = [
		"pi.company=%(company)s",
		"pi.posting_date BETWEEN %(from_date)s AND %(to_date)s",
		"pi.docstatus IN (1, 2)",
	]
	if filters.get("supplier"):
		conditions.append("pi.supplier=%(supplier)s")
	if filters.get("purchase_order"):
		conditions.append(
			"EXISTS (SELECT 1 FROM `tabPurchase Invoice Item` item WHERE item.parent=pi.name AND item.purchase_order=%(purchase_order)s)"
		)
	invoices = frappe.db.sql(
		f"""
		SELECT pi.name, pi.posting_date, pi.supplier, pi.currency, pi.party_account_currency,
			pi.grand_total, pi.outstanding_amount, pi.docstatus, pi.is_return
		FROM `tabPurchase Invoice` pi
		WHERE {' AND '.join(conditions)}
		ORDER BY posting_date, name
		""",
		filters,
		as_dict=True,
	)
	data = []
	for invoice in invoices:
		result = evaluate_purchase_invoice(invoice.name)
		if filters.get("reconciliation_status") and result["reconciliation_status"] != filters.reconciliation_status:
			continue
		payment_summary = get_purchase_invoice_payment_summary(invoice.name)
		result.update(
			{
				"posting_date": invoice.posting_date,
				"currency": invoice.currency,
				"party_account_currency": invoice.party_account_currency,
				"supplier": invoice.supplier,
				"grand_total": invoice.grand_total,
				"outstanding_amount": invoice.outstanding_amount,
				"payment_status": get_purchase_payment_status(
					invoice.grand_total,
					invoice.grand_total - payment_summary["paid_amount"],
					invoice.outstanding_amount,
					invoice.docstatus,
					invoice.is_return,
				),
				**payment_summary,
			}
		)
		if filters.get("exception_only") and result["reconciliation_status"] != "Blocked" and result["payment_status"] not in (
			PAYMENT_STATUS_CANCELLED,
			PAYMENT_STATUS_EXCEPTION,
		):
			continue
		if filters.get("payment_status") and result["payment_status"] != filters.payment_status:
			continue
		data.append(result)
	return currency_report_result(get_purchase_invoice_columns(), data, filters.company)


def get_purchase_invoice_columns():
	return [
		{"label": _("日期"), "fieldname": "posting_date", "fieldtype": "Date", "width": 100},
		{"label": _("供应商"), "fieldname": "supplier", "fieldtype": "Link", "options": "Supplier", "width": 180},
		{"label": _("采购发票"), "fieldname": "purchase_invoice", "fieldtype": "Link", "options": "Purchase Invoice", "width": 170},
		{"label": _("采购订单"), "fieldname": "purchase_orders", "fieldtype": "Data", "width": 180},
		{"label": _("采购收货单"), "fieldname": "purchase_receipts", "fieldtype": "Data", "width": 180},
		{"label": _("进项税务发票"), "fieldname": "tax_invoices", "fieldtype": "Data", "width": 180},
		{"label": _("付款单"), "fieldname": "payment_entries", "fieldtype": "Data", "width": 180},
		{"label": _("付款状态"), "fieldname": "payment_status", "fieldtype": "Data", "width": 100},
		{"label": _("对账策略"), "fieldname": "reconciliation_policy", "fieldtype": "Data", "width": 180},
		{"label": _("齐套状态"), "fieldname": "reconciliation_status", "fieldtype": "Data", "width": 100},
		{"label": _("原因"), "fieldname": "reconciliation_reason", "fieldtype": "Data", "width": 260},
		{"label": _("订单数量"), "fieldname": "ordered_qty", "fieldtype": "Float", "width": 90},
		{"label": _("累计收货"), "fieldname": "received_qty", "fieldtype": "Float", "width": 90},
		{"label": _("累计开票"), "fieldname": "billed_qty", "fieldtype": "Float", "width": 90},
		{"label": _("待收数量"), "fieldname": "remaining_receive_qty", "fieldtype": "Float", "width": 90},
		{"label": _("待票数量"), "fieldname": "remaining_bill_qty", "fieldtype": "Float", "width": 90},
		{"label": _("订单差异"), "fieldname": "po_variance_status", "fieldtype": "Data", "width": 100},
		{"label": _("订单差异原因"), "fieldname": "po_variance_reason", "fieldtype": "Data", "width": 220},
		{"label": _("发票金额"), "fieldname": "grand_total", "fieldtype": "Currency", "options": "currency", "width": 120},
		{"label": _("已付金额"), "fieldname": "paid_amount", "fieldtype": "Currency", "options": "party_account_currency", "width": 120},
		{"label": _("未付金额"), "fieldname": "outstanding_amount", "fieldtype": "Currency", "options": "party_account_currency", "width": 120},
	]


def get_purchase_order_columns():
	return [
		{"label": _("日期"), "fieldname": "transaction_date", "fieldtype": "Date", "width": 95},
		{"label": _("采购订单"), "fieldname": "purchase_order", "fieldtype": "Link", "options": "Purchase Order", "width": 170},
		{"label": _("供应商"), "fieldname": "supplier", "fieldtype": "Link", "options": "Supplier", "width": 160},
		{"label": _("对账策略"), "fieldname": "reconciliation_policy", "fieldtype": "Data", "width": 180},
		{"label": _("订单数量"), "fieldname": "ordered_qty", "fieldtype": "Float", "width": 90},
		{"label": _("采购收货单"), "fieldname": "purchase_receipts", "fieldtype": "Data", "width": 160},
		{"label": _("累计收货"), "fieldname": "received_qty", "fieldtype": "Float", "width": 90},
		{"label": _("采购发票"), "fieldname": "purchase_invoices", "fieldtype": "Data", "width": 160},
		{"label": _("累计开票"), "fieldname": "billed_qty", "fieldtype": "Float", "width": 90},
		{"label": _("待收数量"), "fieldname": "remaining_receive_qty", "fieldtype": "Float", "width": 90},
		{"label": _("待票数量"), "fieldname": "remaining_bill_qty", "fieldtype": "Float", "width": 90},
		{"label": _("进项税票"), "fieldname": "tax_invoices", "fieldtype": "Data", "width": 160},
		{"label": _("付款单"), "fieldname": "payment_entries", "fieldtype": "Data", "width": 150},
		{"label": _("付款状态"), "fieldname": "payment_status", "fieldtype": "Data", "width": 100},
		{"label": _("发票金额"), "fieldname": "invoice_amount", "fieldtype": "Currency", "options": "currency", "width": 110},
		{"label": _("已付金额"), "fieldname": "paid_amount", "fieldtype": "Currency", "options": "party_account_currency", "width": 110},
		{"label": _("未付金额"), "fieldname": "outstanding_amount", "fieldtype": "Currency", "options": "party_account_currency", "width": 110},
		{"label": _("状态"), "fieldname": "reconciliation_status", "fieldtype": "Data", "width": 90},
		{"label": _("异常原因"), "fieldname": "reconciliation_reason", "fieldtype": "Data", "width": 200},
	]
