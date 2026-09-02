"""China Finance additions around ERPNext's native bank reconciliation tool."""

import json
import re

import frappe
from frappe.utils import flt
from erpnext.accounts.doctype.bank_reconciliation_tool.bank_reconciliation_tool import (
	create_journal_entry_bts,
	get_bank_transactions,
	reconcile_vouchers,
)

# Default account mapping: description keyword -> account number
# Override via China Finance Settings if needed.
DEFAULT_ACCOUNT_MAPPING = {
	"利息": "660302",
	"手续费": "660303",
	"服务费": "660303",
	"报销": "660202",
	"社保": "221103",
	"工资": "221101",
	"代发": "221101",
	"招聘": "660211",
	"租金水电物业管理费": "660299",
	"租金": "660207",
	"物业水电": "660208",
	"物业": "660208",
	"缴税": "22210104",
	"公积金": "221104",
	"补缴": "221104",
	"投资": "4001",
	"退款": "1221",
	"退回": "1221",
	"验证": "1221",
	"实名": "1221",
}


@frappe.whitelist()
def get_bank_transactions_with_summary(*args, **kwargs):
	# Frappe injects the RPC command name into whitelisted calls; the native
	# ERPNext function only accepts the business arguments.
	kwargs.pop("cmd", None)
	transactions = get_bank_transactions(*args, **kwargs)
	if not transactions:
		return transactions

	names = [row.name for row in transactions]
	summaries = frappe.get_all(
		"Bank Transaction",
		filters={"name": ["in", names]},
		fields=["name", "custom_summary", "description"],
	)
	summary_map = {row.name: row.custom_summary for row in summaries}
	for row in transactions:
		stored = next((item for item in summaries if item.name == row.name), None)
		row.custom_summary = clean_bank_summary(
			(summary_map.get(row.name) or (stored.description if stored else ""))
		)
	return transactions


def clean_bank_summary(value):
	"""Keep the business summary and remove bank reference metadata from display."""
	value = (value or "").strip()
	if "｜" in value:
		value = value.split("｜", 1)[0].strip()
	value = re.split(r"\s*参考\s*#?.*$", value, maxsplit=1, flags=re.IGNORECASE)[0].strip()
	return value


def prepare_bank_transaction(doc, method=None):
	"""Persist useful CMB metadata before the standard Bank Transaction submit hook."""
	description = str(doc.description or "")
	if frappe.db.has_column("Bank Transaction", "custom_summary") and not doc.get("custom_summary"):
		doc.custom_summary = clean_bank_summary(description)

	metadata = {
		"bank_party_name": _extract_bank_metadata(description, "对方"),
		"bank_party_account_number": _extract_bank_metadata(description, "账号"),
		"transaction_type": _extract_bank_metadata(description, "交易类型") or doc.transaction_type,
	}
	for fieldname, value in metadata.items():
		if value and frappe.get_meta("Bank Transaction").has_field(fieldname) and not doc.get(fieldname):
			setattr(doc, fieldname, value)

	# CMB 流水号 is the stable idempotency key. Keep it in the native
	# transaction_id field as well as reference_number for reconciliation.
	if doc.reference_number and not doc.transaction_id:
		doc.transaction_id = str(doc.reference_number).strip()

	if doc.transaction_id and doc.bank_account:
		existing = frappe.db.get_value(
			"Bank Transaction",
			{
				"bank_account": doc.bank_account,
				"docstatus": ["!=", 2],
				"transaction_id": doc.transaction_id,
			},
			"name",
		)
		if not existing:
			existing = frappe.db.get_value(
				"Bank Transaction",
				{
					"bank_account": doc.bank_account,
					"docstatus": ["!=", 2],
					"reference_number": doc.reference_number,
				},
				"name",
			)
		if existing and existing != doc.name:
			frappe.throw(_("银行流水 {0} 已导入为 {1}，请勿重复导入。" ).format(doc.transaction_id, existing))


def _extract_bank_metadata(description, label):
	match = re.search(rf"(?:^|｜){re.escape(label)}：([^｜]*)", description or "")
	return match.group(1).strip() if match else ""


