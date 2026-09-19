import frappe
from frappe import _


DEFAULT_CRM_API_USER = "crm system"


def get_crm_api_user():
	return frappe.conf.get("crm_api_user") or DEFAULT_CRM_API_USER


def is_crm_api_user():
	return getattr(frappe.session, "user", None) == get_crm_api_user()


def validate_crm_api_user():
	if not is_crm_api_user():
		frappe.throw(_("当前用户没有 CRM 接口调用权限。"), frappe.PermissionError)
