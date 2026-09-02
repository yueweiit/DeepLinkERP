import hashlib
import json
from decimal import Decimal

import frappe
from frappe import _
from frappe.utils import cint, flt, getdate, now_datetime


GL_SOURCE_DOCTYPES = (
	"Journal Entry",
	"Payment Entry",
	"Sales Invoice",
	"Purchase Invoice",
	"Stock Entry",
	"Delivery Note",
	"Purchase Receipt",
	"Asset",
	"Asset Capitalization",
	"Asset Depreciation Entry",
	"Payroll Entry",
	"Period Closing Voucher",
)

FORMAL_VOUCHER_SOURCES = ("Journal Entry", "Payment Entry")

SNAPSHOT_RETRY_ROLES = ("System Manager", "China Finance Manager")
SNAPSHOT_BACKLINK_DOCTYPES = ("China Accounting Voucher", "China Cash Flow Assignment")


def _get_source_document(source_doctype, source_name):
	if source_doctype not in GL_SOURCE_DOCTYPES:
		frappe.throw(_("{0} 不是支持的总账来源单据").format(source_doctype))
	if not frappe.db.exists(source_doctype, source_name):
		frappe.throw(_("来源单据不存在"))
	doc = frappe.get_doc(source_doctype, source_name)
	if not doc.has_permission("read"):
		frappe.throw(_("无权查看来源单据"), frappe.PermissionError)
	return doc


def get_company_settings(company):
	if not company or not frappe.db.exists("DocType", "China Finance Settings"):
		return None
	name = frappe.db.get_value(
		"China Finance Settings",
		{"company": company, "enabled": 1},
		"name",
	)
	return frappe.get_cached_doc("China Finance Settings", name) if name else None


def get_posting_date(doc):
	for fieldname in ("posting_date", "transaction_date", "purchase_date"):
		if doc.meta.has_field(fieldname) and doc.get(fieldname):
			return getdate(doc.get(fieldname))
	return getdate(doc.creation)


def get_company(doc):
	if doc.meta.has_field("company") and doc.get("company"):
		return doc.company
	return None


def validate_source_approval(doc, method=None):
	settings = get_company_settings(get_company(doc))
	if not settings or not settings.enforce_role_separation:
		return
	posting_date = get_posting_date(doc)
	if posting_date < getdate(settings.activation_date):
		return
	workflow_name = frappe.db.get_value("Workflow", {"document_type": doc.doctype, "is_active": 1}, "name")
	if not workflow_name:
		frappe.throw(_("{0} 已启用制单审核分离，但 {1} 没有启用审批工作流").format(settings.company, doc.doctype))
	reviewer = get_reviewer(doc.doctype, doc.name)
	if not reviewer:
		frappe.throw(_("单据尚未完成独立审核，不能记账"))
	if reviewer in {doc.owner, frappe.session.user}:
		frappe.throw(_("制单人、审核人和记账人不能由同一用户兼任"))


def on_gl_source_submit(doc, method=None):
	create_voucher_from_source(doc, "Posting")


def on_gl_source_cancel(doc, method=None):
	"""Do not let an audit snapshot failure roll back an ERPNext cancellation."""
	# The snapshot and its cash-flow assignment dynamically link back to the
	# source document. They are audit records, not business dependants, so they
	# must not trigger Frappe's "cancel all linked documents" flow.
	_ignore_snapshot_backlinks(doc)
	settings = get_company_settings(get_company(doc))
	if not settings or getdate(get_posting_date(doc)) < getdate(settings.activation_date):
		return
	issue = _ensure_cancellation_sync_issue(doc)
	try:
		frappe.enqueue(
			"china_finance.services.voucher.process_cancellation_snapshot",
			queue="short",
			enqueue_after_commit=True,
			source_doctype=doc.doctype,
			source_name=doc.name,
			issue_name=issue.name,
		)
	except Exception as exc:
		_record_sync_failure(issue.name, exc)
		frappe.log_error(title=_("中国会计凭证冲销快照排队失败"), message=frappe.get_traceback())


def prepare_source_cancellation(doc, method=None):
	"""Exclude audit-only backlinks before Frappe validates source cancellation."""
	_ignore_snapshot_backlinks(doc)