@frappe.whitelist()
def create_journal_entry_with_summary(remarks=None, **kwargs):
	"""Create an editable Journal Entry draft and link it to the bank transaction."""
	kwargs.pop("cmd", None)
	kwargs.pop("allow_edit", None)
	bank_transaction_name = kwargs.get("bank_transaction_name")
	if bank_transaction_name:
		bank_transaction = frappe.get_doc("Bank Transaction", bank_transaction_name)
		_validate_bank_account_company(bank_transaction.bank_account, bank_transaction.company)
	journal_entry = create_journal_entry_bts(**kwargs, allow_edit=True)
	if remarks:
		if journal_entry.meta.has_field("user_remark"):
			journal_entry.user_remark = remarks
		if journal_entry.meta.has_field("remark"):
			journal_entry.remark = remarks
		for entry in journal_entry.accounts:
			entry.user_remark = remarks
	if journal_entry.meta.has_field("custom_china_bank_transaction"):
		journal_entry.custom_china_bank_transaction = kwargs["bank_transaction_name"]
	journal_entry.insert()
	if frappe.db.has_column("Bank Transaction", "custom_china_journal_entry"):
		frappe.db.set_value(
			"Bank Transaction",
			kwargs["bank_transaction_name"],
			"custom_china_journal_entry",
			journal_entry.name,
			update_modified=False,
		)
	return journal_entry


def on_journal_entry_submit(doc, method=None):
	"""Reconcile a reviewed bank-generated Journal Entry after it is submitted."""
	bank_transaction_name = doc.get("custom_china_bank_transaction")
	if not bank_transaction_name or not frappe.db.exists("Bank Transaction", bank_transaction_name):
		return

	bank_transaction = frappe.get_doc("Bank Transaction", bank_transaction_name)
	if bank_transaction.docstatus != 1 or flt(bank_transaction.allocated_amount) > 0:
		return

	if frappe.db.has_column("Bank Transaction", "custom_china_journal_entry"):
		frappe.db.set_value(
			"Bank Transaction",
			bank_transaction_name,
			"custom_china_journal_entry",
			doc.name,
			update_modified=False,
		)

	amount = flt(bank_transaction.deposit) if flt(bank_transaction.deposit) > 0 else flt(bank_transaction.withdrawal)
	if amount <= 0:
		return

	try:
		reconcile_vouchers(
			bank_transaction_name,
			json.dumps([{
				"payment_doctype": "Journal Entry",
				"payment_name": doc.name,
				"amount": amount,
			}]),
		)
	except Exception:
		frappe.log_error(
			f"Bank reconciliation after Journal Entry submit failed for {doc.name}: {frappe.get_traceback()}",
			"Bank Reconciliation After Journal Entry Submit",
		)


def auto_create_voucher_on_submit(doc, method=None):
	"""Create a draft Journal Entry when a Bank Transaction is submitted.

	Called via doc_events on_submit hook. Only creates a voucher if:
	- The bank transaction has no allocated amount yet
	- A matching bank account GL account exists
	"""
	if flt(doc.allocated_amount) > 0:
		return
	if (
		frappe.db.has_column("Bank Transaction", "custom_china_journal_entry")
		and doc.get("custom_china_journal_entry")
		and frappe.db.exists("Journal Entry", doc.custom_china_journal_entry)
	):
		return

	bank_account_gl = _get_valid_bank_account_gl(doc.bank_account, doc.company)
	if not bank_account_gl:
		return

	company = doc.company
	raw_description = str(doc.description or "")
	desc = clean_bank_summary(doc.get("custom_summary") or raw_description)
	amount = flt(doc.withdrawal) if flt(doc.withdrawal) > 0 else flt(doc.deposit)
	is_withdrawal = flt(doc.withdrawal) > 0

	if amount <= 0:
		return

	expense_account = _resolve_account(raw_description or desc, company)
	if not expense_account:
		frappe.log_error(
			f"Auto voucher: no account found for bank transaction {doc.name} ({desc})",
			"Bank Auto Voucher",
		)
		return

	try:
		je = frappe.new_doc("Journal Entry")
		je.posting_date = doc.date
		je.company = company
		je.voucher_type = "Journal Entry"
		je.cheque_no = doc.reference_number or doc.name
		je.cheque_date = doc.date
		je.remark = f"银行流水 {doc.name}：{desc}"
		if je.meta.has_field("user_remark"):
			je.user_remark = clean_bank_summary(desc)
		if je.meta.has_field("custom_china_bank_transaction"):
			je.custom_china_bank_transaction = doc.name

		if is_withdrawal:
			expense_entry = {
				"account": expense_account,
				"debit_in_account_currency": amount,
				"credit_in_account_currency": 0,
			}
			expense_entry.update(_get_safe_party_fields(expense_account, doc))
			je.append("accounts", expense_entry)
			je.append("accounts", {
				"account": bank_account_gl,
				"debit_in_account_currency": 0,
				"credit_in_account_currency": amount,
			})
		else:
			je.append("accounts", {
				"account": bank_account_gl,
				"debit_in_account_currency": amount,
				"credit_in_account_currency": 0,
			})
			expense_entry = {
				"account": expense_account,
				"debit_in_account_currency": 0,
				"credit_in_account_currency": amount,
			}
			expense_entry.update(_get_safe_party_fields(expense_account, doc))
			je.append("accounts", expense_entry)

		je.insert(ignore_permissions=True)
		if frappe.db.has_column("Bank Transaction", "custom_china_journal_entry"):
			frappe.db.set_value(
				"Bank Transaction",
				doc.name,
				"custom_china_journal_entry",
				je.name,
				update_modified=False,
			)
		frappe.msgprint(
			f"已为银行流水 {doc.name} 生成待审核记账凭证 {je.name}，请检查后手动提交",
			alert=True,
		)

	except Exception:
		frappe.log_error(
			f"Auto voucher creation failed for {doc.name}: {frappe.get_traceback()}",
			"Bank Auto Voucher",
		)


