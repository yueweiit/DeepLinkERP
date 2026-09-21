import frappe

from china_finance.china_finance.report.china_purchase_reconciliation.china_purchase_reconciliation import (
	execute as execute_purchase_reconciliation,
)


def execute(filters=None):
	filters = frappe._dict(filters or {})
	filters.view_mode = "Purchase Order"
	return execute_purchase_reconciliation(filters)
