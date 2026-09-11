import re

import frappe
from frappe import _

from china_finance.services.account_display import (
	get_account_display_title,
	strip_account_company_suffix,
)


def execute(filters=None):
	filters = frappe._dict(filters or {})
	display_number_filter = filters.get("voucher_word")
	conditions = [
		"v.company=%(company)s",
		"v.posting_date BETWEEN %(from_date)s AND %(to_date)s",
		"v.docstatus=1",
		"v.source_doctype IN ('Journal Entry', 'Payment Entry')",
		"v.source_event='Posting'",
		"((v.source_doctype='Journal Entry' AND je.docstatus=1) OR (v.source_doctype='Payment Entry' AND pe.docstatus=1))",
	]
	for fieldname, column in (
		("accounting_period", "v.accounting_period"),
		("account", "e.account"),
		("party_type", "e.party_type"),
		("party", "e.party"),
		("source_doctype", "v.source_doctype"),
		("source_name", "v.source_name"),
		("source_event", "v.source_event"),
	):
		if filters.get(fieldname):
			conditions.append(f"{column}=%({fieldname})s")
	if display_number_filter and not re.search(r"\d+$", str(display_number_filter)):
		conditions.append("v.voucher_word=%(voucher_word)s")
	if filters.get("voucher_number"):
		conditions.append("v.source_name=%(voucher_number)s")
	if filters.get("search_text"):
		filters.search_pattern = f"%{filters.search_text}%"
		conditions.append("(v.statutory_number LIKE %(search_pattern)s OR v.source_name LIKE %(search_pattern)s OR v.remarks LIKE %(search_pattern)s OR e.account LIKE %(search_pattern)s OR e.remarks LIKE %(search_pattern)s)")
	entries = frappe.db.sql(
		f"""
		SELECT v.name AS voucher_snapshot,
			COALESCE(je.posting_date, pe.posting_date, v.posting_date) AS posting_date,
			v.accounting_period, v.statutory_number,
			v.voucher_word, v.source_doctype, v.source_name, v.source_event,
			COALESCE(e.debit, 0) + COALESCE(e.credit, 0) AS base_total_amount,
			e.idx AS entry_idx,
			e.account AS account,
			e.party_type, e.party, e.cost_center, e.project,
			CASE
				WHEN v.source_doctype='Journal Entry' THEN jea.user_remark
				ELSE e.remarks
			END AS remarks,
			e.debit, e.credit
		FROM `tabChina Accounting Voucher` v
		INNER JOIN `tabChina Accounting Voucher Entry` e ON e.parent=v.name
		LEFT JOIN `tabJournal Entry` je ON v.source_doctype='Journal Entry' AND je.name=v.source_name
		LEFT JOIN `tabJournal Entry Account` jea
			ON v.source_doctype='Journal Entry'
			AND jea.parent=v.source_name
			AND jea.parenttype='Journal Entry'
			AND jea.idx=e.idx
		LEFT JOIN `tabPayment Entry` pe ON v.source_doctype='Payment Entry' AND pe.name=v.source_name
		WHERE {' AND '.join(conditions)}
		ORDER BY v.accounting_period, v.voucher_word, v.posting_date, v.sequence_number, v.name, e.idx
		""",
		filters,
		as_dict=True,
	)
	_format_account_labels(entries, filters.company)
	entries = _assign_dense_display_numbers(entries)
	if display_number_filter and re.search(r"\d+$", str(display_number_filter)):
		entries = [entry for entry in entries if entry.get("statutory_number") == display_number_filter]
	return get_columns(), build_tree_data(entries)


def _format_account_labels(entries, company):
	"""Render the canonical account name stored by the company chart."""
	account_names = {entry.get("account") for entry in entries if entry.get("account")}
	if not account_names:
		return

	accounts = frappe.get_all(
		"Account",
		filters={"company": company},
		fields=["name", "account_number", "account_name", "parent_account"],
	)
	account_map = {account.name: account for account in accounts}
	label_cache = {}

	def get_label(account_name):
		if account_name in label_cache:
			return label_cache[account_name]

		account = account_map.get(account_name)
		if not account:
			label_cache[account_name] = strip_account_company_suffix(account_name, company)
			return label_cache[account_name]

		label = get_account_display_title(account.account_number, account.account_name)
		if not label:
			label = strip_account_company_suffix(account_name, company)
		label_cache[account_name] = label
		return label

	for entry in entries:
		if entry.get("account"):
			entry["account"] = get_label(entry.account)


