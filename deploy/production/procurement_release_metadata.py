"""Narrow, reversible metadata step for the approved procurement release.

Business documents and shared permissions are never modified. The receipt is
flushed before commit so shell recovery can restore exact original child IDs.
"""

import argparse
import copy
import hashlib
import json
from pathlib import Path

PAGE = "purchase-payables"
NAVIGATION = (("Workspace", "Buying"), ("Workspace Sidebar", "Buying"))


def digest(rows):
	return {
		"count": len(rows),
		"sha256": hashlib.sha256(
			json.dumps(rows, sort_keys=True, default=str, ensure_ascii=False).encode()
		).hexdigest(),
	}


def selectors():
	import frappe

	result = {"Page": [("name", PAGE)], "Has Role": [("parent", PAGE), ("parenttype", "Page")]}
	for doctype, name in NAVIGATION:
		result[doctype] = [("name", name)]
		for field in frappe.get_meta(doctype).fields:
			if field.fieldtype in {"Table", "Table MultiSelect"} and field.options != "Has Role":
				result[field.options] = [("parent", name), ("parenttype", doctype)]
	return result


def capture():
	import frappe

	scope, outside = {}, {}
	for doctype, filters in selectors().items():
		table = ("tab" + doctype).replace("`", "``")
		rows = frappe.db.sql(f"select * from `{table}` order by name", as_dict=True)
		scope[doctype] = [row for row in rows if all(row.get(field) == value for field, value in filters)]
		outside[doctype] = digest(
			[row for row in rows if not all(row.get(field) == value for field, value in filters)]
		)
	documents = {dt: frappe.get_doc(dt, name).as_dict() for dt, name in NAVIGATION}
	return json.loads(json.dumps({"scope": scope, "outside": outside, "documents": documents}, default=str))


def normalize_document(doc, old_names):
	"""Ignore only native save timestamps and generated system fields of new rows."""
	ignored = {"modified", "modified_by", "__islocal", "__unsaved"}
	if doc.get("parenttype") and doc.get("name") not in old_names:
		ignored |= {"name", "creation", "owner"}
	return {
		key: [normalize_document(row, old_names) for row in value] if isinstance(value, list) else value
		for key, value in doc.items()
		if key not in ignored and value is not None
	}


def verify_page(source):
	import frappe

	page = frappe.get_doc("Page", PAGE)
	for key in ("doctype", "name", "module", "title", "standard"):
		assert page.get(key) == source[key], "Procurement Page metadata drift: " + key
	roles = frappe.db.sql(
		"select role, parent, parenttype, parentfield, idx from `tabHas Role` where parent=%s and parenttype='Page' order by idx, name",
		(PAGE,),
		as_dict=True,
	)
	assert roles == [
		{"role": row["role"], "parent": PAGE, "parenttype": "Page", "parentfield": "roles", "idx": index}
		for index, row in enumerate(source["roles"], 1)
	], "Procurement Page roles drift"


def verify_navigation(before, after):
	import frappe

	from deeplinkerp_branding.procurement_navigation import reconcile_links, reconcile_workspace

	assert before["outside"] == after["outside"], "Metadata outside the approved scope changed"
	for doctype, reconcile in (
		("Workspace", reconcile_workspace),
		("Workspace Sidebar", lambda d: reconcile_links(d, "items")),
	):
		original = before["documents"][doctype]
		expected = frappe.get_doc(copy.deepcopy(original))
		reconcile(expected)
		old_names = {row["name"] for value in original.values() if isinstance(value, list) for row in value}
		wanted = normalize_document(json.loads(json.dumps(expected.as_dict(), default=str)), old_names)
		actual = normalize_document(after["documents"][doctype], old_names)
		assert wanted == actual, "Unexpected Buying metadata change: " + doctype