def _ignore_snapshot_backlinks(doc):
	existing = doc.get("ignore_linked_doctypes") or ()
	if isinstance(existing, str):
		existing = (existing,)
	doc.ignore_linked_doctypes = tuple(dict.fromkeys((*existing, *SNAPSHOT_BACKLINK_DOCTYPES)))


def _cancellation_issue_key(doc):
	return f"Cancellation|{doc.doctype}|{doc.name}"


def _ensure_cancellation_sync_issue(doc):
	issue_key = _cancellation_issue_key(doc)
	name = frappe.db.get_value("China Voucher Sync Issue", {"issue_key": issue_key}, "name")
	if name:
		return frappe.get_doc("China Voucher Sync Issue", name)
	issue = frappe.get_doc(
		{
			"doctype": "China Voucher Sync Issue",
			"company": get_company(doc),
			"posting_date": get_posting_date(doc),
			"source_doctype": doc.doctype,
			"source_name": doc.name,
			"issue_key": issue_key,
			"status": "Pending",
		}
	)
	issue.flags.ignore_permissions = True
	try:
		issue.insert()
	except frappe.DuplicateEntryError:
		issue = frappe.get_doc("China Voucher Sync Issue", {"issue_key": issue_key})
	return issue


def _record_sync_failure(issue_name, exc):
	frappe.db.set_value(
		"China Voucher Sync Issue",
		issue_name,
		{"status": "Pending", "last_attempted_on": now_datetime(), "last_error": str(exc)},
		update_modified=False,
	)


def process_cancellation_snapshot(source_doctype, source_name, issue_name=None):
	"""Idempotently create the cancellation snapshot after the source cancellation commits."""
	if source_doctype not in GL_SOURCE_DOCTYPES or not frappe.db.exists(source_doctype, source_name):
		return {"status": "skipped", "reason": "source_not_found"}
	doc = frappe.get_doc(source_doctype, source_name)
	issue = frappe.get_doc("China Voucher Sync Issue", issue_name) if issue_name else _ensure_cancellation_sync_issue(doc)
	frappe.db.set_value(
		"China Voucher Sync Issue", issue.name,
		{"retry_count": cint(issue.retry_count) + 1, "last_attempted_on": now_datetime(), "last_error": None},
		update_modified=False,
	)
	try:
		if doc.docstatus != 2:
			raise frappe.ValidationError(_("来源单据尚未取消，不能生成冲销审计快照"))
		from china_finance.services.cash_flow_assignment import cancel_assignments_for_source

		cancel_assignments_for_source(doc)
		voucher_name = create_voucher_from_source(doc, "Cancellation")
		if not voucher_name:
			raise frappe.ValidationError(_("未找到可生成冲销审计快照的总账分录"))
		frappe.db.set_value(
			"China Voucher Sync Issue",
			issue.name,
			{
				"status": "Resolved", "cancellation_voucher": voucher_name,
				"resolved_on": now_datetime(), "last_error": None,
			},
			update_modified=False,
		)
		return {"status": "resolved", "issue": issue.name, "voucher": voucher_name}
	except Exception as exc:
		_record_sync_failure(issue.name, exc)
		frappe.log_error(title=_("中国会计凭证冲销快照补齐失败"), message=frappe.get_traceback())
		return {"status": "pending", "issue": issue.name, "error": str(exc)}


def get_pending_cancellation_sync_issues(company, from_date, to_date):
	issues = frappe.get_all(
		"China Voucher Sync Issue",
		filters={
			"company": company,
			"posting_date": ["between", [from_date, to_date]],
			"status": "Pending",
		},
		fields=["name", "source_doctype", "source_name", "last_error", "retry_count"],
	)
	pending = []
	for issue in issues:
		# A cancelled source may later be deleted in ERPNext. Keep the audit row,
		# but do not leave an impossible retry as a permanent month-end blocker.
		if not frappe.db.exists(issue.source_doctype, issue.source_name):
			frappe.db.set_value(
				"China Voucher Sync Issue",
				issue.name,
				{
					"status": "Resolved",
					"resolved_on": now_datetime(),
					"last_error": _("来源业务单据已删除，无需补齐冲销审计快照"),
				},
				update_modified=False,
			)
			continue
		pending.append(issue)
	return pending