def _resolve_account(description, company):
	"""Resolve high-confidence bank summaries; leave unclassified rows for review."""
	raw_description = str(description or "")
	description = clean_bank_summary(raw_description)
	search_text = f"{description}｜{raw_description}"
	# Finance has confirmed that a combined rent/property/utilities payment is
	# intentionally booked as one line in Management Expense - Other.
	if _has_mixed_facility_terms(search_text):
		account_number = "660299"
	elif "批量代发" in search_text and any(term in search_text for term in ("付费", "费用", "手续费", "服务费")):
		account_number = "660303"
	elif "招聘" in search_text and "备用金" in search_text:
		account_number = "660211"
	elif "公众号注册退款" in search_text or "企业实名验证" in search_text or "银行账户一分钱打款验证" in search_text:
		account_number = "1221"
	elif "个税" in search_text or "个人所得税" in search_text:
		account_number = "222110"
	elif "社保" in search_text:
		account_number = "221103"
	elif "公积金" in search_text or ("补缴" in search_text and "住房公积金" in search_text):
		account_number = "221104"
	elif "实时缴税" in search_text or "缴税" in search_text or "税单" in search_text:
		# A generic tax-bank reference does not identify the tax subaccount.
		return None
	elif "工资" in search_text or "代发" in search_text:
		account_number = "221101"
	elif "手续费" in search_text or "服务费" in search_text:
		account_number = "660303"
	elif "投资" in search_text:
		account_number = "4001"
	elif "办公" in search_text and "报销" in search_text:
		account_number = "660202"
	elif "报销" in search_text and _extract_bank_metadata(raw_description, "对方"):
		# The CMB statement identifies these rows as employee reimbursements;
		# the reviewed aaa policy books them to Management Expense - Office.
		account_number = "660202"
	elif "租金" in search_text and not any(term in search_text for term in ("物业", "水电", "电费")):
		account_number = "660207"
	elif any(term in search_text for term in ("物业水电", "水电", "电费")) and "租金" not in search_text:
		account_number = "660208"
	elif "验证" in search_text or "实名" in search_text:
		account_number = "1221"
	else:
		return None

	return frappe.db.get_value("Account", {"account_number": account_number, "company": company}, "name")


def _has_mixed_facility_terms(description):
	terms = ("租金", "房租", "物业", "水电", "电费")
	return sum(1 for term in terms if term in description) >= 2


def _get_safe_party_fields(account, bank_transaction):
	"""Carry a bank party only when the target account type accepts it."""
	party_type = bank_transaction.get("party_type")
	party = bank_transaction.get("party")
	if not party_type or not party or not frappe.db.exists(party_type, party):
		return {}
	account_info = frappe.db.get_value(
		"Account", account, ["root_type", "account_type"], as_dict=True
	)
	if not account_info:
		return {}
	allowed = (
		party_type == "Shareholder" and account_info.root_type == "Equity"
	) or (
		party_type == "Supplier" and account_info.account_type == "Payable"
	) or (
		party_type == "Customer" and account_info.account_type == "Receivable"
	) or (
		party_type == "Employee" and account_info.account_type in {"Payable", "Receivable"}
	)
	return {"party_type": party_type, "party": party} if allowed else {}


def _get_valid_bank_account_gl(bank_account, company):
	if not bank_account or not company:
		return None
	account = frappe.db.get_value("Bank Account", bank_account, "account")
	if not account:
		return None
	account_info = frappe.db.get_value(
		"Account", account, ["company", "is_group", "disabled"], as_dict=True
	)
	if (
		not account_info
		or account_info.company != company
		or account_info.is_group
		or account_info.disabled
	):
		frappe.log_error(
			f"Bank account {bank_account} points to an invalid account {account} for company {company}",
			"Bank Account Company Mismatch",
		)
		return None
	return account


def _validate_bank_account_company(bank_account, company):
	account = _get_valid_bank_account_gl(bank_account, company)
	if not account:
		frappe.throw(f"银行账户 {bank_account} 未正确关联公司 {company} 的银行科目")
	return account
