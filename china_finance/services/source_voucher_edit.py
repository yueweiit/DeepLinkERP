"""Controlled editing of formal vouchers from the China voucher ledger."""

import frappe
from frappe import _
from frappe.model.workflow import get_workflow_name
from frappe.utils import flt, getdate

from china_finance.services.voucher import _complete_voucher_workflow, get_company, get_posting_date


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
		):
			blockers.append(_("已参与银行对账（银行流水 {0}），请先撤销银行对账").format(name))

	return list(dict.fromkeys(blockers))


def _get_quick_unreconcile_info(doc):
	"""Allow one-click editing only for a single, full, matched JE allocation."""
	if doc.doctype != "Journal Entry" or doc.docstatus != 1:
		return None

	names = _get_bank_transaction_names(doc)
	if len(names) != 1 or not frappe.db.exists("Bank Transaction", names[0]):
		return None

	bank_transaction = frappe.get_doc("Bank Transaction", names[0])
	if (
		bank_transaction.docstatus != 1
		or bank_transaction.company != get_company(doc)
		or bank_transaction.status not in ("Reconciled", "Settled")
		or not bank_transaction.has_permission("write")
		or len(bank_transaction.payment_entries) != 1
	):
		return None

	entry = bank_transaction.payment_entries[0]
	transaction_amount = abs(flt(bank_transaction.deposit) - flt(bank_transaction.withdrawal))
	if (
		entry.payment_document != doc.doctype
		or entry.payment_entry != doc.name
		or entry.reconciliation_type != "Matched"
		or flt(entry.allocated_amount) <= EDIT_TOLERANCE
		or abs(flt(entry.allocated_amount) - transaction_amount) > EDIT_TOLERANCE
		or flt(bank_transaction.unallocated_amount) > EDIT_TOLERANCE
	):
		return None

	if (
		frappe.db.has_column("Bank Transaction", "custom_china_journal_entry")
		and bank_transaction.get("custom_china_journal_entry") not in (None, "", doc.name)
	):
		return None

	return {
		"bank_transaction": bank_transaction.name,
		"amount": flt(entry.allocated_amount),
	}


def _get_bank_reconciliation_feedback(doc, bank_transaction_names):
	"""Describe whether the amended voucher was linked back to its bank transaction."""
	if not bank_transaction_names:
		return {"status": "not_applicable", "successful": [], "failed": []}

	successful = []
	failed = []
	for name in bank_transaction_names:
		bank_transaction = frappe.db.get_value(
			"Bank Transaction",
			name,
			["name", "docstatus", "status", "allocated_amount", "unallocated_amount"],
			as_dict=True,
		)
		allocated_row = frappe.db.get_value(
			"Bank Transaction Payments",
			{
				"parent": name,
				"payment_document": doc.doctype,
				"payment_entry": doc.name,
			},
			"allocated_amount",
		) if frappe.db.exists("DocType", "Bank Transaction Payments") else None

		is_reconciled = bool(
			bank_transaction
			and bank_transaction.docstatus == 1
			and bank_transaction.status in ("Reconciled", "Settled")
			and flt(bank_transaction.unallocated_amount) <= EDIT_TOLERANCE
			and flt(allocated_row) > EDIT_TOLERANCE
		)
		detail = {
			"name": name,
			"status": bank_transaction.status if bank_transaction else _("不存在"),
			"allocated_amount": flt(bank_transaction.allocated_amount) if bank_transaction else 0,
			"unallocated_amount": flt(bank_transaction.unallocated_amount) if bank_transaction else 0,
			"voucher_allocated_amount": flt(allocated_row),
		}
		(successful if is_reconciled else failed).append(detail)

	return {
		"status": "success" if not failed else "failed",
		"successful": successful,
		"failed": failed,
	}


def _has_existing_amendment(doc):
	return frappe.db.get_value(doc.doctype, {"amended_from": doc.name}, "name")


def _reset_amendment_workflow_state(doc):
	"""Reset a copied submitted document to the workflow's initial draft state."""
	workflow_name = get_workflow_name(doc.doctype)
	if not workflow_name:
		return

	workflow = frappe.get_cached_doc("Workflow", workflow_name)
	workflow_state_field = workflow.workflow_state_field
	if not workflow_state_field or not doc.meta.has_field(workflow_state_field):
		return

	initial_state = workflow.states[0].state if workflow.states else None
	if initial_state:
		doc.set(workflow_state_field, initial_state)


_AMENDMENT_SYSTEM_FIELDS = {
	"name",
	"doctype",
	"owner",
	"creation",
	"modified",
	"modified_by",
	"docstatus",
	"workflow_state",
	"amended_from",
	"amendment_date",
	"custom_china_voucher_number",
	"clearance_date",
	"idx",
	"parent",
	"parentfield",
	"parenttype",
}


def _normalise_amendment_value(value):
	"""Return a document value without naming/workflow fields generated by an amendment."""
	if isinstance(value, list):
		return [_normalise_amendment_value(item) for item in value]
	if isinstance(value, dict):
		return {
			key: _normalise_amendment_value(item)
			for key, item in value.items()
			if key not in _AMENDMENT_SYSTEM_FIELDS and not key.startswith("_")
		}
	return value


def _has_meaningful_amendment_changes(doc):
	"""Check the draft against its cancelled source, ignoring amendment metadata."""
	if not doc.get("amended_from"):
		return True

	source = frappe.get_doc(doc.doctype, doc.amended_from)
	return _normalise_amendment_value(doc.as_dict()) != _normalise_amendment_value(source.as_dict())


