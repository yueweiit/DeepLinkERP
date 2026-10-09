"""Read-only release audit. Emit hashes/counts, never business row contents."""

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath

import frappe

SITE = "deeplinkerp.com"
BENCH = Path("/home/frappe/frappe-bench")
REQUIRED_SOURCE_APPS = ("deeplinkerp_branding", "china_finance", "crm_integration", "oa_purchase_request")
OPERATING_MODELS = ("Operating Expense Company Map", "Operating Expense Source", "Operating Expense Mapping", "Operating Expense Event", "Operating Expense Sync Settings", "Purchase Fulfilment Link","Operating Expense Takeover","Operating Expense Payment")


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
		assert app in set(REQUIRED_SOURCE_APPS), "Unexpected overlay app"
		current = source_files(app)
		for path, versions in files.items():
			relative = PurePosixPath(path)
			assert path and not relative.is_absolute() and ".." not in relative.parts and "\\" not in path
			assert str(relative) == path and relative.parts, "Invalid source path"
			root = BENCH / "apps" / app / app
			assert (root / path).resolve().is_relative_to(root.resolve()), "Source path escapes app"
			assert current.get(path) == versions[phase], f"Source drift: {app}/{path} ({phase})"


def verify_purchase_payment_page(source):
	"""Require existing metadata; reloading a Page would recreate its Has Role children."""
	name = "purchase-payment-records"
	assert source.get("doctype") == "Page" and source.get("name") == name, "Unexpected Page source"
	try:
		page = frappe.get_doc("Page", name)
	except frappe.DoesNotExistError:
		raise AssertionError(f"Missing Page: {name}") from None
	for field in ("doctype", "name", "module", "title", "standard"):
		assert page.get(field) == source[field], f"Page metadata drift: {name} ({field})"
	# Child Document initialization repairs falsy idx and parent links; inspect stored rows directly.
	roles = frappe.db.sql(
		"select role, parent, parenttype, parentfield, idx from `tabHas Role` where parent = %s order by idx, name",
		(name,),
		as_dict=True,
	)
	assert [role.get("role") for role in roles] == [role["role"] for role in source["roles"]], (
		f"Page metadata drift: {name} (roles)"
	)
	for index, role in enumerate(roles, 1):
		assert (
			role.get("parent") == name
			and role.get("parenttype") == "Page"
			and role.get("parentfield") == "roles"
			and role.get("idx") == index
		), f"Page metadata drift: {name} (role child links)"


def source_digest(app):
	root = BENCH / "apps" / app / app
	if not root.is_dir():
		assert app not in REQUIRED_SOURCE_APPS and app not in frappe.get_installed_apps(), f"Missing required/installed preserved app: {app}"
		return None  # Preserve explicit absence; a later unexpected app/source cannot disappear from the audit.
	digest = hashlib.sha256()
	for path in sorted(root.rglob("*")):
		if not path.is_file() or "__pycache__" in path.parts or path.suffix in {".pyc", ".pyo"}:
			continue
		digest.update(str(path.relative_to(root)).encode())
		digest.update(path.read_bytes())
	return digest.hexdigest()


def table_schema(doctype):
	"""Raw native column/default/null/index definitions, without volatile cardinality."""
	name = "tab" + doctype
	columns = frappe.db.sql(
		"select COLUMN_NAME as name, ORDINAL_POSITION as position, COLUMN_TYPE as type, "
		"IS_NULLABLE as nullable, COLUMN_DEFAULT as default_value, CHARACTER_SET_NAME as charset, "
		"COLLATION_NAME as collation, EXTRA as extra, GENERATION_EXPRESSION as expression "
		"from information_schema.COLUMNS where TABLE_SCHEMA=database() and TABLE_NAME=%s order by ORDINAL_POSITION",
		(name,), as_dict=True,
	)
	if not columns:
		return None
	indexes = frappe.db.sql(
		"select INDEX_NAME as name, SEQ_IN_INDEX as sequence, COLUMN_NAME as `column`, "
		"(1-NON_UNIQUE) as `unique`, SUB_PART as prefix, COLLATION as collation, INDEX_TYPE as type, NULLABLE as nullable "
		"from information_schema.STATISTICS where TABLE_SCHEMA=database() and TABLE_NAME=%s order by INDEX_NAME, SEQ_IN_INDEX",
		(name,), as_dict=True,
	)
	options = frappe.db.sql(
		"select ENGINE as engine, ROW_FORMAT as row_format, TABLE_COLLATION as collation, CREATE_OPTIONS as options "
		"from information_schema.TABLES where TABLE_SCHEMA=database() and TABLE_NAME=%s", (name,), as_dict=True,
	)[0]
	result = {"columns": {}, "indexes": {}, "table": options}
	for row in columns:
		result["columns"][row.pop("name")] = row
	for row in indexes:
		result["indexes"].setdefault(row.pop("name"), []).append(row)
	return json.loads(json.dumps(result, default=str))


