"""Read-only release audit. Emit hashes/counts, never business row contents."""

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath

import frappe

SITE = "deeplinkerp.com"
BENCH = Path("/home/frappe/frappe-bench")


def source_files(app):
	root = BENCH / "apps" / app / app
	return {
		str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
		for path in sorted(root.rglob("*"))
		if path.is_file() and "__pycache__" not in path.parts and path.suffix not in {".pyc", ".pyo"}
	}


def verify_sources(manifest, phase):
	assert phase in {"before", "after"}
	for app, files in manifest["apps"].items():
		assert app in {"deeplinkerp_branding", "crm_integration", "china_finance"}, "Unexpected overlay app"
		current = source_files(app)
		for path, versions in files.items():
			relative = PurePosixPath(path)
			assert path and not relative.is_absolute() and ".." not in relative.parts and "\\" not in path
			assert str(relative) == path and relative.parts, "Invalid source path"
			root = BENCH / "apps" / app / app
			assert (root / path).resolve().is_relative_to(root.resolve()), "Source path escapes app"
			assert current.get(path) == versions[phase], f"Source drift: {app}/{path} ({phase})"


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
	tables = [
		"Purchase Order",
		"Purchase Order Item",
		"Material Request",
		"Material Request Item",
		"OA Purchase Request",
		"Stock Entry",
		"Stock Entry Detail",
		"Stock Ledger Entry",
		"GL Entry",
		"Bin",
		"Inventory Original Location Snapshot",
		"Purchase Receipt",
		"Purchase Invoice",
		"Payment Entry",
		"Payment Ledger Entry",
		"China Accounting Voucher",
		"Sales Order",
		"Sales Order Item",
		"CRM Integration Log",
		"User",
		"Role",
		"Has Role",
		"User Permission",
		"Custom DocPerm",
		"China Cash Flow Assignment",
		"China Voucher Sync Issue",
		"Company",
		"CRM Integration Settings",
		"MES Integration Settings",
		"China Finance Settings",
	]
	# Include all installed children: taxes/payment schedules as well as item/OA detail tables.
	for parent in [
		"Purchase Order",
		"OA Purchase Request",
		"Material Request",
		"Stock Entry",
		"Purchase Receipt",
		"Purchase Invoice",
		"Payment Entry",
		"China Accounting Voucher",
		"Sales Order",
		"China Cash Flow Assignment",
		"China Voucher Sync Issue",
		"Company",
		"CRM Integration Settings",
		"MES Integration Settings",
		"China Finance Settings",
	]:
		if frappe.db.exists("DocType", parent):
			tables.extend(
				df.options
				for df in frappe.get_meta(parent).fields
				if df.fieldtype in {"Table", "Table MultiSelect"} and df.options
			)
	result = {
		"site": frappe.local.site,
		"tables": {},
		"preserved_apps": {
			app: source_digest(app)
			for app in [
				"overseas_costing",
				"mes_integration",
				"oa_purchase_request",
				"china_finance",
				"draft_notifications",
				"custom_filters",
				"crm_integration",
				"ai_assistant",
				"client_akivision",
				"mobile_operations",
			]
		},
	}
	for doctype in sorted(set(tables)):
		if not frappe.db.exists("DocType", doctype) or frappe.get_meta(doctype).issingle:
			continue
		# Doctype names come only from this fixed allowlist and installed metadata; quote defensively.
		table = ("tab" + doctype).replace("`", "``")
		rows = frappe.db.sql(f"select * from `{table}` order by name", as_dict=True)
		result["tables"][doctype] = {
			"count": len(rows),
			"sha256": hashlib.sha256(
				json.dumps(rows, sort_keys=True, default=str, ensure_ascii=False).encode()
			).hexdigest(),
		}
	# Single settings have no per-DocType SQL table. Preserve every installed Single, including integration URLs.
	singles = frappe.db.sql(
		"select doctype, field, value from `tabSingles` order by doctype, field, value", as_dict=True
	)
	result["singles"] = {
		"count": len(singles),
		"sha256": hashlib.sha256(
			json.dumps(singles, sort_keys=True, default=str, ensure_ascii=False).encode()
		).hexdigest(),
	}
	result["configuration_sha256"] = {}
	maintenance_mode = 0
	for relative in ("common_site_config.json", SITE + "/site_config.json"):
		config = json.loads((BENCH / "sites" / relative).read_text())
		maintenance_mode = config.pop("maintenance_mode", maintenance_mode)
		result["configuration_sha256"][relative] = hashlib.sha256(
			json.dumps(config, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
		).hexdigest()
	result["maintenance_mode"] = maintenance_mode
	assets = BENCH / "sites/assets/assets.json"
	result["assets_manifest_sha256"] = hashlib.sha256(assets.read_bytes()).hexdigest()
	return result


def main():
	parser = argparse.ArgumentParser()
	parser.add_argument("--release-manifest")
	parser.add_argument("--phase", choices=["before", "after"])
	args = parser.parse_args()
	frappe.init(site=SITE, sites_path=str(BENCH / "sites"))
	frappe.connect()
	try:
		result = capture_audit()
		if args.phase:
			assert result["maintenance_mode"] == 1, "Release audit requires maintenance mode on"
		if args.release_manifest:
			manifest = json.loads(Path(args.release_manifest).read_text())
			verify_sources(manifest, args.phase)
			result["release_sources"] = {app: source_files(app) for app in manifest["apps"]}
		print(json.dumps(result, sort_keys=True, ensure_ascii=False))
	finally:
		frappe.db.rollback()
		frappe.destroy()


if __name__ == "__main__":
	main()
