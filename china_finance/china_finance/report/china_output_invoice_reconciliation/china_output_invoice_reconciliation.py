import frappe
from frappe import _

from china_finance.services.currency_context import currency_report_result

from china_finance.services.tax_reconciliation import evaluate_output_invoice_rows


def execute(filters=None):
	filters = frappe._dict(filters or {})
	data = evaluate_output_invoice_rows(filters.company, filters.from_date, filters.to_date)
	if filters.get("customer"):
		data = [row for row in data if row.customer == filters.customer]
	if filters.get("reconciliation_status"):
		data = [row for row in data if row.reconciliation_status == filters.reconciliation_status]
	return currency_report_result(get_columns(), data, filters.company)


def get_columns():
	return [
		{"label": _("日期"), "fieldname": "posting_date", "fieldtype": "Date", "width": 95},
		{"label": _("销售发票"), "fieldname": "sales_invoice", "fieldtype": "Link", "options": "Sales Invoice", "width": 160},
		{"label": _("客户"), "fieldname": "customer", "fieldtype": "Link", "options": "Customer", "width": 150},
		{"label": _("开票要求"), "fieldname": "requirement", "fieldtype": "Data", "width": 95},
		{"label": _("开票申请"), "fieldname": "requests", "fieldtype": "Data", "width": 160},
		{"label": _("申请状态"), "fieldname": "request_statuses", "fieldtype": "Data", "width": 120},
		{"label": _("税务发票"), "fieldname": "tax_invoices", "fieldtype": "Data", "width": 160},
		{"label": _("销售发票金额"), "fieldname": "grand_total", "fieldtype": "Currency", "options": "currency", "width": 120},
		{"label": _("分摊金额"), "fieldname": "allocated_gross_amount", "fieldtype": "Currency", "options": "allocation_currency", "width": 110},
		{"label": _("销项税"), "fieldname": "total_taxes_and_charges", "fieldtype": "Currency", "options": "currency", "width": 100},
		{"label": _("分摊税额"), "fieldname": "allocated_tax_amount", "fieldtype": "Currency", "options": "allocation_currency", "width": 100},
		{"label": _("应收状态"), "fieldname": "outstanding_amount", "fieldtype": "Currency", "options": "party_account_currency", "width": 110},
		{"label": _("对账状态"), "fieldname": "reconciliation_status", "fieldtype": "Data", "width": 100},
		{"label": _("异常原因"), "fieldname": "exception_reason", "fieldtype": "Data", "width": 240},
	]
