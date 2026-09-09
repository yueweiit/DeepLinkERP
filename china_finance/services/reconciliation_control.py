import json

import frappe
from frappe import _
from frappe.utils import flt, getdate, now_datetime


FINANCE_MANAGERS = ("System Manager", "Accounts Manager", "China Finance Manager")
RECONCILIATION_USERS = (*FINANCE_MANAGERS, "Accounts User")


def get_tolerance(company):
	return flt(frappe.db.get_value("China Finance Settings", company, "reconciliation_tolerance") or 0.01)


def get_active_scopes(company, from_date, to_date):
	from_date, to_date = getdate(from_date), getdate(to_date)
	scopes = frappe.get_all(
		"China Reconciliation Scope",
		filters={"company": company, "enabled": 1, "effective_from": ["<=", to_date]},
		fields=[
			"name", "company", "scope_type", "reference_doctype", "reference_name",
			"confirmation_method", "amount_tolerance", "effective_from", "effective_to",
		],
		order_by="scope_type, reference_name",
	)
	return [scope for scope in scopes if not scope.effective_to or getdate(scope.effective_to) >= from_date]


def get_native_bank_reconciliation_data(bank_account, account, company, to_date):
	from erpnext.accounts.doctype.bank_reconciliation_tool.bank_reconciliation_tool import get_account_balance
	from erpnext.accounts.report.bank_reconciliation_statement.bank_reconciliation_statement import get_entries

	filters = frappe._dict(account=account, company=company, report_date=to_date, include_pos_transactions=1)
	return get_account_balance(bank_account, to_date, company), get_entries(filters)


@frappe.whitelist()
def generate_required_statements(company, from_date, to_date):
	frappe.only_for(RECONCILIATION_USERS)
	from china_finance.services.reconciliation import generate_statement

	from_date, to_date = getdate(from_date), getdate(to_date)
	result = {"processed": 0, "succeeded": 0, "failed": 0, "created": 0, "existing": 0, "results": [], "errors": []}
	for scope in get_active_scopes(company, from_date, to_date):
		result["processed"] += 1
		try:
			existing = frappe.db.get_value(
				"China Reconciliation Statement",
				{"scope": scope.name, "from_date": from_date, "to_date": to_date, "status": ["!=", "Superseded"]},
				"name",
				order_by="version desc",
			)
			if existing:
				result["existing"] += 1
				name = existing
			else:
				name = generate_statement(company, scope.scope_type, from_date, to_date, scope=scope.name)["name"]
				result["created"] += 1
			result["succeeded"] += 1
			result["results"].append({"scope": scope.name, "statement": name})
		except Exception as exc:
			result["failed"] += 1
			result["errors"].append({"scope": scope.name, "error": str(exc)})
	return result


def carry_forward_timing_differences(statement_name):
	statement = frappe.get_doc("China Reconciliation Statement", statement_name)
	if not statement.scope:
		return 0
	previous = frappe.get_all(
		"China Reconciliation Difference",
		filters={"scope": statement.scope, "status": "Approved Timing", "statement": ["!=", statement.name]},
		fields=["name", "difference_type", "amount", "source_doctype", "source_name", "reason", "owner_user", "due_date"],
		order_by="creation asc",
	)
	created = 0
	for row in previous:
		if frappe.db.exists("China Reconciliation Difference", {"carried_from": row.name}):
			continue
		frappe.get_doc(
			{
				"doctype": "China Reconciliation Difference", "statement": statement.name,
				"difference_type": row.difference_type, "amount": row.amount,
				"source_doctype": row.source_doctype, "source_name": row.source_name,
				"carried_from": row.name, "reason": row.reason, "owner_user": row.owner_user,
				"due_date": row.due_date, "status": "Open",
			}
		).insert(ignore_permissions=True)
		created += 1
	return created