def _assign_dense_display_numbers(entries):
	"""Renumber only the export view; immutable voucher snapshots keep audit numbers."""
	next_number = {}
	assigned = {}
	result = []
	for entry in entries:
		row = frappe._dict(dict(entry))
		period_key = (row.get("accounting_period") or "", row.get("voucher_word") or "记")
		snapshot = row.get("voucher_snapshot")
		if snapshot not in assigned:
			next_number[period_key] = next_number.get(period_key, 0) + 1
			assigned[snapshot] = f"{period_key[1]}{next_number[period_key]}"
		row["statutory_number"] = assigned[snapshot]
		result.append(row)
	return result


def build_tree_data(entries):
	voucher_rows = {}
	voucher_order = []
	for entry in entries:
		voucher_snapshot = entry.voucher_snapshot
		if voucher_snapshot not in voucher_rows:
			voucher_order.append(voucher_snapshot)
			voucher_rows[voucher_snapshot] = []
		first_line = not voucher_rows[voucher_snapshot]
		voucher_rows[voucher_snapshot].append({
			**entry,
			"posting_date": entry.posting_date if first_line else None,
			"statutory_number": entry.statutory_number if first_line else None,
			"voucher_number": None,
			"print_voucher": None,
			"accounting_period": entry.accounting_period if first_line else None,
			"remarks": clean_voucher_summary(entry.remarks),
			"source_doctype": entry.source_doctype if first_line else None,
			"source_name": entry.source_name if first_line else None,
			"source_event": entry.source_event if first_line else None,
			"voucher_status": None,
			"prepared_by": None,
			"modified_by": None,
			"row_id": f"{voucher_snapshot}:{entry.entry_idx}",
			"parent_row_id": None,
			"indent": 0,
		})
	return [row for voucher_snapshot in voucher_order for row in voucher_rows[voucher_snapshot]]


def clean_voucher_summary(value):
	"""Remove bank reference metadata copied into historical summaries."""
	value = (value or "").strip()
	if "｜" in value:
		value = value.split("｜", 1)[0].strip()
	return re.split(r"\s*参考\s*#?.*$", value, maxsplit=1, flags=re.IGNORECASE)[0].strip()


def get_source_metadata(entry):
	values = frappe.db.get_value(
		entry.source_doctype,
		entry.source_name,
		["docstatus", "owner", "modified_by"],
		as_dict=True,
	)
	return values or frappe._dict(docstatus=1, owner=None, modified_by=None)


def get_auxiliary_accounting(entry):
	parts = []
	if entry.party:
		parts.append(f"{entry.party_type or '往来'}：{entry.party}")
	if entry.cost_center:
		parts.append(f"成本中心：{entry.cost_center}")
	if entry.project:
		parts.append(f"项目：{entry.project}")
	if entry.finance_book:
		parts.append(f"财务账簿：{entry.finance_book}")
	if entry.dimensions_json:
		parts.append(entry.dimensions_json)
	return "；".join(parts)


def get_columns():
	return [
		{"label": _("凭证字号"), "fieldname": "statutory_number", "fieldtype": "Data", "width": 100},
		{"label": _("凭证日期"), "fieldname": "posting_date", "fieldtype": "Date", "width": 130},
		{"label": _("会计期间"), "fieldname": "accounting_period", "fieldtype": "Data", "width": 110},
		{"label": _("摘要"), "fieldname": "remarks", "fieldtype": "Data", "width": 270},
		{"label": _("科目"), "fieldname": "account", "fieldtype": "Data", "width": 330},
		{"label": _("往来单位"), "fieldname": "party", "fieldtype": "Dynamic Link", "options": "party_type", "width": 150},
		{"label": _("借方"), "fieldname": "debit", "fieldtype": "Currency", "width": 150},
		{"label": _("贷方"), "fieldname": "credit", "fieldtype": "Currency", "width": 150},
		{"label": _("本位币金额"), "fieldname": "base_total_amount", "fieldtype": "Currency", "width": 160},
		{"label": _("操作"), "fieldname": "source_action", "fieldtype": "Data", "width": 130},
	]
