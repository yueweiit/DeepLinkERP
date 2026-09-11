"""Controlled editing of formal vouchers from the China voucher ledger."""

import frappe
from frappe import _
from frappe.utils import flt, getdate

from china_finance.services.voucher import get_company, get_posting_date


EDITABLE_SOURCE_DOCTYPES = ("Journal Entry", "Payment Entry")
EDIT_TOLERANCE = 0.005


def _get_source_document(source_doctype, source_name):
	if source_doctype not in EDITABLE_SOURCE_DOCTYPES:
		frappe.throw(_("查凭证只支持修改记账凭证和收付款凭证"))
	if not source_name or not frappe.db.exists(source_doctype, source_name):
		frappe.throw(_("来源凭证不存在"))

	doc = frappe.get_doc(source_doctype, source_name)
	if not doc.has_permission("read"):
		frappe.throw(_("无权查看来源凭证"), frappe.PermissionError)
	return doc


def _permission_blockers(doc):
	blockers = []
	if doc.docstatus == 0:
		if not doc.has_permission("write"):
			blockers.append(_("当前用户没有修改该凭证的权限"))
		return blockers

	if doc.docstatus != 1:
		return [_("来源凭证不是草稿或已提交状态，不能修改")]

	if not doc.has_permission("write"):
		blockers.append(_("当前用户没有修改该凭证的权限"))
	if not doc.has_permission("cancel"):
		blockers.append(_("当前用户没有取消原凭证的权限"))
	if not doc.has_permission("amend"):
		blockers.append(_("当前用户没有修订凭证的权限"))
	if not frappe.has_permission(doc.doctype, "create"):
		blockers.append(_("当前用户没有创建修订凭证的权限"))
	return blockers


def _get_closing_blockers(doc):
	company = get_company(doc)
	posting_date = getdate(get_posting_date(doc))
	blockers = []

	if not company or not posting_date:
		return blockers

	frozen_date = frappe.db.get_value("Company", company, "accounts_frozen_till_date")
	if frozen_date and posting_date <= getdate(frozen_date):
		blockers.append(
			_("凭证日期 {0} 已被冻结（冻结至 {1}）").format(posting_date, getdate(frozen_date))
		)

	period_closing_vouchers = frappe.db.get_all(
		"Period Closing Voucher",
		filters=[
			["company", "=", company],
			["docstatus", "=", 1],
			["period_start_date", "<=", posting_date],
			["period_end_date", ">=", posting_date],
		],
		fields=["name", "period_start_date", "period_end_date"],
		order_by="period_end_date desc",
		limit=1,
	)
	for voucher in period_closing_vouchers:
		blockers.append(_("所属期间已提交损益结转凭证 {0}").format(voucher.name))

	if frappe.db.exists("DocType", "China Closing Run"):
		closing_runs = frappe.db.get_all(
			"China Closing Run",
			filters=[
				["company", "=", company],
				["docstatus", "=", 1],
				["status", "=", "Closed"],
				["from_date", "<=", posting_date],
				["to_date", ">=", posting_date],
			],
			fields=["name", "from_date", "to_date"],
			order_by="to_date desc",
			limit=1,
		)
		for run in closing_runs:
			blockers.append(_("所属期间已提交期末智能结转 {0}").format(run.name))

	return blockers


def _get_bank_transaction_names(doc):
	names = []
	if frappe.db.exists("DocType", "Bank Transaction Payments"):
		names.extend(
		frappe.db.get_all(
			"Bank Transaction Payments",
			filters={"payment_document": doc.doctype, "payment_entry": doc.name},
			pluck="parent",
		)
		or []
	)

	if doc.meta.has_field("custom_china_bank_transaction") and doc.get("custom_china_bank_transaction"):
		names.append(doc.custom_china_bank_transaction)

	return list(dict.fromkeys(name for name in names if name))


def _get_bank_blockers(doc):
	blockers = []
	names = _get_bank_transaction_names(doc)
	if not names:
		if doc.get("clearance_date"):
			return [_("凭证已完成银行清账，请先撤销银行对账")]
		return blockers

	for name in names:
		bank_transaction = frappe.db.get_value(
			"Bank Transaction",
			{"name": name, "company": get_company(doc)},
			["name", "docstatus", "status", "allocated_amount"],
			as_dict=True,
		)
		if not bank_transaction or bank_transaction.docstatus == 2:
			continue

		allocated_row = frappe.db.get_value(
			"Bank Transaction Payments",
			{
				"parent": name,
				"payment_document": doc.doctype,
				"payment_entry": doc.name,
			},
			"allocated_amount",
		)
		if (
			flt(allocated_row) > EDIT_TOLERANCE
			or doc.get("clearance_date")
			or bank_transaction.status in ("Reconciled", "Settled")
		):
			blockers.append(_("已参与银行对账（银行流水 {0}），请先撤销银行对账").format(name))

	return list(dict.fromkeys(blockers))


