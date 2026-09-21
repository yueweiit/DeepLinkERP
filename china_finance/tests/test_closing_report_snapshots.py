"""Closing snapshots use isolated, rolled-back company and template records."""

import hashlib
import json
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import getdate

from china_finance.services.closing import run_closing_checks, submit_closing_run
from china_finance.services.financial_statement import snapshot_statement
from china_finance.services.statutory_reporting import generate_statutory_report_package


class TestClosingReportSnapshots(IntegrationTestCase):
	def setUp(self):
		super().setUp()
		self.prefix = "_Test Closing Reports " + frappe.generate_hash(length=8)
		frappe.db.savepoint("closing_report_test")
		self.addCleanup(frappe.db.rollback, save_point="closing_report_test")
		self.company = self.insert(
			"Company", company_name=self.prefix, abbr=self.prefix[-5:], default_currency="CNY"
		)
		self.cash = self.insert(
			"Account", "cash", company=self.company, account_name="Cash", root_type="Asset",
			report_type="Balance Sheet", account_type="Cash", account_currency="CNY",
		)
		self.capital = self.insert(
			"Account", "capital", company=self.company, account_name="Capital", root_type="Equity",
			report_type="Balance Sheet", account_currency="CNY",
		)
		# A private standard isolates template selection from installed shared templates.
		self.insert(
			"China Finance Settings", company=self.company, enabled=1, accounting_standard=self.prefix,
			activation_date="2026-01-01", reconciliation_tolerance=0.01, freeze_on_close=1,
			profit_loss_account=self.capital, retained_earnings_account=self.capital,
			require_customer_reconciliation=0, require_supplier_reconciliation=0,
			require_bank_reconciliation=0, enforce_role_separation=0,
		)
		self.templates = {}
		for kind in ("Balance Sheet", "Profit and Loss", "Cash Flow", "Changes in Equity"):
			name = self.insert(
				"China Financial Statement Template", kind, template_key=self.prefix + "|" + kind,
				title=kind, accounting_standard=self.prefix, statement_type=kind, version="3.0",
				effective_from="2026-01-01", is_active=1,
			)
			self.templates[kind] = name
			codes = {
				"Balance Sheet": ("TOTAL_ASSETS", "TOTAL_LIABILITIES_EQUITY"),
				"Profit and Loss": ("NET_PROFIT",),
				"Cash Flow": ("CASH_RECONCILIATION_DIFFERENCE",),
				"Changes in Equity": ("NET_PROFIT",),
			}[kind]
			for idx, code in enumerate(codes, 1):
				self.insert(
					"China Financial Statement Row", kind + code, parent=name, parenttype="China Financial Statement Template",
					parentfield="rows", idx=idx, row_code=code, label=code, row_type="Mapped Accounts",
					balance_direction="Credit Positive" if code == "TOTAL_LIABILITIES_EQUITY" else "Debit Positive",
					show_zero=1,
				)
		for label, account, code in (
			("cash", self.cash, "TOTAL_ASSETS"), ("capital", self.capital, "TOTAL_LIABILITIES_EQUITY")
		):
			self.insert(
				"China Financial Statement Mapping", label, company=self.company,
				template=self.templates["Balance Sheet"], account=account, row_code=code,
				effective_from="2026-01-01", sign_multiplier="1", reviewed=1,
			)
		self.pcv = self.insert(
			"Period Closing Voucher", company=self.company, period_start_date="2026-01-01",
			period_end_date="2026-01-31", docstatus=1,
		)
		name = self.insert(
			"China Closing Run", company=self.company, closing_type="Monthly", from_date="2026-01-01",
			to_date="2026-01-31", period_closing_voucher=self.pcv, status="Draft", naming_series="CNC-.YYYY.-.#####",
		)
		self.run = frappe.get_doc("China Closing Run", name)
		fiscal_year = patch(
			"china_finance.services.financial_statement.get_fiscal_year_start",
			side_effect=lambda company, date: getdate(f"{getdate(date).year}-01-01"),
		)
		fiscal_year.start()
		self.addCleanup(fiscal_year.stop)

	def insert(self, doctype, suffix="", **values):
		name = self.prefix + (" " + suffix if suffix else "")
		frappe.get_doc({"doctype": doctype, "name": name, **values}).db_insert()
		return name

	def make_snapshot(self, kind="Balance Sheet"):
		name = snapshot_statement(self.run, kind)
		doc = frappe.get_doc("China Report Snapshot", name)
		return doc, json.loads(doc.data_json)

	def test_monthly_missing_comparison_keeps_current_amounts_and_blank_comparatives(self):
		for label, account, debit, credit in (("cash", self.cash, 123, 0), ("capital", self.capital, 0, 123)):
			self.insert(
				"GL Entry", label, company=self.company, account=account, posting_date="2026-01-15",
				debit=debit, credit=credit, is_cancelled=0, is_opening="No",
			)
		doc, payload = self.make_snapshot()
		self.assertEqual(doc.report_status, "草表")
		self.assertEqual(payload["report_status"], "草表")
		self.assertEqual(payload["comparison_status"], "Missing Template")
		self.assertEqual(payload["comparison_to_date"], "2025-12-31")
		self.assertTrue(all(row["amount"] == 123 for row in payload["rows"]))
		self.assertTrue(all(row["comparison_amount"] is None for row in payload["rows"]))
		self.assertIn("2025-12-31", payload["comparison_details"])
		self.assertEqual(doc.sha256, hashlib.sha256(doc.data_json.encode()).hexdigest())

	def test_missing_comparison_is_reported_in_monthly_checks_as_warning(self):
		checks = {row["check_code"]: row for row in run_closing_checks(
			self.company, self.run.from_date, self.run.to_date, self.pcv, "Monthly"
		)}
		self.assertTrue(checks["REPORT_TEMPLATE_COVERAGE"]["passed"])
		self.assertFalse(checks["COMPARISON_TEMPLATE_COVERAGE"]["passed"])
		self.assertEqual(checks["COMPARISON_TEMPLATE_COVERAGE"]["severity"], "Warning")
		self.assertIn("2025-12-31", checks["COMPARISON_TEMPLATE_COVERAGE"]["details"])

	def test_monthly_submit_creates_four_draft_snapshots_and_freezes_period(self):
		with patch("frappe.enqueue") as enqueue:
			result = submit_closing_run(self.run.name)
		self.assertEqual(result["status"], "Closed")
		self.assertEqual(result["docstatus"], 1)
		snapshots = frappe.get_all(
			"China Report Snapshot", filters={"closing_run": self.run.name}, fields=["report_status", "data_json"]
		)
		self.assertEqual(len(snapshots), 4)
		self.assertTrue(all(row.report_status == "草表" for row in snapshots))
		self.assertTrue(all(json.loads(row.data_json)["comparison_status"] == "Missing Template" for row in snapshots))
		self.assertEqual(getdate(frappe.db.get_value("Company", self.company, "accounts_frozen_till_date")), getdate("2026-01-31"))
		self.assertTrue(enqueue.call_args.kwargs["enqueue_after_commit"])

	def test_year_end_still_rejects_missing_comparison(self):
		self.run.closing_type = "Year End"
		with self.assertRaises(frappe.ValidationError):
			self.make_snapshot()
		self.assertFalse(frappe.db.exists("China Report Snapshot", {"closing_run": self.run.name}))

	def test_current_period_template_is_still_required(self):
		frappe.db.set_value("China Financial Statement Template", self.templates["Balance Sheet"], "is_active", 0)
		with self.assertRaises(frappe.ValidationError):
			self.make_snapshot()
		checks = {row["check_code"]: row for row in run_closing_checks(
			self.company, self.run.from_date, self.run.to_date, self.pcv, "Monthly"
		)}
		self.assertFalse(checks["REPORT_TEMPLATE_COVERAGE"]["passed"])
		self.assertEqual(checks["REPORT_TEMPLATE_COVERAGE"]["severity"], "Blocking")

	def test_available_comparison_preserves_formal_snapshot_behavior(self):
		frappe.db.set_value("China Financial Statement Template", self.templates["Balance Sheet"], "effective_from", "2025-01-01")
		doc, payload = self.make_snapshot()
		self.assertEqual(doc.report_status, "正式")
		self.assertEqual(payload["comparison_status"], "Available")
		self.assertTrue(all(row["comparison_amount"] == 0 for row in payload["rows"]))

	def test_comparison_calculation_errors_are_not_suppressed(self):
		from china_finance.services.financial_statement import build_statement

		frappe.db.set_value("China Financial Statement Template", self.templates["Balance Sheet"], "effective_from", "2025-01-01")
		def calculate(company, kind, from_date, to_date, **kwargs):
			if getdate(to_date).year == 2025:
				raise RuntimeError("comparison calculation failed")
			return build_statement(company, kind, from_date, to_date, **kwargs)
		with patch("china_finance.services.financial_statement.build_statement", side_effect=calculate):
			with self.assertRaisesRegex(RuntimeError, "comparison calculation failed"):
				self.make_snapshot()

	def test_formal_export_rejects_draft_snapshots_even_after_readiness_is_fixed(self):
		with patch("frappe.enqueue"):
			submit_closing_run(self.run.name)
		with patch("china_finance.services.statutory_reporting.get_statutory_report_readiness_data", return_value={"passed": True}):
			with self.assertRaisesRegex(frappe.ValidationError, "草表快照"):
				generate_statutory_report_package(self.run.name, formats=["Excel"])

	def test_draft_snapshot_is_immutable_and_repeat_does_not_overwrite_it(self):
		doc, _payload = self.make_snapshot()
		frappe.db.set_value("China Financial Statement Template", self.templates["Balance Sheet"], "effective_from", "2025-01-01")
		repeated, _ = self.make_snapshot()
		self.assertEqual(repeated.name, doc.name)
		self.assertEqual(repeated.data_json, doc.data_json)
		doc.report_status = "正式"
		with self.assertRaises(frappe.ValidationError):
			doc.save(ignore_permissions=True)
