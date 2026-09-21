import frappe
from frappe import _

from china_finance.services.currency_context import currency_report_result


def execute(filters=None):
	filters = frappe._dict(filters or {})
	conditions = ["ti.company=%(company)s", "ti.invoice_date BETWEEN %(from_date)s AND %(to_date)s", "ti.docstatus=1"]
	if filters.get("direction"):
		conditions.append("ti.direction=%(direction)s")
	if filters.get("invoice_status"):
		conditions.append("ti.invoice_status=%(invoice_status)s")
	data = frappe.db.sql(
		f"""
		SELECT ti.name, ti.invoice_date, ti.direction, ti.invoice_type, ti.invoice_number, ti.invoice_status,
			ti.seller_name, ti.buyer_name, ti.currency, ti.net_amount, ti.tax_amount, ti.gross_amount,
			ti.verification_status, ti.deduction_status, ti.deduction_period, ti.accounting_status,
			COALESCE((
				SELECT SUM(a.allocated_gross_amount)
				FROM `tabChina Tax Invoice Allocation` a
				WHERE a.parent=ti.name AND ti.docstatus=1
			), 0) AS allocated_amount
		FROM `tabChina Tax Invoice` ti
		WHERE {' AND '.join(conditions)}
		ORDER BY ti.invoice_date, ti.invoice_number
		""",
		filters,
		as_dict=True,
	)
	for row in data:
		row.unallocated_amount = row.gross_amount - row.allocated_amount
	return currency_report_result(get_columns(), data, filters.company)


def get_columns():
	return [
		{"label": _("日期"), "fieldname": "invoice_date", "fieldtype": "Date", "width": 100},
		{"label": _("进销项"), "fieldname": "direction", "fieldtype": "Data", "width": 70},
		{"label": _("发票号码"), "fieldname": "name", "fieldtype": "Link", "options": "China Tax Invoice", "width": 180},
		{"label": _("发票类型"), "fieldname": "invoice_type", "fieldtype": "Data", "width": 140},
		{"label": _("状态"), "fieldname": "invoice_status", "fieldtype": "Data", "width": 70},
		{"label": _("销售方"), "fieldname": "seller_name", "fieldtype": "Data", "width": 180},
		{"label": _("购买方"), "fieldname": "buyer_name", "fieldtype": "Data", "width": 180},
		{"label": _("不含税金额"), "fieldname": "net_amount", "fieldtype": "Currency", "options": "currency", "width": 120},
		{"label": _("税额"), "fieldname": "tax_amount", "fieldtype": "Currency", "options": "currency", "width": 110},
		{"label": _("价税合计"), "fieldname": "gross_amount", "fieldtype": "Currency", "options": "currency", "width": 120},
		{"label": _("未分摊金额"), "fieldname": "unallocated_amount", "fieldtype": "Currency", "options": "currency", "width": 120},
		{"label": _("抵扣状态"), "fieldname": "deduction_status", "fieldtype": "Data", "width": 100},
		{"label": _("抵扣期间"), "fieldname": "deduction_period", "fieldtype": "Date", "width": 100},
		{"label": _("入账状态"), "fieldname": "accounting_status", "fieldtype": "Data", "width": 100},
	]