def capture_audit(*, je_columns=None, oa_columns=None, native_columns=None):
	"""Capture inside the caller's transaction; the CLI remains read-only."""
	for app in set(REQUIRED_SOURCE_APPS) | set(frappe.get_installed_apps()):
		assert (BENCH / "apps" / app / app).is_dir(), "Missing required/installed app source: " + app
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
		"Journal Entry",
		"Bin",
		"Inventory Original Location Snapshot",
		"Purchase Receipt",
		"Purchase Invoice",
		"Payment Entry",
		"Repost Item Valuation",
		"Integration Request",
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
		"File",
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
		"Repost Item Valuation",
		"Integration Request",
		"Journal Entry",
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
		"schemas": {},
		"release_sources_all": {app: source_files(app) for app in sorted(set(REQUIRED_SOURCE_APPS) | set(frappe.get_installed_apps()))},
		"preserved_apps": {
			app: source_digest(app)
			for app in sorted(set(REQUIRED_SOURCE_APPS) | set(frappe.get_installed_apps())) if app != "deeplinkerp_branding"
		},
	}
	for doctype in sorted(set(tables)):
		if not frappe.db.exists("DocType", doctype) or frappe.get_meta(doctype).issingle:
			continue
		# Doctype names come only from this fixed allowlist and installed metadata; quote defensively.
		table = ("tab" + doctype).replace("`", "``")
		projection = "*"
		original = je_columns if doctype == "Journal Entry" else oa_columns if doctype == "OA Purchase Request" else (native_columns or {}).get(doctype)
		if original is not None:
			assert original and "name" in original and len(original) == len(set(original))
			assert all(isinstance(field, str) and field.isidentifier() for field in original)
			projection = ",".join("`" + field + "`" for field in original)
		rows = frappe.db.sql(f"select {projection} from `{table}` order by name", as_dict=True)
		result["tables"][doctype] = {
			"count": len(rows),
			"sha256": hashlib.sha256(
				json.dumps(rows, sort_keys=True, default=str, ensure_ascii=False).encode()
			).hexdigest(),
		}
		result["schemas"][doctype] = table_schema(doctype)
	result["native_new_columns"] = {}
	if native_columns:
		from procurement_release_metadata import _native_reversal_contract
		contract = _native_reversal_contract()
		for dt, original in native_columns.items():
			for key in set(result["schemas"][dt]["columns"]) - set(original):
				assert key == (contract["activity_column"] if dt == "Integration Request" else contract["fieldname"]), "Unapproved native addition"
				condition = _native_activity_mismatch(contract) if dt == "Integration Request" else "`" + key + "` is not null"
				result["native_new_columns"][dt + "/" + key] = frappe.db.sql("select count(*) from `tab" + dt + "` where " + condition)[0][0]
	# Original rows remain hashed using their frozen projection. Independently
	# inspect every newly added OA column so later source writes cannot hide
	# behind that projection during the fresh final release audit.
	result["oa_new_columns"] = {}
	if oa_columns is not None and result["schemas"].get("OA Purchase Request"):
		from procurement_release_metadata import _oa_nondefault_condition
		for field in set(result["schemas"]["OA Purchase Request"]["columns"]) - set(oa_columns):
			assert field.isidentifier()
			result["oa_new_columns"][field] = frappe.db.sql("select count(*) from `tabOA Purchase Request` where " + _oa_nondefault_condition(field))[0][0]
	# These already-active rows must remain protected by the fresh final audit,
	# not only the earlier private receipt snapshot. New absent-before models
	# are allowed solely as exact-contract empty tables by the receipt verifier.
	result["operating_models"] = {}
	for doctype in OPERATING_MODELS:
		schema = table_schema(doctype)
		rows = frappe.db.sql("select * from `" + ("tab" + doctype).replace("`", "``") + "` order by name", as_dict=True) if schema else []
		result["operating_models"][doctype] = {"schema": schema, "rows": {"count": len(rows), "sha256": hashlib.sha256(json.dumps(rows, sort_keys=True, default=str, ensure_ascii=False).encode()).hexdigest()}}
	result["purchase_source_sync_enabled"] = bool(getattr(frappe, "conf", {}).get("purchase_source_sync_enabled"))
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
	for relative in ("common_site_config.json", frappe.local.site + "/site_config.json"):
		config = json.loads((BENCH / "sites" / relative).read_text())
		maintenance_mode = config.pop("maintenance_mode", maintenance_mode)
		result["configuration_sha256"][relative] = hashlib.sha256(
			json.dumps(config, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
		).hexdigest()
	result["maintenance_mode"] = maintenance_mode
	if result["purchase_source_sync_enabled"]:
		from joint_release_guards import verified_quiescence
		result["release_quiescent"] = maintenance_mode == 1 and verified_quiescence()
	assets = BENCH / "sites/assets/assets.json"
	result["assets_manifest_sha256"] = hashlib.sha256(assets.read_bytes()).hexdigest()
	return result


def _native_activity_mismatch(contract):
	return "`" + contract["activity_column"] + "` is null or `" + contract["activity_column"] + "` <> (" + contract["activity_expression"] + ")"


def capture_joint_state(*, original_columns=None, original_oa_columns=None, original_native_columns=None, native_only=False):
	"""Private receipt snapshot. Raw JE projection and all scoped metadata stay private."""
	from procurement_release_metadata import JOINT_MODELS, capture_joint_metadata, _native_reversal_contract
	assert OPERATING_MODELS == JOINT_MODELS, "Operating audit scope drift"

	schema = table_schema("Journal Entry")
	assert schema, "Native Journal Entry table is required"
	columns = original_columns or list(schema["columns"])
	assert all(isinstance(field, str) and field.isidentifier() for field in columns)
	rows = frappe.db.sql("select " + ",".join("`" + field + "`" for field in columns) + " from `tabJournal Entry` order by name", as_dict=True)
	oa_schema = table_schema("OA Purchase Request")
	oa = None
	if oa_schema:
		oa_columns = original_oa_columns or list(oa_schema["columns"])
		assert "name" in oa_columns and len(oa_columns) == len(set(oa_columns)) and all(isinstance(field, str) and field.isidentifier() for field in oa_columns)
		oa = {"schema": oa_schema, "original_columns": oa_columns, "rows": frappe.db.sql("select " + ",".join("`" + field + "`" for field in oa_columns) + " from `tabOA Purchase Request` order by name", as_dict=True)}
	models = {}
	for doctype in JOINT_MODELS:
		model_schema = table_schema(doctype)
		models[doctype] = {"schema": model_schema, "rows": frappe.db.sql("select * from `" + ("tab" + doctype).replace("`", "``") + "` order by name", as_dict=True) if model_schema else []}
	native = {}
	for dt in _native_reversal_contract()["tables"]:
		definition = table_schema(dt)
		assert definition, "Required native table missing: " + dt
		projection = (original_native_columns or {}).get(dt) or list(definition["columns"])
		assert "name" in projection and len(set(projection)) == len(projection) and all(key.isidentifier() for key in projection)
		native[dt] = {"schema": definition, "original_columns": projection, "rows": frappe.db.sql("select " + ",".join("`" + key + "`" for key in projection) + " from `tab" + dt + "` order by name", as_dict=True)}
	result = {"audit": capture_audit(je_columns=columns, oa_columns=oa["original_columns"] if oa else None, native_columns={dt: table["original_columns"] for dt, table in native.items()}), "metadata": capture_joint_metadata(native_only=True) if native_only else capture_joint_metadata(), "oa": oa, "native_tables": native,
		"je": {"schema": schema, "original_columns": columns, "rows": rows}, "models": models,
		"operating_singles": frappe.db.sql("select * from `tabSingles` where doctype='Operating Expense Sync Settings' order by field", as_dict=True)}
	if native_only:
		result["native_only"] = True
	return json.loads(json.dumps(result, default=str, ensure_ascii=False))


def main():
	parser = argparse.ArgumentParser()
	parser.add_argument("--release-manifest")
	parser.add_argument("--phase", choices=["before", "after", "current"])
	parser.add_argument("--purchase-payment-page-source")
	parser.add_argument("--procurement-metadata", action="store_true")
	parser.add_argument("--joint-metadata", action="store_true")
	parser.add_argument("--joint-receipt")
	from joint_release_guards import SHARED_SITES
	parser.add_argument("--site", choices=SHARED_SITES, default=SITE)
	parser.add_argument("--native-only", action="store_true")
	args = parser.parse_args()
	assert args.native_only == (args.site != SITE), "Main full/secondary native-only scope required"
	frappe.init(site=args.site, sites_path=str(BENCH / "sites"))
	frappe.connect()
	try:
		if args.purchase_payment_page_source:
			verify_purchase_payment_page(json.loads(Path(args.purchase_payment_page_source).read_text()))
		if args.phase == "current":
			assert args.release_manifest and not args.joint_receipt, "Current contract requires the frozen manifest, not a historical receipt"
			verify_sources(json.loads(Path(args.release_manifest).read_text()), "after")
			from procurement_release_metadata import verify_current_joint_contract
			print(json.dumps(verify_current_joint_contract(native_only=args.native_only), sort_keys=True, ensure_ascii=False))
			return
		original_columns = original_oa_columns = original_native_columns = None
		if args.joint_receipt:
			from joint_release_guards import DDLReceipt
			state = DDLReceipt.load(args.joint_receipt).state
			assert state["identity"]["site"] == args.site and state["identity"]["native_only"] == args.native_only, "Cross-site/scope audit receipt refused"
			before = state["before"]
			original_columns = before["je"]["original_columns"]
			original_oa_columns = before["oa"]["original_columns"] if before.get("oa") else None
			original_native_columns = {dt: table["original_columns"] for dt, table in before.get("native_tables", {}).items()}
		result = capture_audit(je_columns=original_columns, oa_columns=original_oa_columns, native_columns=original_native_columns)
		if args.procurement_metadata:
			from procurement_release_metadata import capture

			result["procurement_metadata"] = capture()
		if args.joint_metadata:
			from procurement_release_metadata import capture_joint_metadata
			result["joint_metadata"] = capture_joint_metadata(native_only=args.native_only)
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