def _has_existing_amendment(doc):
	return frappe.db.get_value(doc.doctype, {"amended_from": doc.name}, "name")


def _build_status(doc):
	blockers = _permission_blockers(doc)
	if doc.docstatus in (0, 1):
		blockers.extend(_get_closing_blockers(doc))
	if doc.docstatus == 1:
		blockers.extend(_get_bank_blockers(doc))
		if _has_existing_amendment(doc):
			blockers.append(_("该凭证已经存在修订凭证，不能重复修订"))

	if doc.docstatus == 0:
		action = "open_draft"
	elif doc.docstatus == 1:
		action = "amend"
	else:
		action = "unavailable"
		blockers.append(_("已取消的凭证不能从查凭证重复发起修订"))

	return {
		"source_doctype": doc.doctype,
		"source_name": doc.name,
		"company": get_company(doc),
		"posting_date": str(get_posting_date(doc)),
		"docstatus": doc.docstatus,
		"action": action,
		"requires_amendment": doc.docstatus == 1,
		"can_edit": not blockers and doc.docstatus in (0, 1),
		"reason": "；".join(dict.fromkeys(blockers)),
		"bank_transactions": _get_bank_transaction_names(doc),
	}


@frappe.whitelist()
def get_source_edit_status(source_doctype, source_name):
	"""Return the server-side edit decision used by the voucher ledger UI."""
	return _build_status(_get_source_document(source_doctype, source_name))


def _lock_source_row(source_doctype, source_name):
	table = {
		"Journal Entry": "tabJournal Entry",
		"Payment Entry": "tabPayment Entry",
	}[source_doctype]
	frappe.db.sql(f"SELECT name FROM `{table}` WHERE name=%s FOR UPDATE", (source_name,))


@frappe.whitelist()
def prepare_source_voucher_edit(source_doctype, source_name):
	"""Open a draft or atomically cancel-and-create an amendment for a submitted voucher."""
	doc = _get_source_document(source_doctype, source_name)
	_lock_source_row(source_doctype, source_name)
	doc = _get_source_document(source_doctype, source_name)
	status = _build_status(doc)
	if not status["can_edit"]:
		frappe.throw(_("当前凭证不能修改：{0}").format(status["reason"] or _("不满足修改条件")))

	if doc.docstatus == 0:
		return {
			"mode": "draft",
			"source_doctype": source_doctype,
			"source_name": source_name,
			"name": source_name,
		}

	if source_doctype == "Journal Entry" and len(doc.get("accounts") or []) > 100:
		frappe.throw(_("该凭证分录超过100行，请打开原凭证按标准流程取消并修订"))

	bank_transaction_names = _get_bank_transaction_names(doc)
	doc.cancel()
	doc.reload()
	if doc.docstatus != 2:
		frappe.throw(_("原凭证取消尚未完成，请稍后再试"))

	amended = frappe.copy_doc(doc)
	amended.amended_from = source_name
	if amended.meta.has_field("custom_china_voucher_number"):
		amended.custom_china_voucher_number = None
	if amended.meta.has_field("clearance_date"):
		amended.clearance_date = None

	if amended.meta.has_field("custom_china_bank_transaction") and bank_transaction_names:
		amended.custom_china_bank_transaction = bank_transaction_names[0]

	amended.insert()
	if bank_transaction_names and frappe.db.has_column("Bank Transaction", "custom_china_journal_entry"):
		for bank_transaction_name in bank_transaction_names:
			frappe.db.set_value(
				"Bank Transaction",
				bank_transaction_name,
				"custom_china_journal_entry",
				amended.name,
				update_modified=False,
			)

	return {
		"mode": "amended_draft",
		"source_doctype": source_doctype,
		"source_name": source_name,
		"name": amended.name,
		"message": _("原凭证已取消，已生成修订草稿 {0}").format(amended.name),
	}
