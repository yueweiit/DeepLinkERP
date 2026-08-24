import re

import frappe
from frappe import _


def execute(filters=None):
	filters = frappe._dict(filters or {})
	conditions = [
		"v.company=%(company)s",
		"v.posting_date BETWEEN %(from_date)s AND %(to_date)s",
		"v.docstatus=1",
		"v.source_doctype IN ('Journal Entry', 'Payment Entry')",
	]
	for fieldname, column in (
		("voucher_word", "v.voucher_word"),
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
	if filters.get("voucher_number"):
		conditions.append("v.source_name=%(voucher_number)s")
	if filters.get("search_text"):
		filters.search_pattern = f"%{filters.search_text}%"
		conditions.append("(v.statutory_number LIKE %(search_pattern)s OR v.source_name LIKE %(search_pattern)s OR v.remarks LIKE %(search_pattern)s OR e.account LIKE %(search_pattern)s OR e.remarks LIKE %(search_pattern)s)")
	entries = frappe.db.sql(
		f"""
		SELECT v.name AS voucher_snapshot, v.posting_date, v.accounting_period, v.statutory_number,
			v.voucher_word, v.source_doctype, v.source_name, v.source_event,
			v.total_debit AS base_total_amount,
			e.idx AS entry_idx, e.account, e.party_type, e.party, e.cost_center, e.project,
			COALESCE(NULLIF(e.remarks, ''), v.remarks) AS remarks, e.debit, e.credit
		FROM `tabChina Accounting Voucher` v
		INNER JOIN `tabChina Accounting Voucher Entry` e ON e.parent=v.name
		WHERE {' AND '.join(conditions)}
		ORDER BY v.posting_date, v.sequence_number, v.name, e.idx
		""",
		filters,
		as_dict=True,
	)
	return get_columns(), build_tree_data(entries)


def build_tree_data(entries):
	voucher_rows = {}
	voucher_order = []
	summary_cache = {}
	metadata_cache = {}
	for entry in entries:
		voucher_snapshot = entry.voucher_snapshot
		if voucher_snapshot not in summary_cache:
			summary_cache[voucher_snapshot] = get_source_summary(entry)
		summary = summary_cache[voucher_snapshot]
		if voucher_snapshot not in metadata_cache:
			metadata_cache[voucher_snapshot] = get_source_metadata(entry)
		metadata = metadata_cache[voucher_snapshot]
		if voucher_snapshot not in voucher_rows:
			voucher_order.append(voucher_snapshot)
			voucher_rows[voucher_snapshot] = [{
					"row_id": voucher_snapshot,
					"parent_row_id": None,
					"voucher_snapshot": voucher_snapshot,
					"indent": 0,
					"posting_date": entry.posting_date,
					"statutory_number": entry.statutory_number,
					"voucher_number": entry.source_name,
					"print_voucher": "",
					"accounting_period": entry.accounting_period,
					"remarks": summary,
					"source_doctype": entry.source_doctype,
					"source_name": entry.source_name,
				"source_event": entry.source_event,
				"base_total_amount": entry.base_total_amount,
				"voucher_status": metadata.docstatus,
				"prepared_by": metadata.owner,
				"modified_by": metadata.modified_by,
					"account": _("凭证合计"),
					"debit": 0,
					"credit": 0,
			}]
		root = voucher_rows[voucher_snapshot][0]
		root["debit"] += entry.debit or 0
		root["credit"] += entry.credit or 0
		voucher_rows[voucher_snapshot].append(
			{
				**entry,
				"posting_date": None,
				"statutory_number": None,
				"voucher_number": None,
				"print_voucher": None,
				"accounting_period": None,
				"remarks": None,
				"source_doctype": None,
				"voucher_status": None,
				"prepared_by": None,
				"modified_by": None,
				"auxiliary_accounting": get_auxiliary_accounting(entry),
				"base_total_amount": None,
				"row_id": f"{voucher_snapshot}:{entry.entry_idx}",
				"parent_row_id": voucher_snapshot,
				"indent": 1,
			}
		)
	return [row for voucher_snapshot in voucher_order for row in voucher_rows[voucher_snapshot]]


def get_source_summary(entry):
	"""Use the source document's concise business summary for display only."""
	if entry.source_doctype == "Journal Entry":
		remark = frappe.db.get_value("Journal Entry", entry.source_name, "user_remark")
		return clean_voucher_summary(remark or entry.remarks)
	if entry.source_doctype == "Payment Entry":
		payment_type, party = frappe.db.get_value(
			"Payment Entry", entry.source_name, ["payment_type", "party"]
		) or (None, None)
		return f"{'收款' if payment_type == 'Receive' else '付款'} {party or ''}".strip()
	return clean_voucher_summary(entry.remarks)


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
		{"label": _("凭证字号"), "fieldname": "statutory_number", "fieldtype": "Data", "width": 80},
		{"label": _("凭证编号"), "fieldname": "voucher_number", "fieldtype": "Data", "width": 160},
		{"label": _("查看/打印"), "fieldname": "print_voucher", "fieldtype": "HTML", "width": 85},
		{"label": _("凭证日期"), "fieldname": "posting_date", "fieldtype": "Date", "width": 120},
		{"label": _("会计期间"), "fieldname": "accounting_period", "fieldtype": "Data", "width": 100},
		{"label": _("摘要"), "fieldname": "remarks", "fieldtype": "Data", "width": 130},
		{"label": _("来源类型"), "fieldname": "source_doctype", "fieldtype": "Link", "options": "DocType", "width": 110},
		{"label": _("科目"), "fieldname": "account", "fieldtype": "Link", "options": "Account", "width": 130},
		{"label": _("往来单位"), "fieldname": "party", "fieldtype": "Dynamic Link", "options": "party_type", "width": 80},
		{"label": _("辅助核算"), "fieldname": "auxiliary_accounting", "fieldtype": "Data", "width": 180},
		{"label": _("借方"), "fieldname": "debit", "fieldtype": "Currency", "width": 125},
		{"label": _("贷方"), "fieldname": "credit", "fieldtype": "Currency", "width": 125},
		{"label": _("本位币总金额"), "fieldname": "base_total_amount", "fieldtype": "Currency", "width": 120},
		{"label": _("凭证状态"), "fieldname": "voucher_status", "fieldtype": "Int", "width": 90},
		{"label": _("制单人"), "fieldname": "prepared_by", "fieldtype": "Link", "options": "User", "width": 60},
		{"label": _("修改人"), "fieldname": "modified_by", "fieldtype": "Link", "options": "User", "width": 60},
	]
