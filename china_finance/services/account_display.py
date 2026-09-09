"""Account tree and display helpers for China Finance."""

import frappe


def get_account_display_name(
	account_name,
	parent_account_name=None,
	account_number=None,
	parent_account_number=None,
):
	"""Return the stored account hierarchy without dropping its parent label.

	Numbered account names are now stored as ``大类－小类`` (and, where
	applicable, ``大类－分类－明细``). The company suffix is not part of this
	field; it remains only in ERPNext's internal Account name.
	"""
	return str(account_name or "").strip()


def get_account_display_title(
	account_number,
	account_name,
	parent_account_name=None,
	parent_account_number=None,
):
	"""Return the user-facing account label without the company suffix."""
	number = str(account_number or "").strip()
	name = get_account_display_name(
		account_name,
		parent_account_name=parent_account_name,
		account_number=account_number,
		parent_account_number=parent_account_number,
	)
	return f"{number} - {name}" if number and name else number or name


def strip_account_company_suffix(account_name, company=None):
	"""Remove the canonical company abbreviation from a fallback Account name."""
	value = str(account_name or "").strip()
	if not value or not company:
		return value

	abbr = frappe.get_cached_value("Company", company, "abbr")
	suffix = f" - {str(abbr or '').strip()}"
	return value[:-len(suffix)].rstrip() if suffix != " - " and value.endswith(suffix) else value


def get_account_display_label(account, company=None):
	"""Return a clean label for an Account row or a canonical Account name."""
	if not account:
		return ""

	if isinstance(account, str):
		account = frappe.db.get_value(
			"Account", account,
			["name", "account_number", "account_name", "parent_account"],
			as_dict=True,
		) or {"name": account}

	account_name = account.get("account_name")
	if not account_name:
		account_name = strip_account_company_suffix(account.get("name"), company)
	parent = None
	if account.get("parent_account") and not account.get("parent_account_name"):
		parent = frappe.db.get_value(
			"Account",
			account.get("parent_account"),
			["account_name", "account_number"],
			as_dict=True,
		)
	return get_account_display_title(
		account.get("account_number"),
		account_name,
		parent_account_name=account.get("parent_account_name") or (parent or {}).get("account_name"),
		parent_account_number=account.get("parent_account_number") or (parent or {}).get("account_number"),
	)


def normalize_six_digit_account_names(company):
	"""Compatibility helper for older callers.

	The chart synchronizer now writes the complete source hierarchy, so this
	legacy helper no longer strips parent names. It only reports the current
	state and intentionally performs no database update.
	"""
	return {"updated": 0, "accounts": [], "company": company}


@frappe.whitelist()
def get_children(doctype, parent, company, is_root=False, include_disabled=False):
	"""Return Account tree nodes with a clean display title.

	The node value remains Account.name so tree operations and links keep using
	the original, globally unique ERPNext identifier.
	"""
	from erpnext.accounts.utils import get_children as get_erpnext_children

	nodes = get_erpnext_children(
		doctype=doctype,
		parent=parent,
		company=company,
		is_root=is_root,
		include_disabled=include_disabled,
	)
	if doctype != "Account" or not nodes:
		return nodes

	names = [node.get("value") for node in nodes if node.get("value")]
	accounts = frappe.get_all(
		"Account",
		filters={"name": ["in", names]},
		fields=["name", "account_name", "account_number", "parent_account"],
	)
	account_by_name = {account.name: account for account in accounts}
	parent_names = {account.parent_account for account in accounts if account.parent_account}
	parents = frappe.get_all(
		"Account",
		filters={"name": ["in", list(parent_names)]},
		fields=["name", "account_name", "account_number"],
	) if parent_names else []
	parent_by_name = {account.name: account for account in parents}

	for node in nodes:
		account = account_by_name.get(node.get("value"))
		if account:
			parent = parent_by_name.get(account.parent_account)
			node["title"] = get_account_display_title(
				account.account_number,
				account.account_name,
				parent_account_name=parent.account_name if parent else None,
				parent_account_number=parent.account_number if parent else None,
			)

	return nodes
