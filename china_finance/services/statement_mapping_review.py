import frappe
from frappe import _
from frappe.utils import now_datetime

from china_finance.services.account_display import get_account_display_label, strip_account_company_suffix


REVIEW_ROLES = ("System Manager", "Accounts Manager", "China Finance Manager")


def _require_mapping_write_access(name):
	frappe.only_for(REVIEW_ROLES)
	doc = frappe.get_doc("China Financial Statement Mapping", name)
	if not doc.has_permission("write"):
		frappe.throw(_("无权复核该财务报表科目映射"), frappe.PermissionError)
	return doc


def _row_details(template):
	return {
		row.row_code: {
			"row_code": row.row_code,
			"label": row.label,
			"row_type": row.row_type,
			"display": "{0} | {1}".format(row.row_code, row.label),
		}
		for row in template.rows
	}


@frappe.whitelist()
def get_mapping_review_context(name):
	doc = frappe.get_doc("China Financial Statement Mapping", name)
	if not doc.has_permission("read"):
		frappe.throw(_("无权查看该财务报表科目映射"), frappe.PermissionError)
	template = frappe.get_cached_doc("China Financial Statement Template", doc.template)
	account = frappe.db.get_value(
		"Account", doc.account,
		["name", "account_name", "account_number", "root_type", "account_type"], as_dict=True,
	) or {}
	account_name = account.get("account_name") or strip_account_company_suffix(doc.account, doc.company)
	account_label = get_account_display_label(account, doc.company) or account_name
	rows = _row_details(template)
	return {
		"mapping_source": doc.mapping_source,
		"reviewed": bool(doc.reviewed),
		"statement_type": template.statement_type,
		"account": {
			"name": doc.account,
			"account_name": account_name,
			"account_number": account.get("account_number"),
			"account_label": account_label,
			"root_type": account.get("root_type"),
			"account_type": account.get("account_type"),
		},
		"row": rows.get(doc.row_code),
		"cash_inflow_row": rows.get(doc.cash_inflow_row_code),
		"cash_outflow_row": rows.get(doc.cash_outflow_row_code),
		"guidance": _get_guidance(template.statement_type, doc.mapping_source, doc.reviewed),
	}


def _get_guidance(statement_type, mapping_source, reviewed):
	if reviewed:
		return _("该映射已复核；修改归类、科目、期间或金额方向后，系统会自动要求重新复核。")
	if statement_type == "Cash Flow":
		return _("请根据实际业务判断：收到或支付现金时应列示在哪个现金流量项目。不要用修改映射来调整现金净增加额。")
	if mapping_source == "Automatic":
		return _("这是系统根据科目属性生成的建议。请核对其是否符合本公司的会计政策和报表口径后再确认。")
	return _("请核对该科目在所选报表中的列报项目、金额方向及适用期间后确认。")


@frappe.whitelist()
def set_mapping_reviewed(name, review_notes=None, reviewed=1):
	doc = _require_mapping_write_access(name)
	if frappe.utils.cint(reviewed):
		doc.reviewed = 1
		doc.reviewed_by = frappe.session.user
		doc.reviewed_on = now_datetime()
		doc.review_notes = (review_notes or "").strip() or None
	else:
		doc.reviewed = 0
		doc.reviewed_by = None
		doc.reviewed_on = None
		doc.review_notes = None
	doc.flags.ignore_validate_update_after_submit = True
	doc.save()
	return {
		"name": doc.name,
		"reviewed": bool(doc.reviewed),
		"reviewed_by": doc.reviewed_by,
		"reviewed_on": doc.reviewed_on,
	}
