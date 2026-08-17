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
	"手续费": "660303",
	"服务费": "660303",
	"报销": "660299",
	"工资": "221101",
	"代发": "221101",
	"租金": "660299",
	"物业": "660299",
	"缴税": "22210104",
	"公积金": "221104",
	"补缴": "221104",
	"投资": "4001",
	"退款": "6301",
	"退回": "6301",
	"验证": "660299",
	"实名": "660299",
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


@frappe.whitelist()
def create_journal_entry_with_summary(remarks=None, **kwargs):
	"""Create the native editable Journal Entry draft and set its summary."""
	kwargs.pop("cmd", None)
	allow_edit = kwargs.pop("allow_edit", None)
	journal_entry = create_journal_entry_bts(**kwargs, allow_edit=True)
	if remarks:
		journal_entry.remarks = remarks
		for entry in journal_entry.accounts:
			entry.user_remark = remarks
	if allow_edit:
		return journal_entry

	journal_entry.insert()
	journal_entry.submit()
	bank_transaction = frappe.db.get_value(
		"Bank Transaction",
		kwargs["bank_transaction_name"],
		["deposit", "withdrawal"],
		as_dict=True,
	)
	paid_amount = (
		bank_transaction.deposit
		if bank_transaction.deposit > 0.0
		else bank_transaction.withdrawal
	)
	return reconcile_vouchers(
		kwargs["bank_transaction_name"],
		json.dumps([{
			"payment_doctype": "Journal Entry",
			"payment_name": journal_entry.name,
			"amount": paid_amount,
		}]),
	)


def auto_create_voucher_on_submit(doc, method=None):
	"""Create a Journal Entry when a Bank Transaction is submitted.

	Called via doc_events on_submit hook. Only creates a voucher if:
	- The bank transaction has no allocated amount yet
	- A matching bank account GL account exists
	"""
	if flt(doc.allocated_amount) > 0:
		return

	bank_account_gl = frappe.db.get_value("Bank Account", doc.bank_account, "account")
	if not bank_account_gl:
		return

	company = doc.company
	desc = doc.description or ""
	amount = flt(doc.withdrawal) if flt(doc.withdrawal) > 0 else flt(doc.deposit)
	is_withdrawal = flt(doc.withdrawal) > 0

	if amount <= 0:
		return

	expense_account = _resolve_account(desc, company)
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
		je.remark = f"Auto-created for bank transaction {doc.name}: {desc}"

		if is_withdrawal:
			je.append("accounts", {
				"account": expense_account,
				"debit_in_account_currency": amount,
				"credit_in_account_currency": 0,
			})
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
			je.append("accounts", {
				"account": expense_account,
				"debit_in_account_currency": 0,
				"credit_in_account_currency": amount,
			})

		je.insert(ignore_permissions=True)
		je.submit()

		# Auto-reconcile
		reconcile_vouchers(
			doc.name,
			json.dumps([{
				"payment_doctype": "Journal Entry",
				"payment_name": je.name,
				"amount": amount,
			}]),
		)
		frappe.msgprint(
			f"Auto-created Journal Entry {je.name} for Bank Transaction {doc.name}",
			alert=True,
		)

	except Exception:
		frappe.log_error(
			f"Auto voucher creation failed for {doc.name}: {frappe.get_traceback()}",
			"Bank Auto Voucher",
		)


def _resolve_account(description, company):
	"""Find the best matching account based on description keywords."""
	for keyword, account_number in DEFAULT_ACCOUNT_MAPPING.items():
		if keyword in description:
			account = frappe.db.get_value(
				"Account",
				{"account_number": account_number, "company": company},
				"name",
			)
			if account:
				return account

	# Fallback: 管理费用－其他
	return frappe.db.get_value(
		"Account",
		{"account_number": "660299", "company": company},
		"name",
	)