def _build_status(doc):
	permission_blockers = _permission_blockers(doc)
	closing_blockers = []
	bank_blockers = []
	amendment_blocker = []
	blockers = list(permission_blockers)
	if doc.docstatus in (0, 1):
		closing_blockers = _get_closing_blockers(doc)
		blockers.extend(closing_blockers)
	if doc.docstatus == 1:
		bank_blockers = _get_bank_blockers(doc)
		blockers.extend(bank_blockers)
		if _has_existing_amendment(doc):
			amendment_blocker.append(_("该凭证已经存在修订凭证，不能重复修订"))
			blockers.extend(amendment_blocker)

	if doc.docstatus == 0:
		action = "open_draft"
	elif doc.docstatus == 1:
		action = "amend"
	else:
		action = "unavailable"
		blockers.append(_("已取消的凭证不能从查凭证重复发起修订"))

	quick_unreconcile = None
	if (
		doc.docstatus == 1
		and bank_blockers
		and not permission_blockers
		and not closing_blockers
		and not amendment_blocker
		and not (doc.doctype == "Journal Entry" and len(doc.get("accounts") or []) > 100)
	):
		quick_unreconcile = _get_quick_unreconcile_info(doc)

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
		"quick_unreconcile": quick_unreconcile,
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
	_reset_amendment_workflow_state(amended)
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
		"docstatus": amended.docstatus,
		"workflow_state": amended.get("workflow_state"),
		"message": _("原凭证已取消，修订凭证 {0} 已生成草稿；修改并保存后将自动审核并记账").format(
			amended.name
		),
	}


@frappe.whitelist()
def unreconcile_and_prepare_source_voucher_edit(source_doctype, source_name):
	"""Remove this JE's sole full bank match, then immediately create its amendment draft."""
	doc = _get_source_document(source_doctype, source_name)
	if source_doctype != "Journal Entry":
		frappe.throw(_("一键撤销核销并修改目前仅支持记账凭证"))

	_lock_source_row(source_doctype, source_name)
	doc = _get_source_document(source_doctype, source_name)
	status = _build_status(doc)
	quick_info = status.get("quick_unreconcile")
	if not quick_info:
		frappe.throw(_("当前银行流水不满足安全的一键撤销条件，请按提示先手动撤销核销"))

	bank_transaction_name = quick_info["bank_transaction"]
	if not frappe.db.sql(
		"SELECT name FROM `tabBank Transaction` WHERE name=%s FOR UPDATE",
		(bank_transaction_name,),
	):
		frappe.throw(_("银行流水不存在或已被删除，请刷新后重试"))

	bank_transaction = frappe.get_doc("Bank Transaction", bank_transaction_name)
	if not bank_transaction.has_permission("write"):
		frappe.throw(_("当前用户没有修改该银行流水的权限"), frappe.PermissionError)
	quick_info = _get_quick_unreconcile_info(doc)
	if not quick_info or quick_info["bank_transaction"] != bank_transaction_name:
		frappe.throw(_("银行流水状态已变化，请刷新后重试"))

	entry = next(
		(
			row
			for row in bank_transaction.payment_entries
			if row.payment_document == doc.doctype and row.payment_entry == doc.name
		),
		None,
	)
	if not entry:
		frappe.throw(_("未找到当前凭证对应的银行对账分配，请刷新后重试"))

	bank_transaction.remove_payment_entry(entry)
	bank_transaction.save()

	result = prepare_source_voucher_edit(source_doctype, source_name)
	if result.get("name"):
		result["unreconciled_bank_transaction"] = bank_transaction_name
		result["message"] = _(
			"已撤销银行流水 {0} 中与当前凭证对应的核销，并生成修订草稿 {1}"
		).format(bank_transaction_name, result["name"])
	return result


@frappe.whitelist()
def complete_source_voucher_edit(source_doctype, source_name):
	"""Automatically review and post an amended voucher after its real edit is saved."""
	doc = _get_source_document(source_doctype, source_name)
	if doc.docstatus != 0 or not doc.get("amended_from"):
		frappe.throw(_("只有已保存的修订草稿才能自动审核并记账"))

	if not doc.has_permission("write") or not doc.has_permission("submit"):
		frappe.throw(_("当前用户没有保存并记账该修订凭证的权限"), frappe.PermissionError)

	if not _has_meaningful_amendment_changes(doc):
		return {
			"posted": False,
			"name": doc.name,
			"message": _("未检测到凭证内容变化，修订草稿暂未记账"),
		}

	doc = _complete_voucher_workflow(doc)
	bank_transaction_names = _get_bank_transaction_names(doc)
	if bank_transaction_names and frappe.db.has_column("Bank Transaction", "custom_china_journal_entry"):
		for bank_transaction_name in bank_transaction_names:
			frappe.db.set_value(
				"Bank Transaction",
				bank_transaction_name,
				"custom_china_journal_entry",
				doc.name,
				update_modified=False,
			)
	bank_reconciliation = _get_bank_reconciliation_feedback(doc, bank_transaction_names)
	message = _("修订凭证 {0} 已自动审核并记账").format(doc.name)
	if bank_reconciliation["status"] == "success":
		message += _("；关联银行流水 {0} 已自动重新核销").format(
			"、".join(row["name"] for row in bank_reconciliation["successful"])
		)
	elif bank_reconciliation["status"] == "failed":
		message += _("；但关联银行流水未能自动重新核销，请及时处理")

	return {
		"posted": True,
		"name": doc.name,
		"docstatus": doc.docstatus,
		"workflow_state": doc.get("workflow_state"),
		"doc": doc.as_dict(),
		"bank_reconciliation": bank_reconciliation,
		"message": message,
	}
