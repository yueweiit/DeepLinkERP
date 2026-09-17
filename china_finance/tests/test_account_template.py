from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase, UnitTestCase

from china_finance.overrides.company import ChinaFinanceCompany
from china_finance.services.account_template import (
	COMPANY_TEMPLATE,
	count_chart_accounts,
	get_company_template_chart,
	get_company_template_data,
	get_charts_for_country,
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
