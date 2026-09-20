"""Present expense offsets on their natural side without changing GL balances."""

from collections import defaultdict

import frappe
from frappe.query_builder import Case
from frappe.query_builder.functions import Sum
from frappe.utils import flt
from pypika.terms import Bracket, LiteralValue


def get_expense_turnover_offsets(filters, account_names):
	"""Return amounts to subtract from both turnover columns, grouped by party.

	Ordinary expense credits become negative debits. Expense debits from period
	closing become negative credits. Subtracting the same amount from both
	columns preserves every opening/closing balance and the trial balance.
	"""
	if not account_names:
		return []

	gle = frappe.qb.DocType("GL Entry")
	account = frappe.qb.DocType("Account")
	is_closing = gle.voucher_type == "Period Closing Voucher"
	query = (
		get_activity_gl_query(filters, account_names, current_period_only=True)
		.inner_join(account).on(account.name == gle.account)
		.select(
			gle.account, gle.party_type, gle.party,
			Sum(Case().when(is_closing, gle.debit).else_(gle.credit)).as_("offset"),
		)
		.where(account.root_type == "Expense")
		.groupby(gle.account, gle.party_type, gle.party)
	)
	return query.run(as_dict=True)


def get_activity_gl_query(filters, account_names, *, current_period_only):
	"""Scope turnover and party details to the native report's visible GL rows."""
	from erpnext.accounts.report.financial_statements import apply_additional_conditions
	from frappe.desk.reportview import build_match_conditions

	gle = frappe.qb.DocType("GL Entry")
	query = (
		frappe.qb.from_(gle)
		.where(gle.company == filters.company)
		.where(gle.account.isin(account_names))
		.where(gle.is_cancelled == 0)
		.where(gle.posting_date <= filters.to_date)
	)
	include_closing = bool(flt(filters.with_period_closing_entry_for_current_period))
	if current_period_only:
		if not frappe.get_single_value("Accounts Settings", "ignore_is_opening_check_for_reporting"):
			query = query.where(gle.is_opening == "No")
	elif not include_closing:
		query = query.where(
			(gle.posting_date < filters.from_date) | (gle.voucher_type != "Period Closing Voucher")
		)
	# Use the native report's date, cost-center subtree, project, finance-book
	# and accounting-dimension restrictions, including its current-period toggle.
	query = apply_additional_conditions(
		"GL Entry", query, filters.from_date if current_period_only else None,
		current_period_only and not include_closing, filters.copy(),
	)
	if match_conditions := build_match_conditions("GL Entry"):
		query = query.where(Bracket(LiteralValue(match_conditions)))
	return query


def adjust_account_expense_turnover(rows, offsets):
	"""Apply each leaf's offset once to that account and all its ancestors."""
	by_account = {row.get("account"): row for row in rows if row.get("account")}
	amounts = defaultdict(float)
	for offset in offsets:
		amounts[offset.account] += flt(offset.offset)
	for account, amount in amounts.items():
		visited = set()
		while account in by_account and account not in visited:
			visited.add(account)
			row = by_account[account]
			row["debit"] = flt(row.get("debit")) - amount
			row["credit"] = flt(row.get("credit")) - amount
			account = row.get("parent_account")


def adjust_party_expense_turnover(rows, offsets):
	"""Use the same offsets for party detail rows as for their account totals."""
	amounts = defaultdict(float)
	for offset in offsets:
		amounts[(offset.account, offset.party_type or "", offset.party or "")] += flt(offset.offset)
	for row in rows:
		amount = amounts[(row.account, row.party_type or "", row.party or "")]
		row["debit"] = flt(row.get("debit")) - amount
		row["credit"] = flt(row.get("credit")) - amount