def refresh_bank_snapshot(statement, save=False):
	if isinstance(statement, str):
		statement = frappe.get_doc("China Reconciliation Statement", statement)
	if statement.statement_type != "Bank" or not statement.bank_account:
		frappe.throw(_("只有已选择银行账户的银行对账单可以生成快照"))
	if statement.docstatus:
		frappe.throw(_("已提交银行对账快照不可重新生成"))

	account = frappe.db.get_value("Bank Account", statement.bank_account, "account")
	if not account:
		frappe.throw(_("银行账户未关联会计科目"))
	from_date = getdate(statement.from_date)
	to_date = getdate(statement.to_date)
	calculated_bank_balance, book_entries = get_native_bank_reconciliation_data(
		statement.bank_account, account, statement.company, to_date
	)
	bank_transactions = frappe.get_all(
		"Bank Transaction",
		filters={"company": statement.company, "bank_account": statement.bank_account, "docstatus": 1, "date": ["<=", to_date]},
		fields=["name", "date", "deposit", "withdrawal", "unallocated_amount", "status", "description"],
		order_by="date, name",
	)
	tolerance = get_tolerance(statement.company)
	unallocated = [row for row in bank_transactions if abs(flt(row.unallocated_amount)) > tolerance]
	opening_book_entries = [row for row in book_entries if getdate(row.get("posting_date")) < from_date]
	period_book_entries = [row for row in book_entries if getdate(row.get("posting_date")) >= from_date]
	period_bank_transactions = [row for row in bank_transactions if getdate(row.date) >= from_date]
	statement.account = account
	statement.calculated_bank_balance = flt(calculated_bank_balance, 2)
	statement.outstanding_book_count = len(book_entries)
	statement.opening_outstanding_book_count = len(opening_book_entries)
	statement.period_outstanding_book_count = len(period_book_entries)
	statement.unallocated_bank_count = len(unallocated)
	statement.unallocated_bank_amount = sum(flt(row.unallocated_amount) for row in unallocated)
	statement.bank_snapshot_json = json.dumps(
		{
			"generated_on": str(now_datetime()),
			"book_outstanding": book_entries,
			"book_outstanding_opening": opening_book_entries,
			"book_outstanding_period": period_book_entries,
			"bank_transactions_period": period_bank_transactions,
			"unallocated_bank_transactions": unallocated,
		},
		ensure_ascii=False, sort_keys=True, default=str,
	)
	lines = []
	# 期初未达账项仍保留在银行快照和余额计算中，但不放入本期明细，避免历史凭证混入本期对账单。
	for row in period_book_entries:
		lines.append(
			{
				"period_category": "本期未达",
				"line_source": "Book Outstanding", "match_status": "Timing", "posting_date": row.get("posting_date"),
				"voucher_type": row.get("payment_document"), "voucher_no": row.get("payment_entry"), "account": account,
				"remarks": row.get("against_account") or row.get("reference_no"), "debit": row.get("debit"),
				"credit": row.get("credit"), "reconciling_amount": flt(row.get("credit")) - flt(row.get("debit")),
			}
		)
	for row in period_bank_transactions:
		matched = abs(flt(row.unallocated_amount)) <= tolerance
		lines.append(
			{
				"period_category": "本期银行流水", "line_source": "Bank Transaction",
				"match_status": "Matched" if matched else "Unmatched", "posting_date": row.date,
				"voucher_type": "Bank Transaction", "voucher_no": row.name, "account": account,
				"remarks": row.description, "debit": row.deposit, "credit": row.withdrawal,
				"reconciling_amount": 0 if matched else flt(row.deposit) - flt(row.withdrawal),
			}
		)
	category_order = {"本期未达": 1, "本期银行流水": 2}
	lines.sort(key=lambda row: (category_order.get(row.get("period_category"), 99), getdate(row.get("posting_date")), row.get("voucher_no") or ""))
	statement.set("lines", lines)
	if save:
		statement.save()
	return statement


@frappe.whitelist()
def generate_bank_reconciliation_snapshot(name):
	frappe.only_for(RECONCILIATION_USERS)
	statement = refresh_bank_snapshot(name, save=True)
	return {
		"name": statement.name, "calculated_bank_balance": statement.calculated_bank_balance,
		"outstanding_book_count": statement.outstanding_book_count,
		"unallocated_bank_count": statement.unallocated_bank_count,
	}


@frappe.whitelist()
def create_difference(statement, difference_type, amount, reason, owner_user, due_date, source_doctype=None, source_name=None):
	frappe.only_for(RECONCILIATION_USERS)
	doc = frappe.get_doc(
		{
			"doctype": "China Reconciliation Difference", "statement": statement,
			"difference_type": difference_type, "amount": flt(amount), "reason": reason,
			"owner_user": owner_user, "due_date": getdate(due_date), "source_doctype": source_doctype,
			"source_name": source_name,
		}
	).insert()
	return {"name": doc.name, "status": doc.status}


