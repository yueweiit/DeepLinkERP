"""Account-tree helpers for creating numbered child accounts."""

import hashlib
import re

import frappe
from frappe import _
from frappe.model.naming import getseries
from frappe.utils import cint, cstr, sbool


_ACCOUNT_FIELDS = (
	"account_name",
	"company",
	"parent_account",
	"is_group",
	"root_type",
	"account_type",
	"account_category",
	"tax_rate",
	"account_currency",
	"balance_must_be",
	"include_in_gross",
)


def _as_dict(args=None):
	if args is None:
		args = frappe.local.form_dict
	if isinstance(args, str):
		args = frappe.parse_json(args)
	return frappe._dict(args or {})


def _get_parent(parent_account, company=None):
	if not parent_account:
		return None
	if not frappe.db.exists("Account", parent_account) and company:
		parent_account = frappe.db.get_value(
			"Account", {"account_name": parent_account, "company": company}, "name"
		)
	if not parent_account:
		return None
	return frappe.get_doc("Account", parent_account)


def _series_key(company, parent):
	identity = f"{company}\0{parent.name}".encode("utf-8")
	digest = hashlib.sha1(identity).hexdigest()[:16]
	return f"CHINA-ACCOUNT-{digest}"


def _parent_prefix(parent):
	prefix = cstr(parent.account_number or "").strip()
	return prefix


def _existing_child_numbers(company, parent):
	rows = frappe.db.sql(
		"""
		SELECT account_number
		FROM `tabAccount`
		WHERE company=%s AND parent_account=%s AND account_number IS NOT NULL
		""",
		(company, parent.name),
		as_dict=True,
	)
	return {cstr(row.account_number).strip() for row in rows if cstr(row.account_number).strip()}


def _candidate_from_counter(prefix, counter):
	return f"{prefix}{counter:02d}"


def _numeric_child_numbers(existing):
	return [int(number) for number in existing if number.isdigit()]


def _series_current(key):
	series_rows = frappe.db.sql(
		"SELECT current FROM `tabSeries` WHERE name=%s",
		(key,),
		as_list=True,
	)
	return cint(series_rows[0][0]) if series_rows else 0


def _ensure_series_at_least(key, value):
	"""Seed the application sequence from pre-existing account numbers.

	The account tree feature was added after many accounts already existed.  If
	we let getseries() start at 1, a parent with codes up to 1703 would need to
	consume 1703 values before reaching the next available code.  tabSeries is
	also the high-water mark that prevents an automatically allocated number
	from being reused after an account is deleted.
	"""
	value = cint(value)
	if value <= 0:
		return
	frappe.db.sql(
		"""
		INSERT INTO `tabSeries` (`name`, `current`)
		VALUES (%s, %s)
		ON DUPLICATE KEY UPDATE `current` = GREATEST(`current`, VALUES(`current`))
		""",
		(key, value),
	)


def _numbering_mode(company, parent):
	"""Return the numbering rules for a child of parent.

	Coded parents (2241, 6602, ...) use a two-digit child suffix.  Some chart
	templates have an unnumbered display group such as 非流动资产, while its
	direct children are four-digit accounts (1501, 1502, ...).  Such a parent
	is a first-level category in practice, so use the next unused four-digit
	code among its direct children.
	"""
	parent_code = _parent_prefix(parent)
	if parent_code:
		return "child"
	existing = _existing_child_numbers(company, parent)
	if _numeric_child_numbers(existing):
		return "category"
	return "manual"


def _preview_next_account_number(company, parent):
	prefix = _parent_prefix(parent)
	existing = _existing_child_numbers(company, parent)
	key = _series_key(company, parent)
	current = _series_current(key)
	if not prefix:
		numeric_numbers = _numeric_child_numbers(existing)
		if not numeric_numbers:
			return ""
		counter = max(current, max(numeric_numbers, default=0)) + 1
		while str(counter) in existing:
			counter += 1
		return f"{counter:04d}"

	used_suffixes = {
		int(number[len(prefix):])
		for number in existing
		if number.startswith(prefix) and number[len(prefix):].isdigit()
	}
	counter = max(current, max(used_suffixes, default=0)) + 1
	while _candidate_from_counter(prefix, counter) in existing:
		counter += 1
	return _candidate_from_counter(prefix, counter)


def _allocate_next_account_number(company, parent):
	prefix = _parent_prefix(parent)
	key = _series_key(company, parent)
	existing = _existing_child_numbers(company, parent)
	if not prefix:
		numeric_numbers = _numeric_child_numbers(existing)
		if not numeric_numbers:
			frappe.throw(
				_("上级科目 {0} 没有可用于自动编码的同级数字科目，请直接填写科目编码").format(
					parent.name
				)
			)
		_ensure_series_at_least(key, max(numeric_numbers))
		while True:
			candidate = getseries(key, 4)
			if not frappe.db.exists("Account", {"company": company, "account_number": candidate}):
				return candidate

	used_suffixes = {
		int(number[len(prefix):])
		for number in existing
		if number.startswith(prefix) and number[len(prefix):].isdigit()
	}
	_ensure_series_at_least(key, max(used_suffixes, default=0))
	while True:
		candidate = f"{prefix}{getseries(key, 2)}"
		if not frappe.db.exists("Account", {"company": company, "account_number": candidate}):
			return candidate


