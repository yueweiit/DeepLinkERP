"""Additive deployment of the voucher preparation UI, without business-data repair."""

import frappe

PREPARATION_FIELDS = [
	{
		"fieldname": "custom_china_cash_flow_plan",
		"label": "草稿现金流项目",
		"fieldtype": "Long Text",
		"hidden": 1,
		"insert_after": "user_remark",
	},
	{
		"fieldname": "custom_china_ready_hash",
		"label": "核对版本",
		"fieldtype": "Data",
		"hidden": 1,
		"read_only": 1,
		"no_copy": 1,
		"insert_after": "custom_china_cash_flow_plan",
	},
	{
		"fieldname": "custom_china_ready_by",
		"label": "核对人",
		"fieldtype": "Link",
		"options": "User",
		"read_only": 1,
		"no_copy": 1,
		"insert_after": "custom_china_ready_hash",
	},
	{
		"fieldname": "custom_china_ready_on",
		"label": "核对时间",
		"fieldtype": "Datetime",
		"read_only": 1,
		"no_copy": 1,
		"insert_after": "custom_china_ready_by",
	},
]


def sync_preparation_schema():
	"""Run with bench execute after publishing code; does not enable any company."""
	from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

	from china_finance.setup.install import sync_navigation_metadata

	for name in ("china_finance_settings", "china_closing_run"):
		frappe.reload_doc("china_finance", "doctype", name, force=True)
	frappe.reload_doc("china_finance", "report", "china_voucher_ledger", force=True)
	create_custom_fields({"Journal Entry": PREPARATION_FIELDS})
	sync_navigation_metadata()
	frappe.clear_cache()
	return {
		"site": frappe.local.site,
		"schema_ready": True,
		"message": "凭证准备字段和导航已更新；请在中国财务设置中选择生效日期并启用。",
	}