@frappe.whitelist()
def retry_cancellation_snapshot(issue_name):
	frappe.only_for(SNAPSHOT_RETRY_ROLES)
	issue = frappe.get_doc("China Voucher Sync Issue", issue_name)
	if issue.status != "Pending":
		return {"status": issue.status, "issue": issue.name, "voucher": issue.cancellation_voucher}
	return process_cancellation_snapshot(issue.source_doctype, issue.source_name, issue.name)


@frappe.whitelist()
def get_source_snapshot_status(source_doctype, source_name):
	doc = _get_source_document(source_doctype, source_name)
	settings = get_company_settings(get_company(doc))
	if not settings:
		return {"not_applicable": True}
	voucher_name = frappe.db.get_value(
		"China Accounting Voucher", {"source_key": f"Posting|{source_doctype}|{source_name}"}, "name"
	)
	if not voucher_name:
		from china_finance.services.cash_equivalent_scope import get_cash_scope_accounts
		cash_accounts = get_cash_scope_accounts(get_company(doc), now_datetime().date())
		has_cash_entry = bool(cash_accounts and frappe.db.exists(
			"GL Entry",
			{
				"voucher_type": source_doctype,
				"voucher_no": source_name,
				"account": ["in", cash_accounts],
				"is_cancelled": 0,
			},
		))
		return {
			"snapshot_ready": False,
			"can_create_assignment": has_cash_entry,
			"reason": _("审计快照尚未生成"),
		}
	voucher = frappe.get_doc("China Accounting Voucher", voucher_name)
	assignment = frappe.db.get_value(
		"China Cash Flow Assignment",
		{"china_accounting_voucher": voucher.name},
		["name", "status"],
		as_dict=True,
		order_by="revision desc, creation desc",
	)
	from china_finance.services.cash_flow_assignment import get_cash_legs_for_voucher

	cash_legs = get_cash_legs_for_voucher(voucher)
	needs_assignment = bool(doc.docstatus == 1 and cash_legs)
	return {
		"snapshot_ready": voucher.docstatus == 1,
		"snapshot_name": voucher.name,
		"statutory_number": voucher.statutory_number,
		"can_view_snapshot": voucher.has_permission("read"),
		"assignment": assignment,
		"assignment_required": needs_assignment,
		"assignment_reason": _("该单据不包含现金/银行分录") if not needs_assignment and not assignment else "",
	}


@frappe.whitelist()
def create_cash_flow_assignment_from_source(source_doctype, source_name):
	frappe.only_for(("Accounts User", "China Finance User", "Accounts Manager", "China Finance Manager", "System Manager"))
	doc = _get_source_document(source_doctype, source_name)
	if doc.docstatus != 1:
		frappe.throw(_("仅已提交来源单据可以指定现金流量"))
	voucher_name = frappe.db.get_value(
		"China Accounting Voucher", {"source_key": f"Posting|{source_doctype}|{source_name}", "docstatus": 1}, "name"
	)
	if not voucher_name:
		voucher_name = create_voucher_from_source(doc, "Posting", force=True)
	if not voucher_name:
		frappe.throw(_("审计快照尚未生成，且来源单据没有可用总账分录"))
	from china_finance.services.cash_flow_assignment import create_cash_flow_assignment

	name = create_cash_flow_assignment(voucher_name)
	if not name:
		frappe.throw(_("该单据不包含需要指定的外部现金流"))
	return {"name": name}


@frappe.whitelist()
def recreate_cash_flow_assignment_from_source(source_doctype, source_name):
	frappe.only_for(("Accounts User", "China Finance User", "Accounts Manager", "China Finance Manager", "System Manager"))
	_get_source_document(source_doctype, source_name)
	voucher_name = frappe.db.get_value(
		"China Accounting Voucher", {"source_key": f"Posting|{source_doctype}|{source_name}", "docstatus": 1}, "name"
	)
	if not voucher_name:
		frappe.throw(_("审计快照尚未生成"))
	assignment_name = frappe.db.get_value(
		"China Cash Flow Assignment",
		{"china_accounting_voucher": voucher_name, "status": "Cancelled"},
		"name",
		order_by="revision desc, creation desc",
	)
	if not assignment_name:
		frappe.throw(_("没有可重新创建的已作废现金流量指定单"))
	from china_finance.services.cash_flow_assignment import recreate_cash_flow_assignment

	return recreate_cash_flow_assignment(assignment_name)