def _normalize_child_name(parent_name, child_name):
	child_name = cstr(child_name or "").strip()
	if not child_name:
		frappe.throw(_("请输入下级科目名称"))

	# Accept both the normal hyphen and the full-width variants. This lets a
	# user paste "其他应付款-工资" without producing a duplicated prefix.
	child_name = _strip_parent_prefix(parent_name, child_name)
	if not child_name:
		frappe.throw(_("下级科目名称不能只填写上级科目名称"))
	return f"{parent_name}-{child_name}"


def _strip_parent_prefix(parent_name, child_name):
	pattern = rf"^{re.escape(parent_name)}\s*[-－—–]\s*"
	return re.sub(pattern, "", cstr(child_name or "").strip(), count=1).strip()


def _get_parent_context(parent_account, company=None):
	parent = _get_parent(parent_account, company)
	if not parent:
		return None, None
	if not parent.is_group:
		frappe.throw(_("上级科目 {0} 不是分组科目，不能新增下级科目").format(parent.name))
	if company and parent.company != company:
		frappe.throw(_("上级科目与所选公司不一致"))
	return parent, parent.company


@frappe.whitelist()
def get_next_account_number(parent_account, company=None):
	"""Preview the next child code without consuming the sequence number."""
	frappe.has_permission("Account", "create", throw=True)
	parent, company = _get_parent_context(parent_account, company)
	if not parent:
		return {"account_number": "", "account_name": "", "display_name": ""}

	account_number = _preview_next_account_number(company, parent)
	include_parent_prefix = bool(_parent_prefix(parent))
	parent_name = parent.account_name
	account_name_preview = f"{parent_name}-" if include_parent_prefix else ""
	display_name = (
		f"{account_number} - {account_name_preview}"
		if account_number
		else _("请直接填写科目编码")
	)
	return {
		"account_number": account_number,
		"parent_name": parent_name,
		"parent_account": parent.name,
		"include_parent_prefix": include_parent_prefix,
		"numbering_mode": _numbering_mode(company, parent),
		"manual_required": not bool(account_number),
		"account_name": account_name_preview,
		"display_name": display_name,
	}


@frappe.whitelist()
def add_account(args=None):
	"""Create an Account from the chart tree with an optional auto code."""
	frappe.has_permission("Account", "create", throw=True)
	args = _as_dict(args)
	if args.get("doctype") and args.doctype != "Account":
		frappe.throw(_("科目树新增接口只支持 Account"))

	company = args.get("company")
	parent, company = _get_parent_context(args.get("parent") or args.get("parent_account"), company)
	is_root = sbool(args.get("is_root"))
	if not parent and not is_root:
		frappe.throw(_("请选择一个分组科目作为上级科目"))
	if not company:
		frappe.throw(_("请选择公司"))

	account_name = cstr(args.get("account_name") or "").strip()
	if parent:
		if _parent_prefix(parent):
			account_name = _normalize_child_name(parent.account_name, account_name)
		else:
			account_name = _strip_parent_prefix(parent.account_name, account_name)
	if not account_name:
		frappe.throw(_("请输入科目名称"))

	manual = sbool(args.get("manual_account_number"))
	requested_account_number = cstr(args.get("account_number") or "").strip()
	auto_account_number = _preview_next_account_number(company, parent) if parent else ""
	requested_manual_number = bool(
		requested_account_number and requested_account_number != auto_account_number
	)
	if requested_manual_number:
		manual = True
	if manual:
		manual_number = cstr(args.get("manual_account_number_value") or "").strip()
		if not manual_number and requested_manual_number:
			manual_number = requested_account_number
		if not manual_number:
			frappe.throw(_("已选择手动编码，请填写科目编码"))
		account_number = manual_number
	elif parent:
		account_number = _allocate_next_account_number(company, parent)
	else:
		frappe.throw(_("新增一级科目时必须手动填写科目编码"))

	if manual and parent and account_number.isdigit():
		if _parent_prefix(parent) and account_number.startswith(_parent_prefix(parent)):
			suffix = account_number[len(_parent_prefix(parent)) :]
			if suffix.isdigit():
				_ensure_series_at_least(_series_key(company, parent), int(suffix))
		elif not _parent_prefix(parent):
			_ensure_series_at_least(_series_key(company, parent), int(account_number))

	values = {fieldname: args.get(fieldname) for fieldname in _ACCOUNT_FIELDS if args.get(fieldname) is not None}
	values.update(
		{
			"doctype": "Account",
			"company": company,
			"account_name": account_name,
			"account_number": account_number,
			"parent_account": parent.name if parent else None,
			"is_group": cint(args.get("is_group")),
			"freeze_account": "No",
			"old_parent": "",
		}
	)
	account = frappe.get_doc(values)
	account.validate_account_number(account_number)
	account.insert()
	return account.name
