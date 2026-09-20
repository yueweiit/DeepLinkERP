import unittest
from unittest.mock import patch

import frappe

from china_finance.services.statement_mapping_repair import corrected_cash_flow_classification, repair_cash_flow_mappings
from china_finance.setup.templates import classify_account_number


def account(number, name):
	return frappe._dict(account_number=number, account_name=name, account_type="Expense", root_type="Expense")


def mapping(account_name, code, **kwargs):
	return frappe._dict(account=account_name, row_code=code, **kwargs)


class TestStatementReconciliation(unittest.TestCase):
	def test_payroll_and_employee_deductions(self):
		for number, name in [("660209", "管理费用－工资"), ("660208", "管理费用－社会保险费"),
			("660229", "管理费用－公积金"), ("122102", "其他应收款-社保"), ("122103", "其他应收款-公积金")]:
			with self.subTest(number=number):
				self.assertEqual(classify_account_number(number, "Cash Flow", account(number, name)),
					("CASH_PAID_EMPLOYEES", "OTHER_OPERATING_RECEIPTS", "CASH_PAID_EMPLOYEES"))

	def test_other_expenses_and_advances_unchanged(self):
		for number, name in [("660201", "办公费"), ("122104", "备用金"), ("122101", "验证款")]:
			self.assertEqual(classify_account_number(number, "Cash Flow", account(number, name))[2], "OTHER_OPERATING_PAYMENTS")

	def test_interest_receipts_operating_but_payments_financing(self):
		self.assertEqual(classify_account_number("660302", "Cash Flow", account("660302", "利息")),
			("CASH_PAID_DIVIDENDS_INTEREST", "OTHER_OPERATING_RECEIPTS", "CASH_PAID_DIVIDENDS_INTEREST"))
		self.assertEqual(classify_account_number("2231", "Cash Flow", account("2231", "应付利息"))[1], "OTHER_FINANCING_RECEIPTS")

	def test_tax_and_payroll_refund_rules_unchanged(self):
		self.assertEqual(classify_account_number("222112", "Cash Flow", account("222112", "个税"))[2], "CASH_PAID_TAXES")
		self.assertEqual(classify_account_number("221101", "Cash Flow", account("221101", "工资"))[1], "OTHER_OPERATING_RECEIPTS")

	def test_repair_only_matches_old_rule_and_is_idempotent(self):
		a = account("660208", "社会保险费")
		m = mapping("a", "OTHER_OPERATING_PAYMENTS", cash_inflow_row_code="OTHER_OPERATING_RECEIPTS",
			cash_outflow_row_code="OTHER_OPERATING_PAYMENTS")
		fixed = corrected_cash_flow_classification(a, m)
		self.assertEqual(fixed[2], "CASH_PAID_EMPLOYEES")
		m.row_code, m.cash_inflow_row_code, m.cash_outflow_row_code = fixed
		self.assertIsNone(corrected_cash_flow_classification(a, m))
		m.cash_outflow_row_code = "CASH_PAID_LONG_TERM_ASSETS"
		self.assertIsNone(corrected_cash_flow_classification(a, m))

	def test_migration_preserves_manual_mappings_by_default(self):
		with patch("frappe.get_all", side_effect=[["Cash Flow Template"], []]) as get_all:
			self.assertEqual(repair_cash_flow_mappings(), [])
			self.assertEqual(get_all.call_args.kwargs["filters"]["mapping_source"], "Automatic")