def create_voucher_from_source(doc, source_event="Posting", force=False):
	company = get_company(doc)
	settings = get_company_settings(company)
	if not settings:
		return None
	posting_date = get_posting_date(doc)
	if posting_date < getdate(settings.activation_date) and not force:
		return None

	source_key = f"{source_event}|{doc.doctype}|{doc.name}"
	existing = frappe.db.get_value("China Accounting Voucher", {"source_key": source_key}, "name")
	if existing:
		return existing

	entries = get_gl_entries(doc.doctype, doc.name, cancelled=source_event == "Cancellation")
	reversal_of = None
	if source_event == "Cancellation":
		reversal_of = frappe.db.get_value(
			"China Accounting Voucher",
			{"source_key": f"Posting|{doc.doctype}|{doc.name}", "docstatus": 1},
			"name",
		)
		if not entries and reversal_of:
			entries = reverse_voucher_entries(reversal_of)
	if not entries:
		return None

	voucher_word = classify_voucher_word(entries, settings)
	company_currency = frappe.get_cached_value("Company", company, "default_currency")
	voucher = frappe.get_doc(
		{
			"doctype": "China Accounting Voucher",
			"company": company,
			"posting_date": posting_date,
			"voucher_word": voucher_word,
			"source_doctype": doc.doctype,
			"source_name": doc.name,
			"source_event": source_event,
			"source_key": source_key,
			"reversal_of": reversal_of,
			"prepared_by": doc.owner,
			"reviewed_by": get_reviewer(doc.doctype, doc.name),
			"posted_by": frappe.session.user,
			"currency": company_currency,
			"remarks": getattr(doc, "remarks", None) or getattr(doc, "user_remark", None),
			"entries": entries,
		}
	)
	voucher.flags.ignore_permissions = True
	# The cancellation snapshot must retain the link to its cancelled source
	# document. Frappe normally rejects links to cancelled documents, but this
	# audit snapshot is created precisely because the source was cancelled.
	if source_event == "Cancellation":
		voucher.flags.ignore_links = True
	voucher.insert()
	voucher.submit()
	if doc.doctype in ("Journal Entry", "Payment Entry") and frappe.db.has_column(doc.doctype, "custom_china_voucher_number"):
		frappe.db.set_value(
			doc.doctype,
			doc.name,
			"custom_china_voucher_number",
			voucher.statutory_number,
			update_modified=False,
		)
	if source_event == "Posting":
		from china_finance.services.cash_flow_assignment import create_assignment_if_required

		create_assignment_if_required(voucher.name)
	if reversal_of:
		frappe.db.set_value(
			"China Accounting Voucher",
			reversal_of,
			{"status": "Reversed", "reversed_by": voucher.name},
			update_modified=False,
		)
	return voucher.name


def get_gl_entries(voucher_type, voucher_no, cancelled=False):
	filters = {"voucher_type": voucher_type, "voucher_no": voucher_no}
	if frappe.db.has_column("GL Entry", "is_cancelled"):
		filters["is_cancelled"] = 1 if cancelled else 0
	rows = frappe.get_all(
		"GL Entry",
		filters=filters,
		fields=[
			"name", "account", "account_currency", "debit", "credit",
			"debit_in_account_currency", "credit_in_account_currency", "party_type", "party",
			"cost_center", "project", "finance_book", "against_voucher_type", "against_voucher", "remarks",
		],
		order_by="creation asc, name asc",
	)
	return [to_voucher_entry(row) for row in rows]


