import frappe
from frappe.tests import UnitTestCase

from china_finance.overrides.company import ChinaFinanceCompany
from china_finance.services.account_template import (
	COMPANY_TEMPLATE,
	SOURCE_COMPANY,
	get_charts_for_country,
)


class TestAccountTemplate(UnitTestCase):
	def test_source_company_template_is_available_for_china(self):
		self.assertIn(COMPANY_TEMPLATE, get_charts_for_country("China", with_standard=True))

	def test_source_company_template_uses_existing_company_copy_path(self):
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

		self.assertEqual(company.create_chart_of_accounts_based_on, "Existing Company")
		self.assertEqual(company.existing_company, SOURCE_COMPANY)
		self.assertTrue(company.chart_of_accounts)
