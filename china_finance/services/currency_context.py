"""Explicit currency context for financial amounts; never use the user's default."""

import frappe
from frappe import _


COMPANY_CURRENCY_DOCTYPES = (
	"China Finance Settings", "China Cash Flow Assignment", "China Prior Period Error Adjustment",
	"China Purchase Reconciliation Rule", "China Reconciliation Difference",
	"China Reconciliation Scope", "China Reconciliation Statement",
)
SOURCE_CURRENCY_DOCTYPES = {
	"China Tax Invoice Request": ("Sales Invoice", "sales_invoice"),
	"China Input Tax Deduction Batch": ("China Tax Invoice", "tax_invoice"),
}
CURRENCY_DOCTYPES = (*COMPANY_CURRENCY_DOCTYPES,
	"China Accounting Voucher", "China Tax Invoice", *SOURCE_CURRENCY_DOCTYPES)


def company_currency(company):
	return frappe.get_cached_value("Company", company, "default_currency") if company else None


def set_document_currency(doc, method=None):
	if doc.doctype in SOURCE_CURRENCY_DOCTYPES:
		source_type, source_field = SOURCE_CURRENCY_DOCTYPES[doc.doctype]
		currencies = set()
		for row in doc.get("items") or []:
			if row.get(source_field):
				value = frappe.db.get_value(source_type, row.get(source_field), "currency")
				if not value:
					frappe.throw(_("来源单据 {0} 缺少币种，请先核对").format(row.get(source_field)))
				currencies.add(value)
		if len(currencies) > 1:
			frappe.throw(_("{0} 包含不同币种，不能合计；请按币种分别建立单据").format(doc.doctype))
		doc.currency = next(iter(currencies), None) or doc.get("currency") or company_currency(doc.company)
	elif not doc.get("currency") or (
		doc.doctype in COMPANY_CURRENCY_DOCTYPES and method == "before_validate"
		and not doc.docstatus and doc.has_value_changed("company")
	):
		doc.currency = company_currency(doc.get("company"))
	if doc.doctype == "China Reconciliation Statement":
		doc.bank_currency = (
			frappe.get_cached_value("Account", doc.account, "account_currency")
			if doc.get("statement_type") == "Bank" and doc.get("account") else None
		) or doc.currency
		for row in doc.get("lines") or []:
			row.currency = (doc.bank_currency if row.line_source in
				("Book Outstanding", "Bank Transaction") else doc.currency)
	if doc.doctype == "China Reconciliation Difference" and doc.get("statement"):
		statement = frappe.get_doc("China Reconciliation Statement", doc.statement)
		set_document_currency(statement)
		doc.currency = statement.bank_currency if statement.statement_type == "Bank" else statement.currency
	if doc.doctype == "China Reconciliation Scope":
		doc.currency = company_currency(doc.get("company"))
		if doc.get("scope_type") == "Bank" and doc.reference_name:
			account = frappe.db.get_value("Bank Account", doc.reference_name, "account")
			if account:
				doc.currency = frappe.get_cached_value("Account", account, "account_currency") or doc.currency


def bind_report_currency(columns, rows, company, force_company=False):
	"""Return row-level currencies for browser, export and server-side formatting."""
	default = company_currency(company)
	contexts = set()
	for column in columns:
		if column.get("fieldtype") == "Currency":
			column.setdefault("options", "currency")
			contexts.add(column["options"])
	for row in rows or []:
		if not row:
			continue
		if force_company or not row.get("currency"):
			row["currency"] = default
		for context in contexts:
			if ":" not in context and not row.get(context):
				for column in columns:
					if column.get("fieldtype") == "Currency" and column.get("options") == context and row.get(column["fieldname"]):
						frappe.throw(_("金额列“{0}”缺少币种，请先核对来源单据").format(column.get("label") or column["fieldname"]))
				row[context] = row["currency"]
	for context in sorted(contexts):
		if ":" not in context and not any(c.get("fieldname") == context for c in columns):
			columns.append({"label": _("币种"), "fieldname": context,
				"fieldtype": "Link", "options": "Currency", "hidden": 1})
	return columns, rows


def currency_report_result(columns, rows, company, message=None):
	"""Keep native totals for a single currency, never sum unlike denominations."""
	bind_report_currency(columns, rows, company)
	contexts = {c["options"] for c in columns if c.get("fieldtype") == "Currency"}
	mixed = any(len({row.get(context) for row in rows or [] if row}) > 1 for context in contexts)
	if mixed:
		message = "<br>".join(filter(None, (
			message, _("包含不同币种，金额按各行币种列示；未进行汇率换算，不显示跨币种合计。"),
		)))
	return columns, rows, message, None, None, mixed


def backfill_currency_context():
	"""Fill only missing currency metadata; preserve amounts and audit timestamps."""
	result = {"updated": 0, "needs_review": []}
	for doctype in CURRENCY_DOCTYPES:
		for name in frappe.get_all(doctype, filters={"currency": ["is", "not set"]}, pluck="name"):
			doc = frappe.get_doc(doctype, name)
			try:
				set_document_currency(doc)
			except frappe.ValidationError as exc:
				result["needs_review"].append({"doctype": doctype, "name": name, "reason": str(exc)})
				continue
			if doc.currency:
				frappe.db.set_value(doctype, name, "currency", doc.currency, update_modified=False)
				result["updated"] += 1
	for name in frappe.get_all("China Reconciliation Statement",
			pluck="name"):
		doc = frappe.get_doc("China Reconciliation Statement", name)
		set_document_currency(doc)
		if not frappe.db.get_value(doc.doctype, name, "bank_currency"):
			frappe.db.set_value(doc.doctype, name, "bank_currency", doc.bank_currency, update_modified=False)
		for row in doc.lines:
			if not frappe.db.get_value(row.doctype, row.name, "currency"):
				frappe.db.set_value(row.doctype, row.name, "currency", row.currency, update_modified=False)
	if result["needs_review"]:
		frappe.log_error(title=_("历史财务单据币种需要核对"), message=frappe.as_json(result["needs_review"]))
	return result
