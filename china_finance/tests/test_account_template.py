from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase, UnitTestCase

from china_finance.overrides.company import ChinaFinanceCompany
from china_finance.services.account_template import (
	COMPANY_TEMPLATE,
	count_chart_accounts,
	flatten_company_template_chart,
	get_company_template_chart,
	get_company_template_data,
	get_charts_for_country,
	preview_existing_company_template_sync,
	sync_existing_company_to_template,
)
from china_finance.setup.china_coa_profile import CHART_TEMPLATE


class TestAccountTemplate(UnitTestCase):
	def test_source_company_template_is_available_for_china(self):
		self.assertIn(COMPANY_TEMPLATE, get_charts_for_country("China", with_standard=True))
		self.assertNotIn(COMPANY_TEMPLATE, get_charts_for_country("India", with_standard=True))

	def test_bundled_template_matches_current_source_snapshot(self):
		data = get_company_template_data()
		self.assertEqual(data["account_count"], 335)
		self.assertEqual(count_chart_accounts(get_company_template_chart()), data["account_count"])
		self.assertEqual(set(get_company_template_chart()), {"资产", "负债", "所有者权益", "收入", "费用"})
		rows = flatten_company_template_chart()
		self.assertEqual(len(rows), data["account_count"])
		self.assertEqual(len({row["account_number"] for row in rows if row["account_number"]}), 313)
		self.assertTrue(all(row["root_type"] for row in rows))

	def test_source_company_template_uses_bundled_chart_path(self):
		company = frappe.new_doc("Company")
		company.update(
			{
				"company_name": "模板测试公司",
				"abbr": "MTC",
				"country": "China",
				"create_chart_of_accounts_based_on": "Standard Template",
				"chart_of_accounts": COMPANY_TEMPLATE,
			}
		)
		self.assertIsInstance(company, ChinaFinanceCompany)

		company.validate_coa_input()

		self.assertEqual(company.create_chart_of_accounts_based_on, "Standard Template")
		self.assertIsNone(company.existing_company)
		self.assertEqual(company.chart_of_accounts, CHART_TEMPLATE)
		self.assertTrue(company._use_company_account_template)


class TestAccountTemplateIntegration(IntegrationTestCase):
	def test_new_company_is_created_from_bundled_template(self):
		suffix = frappe.generate_hash(length=5).upper()
		company = frappe.get_doc(
			{
				"doctype": "Company",
				"company_name": f"_Test Bundled CoA {suffix}",
				"abbr": suffix,
				"country": "China",
				"default_currency": "CNY",
				"create_chart_of_accounts_based_on": "Standard Template",
				"chart_of_accounts": COMPANY_TEMPLATE,
			}
		)
		# The shared test site can retain invalid Mode of Payment links from
		# unrelated ERPNext tests. They do not participate in CoA creation.
		with patch.object(ChinaFinanceCompany, "set_mode_of_payment_account"):
			company.insert()

		self.assertEqual(
			frappe.db.count("Account", {"company": company.name, "disabled": 0}),
			get_company_template_data()["account_count"],
		)
		for account_number in ("2301", "2401"):
			self.assertEqual(
				frappe.db.get_value(
					"Account",
					{"company": company.name, "account_number": account_number},
					"account_name",
				),
				"递延收益",
			)

	def test_zero_ledger_standard_company_can_be_upgraded_to_bundled_template(self):
		suffix = frappe.generate_hash(length=5).upper()
		company = frappe.get_doc(
			{
				"doctype": "Company",
				"company_name": f"_Test CoA Upgrade {suffix}",
				"abbr": suffix,
				"country": "China",
				"default_currency": "CNY",
				"create_chart_of_accounts_based_on": "Standard Template",
				"chart_of_accounts": CHART_TEMPLATE,
			}
		)
		with patch.object(ChinaFinanceCompany, "set_mode_of_payment_account"):
			company.insert()

		preview = preview_existing_company_template_sync(company.name)
		self.assertTrue(preview["can_apply"])
		self.assertGreater(preview["missing_count"], 0)

		with patch.object(frappe.db, "commit"):
			result = sync_existing_company_to_template(company.name, apply=True)

		self.assertTrue(result["applied"])
		self.assertGreater(result["created_count"], 0)
		self.assertEqual(
			frappe.db.count("Account", {"company": company.name, "disabled": 0}),
			get_company_template_data()["account_count"] + result["retained_extra_count"],
		)
		for account_number, account_name in (("2301", "递延收益"), ("2401", "递延收益"), ("660225", "管理费用－折旧费")):
			self.assertEqual(
				frappe.db.get_value(
					"Account",
					{"company": company.name, "account_number": account_number},
					"account_name",
				),
				account_name,
			)
		self.assertEqual(
			frappe.db.get_value(
				"Account",
				frappe.db.get_value("Company", company.name, "depreciation_expense_account"),
				"account_number",
			),
			"660225",
		)
		after_sync = preview_existing_company_template_sync(company.name)
		self.assertEqual(after_sync["missing_count"], 0)
		self.assertEqual(after_sync["rename_count"], 0)
		self.assertEqual(after_sync["reparent_count"], 0)
