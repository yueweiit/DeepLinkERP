import frappe
from frappe import _

from china_finance.services.currency_context import currency_report_result


def execute(filters=None):
	filters = frappe._dict(filters or {})
	data = frappe.db.sql(
		"""
		SELECT ti.invoice_type, item.tax_rate, COALESCE(NULLIF(ti.currency, ''), company.default_currency) AS currency,
			CASE WHEN ti.direction='进项' AND ti.deduction_status!='已抵扣' THEN '待抵扣进项' ELSE ti.direction END AS tax_category,
			COUNT(DISTINCT ti.name) AS invoice_count,
			SUM(item.net_amount) AS net_amount,
			SUM(item.tax_amount) AS tax_amount,
			SUM(item.gross_amount) AS gross_amount
		FROM `tabChina Tax Invoice` ti
		INNER JOIN `tabCompany` company ON company.name=ti.company
		INNER JOIN `tabChina Tax Invoice Item` item ON item.parent=ti.name
		WHERE ti.company=%(company)s AND ti.invoice_date BETWEEN %(from_date)s AND %(to_date)s
			AND ti.docstatus=1 AND ti.invoice_status!='作废'
		GROUP BY tax_category, ti.invoice_type, item.tax_rate, COALESCE(NULLIF(ti.currency, ''), company.default_currency)
		ORDER BY tax_category DESC, item.tax_rate DESC, ti.invoice_type
		""",
		filters,
		as_dict=True,
	)
	return currency_report_result(
		get_columns(), data, filters.company, _("本报表为申报核对底稿，不直接向税务机关提交数据。")
	)


def get_columns():
	return [
		{"label": _("税务类别"), "fieldname": "tax_category", "fieldtype": "Data", "width": 110},
		{"label": _("币种"), "fieldname": "currency", "fieldtype": "Link", "options": "Currency", "width": 80},
		{"label": _("发票类型"), "fieldname": "invoice_type", "fieldtype": "Data", "width": 180},
		{"label": _("税率"), "fieldname": "tax_rate", "fieldtype": "Percent", "width": 90},
		{"label": _("发票张数"), "fieldname": "invoice_count", "fieldtype": "Int", "width": 100},
		{"label": _("不含税金额"), "fieldname": "net_amount", "fieldtype": "Currency", "options": "currency", "width": 140},
		{"label": _("税额"), "fieldname": "tax_amount", "fieldtype": "Currency", "options": "currency", "width": 130},
		{"label": _("价税合计"), "fieldname": "gross_amount", "fieldtype": "Currency", "options": "currency", "width": 140},
	]
