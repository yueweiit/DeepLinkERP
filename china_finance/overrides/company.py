"""Company controller extensions for China Finance."""

import frappe
from frappe import _

from erpnext.setup.doctype.company.company import Company

from china_finance.services.account_template import (
	COMPANY_TEMPLATE,
	SOURCE_COMPANY,
	source_company_available,
)
from china_finance.setup.china_coa_profile import CHART_TEMPLATE


class ChinaFinanceCompany(Company):
	"""Allow a new company to copy the Yuewei chart from a named template."""

	def validate_coa_input(self):
		if self.is_new() and self.chart_of_accounts == COMPANY_TEMPLATE:
			if self.parent_company:
				frappe.throw(_("公司科目模板不能与上级公司同时使用"))
			if not source_company_available():
				frappe.throw(_("悦为智能技术(东莞)有限公司的科目模板当前不可用"))

			# ERPNext already has a complete and tested "Existing Company" copy
			# path.  Translate the visible template choice into that path, while
			# retaining a real chart template value for profile and reporting code.
			self.create_chart_of_accounts_based_on = "Existing Company"
			self.existing_company = SOURCE_COMPANY
			super().validate_coa_input()
			self.chart_of_accounts = (
				frappe.db.get_value("Company", SOURCE_COMPANY, "chart_of_accounts") or CHART_TEMPLATE
			)
			return

		super().validate_coa_input()
