"""Company-based chart of accounts template integration."""

import frappe


SOURCE_COMPANY = "悦为智能技术(东莞)有限公司"
COMPANY_TEMPLATE = f"{SOURCE_COMPANY}（公司科目模板）"


def source_company_available():
	"""Return whether the source company's chart can be copied."""
	return bool(
		frappe.db.exists("Company", SOURCE_COMPANY)
		and frappe.db.exists("Account", {"company": SOURCE_COMPANY})
	)


@frappe.whitelist()
def get_charts_for_country(country, with_standard=False):
	"""Add the Yuewei company chart to ERPNext's country template options."""
	from erpnext.accounts.doctype.account.chart_of_accounts.chart_of_accounts import (
		get_charts_for_country as get_native_charts_for_country,
	)

	charts = get_native_charts_for_country(country, with_standard=with_standard) or []
	source_country = frappe.db.get_value("Company", SOURCE_COMPANY, "country")
	if source_company_available() and source_country and source_country == country:
		charts = [*charts, COMPANY_TEMPLATE]

	return list(dict.fromkeys(charts))