def apply_metadata(source, before, *, commit=True):
	import frappe

	from deeplinkerp_branding.procurement_navigation import ensure_procurement_navigation

	assert capture() == before, "Metadata baseline changed before apply"
	if not before["scope"]["Page"]:
		assert source["name"] == PAGE
		assert not frappe.db.exists("Page", PAGE), "New procurement Page appeared before import"
		old_import, old_developer = frappe.flags.in_import, frappe.conf.developer_mode
		frappe.flags.in_import, frappe.conf.developer_mode = True, False
		try:
			from frappe.modules.import_file import import_doc

			path = frappe.get_app_path(
				"deeplinkerp_branding",
				"deeplinkerp_branding",
				"page",
				"purchase_payables",
				"purchase_payables.json",
			)
			import_doc(copy.deepcopy(source), ignore_version=True, path=path)
		finally:
			frappe.flags.in_import, frappe.conf.developer_mode = old_import, old_developer
	verify_page(source)
	first = ensure_procurement_navigation()
	assert first["ok"]
	after = capture()
	verify_navigation(before, after)
	second = ensure_procurement_navigation()
	assert second == {"ok": True, "changed": []}, "Navigation is not idempotent"
	assert capture() == after, "Second metadata reconciliation wrote rows"
	if before["scope"]["Page"]:
		assert before["scope"]["Page"] == after["scope"]["Page"]
		assert before["scope"]["Has Role"] == after["scope"]["Has Role"]
	receipt = {
		"semantic_validated": True,
		"before": before,
		"after": after,
		"second_reconcile_unchanged": True,
		"new_page": not bool(before["scope"]["Page"]),
	}
	if commit:
		print(json.dumps(receipt, default=str, ensure_ascii=False), flush=True)
		frappe.db.commit()
	return receipt


def restore_metadata(receipt, *, commit=True):
	import frappe

	current = capture()
	if current == receipt["before"]:
		return {"restored": True, "already_original": True}
	assert current == receipt["after"], "Metadata drift after release; retain maintenance for manual recovery"
	for doctype, filters in selectors().items():
		table = ("tab" + doctype).replace("`", "``")
		where = " and ".join("`" + field + "` = %s" for field, _ in filters)
		frappe.db.sql(f"delete from `{table}` where {where}", tuple(value for _, value in filters))
		for row in receipt["before"]["scope"][doctype]:
			columns = sorted(row)
			assert all("`" not in field for field in columns)
			names = ",".join("`" + field + "`" for field in columns)
			placeholders = ",".join(["%s"] * len(columns))
			frappe.db.sql(
				f"insert into `{table}` ({names}) values ({placeholders})",
				tuple(row[field] for field in columns),
			)
	assert capture() == receipt["before"], "Exact metadata rollback could not be verified"
	if commit:
		frappe.db.commit()
	return {"restored": True, "original_child_ids_and_rows": True}


def verify_audit_delta(before, after, receipt):
	"""Allow the new Page roles only after exact scope receipt and outside hashes match."""
	assert receipt["semantic_validated"] and receipt["second_reconcile_unchanged"]
	assert before.pop("procurement_metadata") == receipt["before"]
	assert after.pop("procurement_metadata") == receipt["after"]
	assert receipt["before"]["outside"] == receipt["after"]["outside"]
	old_roles = receipt["before"]["scope"]["Has Role"]
	new_roles = receipt["after"]["scope"]["Has Role"]
	if receipt["new_page"]:
		assert not old_roles and len(new_roles) == 3
		assert {row["role"] for row in new_roles} == {"System Manager", "Accounts User", "Accounts Manager"}
	else:
		assert old_roles == new_roles
		assert before["tables"]["Has Role"] == after["tables"]["Has Role"], "Existing permission rows changed"
	assert after["tables"]["Has Role"]["count"] - before["tables"]["Has Role"]["count"] == len(
		new_roles
	) - len(old_roles)
	before["tables"].pop("Has Role")
	after["tables"].pop("Has Role")


def main():
	import frappe

	parser = argparse.ArgumentParser()
	parser.add_argument("--apply", metavar="PAGE_SOURCE")
	parser.add_argument("--before-audit")
	parser.add_argument("--rollback", metavar="RECEIPT")
	args = parser.parse_args()
	bench = Path("/home/frappe/frappe-bench")
	frappe.init(site="deeplinkerp.com", sites_path=str(bench / "sites"))
	frappe.connect()
	try:
		assert frappe.conf.maintenance_mode == 1, "Metadata changes require verified maintenance"
		frappe.set_user("Administrator")
		if args.apply:
			baseline = json.loads(Path(args.before_audit).read_text())["procurement_metadata"]
			apply_metadata(json.loads(Path(args.apply).read_text()), baseline)
		elif args.rollback:
			print(json.dumps(restore_metadata(json.loads(Path(args.rollback).read_text()))))
		else:
			raise ValueError("Exact apply or rollback action required")
	finally:
		frappe.db.rollback()
		frappe.destroy()


if __name__ == "__main__":
	main()
