import frappe
from frappe import _

from china_finance.services.currency_context import currency_report_result


def execute(filters=None):
	filters = frappe._dict(filters or {})
	conditions = ["si.company=%(company)s", "si.posting_date BETWEEN %(from_date)s AND %(to_date)s", "si.docstatus=1"]
	if filters.get("customer"):
		conditions.append("si.customer=%(customer)s")
	data = frappe.db.sql(
		f"""
		SELECT si.posting_date, si.customer, si.name AS sales_invoice,
			items.sales_orders, items.delivery_notes, tax.tax_invoices, payments.payment_entries,
			si.currency, si.party_account_currency, si.grand_total, si.outstanding_amount,
			CASE WHEN si.outstanding_amount=0 THEN 'Paid' WHEN si.outstanding_amount<si.grand_total THEN 'Partly Paid' ELSE 'Unpaid' END AS payment_status
		FROM `tabSales Invoice` si
		LEFT JOIN (
			SELECT parent, GROUP_CONCAT(DISTINCT sales_order ORDER BY sales_order SEPARATOR ', ') AS sales_orders,
				GROUP_CONCAT(DISTINCT delivery_note ORDER BY delivery_note SEPARATOR ', ') AS delivery_notes
			FROM `tabSales Invoice Item` GROUP BY parent
		) items ON items.parent=si.name
		LEFT JOIN (
			SELECT a.reference_name, GROUP_CONCAT(DISTINCT a.parent ORDER BY a.parent SEPARATOR ', ') AS tax_invoices
			FROM `tabChina Tax Invoice Allocation` a
			INNER JOIN `tabChina Tax Invoice` ti ON ti.name=a.parent AND ti.docstatus=1
			WHERE a.reference_doctype='Sales Invoice' GROUP BY a.reference_name
		) tax ON tax.reference_name=si.name
		LEFT JOIN (
			SELECT per.reference_name, GROUP_CONCAT(DISTINCT per.parent ORDER BY per.parent SEPARATOR ', ') AS payment_entries
			FROM `tabPayment Entry Reference` per
			INNER JOIN `tabPayment Entry` pe ON pe.name=per.parent AND pe.docstatus=1
			WHERE per.reference_doctype='Sales Invoice' GROUP BY per.reference_name
		) payments ON payments.reference_name=si.name
		WHERE {' AND '.join(conditions)}
		ORDER BY si.posting_date, si.name
		""",
		filters,
		as_dict=True,
	)
	return currency_report_result(get_columns(), data, filters.company)


def get_columns():
	return [
		{"label": _("日期"), "fieldname": "posting_date", "fieldtype": "Date", "width": 100},
		{"label": _("客户"), "fieldname": "customer", "fieldtype": "Link", "options": "Customer", "width": 180},
		{"label": _("销售订单"), "fieldname": "sales_orders", "fieldtype": "Data", "width": 180},
		{"label": _("出库单"), "fieldname": "delivery_notes", "fieldtype": "Data", "width": 180},
		{"label": _("应收发票"), "fieldname": "sales_invoice", "fieldtype": "Link", "options": "Sales Invoice", "width": 160},
		{"label": _("税务发票"), "fieldname": "tax_invoices", "fieldtype": "Data", "width": 180},
		{"label": _("收款单"), "fieldname": "payment_entries", "fieldtype": "Data", "width": 180},
		{"label": _("发票金额"), "fieldname": "grand_total", "fieldtype": "Currency", "options": "currency", "width": 120},
		{"label": _("未收金额"), "fieldname": "outstanding_amount", "fieldtype": "Currency", "options": "party_account_currency", "width": 120},
		{"label": _("回款状态"), "fieldname": "payment_status", "fieldtype": "Data", "width": 100},
	]

