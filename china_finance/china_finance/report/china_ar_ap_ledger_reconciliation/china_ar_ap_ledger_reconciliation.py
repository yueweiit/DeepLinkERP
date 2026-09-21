import frappe
from frappe import _

from china_finance.services.currency_context import bind_report_currency

from china_finance.services.ledger_reconciliation import get_ar_ap_ledger_rows


def execute(filters=None):
	filters = frappe._dict(filters or {})
	data = get_ar_ap_ledger_rows(
		filters.company, filters.to_date, filters.account, filters.party_type, filters.party
	)
	if filters.reconciliation_status:
		data = [row for row in data if row.reconciliation_status == filters.reconciliation_status]
	return bind_report_currency(get_columns(), data, filters.company)


def get_columns():
	return [
		{"label": _("科目"), "fieldname": "account", "fieldtype": "Link", "options": "Account", "width": 180},
		{"label": _("单据类型"), "fieldname": "voucher_type", "fieldtype": "Link", "options": "DocType", "width": 130},
		{"label": _("单据"), "fieldname": "voucher_no", "fieldtype": "Dynamic Link", "options": "voucher_type", "width": 170},
		{"label": _("往来类型"), "fieldname": "party_type", "fieldtype": "Link", "options": "DocType", "width": 100},
		{"label": _("往来单位"), "fieldname": "party", "fieldtype": "Dynamic Link", "options": "party_type", "width": 150},
		{"label": _("总账余额"), "fieldname": "gl_balance", "fieldtype": "Currency", "options": "currency", "width": 120},
		{"label": _("付款台账余额"), "fieldname": "pl_balance", "fieldtype": "Currency", "options": "currency", "width": 130},
		{"label": _("差额"), "fieldname": "difference", "fieldtype": "Currency", "options": "currency", "width": 120},
		{"label": _("状态"), "fieldname": "reconciliation_status", "fieldtype": "Data", "width": 90},
	]
