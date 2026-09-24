import frappe
from frappe import _
from frappe.utils import flt

from china_finance.services.purchase_reconciliation import get_purchase_invoice_payment_summary
from china_finance.services.purchase_payables import get_receipt_payment_summary


DISPLAY_STATUS_NOT_INVOICED = "未生成应付"


def execute(filters=None):
	filters = frappe._dict(filters or {})
	conditions = [
		"pr.company=%(company)s",
		"pr.posting_date BETWEEN %(from_date)s AND %(to_date)s",
		"pr.docstatus=1",
	]
	if filters.get("supplier"):
		conditions.append("pr.supplier=%(supplier)s")
	receipts = frappe.db.sql(
		f"""
		SELECT pr.name AS purchase_receipt, pr.posting_date, pr.supplier, pr.company
		FROM `tabPurchase Receipt` pr
		WHERE {' AND '.join(conditions)}
		ORDER BY pr.posting_date, pr.name
		""",
		filters,
		as_dict=True,
	)

	data = []
	for receipt in receipts:
		summary = get_receipt_payment_summary(receipt.purchase_receipt)
		status = summary["payment_status"]
		if not summary["purchase_invoices"]:
			status = DISPLAY_STATUS_NOT_INVOICED
		if filters.get("payment_status") and status != filters.payment_status:
			continue

		purchase_orders = frappe.get_all(
			"Purchase Receipt Item",
			filters={"parent": receipt.purchase_receipt},
			pluck="purchase_order",
			limit_page_length=0,
		)
		payment_entries = []
		for invoice_name in summary["purchase_invoices"]:
			payment_entries.extend(
				get_purchase_invoice_payment_summary(invoice_name)["payment_entries"].split(", ")
			)
		data.append(
			{
				"posting_date": receipt.posting_date,
				"purchase_receipt": receipt.purchase_receipt,
				"supplier": receipt.supplier,
				"purchase_orders": ", ".join(dict.fromkeys(filter(None, purchase_orders))),
				"purchase_invoices": ", ".join(summary["purchase_invoices"]),
				"payment_entries": ", ".join(dict.fromkeys(filter(None, payment_entries))),
				"invoice_amount": summary["invoice_amount"],
				"outstanding_amount": summary["outstanding_amount"],
				"payment_status": status,
			}
		)
	return get_columns(), data, None, None, get_report_summary(data), 1


def get_columns():
	return [
		{"label": _("日期"), "fieldname": "posting_date", "fieldtype": "Date", "width": 100},
		{"label": _("采购收货单"), "fieldname": "purchase_receipt", "fieldtype": "Link", "options": "Purchase Receipt", "width": 170},
		{"label": _("供应商"), "fieldname": "supplier", "fieldtype": "Link", "options": "Supplier", "width": 160},
		{"label": _("采购订单"), "fieldname": "purchase_orders", "fieldtype": "Data", "width": 180},
		{"label": _("采购应付单"), "fieldname": "purchase_invoices", "fieldtype": "Data", "width": 180},
		{"label": _("付款单"), "fieldname": "payment_entries", "fieldtype": "Data", "width": 180},
		{"label": _("应付金额"), "fieldname": "invoice_amount", "fieldtype": "Currency", "width": 120},
		{"label": _("未付金额"), "fieldname": "outstanding_amount", "fieldtype": "Currency", "width": 120},
		{"label": _("付款状态"), "fieldname": "payment_status", "fieldtype": "Data", "width": 100},
	]


def get_report_summary(data):
	return [
		{"label": _("收货单数"), "value": len(data), "datatype": "Int"},
		{
			"label": _("未付金额"),
			"value": sum(flt(row["outstanding_amount"]) for row in data),
			"datatype": "Currency",
			"indicator": "orange",
		},
	]