def to_voucher_entry(row):
	known_fields = {
		"name", "account", "account_currency", "debit", "credit", "debit_in_account_currency",
		"credit_in_account_currency", "party_type", "party", "cost_center", "project", "finance_book",
		"against_voucher_type", "against_voucher", "remarks",
	}
	return {
		"gl_entry": row.name,
		"account": row.account,
		"account_currency": row.account_currency,
		"debit": row.debit,
		"credit": row.credit,
		"debit_in_account_currency": row.debit_in_account_currency,
		"credit_in_account_currency": row.credit_in_account_currency,
		"party_type": row.party_type,
		"party": row.party,
		"cost_center": row.cost_center,
		"project": row.project,
		"finance_book": row.finance_book,
		"against_voucher_type": row.against_voucher_type,
		"against_voucher": row.against_voucher,
		"remarks": row.remarks,
		"dimensions_json": json.dumps({key: value for key, value in row.items() if key not in known_fields and value}, ensure_ascii=False),
	}


def reverse_voucher_entries(voucher_name):
	doc = frappe.get_doc("China Accounting Voucher", voucher_name)
	return [
		{
			"account": row.account,
			"account_currency": row.account_currency,
			"debit": row.credit,
			"credit": row.debit,
			"debit_in_account_currency": row.credit_in_account_currency,
			"credit_in_account_currency": row.debit_in_account_currency,
			"party_type": row.party_type,
			"party": row.party,
			"cost_center": row.cost_center,
			"project": row.project,
			"finance_book": row.finance_book,
			"against_voucher_type": row.against_voucher_type,
			"against_voucher": row.against_voucher,
			"remarks": _("冲销 {0}").format(doc.statutory_number),
			"dimensions_json": row.dimensions_json,
		}
		for row in doc.entries
	]


def classify_voucher_word(entries, settings):
	return "记"


def assign_voucher_number(voucher):
	if voucher.voucher_key:
		return
	if voucher.source_doctype not in FORMAL_VOUCHER_SOURCES:
		# Business-document snapshots remain available for ledger tracing, but
		# must not consume the formal accounting-voucher sequence.
		voucher.sequence_number = 0
		voucher.statutory_number = None
		voucher.voucher_key = f"business|{voucher.company}|{voucher.source_doctype}|{voucher.source_name}|{voucher.source_event}"
		return
	settings = get_company_settings(voucher.company)
	if not settings:
		frappe.throw(_("公司 {0} 未启用中国财务设置").format(voucher.company))
	period_key = voucher.accounting_period
	sequence_key = "|".join((voucher.company, voucher.fiscal_year, period_key, voucher.voucher_word, "formal"))

	row = frappe.db.sql(
		"SELECT name, current_value FROM `tabChina Voucher Sequence` WHERE sequence_key=%s FOR UPDATE",
		(sequence_key,),
		as_dict=True,
	)
	if not row:
		try:
			frappe.get_doc(
				{
					"doctype": "China Voucher Sequence",
					"sequence_key": sequence_key,
					"company": voucher.company,
					"fiscal_year": voucher.fiscal_year,
					"accounting_period": voucher.accounting_period,
					"voucher_word": voucher.voucher_word,
					"current_value": get_existing_formal_sequence(voucher, sequence_key),
				}
			).insert(ignore_permissions=True)
		except frappe.DuplicateEntryError:
			pass
		row = frappe.db.sql(
			"SELECT name, current_value FROM `tabChina Voucher Sequence` WHERE sequence_key=%s FOR UPDATE",
			(sequence_key,),
			as_dict=True,
		)

	sequence = cint(row[0].current_value) + 1
	frappe.db.set_value("China Voucher Sequence", row[0].name, "current_value", sequence, update_modified=False)
	voucher.sequence_number = sequence
	# The sequence key contains the accounting period, so the displayed
	# voucher mark restarts at 1 each month while remaining concise.
	voucher.statutory_number = f"{voucher.voucher_word}{sequence}"
	voucher.voucher_key = f"{sequence_key}|{sequence:08d}"


def get_existing_formal_sequence(voucher, sequence_key):
	"""Seed the new formal sequence from historical Journal/Payment vouchers."""
	return frappe.db.sql(
		"""
		SELECT COALESCE(MAX(sequence_number), 0)
		FROM `tabChina Accounting Voucher`
		WHERE company=%s AND fiscal_year=%s AND accounting_period=%s
			AND voucher_word=%s AND source_doctype IN ('Journal Entry', 'Payment Entry')
		""",
		(voucher.company, voucher.fiscal_year, voucher.accounting_period, voucher.voucher_word),
	)[0][0]


