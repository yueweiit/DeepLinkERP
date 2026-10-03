"""Read-only release audit. Emit hashes/counts, never business row contents."""
import hashlib
import json
from pathlib import Path

import frappe

SITE = "deeplinkerp.com"
BENCH = Path("/home/frappe/frappe-bench")


def source_digest(app):
	root = BENCH / "apps" / app / app
	assert root.is_dir(), f"Missing preserved app: {app}"
	digest = hashlib.sha256()
	for path in sorted(root.rglob("*")):
		if not path.is_file() or "__pycache__" in path.parts or path.suffix in {".pyc", ".pyo"}:
			continue
		digest.update(str(path.relative_to(root)).encode())
		digest.update(path.read_bytes())
	return digest.hexdigest()


def capture_audit():
	"""Capture inside the caller's transaction; the CLI remains read-only."""
	tables = ["Purchase Order", "Purchase Order Item", "Material Request", "Material Request Item",
		"OA Purchase Request", "Stock Entry", "Stock Entry Detail", "Stock Ledger Entry", "GL Entry",
		"Bin", "Inventory Original Location Snapshot", "Purchase Receipt", "Purchase Invoice", "Payment Entry", "Payment Ledger Entry", "China Accounting Voucher", "Sales Order", "Sales Order Item"]
	# Include all installed children: taxes/payment schedules as well as item/OA detail tables.
	for parent in ["Purchase Order", "OA Purchase Request", "Material Request", "Stock Entry", "Purchase Receipt", "Purchase Invoice", "Payment Entry", "China Accounting Voucher", "Sales Order"]:
		if frappe.db.exists("DocType", parent):
			tables.extend(df.options for df in frappe.get_meta(parent).fields
				if df.fieldtype in {"Table", "Table MultiSelect"} and df.options)
	result = {"site": frappe.local.site, "tables": {}, "preserved_apps": {
		app: source_digest(app) for app in ["overseas_costing", "mes_integration", "oa_purchase_request", "china_finance", "draft_notifications", "custom_filters", "crm_integration", "ai_assistant", "client_akivision", "mobile_operations"]}}
	for doctype in sorted(set(tables)):
		if not frappe.db.exists("DocType", doctype):
			continue
		# Doctype names come only from this fixed allowlist and installed metadata; quote defensively.
		table = ("tab" + doctype).replace("`", "``")
		rows = frappe.db.sql(f"select * from `{table}` order by name", as_dict=True)
		result["tables"][doctype] = {"count": len(rows), "sha256": hashlib.sha256(
			json.dumps(rows, sort_keys=True, default=str, ensure_ascii=False).encode()).hexdigest()}
	assets = BENCH / "sites/assets/assets.json"
	result["assets_manifest_sha256"] = hashlib.sha256(assets.read_bytes()).hexdigest()
	return result


def main():
	frappe.init(site=SITE, sites_path=str(BENCH / "sites"))
	frappe.connect()
	try:
		print(json.dumps(capture_audit(), sort_keys=True, ensure_ascii=False))
	finally:
		frappe.db.rollback()
		frappe.destroy()


if __name__ == "__main__":
	main()