def _open_difference(name):
	doc = frappe.get_doc("China Reconciliation Difference", name)
	if doc.status != "Open":
		frappe.throw(_("只有待处理差异可以变更状态"))
	return doc


@frappe.whitelist()
def resolve_difference(name, resolution_notes, resolution_doctype=None, resolution_name=None, evidence_file=None):
	frappe.only_for(FINANCE_MANAGERS)
	doc = _open_difference(name)
	if resolution_name and not resolution_doctype:
		frappe.throw(_("填写处理单据时必须选择单据类型"))
	if not resolution_name and not evidence_file:
		frappe.throw(_("确认解决必须关联处理单据或上传处理附件"))
	doc.db_set("status", "Resolved")
	doc.db_set("resolution_doctype", resolution_doctype)
	doc.db_set("resolution_name", resolution_name)
	doc.db_set("resolution_notes", resolution_notes)
	doc.db_set("evidence_file", evidence_file)
	doc.db_set("resolved_by", frappe.session.user)
	doc.db_set("resolved_on", now_datetime())
	return {"name": doc.name, "status": "Resolved"}


@frappe.whitelist()
def approve_timing_difference(name):
	frappe.only_for(FINANCE_MANAGERS)
	doc = _open_difference(name)
	if doc.difference_type not in ("Book Timing", "Bank Timing"):
		frappe.throw(_("只有账面或银行时间性差异可以批准跨期跟踪"))
	doc.db_set("status", "Approved Timing")
	doc.db_set("approved_by", frappe.session.user)
	doc.db_set("approved_on", now_datetime())
	return {"name": doc.name, "status": "Approved Timing"}


@frappe.whitelist()
def waive_difference(name, resolution_notes, evidence_file=None):
	frappe.only_for(FINANCE_MANAGERS)
	if not evidence_file:
		frappe.throw(_("豁免差异必须上传审批附件"))
	doc = _open_difference(name)
	doc.db_set("status", "Waived")
	doc.db_set("resolution_notes", resolution_notes)
	doc.db_set("evidence_file", evidence_file)
	doc.db_set("approved_by", frappe.session.user)
	doc.db_set("approved_on", now_datetime())
	return {"name": doc.name, "status": "Waived"}


def get_reconciliation_closing_checks(company, from_date, to_date):
	scopes = get_active_scopes(company, from_date, to_date)
	missing, statements = [], []
	for scope in scopes:
		statement = frappe.db.get_value(
			"China Reconciliation Statement",
			{
				"scope": scope.name, "from_date": getdate(from_date), "to_date": getdate(to_date),
				"docstatus": 1, "status": "Confirmed",
			},
			"name",
			order_by="version desc",
		)
		if statement:
			statements.append(statement)
		else:
			missing.append({"scope": scope.name, "type": scope.scope_type, "reference": scope.reference_name})
	open_count = timing_count = 0
	if statements:
		open_count = frappe.db.count("China Reconciliation Difference", {"statement": ["in", statements], "status": "Open"})
		timing_count = frappe.db.count(
			"China Reconciliation Difference", {"statement": ["in", statements], "status": "Approved Timing"}
		)
	stale_drafts = frappe.db.count(
		"China Reconciliation Statement", {"company": company, "to_date": ["<=", getdate(to_date)], "docstatus": 0}
	)
	return {
		"coverage": {
			"passed": not missing, "required": len(scopes), "confirmed": len(statements), "missing": missing,
			"details": _("强制对账 {0} 项，已确认 {1} 项，缺失 {2} 项").format(len(scopes), len(statements), len(missing)),
		},
		"differences": {
			"passed": open_count == 0, "open_count": open_count, "timing_count": timing_count,
			"details": _("待处理差异 {0} 项，已批准时间性差异 {1} 项").format(open_count, timing_count),
		},
		"drafts": {"passed": True, "count": stale_drafts, "details": _("未纳入强制覆盖的待确认草稿 {0} 张").format(stale_drafts)},
	}


@frappe.whitelist()
def preview_reconciliation_coverage(company, from_date, to_date):
	frappe.only_for((*FINANCE_MANAGERS, "China Finance Auditor"))
	return get_reconciliation_closing_checks(company, getdate(from_date), getdate(to_date))