def calculate_entries_hash(entries):
	payload = []
	for row in entries:
		getter = row.get if hasattr(row, "get") else lambda key: getattr(row, key, None)
		payload.append(
			{
				"account": getter("account"),
				"debit": str(Decimal(str(getter("debit") or 0)).quantize(Decimal("0.01"))),
				"credit": str(Decimal(str(getter("credit") or 0)).quantize(Decimal("0.01"))),
				"party_type": getter("party_type"),
				"party": getter("party"),
				"cost_center": getter("cost_center"),
				"project": getter("project"),
				"finance_book": getter("finance_book"),
			}
		)
	canonical = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
	return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def get_reviewer(doctype, docname):
	if not frappe.db.exists("DocType", "Workflow Action"):
		return None
	return frappe.db.get_value(
		"Workflow Action",
		{"reference_doctype": doctype, "reference_name": docname, "status": "Completed", "completed_by": ["is", "set"]},
		"completed_by",
		order_by="modified desc",
	)


@frappe.whitelist()
def rebuild_missing_vouchers(company, from_date=None, to_date=None, limit=500):
	frappe.only_for(("System Manager", "China Finance Manager"))
	settings = get_company_settings(company)
	if not settings:
		frappe.throw(_("公司尚未启用中国财务"))
	filters = {"company": company, "is_cancelled": 0}
	filters["posting_date"] = ["between", [from_date or settings.activation_date, to_date or frappe.utils.today()]]
	rows = frappe.get_all(
		"GL Entry",
		filters=filters,
		fields=["voucher_type", "voucher_no"],
		group_by="voucher_type, voucher_no",
		limit_page_length=cint(limit),
	)
	result = {"processed": 0, "created": 0, "skipped": 0, "errors": []}
	for row in rows:
		result["processed"] += 1
		if not frappe.db.exists("DocType", row.voucher_type) or not frappe.db.exists(row.voucher_type, row.voucher_no):
			result["skipped"] += 1
			continue
		try:
			name = create_voucher_from_source(frappe.get_doc(row.voucher_type, row.voucher_no))
			result["created"] += int(bool(name))
		except Exception as exc:
			result["errors"].append({"doctype": row.voucher_type, "name": row.voucher_no, "error": str(exc)})
	return result


def backfill_enabled_company_vouchers(company, limit=200):
	"""Create missing historical snapshots without relying on activation_date."""
	frappe.only_for(SNAPSHOT_RETRY_ROLES)
	settings = get_company_settings(company)
	if not settings:
		return {"processed": 0, "created": 0, "skipped": 0, "errors": []}
	rows = frappe.db.sql(
		"""
		SELECT gl.voucher_type, gl.voucher_no
		FROM `tabGL Entry` gl
		LEFT JOIN `tabChina Accounting Voucher` voucher
			ON voucher.source_key=CONCAT('Posting|', gl.voucher_type, '|', gl.voucher_no)
		WHERE gl.company=%(company)s
			AND gl.is_cancelled=0
			AND gl.voucher_type IN %(voucher_types)s
			AND voucher.name IS NULL
		GROUP BY gl.voucher_type, gl.voucher_no
		ORDER BY MIN(gl.posting_date), gl.voucher_type, gl.voucher_no
		LIMIT %(limit)s
		""",
		{"company": company, "voucher_types": GL_SOURCE_DOCTYPES, "limit": cint(limit)},
		as_dict=True,
	)
	result = {"processed": 0, "created": 0, "skipped": 0, "errors": []}
	for row in rows:
		result["processed"] += 1
		try:
			if not frappe.db.exists(row.voucher_type, row.voucher_no):
				result["skipped"] += 1
				continue
			name = create_voucher_from_source(
				frappe.get_doc(row.voucher_type, row.voucher_no), force=True
			)
			result["created"] += int(bool(name))
		except Exception as exc:
			result["errors"].append({"doctype": row.voucher_type, "name": row.voucher_no, "error": str(exc)})
	return result
