import io
import json
import zipfile
from types import SimpleNamespace

import frappe
from frappe.tests import UnitTestCase

from china_finance.services.financial_statement import (
	apply_temporary_inventory_accrual_presentation,
	apply_balance_sheet_reclassifications,
	apply_vat_net_presentation,
	build_statement_checks,
	get_mapping_for_date,
	render_rows,
	validate_formula_graph,
)
from china_finance.services.statutory_reporting import _build_excel
from china_finance.china_finance.report.china_financial_statements.china_financial_statements import (
	get_profit_and_loss_metrics,
)
from china_finance.setup.templates import ENTERPRISE_ROWS, SMALL_ENTERPRISE_ROWS, build_seed_rows


def row(code, row_type="Mapped Accounts", formula=None, direction="Debit Positive"):
	return SimpleNamespace(
		row_code=code, statutory_line_number=None, label=code, row_type=row_type,
		formula=formula, balance_direction=direction, indent=0, bold=0, show_zero=1,
	)


class TestStatutoryFormulaEngine(UnitTestCase):
	def test_balance_sheet_check_reports_difference(self):
		rows = [
			{"row_code": "TOTAL_ASSETS", "label": "资产合计", "row_type": "Formula", "amount": 100},
			{"row_code": "TOTAL_LIABILITIES_EQUITY", "label": "负债和权益合计", "row_type": "Formula", "amount": 90},
		]
		checks = build_statement_checks("Balance Sheet", rows, [])
		self.assertFalse(next(item for item in checks if item["code"] == "BALANCE_SHEET_BALANCE")["passed"])

	def test_profit_and_loss_check_flags_negative_mapped_amount(self):
		rows = [{"row_code": "OPERATING_REVENUE", "label": "营业收入", "row_type": "Mapped Accounts", "amount": -1}]
		checks = build_statement_checks("Profit and Loss", rows, [])
		check = next(item for item in checks if item["code"] == "NEGATIVE_PROFIT_AND_LOSS_AMOUNT")
		self.assertFalse(check["passed"])
		self.assertFalse(check["blocking"])

	def test_profit_and_loss_allows_negative_interest_income(self):
		rows = [{
			"row_code": "INTEREST_EXPENSES", "label": "利息费用（收入以“-”号填列）",
			"row_type": "Mapped Accounts", "amount": -0.48,
		}]
		check = next(
			item for item in build_statement_checks("Profit and Loss", rows, [])
			if item["code"] == "NEGATIVE_PROFIT_AND_LOSS_AMOUNT"
		)
		self.assertTrue(check["passed"])

	def test_statement_check_flags_account_mapped_to_multiple_rows(self):
		rows = [{"row_code": "A", "label": "项目A", "row_type": "Mapped Accounts", "amount": 1}]
		mappings = [SimpleNamespace(account="1001", row_code="A"), SimpleNamespace(account="1001", row_code="B")]
		checks = build_statement_checks("Profit and Loss", rows, mappings)
		self.assertFalse(next(item for item in checks if item["code"] == "CROSS_ROW_REPORT_MAPPING")["passed"])

	def test_unmapped_account_check_is_review_only(self):
		checks = build_statement_checks(
			"Balance Sheet",
			[],
			[],
			[{"account": "1001 - TEST", "balance": 250}],
		)
		check = next(item for item in checks if item["code"] == "UNMAPPED_ACCOUNT_BALANCE")
		self.assertFalse(check["passed"])
		self.assertFalse(check["blocking"])

	def test_ar_ap_reconciliation_is_review_only(self):
		checks = build_statement_checks(
			"Balance Sheet", [], [], ar_ap_check={"passed": False, "count": 2, "difference": 12.5}
		)
		check = next(item for item in checks if item["code"] == "AR_AP_LEDGER_RECONCILIATION")
		self.assertFalse(check["passed"])
		self.assertFalse(check["blocking"])

	def test_profit_and_loss_metrics_include_research_expenses(self):
		rows = [
			{"row_code": "OPERATING_REVENUE", "year_to_date_amount": 100},
			{"row_code": "OPERATING_COST", "year_to_date_amount": 20},
			{"row_code": "RESEARCH_EXPENSES", "year_to_date_amount": 10},
			{"row_code": "NET_PROFIT", "year_to_date_amount": 70},
		]
		self.assertEqual(get_profit_and_loss_metrics(rows)["expenses"], 30)

	def test_formula_dependency_order_is_independent_of_row_order(self):
		template = SimpleNamespace(rows=[
			row("TOTAL", "Formula", "SUBTOTAL + C"),
			row("A"), row("SUBTOTAL", "Formula", "A + B"), row("B"), row("C"),
		])
		result = {item["row_code"]: item["amount"] for item in render_rows(template, {"A": 1, "B": 2, "C": 3})}
		self.assertEqual(result["SUBTOTAL"], 3)
		self.assertEqual(result["TOTAL"], 6)

	def test_small_enterprise_supplementary_detail_is_not_double_counted(self):
		template = SimpleNamespace(
			accounting_standard="小企业会计准则",
			statement_type="Profit and Loss",
			rows=[SimpleNamespace(**item) for item in build_seed_rows(SMALL_ENTERPRISE_ROWS["Profit and Loss"])],
		)
		result = {
			item["row_code"]: item["amount"]
			for item in render_rows(template, {"ADMIN_EXPENSES": 100, "RESEARCH_EXPENSES": 10}, {"RESEARCH_EXPENSES"})
		}
		self.assertEqual(result["ADMIN_EXPENSES"], 100)
		self.assertEqual(result["RESEARCH_EXPENSES"], 10)

	def test_formula_cycle_is_rejected(self):
		rows = [row("A", "Formula", "B + 1"), row("B", "Formula", "A + 1")]
		with self.assertRaises(frappe.ValidationError):
			validate_formula_graph(rows)

	def test_statutory_line_numbers_are_separate_and_contiguous(self):
		seed_rows = build_seed_rows(ENTERPRISE_ROWS["Profit and Loss"])
		line_numbers = [int(item["statutory_line_number"]) for item in seed_rows if item["row_type"] != "Heading"]
		self.assertEqual(line_numbers, list(range(1, len(line_numbers) + 1)))
		self.assertTrue(all(item["statutory_line_number"] is None for item in seed_rows if item["row_type"] == "Heading"))

	def test_mapping_revision_is_selected_by_posting_date(self):
		revisions = {
			"1002 - TEST": [
				SimpleNamespace(effective_from="2026-01-01", effective_to="2026-06-30", row_code="A"),
				SimpleNamespace(effective_from="2026-07-01", effective_to=None, row_code="B"),
			]
		}
		self.assertEqual(get_mapping_for_date(revisions, "1002 - TEST", "2026-03-01").row_code, "A")
		self.assertEqual(get_mapping_for_date(revisions, "1002 - TEST", "2026-08-01").row_code, "B")

	def test_deductible_vat_is_presented_as_other_current_asset(self):
		values = {"OTHER_CURRENT_ASSETS": 0, "TAXES_PAYABLE": 0}
		apply_vat_net_presentation(values, 69.03)
		self.assertEqual(values["OTHER_CURRENT_ASSETS"], 69.03)
		self.assertEqual(values["TAXES_PAYABLE"], 0)

	def test_net_output_vat_is_presented_as_tax_payable(self):
		values = {"OTHER_CURRENT_ASSETS": 0, "TAXES_PAYABLE": 0}
		apply_vat_net_presentation(values, -8.97)
		self.assertEqual(values["OTHER_CURRENT_ASSETS"], 0)
		self.assertEqual(values["TAXES_PAYABLE"], 8.97)

	def test_debit_temporary_inventory_accrual_is_presented_as_current_asset(self):
		values = {"OTHER_CURRENT_ASSETS": 0, "ACCOUNTS_PAYABLE": 0}
		apply_temporary_inventory_accrual_presentation(values, 90)
		self.assertEqual(values["OTHER_CURRENT_ASSETS"], 90)
		self.assertEqual(values["ACCOUNTS_PAYABLE"], 0)

	def test_debit_employee_payable_is_reclassified_without_changing_gl_mapping(self):
		template = SimpleNamespace(rows=[
			row("EMPLOYEE_BENEFITS_PAYABLE", direction="Credit Positive"),
			row("OTHER_CURRENT_ASSETS"),
		])
		values = {"EMPLOYEE_BENEFITS_PAYABLE": -100, "OTHER_CURRENT_ASSETS": 25}
		items = apply_balance_sheet_reclassifications(values, template, "本期")
		self.assertEqual(values["EMPLOYEE_BENEFITS_PAYABLE"], 0)
		self.assertEqual(values["OTHER_CURRENT_ASSETS"], 125)
		self.assertEqual(items[0]["amount"], 100)

	def test_credit_receivable_is_reclassified_to_contract_liability(self):
		template = SimpleNamespace(rows=[
			row("ACCOUNTS_RECEIVABLE"),
			row("ADVANCES_FROM_CUSTOMERS", direction="Credit Positive"),
		])
		values = {"ACCOUNTS_RECEIVABLE": -80, "ADVANCES_FROM_CUSTOMERS": 10}
		apply_balance_sheet_reclassifications(values, template, "本期")
		self.assertEqual(values["ACCOUNTS_RECEIVABLE"], 0)
		self.assertEqual(values["ADVANCES_FROM_CUSTOMERS"], 90)

	def test_normal_balances_and_missing_targets_are_unchanged(self):
		template = SimpleNamespace(rows=[row("EMPLOYEE_BENEFITS_PAYABLE", direction="Credit Positive")])
		values = {"EMPLOYEE_BENEFITS_PAYABLE": 100}
		self.assertEqual(apply_balance_sheet_reclassifications(values, template, "本期"), [])
		self.assertEqual(values["EMPLOYEE_BENEFITS_PAYABLE"], 100)

	def test_formal_excel_contains_four_table_metadata_and_notes(self):
		payload = {
			"rows": [{"statutory_line_number": "1", "label": "货币资金", "amount": 1, "comparison_amount": 0}],
			"financial_statement_notes": {
				"from_date": "2026-01-01", "to_date": "2026-12-31", "version": 1,
				"disclosures": {"basis_of_preparation": "按企业会计准则编制"},
				"policies": [], "statement_data": {},
			},
		}
		snapshot = SimpleNamespace(
			statement_type="Balance Sheet", from_date="2026-01-01", to_date="2026-12-31",
			template_version="3.0", approved_by="Administrator", approved_on="2026-12-31 12:00:00",
			data_json=json.dumps(payload, ensure_ascii=False),
		)
		content = _build_excel([snapshot], "测试公司")
		self.assertTrue(content.startswith(b"PK"))
		with zipfile.ZipFile(io.BytesIO(content)) as workbook:
			workbook_xml = workbook.read("xl/workbook.xml").decode("utf-8")
			self.assertIn("资产负债表", workbook_xml)
			self.assertIn("财务报表附注", workbook_xml)
