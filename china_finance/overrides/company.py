"""Company controller extensions for China Finance."""

import frappe
from frappe import _

from erpnext.setup.doctype.company.company import Company

from china_finance.services.account_template import (
	COMPANY_TEMPLATE,
	company_template_available,
	get_company_template_chart,
)
from china_finance.setup.china_coa_profile import CHART_TEMPLATE


class ChinaFinanceCompany(Company):
	"""Allow a new company to use the bundled Yuewei account template."""

	def validate_coa_input(self):
		if self.is_new() and self.chart_of_accounts == COMPANY_TEMPLATE:
			if self.parent_company:
				frappe.throw(_("公司科目模板不能与上级公司同时使用"))
			if not company_template_available():
				frappe.throw(_("悦为智能技术(东莞)有限公司的科目模板当前不可用"))

			# Keep the standard China profile identity for report/mapping setup, but
			# create the accounts from the bundled company snapshot in on_update.
			self._use_company_account_template = True
			self.create_chart_of_accounts_based_on = "Standard Template"
			self.existing_company = None
			self.chart_of_accounts = CHART_TEMPLATE
			super().validate_coa_input()
			return

		super().validate_coa_input()

	def create_default_accounts(self):
		if not getattr(self, "_use_company_account_template", False):
			return super().create_default_accounts()

		from erpnext.accounts.doctype.account.chart_of_accounts.chart_of_accounts import create_charts

		frappe.local.flags.ignore_root_company_validation = True
		create_charts(
			self.name,
			custom_chart=get_company_template_chart(),
			from_coa_importer=True,
		)

		self.db_set(
			"default_receivable_account",
			frappe.db.get_value(
				"Account", {"company": self.name, "account_type": "Receivable", "is_group": 0}
			),
		)
		self.db_set(
			"default_payable_account",
			frappe.db.get_value(
				"Account", {"company": self.name, "account_type": "Payable", "is_group": 0}
			),
		)
