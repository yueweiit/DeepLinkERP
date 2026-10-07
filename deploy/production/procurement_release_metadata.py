"""Narrow, reversible metadata step for the approved procurement release.

Business documents and shared permissions are never modified. The receipt is
flushed before commit so shell recovery can restore exact original child IDs.
"""

import argparse
import ast
import copy
import contextlib
import hashlib
import json
import os
import re
from pathlib import Path

PAGE = "purchase-payables"
NAVIGATION = (("Workspace", "Buying"), ("Workspace Sidebar", "Buying"))
FULFILMENT_MODEL = "Purchase Fulfilment Link"
JOINT_MODELS = ("Operating Expense Company Map", "Operating Expense Source", "Operating Expense Mapping", "Operating Expense Event", "Operating Expense Sync Settings", FULFILMENT_MODEL)
JOINT_PAGES = (PAGE, "operating-expenses")
JOINT_NAVIGATION = tuple((dt, name) for name in ("Buying", "Accounting", "China Finance") for dt in ("Workspace", "Workspace Sidebar"))
OPERATING_METHOD = "deeplinkerp_branding.services.operating_expenses.scheduled_sync"
PURCHASE_SOURCE_METHOD = "deeplinkerp_branding.services.purchase_source_service.scheduled_sync"
SCHEDULED_METHODS = (OPERATING_METHOD, PURCHASE_SOURCE_METHOD)
CUSTOM_FIELD_ORDER = ("custom_operating_event_key", "custom_operating_source", "custom_operating_recognition", "custom_operating_fingerprint")
OA_DOCTYPE = "OA Purchase Request"
SOURCE_FIELD_ORDER = ("custom_purchase_source_id", "custom_purchase_source_json", "custom_cashier_payment_evidence", "custom_purchase_bound_version", "custom_purchase_payment_reconciliation", "custom_purchase_beneficiary_company", "custom_purchase_company_proposal", "custom_purchase_project", "custom_purchase_company_confirmed", "custom_purchase_company_confirmed_by", "custom_purchase_company_confirmed_on")
FULFILMENT_INDEX_COLUMNS = {"fulfilment_external_active": ("external_order", "active"), "fulfilment_internal_active": ("internal_order", "active")}


def _assert_release_sync_state(before, after=None):
	"""Keep the configured flag, but require the shell's locked, stopped-worker audit."""
	enabled = bool(before.get("purchase_source_sync_enabled"))
	if after is not None:
		assert bool(after.get("purchase_source_sync_enabled")) == enabled, "Source sync configuration changed during release"
	for audit in (before,) if after is None else (before, after):
		if enabled:
			assert audit.get("maintenance_mode") == 1 and audit.get("release_quiescent") is True, "Enabled source sync requires recorded maintenance and shell-held lock/worker quiescence"
	return enabled


def _json(value):
	return json.loads(json.dumps(value, default=str, ensure_ascii=False))


def _quote(value):
	return "`" + value.replace("`", "``") + "`"


def _rows(doctype):
	import frappe
	return _json(frappe.db.sql("select * from " + _quote("tab" + doctype) + " order by name", as_dict=True))


def _joint_selectors():
	"""All native metadata children are included, even when absent from JSON."""
	import frappe
	result = {
		"DocType": [("name", JOINT_MODELS)],
		"Custom Field": [("name", tuple("Journal Entry-" + field for field in CUSTOM_FIELD_ORDER) + tuple(OA_DOCTYPE + "-" + field for field in SOURCE_FIELD_ORDER))],
		"Page": [("name", JOINT_PAGES)],
		"Workspace": [("name", ("Buying", "Accounting", "China Finance"))],
		"Workspace Sidebar": [("name", ("Buying", "Accounting", "China Finance"))],
		"Scheduled Job Type": [("method", SCHEDULED_METHODS)],
	}
	for parent in ("DocType", "Custom Field", "Page", "Workspace", "Workspace Sidebar", "Scheduled Job Type", "Property Setter", "Custom DocPerm"):
		result.setdefault(parent, [])
		for field in frappe.get_meta(parent).fields:
			if field.fieldtype in {"Table", "Table MultiSelect"} and field.options:
				result.setdefault(field.options, []).append(("parenttype", (parent,)))
	return result


def _in_joint_scope(doctype, row):
	if doctype == "DocType":
		return row["name"] in JOINT_MODELS
	if doctype == "Custom Field":
		# Include conflicting/orphan aliases so preflight can reject them.
		return any(row["name"] in {dt + "-" + key for key in fields} or (row.get("dt") == dt and row.get("fieldname") in fields)
			for dt, fields in (("Journal Entry", CUSTOM_FIELD_ORDER), (OA_DOCTYPE, SOURCE_FIELD_ORDER)))
	if doctype == "Page":
		return row["name"] in JOINT_PAGES
	if doctype in {"Workspace", "Workspace Sidebar"}:
		return row["name"] in {"Buying", "Accounting", "China Finance"}
	if doctype == "Scheduled Job Type":
		return row.get("method") in SCHEDULED_METHODS or row.get("name") in SCHEDULED_METHODS
	return (row.get("parenttype"), row.get("parent")) in (
		{("DocType", name) for name in JOINT_MODELS} |
		{("Page", name) for name in JOINT_PAGES} | set(JOINT_NAVIGATION)
	)


def capture_joint_metadata():
	"""Raw scope AND raw outside rows, including original identities and creation."""
	result = {"scope": {}, "outside": {}, "outside_rows": {}}
	for doctype in sorted(_joint_selectors()):
		rows = _rows(doctype)
		result["scope"][doctype] = [row for row in rows if _in_joint_scope(doctype, row)]
		outside = [row for row in rows if not _in_joint_scope(doctype, row)]
		result["outside"][doctype] = digest(outside)
		result["outside_rows"][doctype] = outside
	return result


def _custom_fields():
	"""Reuse the frozen app installer definitions without invoking its hook."""
	import frappe
	path = Path(frappe.get_app_path("deeplinkerp_branding", "operating_expense_install.py"))
	tree = ast.parse(path.read_text())
	calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "create_custom_fields"]
	assert len(calls) == 1 and len(calls[0].args) == 1
	definitions = ast.literal_eval(calls[0].args[0])
	assert set(definitions) == {"Journal Entry"}
	result = {row["fieldname"]: row for row in definitions["Journal Entry"]}
	assert set(result) == {"custom_operating_event_key", "custom_operating_source", "custom_operating_recognition", "custom_operating_fingerprint"}
	for row in result.values():
		assert row["read_only"] == row["no_copy"] == 1 and not row.get("reqd") and not row.get("default")
	assert result["custom_operating_event_key"].get("unique") == 1
	return result


def _source_custom_fields():
	"""Read the exact eleven approved definitions, never execute the app installer."""
	import frappe
	tree = ast.parse(Path(frappe.get_app_path("deeplinkerp_branding", "purchase_source_install.py")).read_text())
	values = [ast.literal_eval(node.value) for node in ast.walk(tree) if isinstance(node, ast.Assign)
		and any(isinstance(target, ast.Name) and target.id == "definitions" for target in node.targets)]
	assert len(values) == 1 and set(values[0]) == {"Purchase Order", OA_DOCTYPE}, "Source installer definition drift"
	rows = values[0][OA_DOCTYPE]
	result = {row["fieldname"]: row for row in rows}
	assert len(rows) == len(result) == 11 and tuple(result) == SOURCE_FIELD_ORDER
	roles = {
		"custom_purchase_beneficiary_company": ("Link", "Company", 0, "最终使用/销售公司"),
		"custom_purchase_company_proposal": ("Link", "Company", 0, "建议采购公司"),
		"custom_purchase_project": ("Link", "Project", 0, "已确认采购项目"),
		"custom_purchase_company_confirmed": ("Check", None, 1, "采购公司已确认"),
		"custom_purchase_company_confirmed_by": ("Link", "User", 1, "采购公司确认人"),
		"custom_purchase_company_confirmed_on": ("Datetime", None, 1, "采购公司确认时间"),
	}
	for name, field in result.items():
		kind, options, hidden, label = roles.get(name, ("Data" if name in {"custom_purchase_source_id", "custom_purchase_bound_version"} else "Long Text", None, 1, field["label"]))
		assert field["fieldtype"] == kind and field["read_only"] == field["no_copy"] == 1 and field.get("hidden", 0) == hidden
		assert not field.get("reqd") and not field.get("default") and field.get("options") == options and field["label"] == label
		assert field.get("unique", 0) == int(name == "custom_purchase_source_id")
		assert field.get("permlevel", 0) == (9 if kind == "Long Text" else 0)
		assert set(field) <= {"fieldname", "label", "fieldtype", "options", "hidden", "read_only", "no_copy", "unique", "permlevel", "reqd", "default"}, "Unapproved source field behavior"
	return result


def _native_sql_row(item):
	"""Coerce a new native row and include every physical metadata column.

	Legacy nullable SQL columns can outlive their native Meta fields. Existing
	rows do not use this path: their complete raw SQL bytes remain authoritative.
	"""
	from frappe.utils import cint
	from audit_unified_purchase import table_schema

	item._fix_numeric_types()
	values = item.get_valid_dict(ignore_virtual=True)
	values["docstatus"] = cint(values.get("docstatus"))
	for key, schema in table_schema(item.doctype)["columns"].items():
		values.setdefault(key, None)
		if values[key] is None and schema["nullable"] == "NO":
			default = schema["default_value"]
			assert default not in {None, "NULL"}, "Unknown non-NULL native metadata default: " + key
			values[key] = int(default.strip("'")) if schema["type"].startswith(("int", "tinyint", "bigint")) else default.strip("'")
	return _json(values)


def _native_rows(source, *, when, seed, defaults=False):
	"""Use native import ordering and native valid-dict coercion, without hooks."""
	import frappe
	from frappe.model.base_document import get_controller

	source = copy.deepcopy(source)
	controller = get_controller(source["doctype"])
	if hasattr(controller, "prepare_for_import"):
		controller.prepare_for_import(source)
	doc = frappe.get_doc(source)
	if defaults:
		# Only native static defaults; user/company defaults cannot change the contract.
		for field in doc.meta.fields:
			if doc.get(field.fieldname) is None and field.default is not None:
				assert field.default not in {"Today", "Now", "__user"} and not str(field.default).startswith(":"), "Dynamic native default in release definition"
				doc.set(field.fieldname, field.default)
	doc.set_parent_in_children()
	result = {}
	for item in (doc, *doc.get_all_children()):
		item.name = item.name or "dlp-ope-" + hashlib.sha256((seed + ":" + item.doctype + ":" + str(item.parentfield) + ":" + str(item.idx)).encode()).hexdigest()[:24]
		item.creation = item.modified = when
		item.owner = item.modified_by = "Administrator"
		item.docstatus = 0
		result.setdefault(item.doctype, []).append(_native_sql_row(item))
	return result


def _definition_rows(source, defaults=False):
	from joint_release_guards import semantic_row
	return {dt: [semantic_row(row) for row in rows] for dt, rows in _native_rows(source, when="2000-01-01 00:00:00.000000", seed="definition", defaults=defaults).items()}


@contextlib.contextmanager
def _read_only_native_planning():
	"""No DB commit/rollback, SQL mutation or Redis mutation during schema capture."""
	import frappe
	from unittest.mock import patch

	original_sql = frappe.db.sql
	original_get_meta = frappe.get_meta
	local_cache = {}
	queries = []
	def native_get_meta(doctype, *args, **kwargs):
		if doctype in JOINT_MODELS:
			from frappe.model.base_document import get_controller
			from frappe.model.meta import Meta
			basename = frappe.scrub(doctype)
			path = Path(frappe.get_app_path("deeplinkerp_branding", "deeplinkerp_branding", "doctype", basename, basename + ".json"))
			source = json.loads(path.read_text())
			get_controller("DocType").prepare_for_import(source)
			return Meta(frappe.get_doc(source))
		return original_get_meta(doctype, cached=False)
	def read_sql(query, *args, **kwargs):
		assert re.match(r"\s*(select|show|describe|explain)\b", str(query), re.I), "Native planning attempted a write"
		return original_sql(query, *args, **kwargs)
	def forbidden(*args, **kwargs):
		raise AssertionError("Native planning attempted commit or external mutation")
	def cache_get(key, generator=None, user=None, expires=False, shared=False, **kwargs):
		identity = ("redis", key, user, shared)
		if identity not in local_cache and generator:
			local_cache[identity] = generator()
		return local_cache.get(identity)
	def cache_set(key, value, user=None, expires_in_sec=None, shared=False):
		local_cache[("redis", key, user, shared)] = value
	with contextlib.ExitStack() as stack:
		stack.enter_context(patch.object(frappe, "get_meta", native_get_meta))
		stack.enter_context(patch.object(frappe.db, "sql", read_sql))
		stack.enter_context(patch.object(frappe.db, "sql_ddl", lambda query, **kwargs: queries.append(str(query))))
		for name in ("commit", "rollback"):
			stack.enter_context(patch.object(frappe.db, name, forbidden))
		# Native get_meta writes even with cached=False. Virtualize those writes.
		stack.enter_context(patch.object(frappe.client_cache, "get_value", lambda key, *a, **kw: local_cache.get(key)))
		stack.enter_context(patch.object(frappe.client_cache, "set_value", lambda key, value, *a, **kw: local_cache.__setitem__(key, value)))
		stack.enter_context(patch.object(frappe.client_cache, "delete_value", lambda key, *a, **kw: local_cache.pop(key, None)))
		# Native table-column reads fill the ordinary Redis cache too. Keep that
		# fill entirely local; direct Redis mutations remain forbidden.
		stack.enter_context(patch.object(frappe.cache, "get_value", cache_get))
		stack.enter_context(patch.object(frappe.cache, "set_value", cache_set))
		stack.enter_context(patch.object(frappe.cache, "delete_value", lambda key, *a, **kw: None))
		for name in ("set", "delete", "hset", "hdel", "sadd", "srem", "publish", "flushdb", "flushall"):
			stack.enter_context(patch.object(frappe.cache, name, forbidden))
		yield queries


def _native_schema_sql(doctype, meta):
	from frappe.database.mariadb.schema import MariaDBTable
	with _read_only_native_planning() as queries:
		table = MariaDBTable(doctype, meta)
		table.validate()
		if table.is_new():
			table.create()
		else:
			table.alter()
	return queries


def _schema_from_create(query):
	"""Exact expected information_schema representation of the frozen native CREATE."""
	match = re.match(r"\s*CREATE TABLE `tab([^`]+)`\s*\(", query, re.I)
	assert match and match[1] in JOINT_MODELS, "Native CREATE escaped the exact model allowlist"
	body = query.split("(\n", 1)[1].rsplit(")\n", 1)[0]
	parts = re.split(r",\s*\n", body)
	result = {"columns": {}, "indexes": {}, "table": {"engine": "InnoDB", "row_format": "Dynamic", "collation": "utf8mb4_unicode_ci", "options": "row_format=DYNAMIC"}}
	index_specs = []
	for part in parts:
		part = part.strip()
		index = re.fullmatch(r"index `?([\w]+)`?\(`?([\w]+)`?\)", part, re.I)
		if index:
			index_specs.append((index[1], index[2], 0))
			continue
		match = re.fullmatch(r"`?([\w]+)`?\s+([\w]+(?:\([\d,]+\))?)(.*)", part, re.S)
		assert match, "Unrecognized native CREATE definition: " + part
		name, kind, flags = match.groups()
		kind = {"int": "int(11)", "tinyint": "tinyint(4)", "bigint": "bigint(20)"}.get(kind, kind)
		text = kind.startswith(("varchar", "text", "longtext"))
		nullable = "NO" if "NOT NULL" in flags.upper() or "PRIMARY KEY" in flags.upper() else "YES"
		default_match = re.search(r"DEFAULT\s+('(?:[^']|'')*'|[^\s]+)", flags, re.I)
		default = default_match[1] if default_match else ("NULL" if nullable == "YES" else None)
		if kind.startswith("decimal") and default != "NULL":
			default = format(float(default.strip("'")), "." + kind.rsplit(",", 1)[1][:-1] + "f")
		elif not text and default is not None:
			default = default.strip("'")
		result["columns"][name] = {"position": len(result["columns"]) + 1, "type": kind, "nullable": nullable, "default_value": default, "charset": "utf8mb4" if text else None, "collation": "utf8mb4_unicode_ci" if text else None, "extra": "", "expression": None}
		if "PRIMARY KEY" in flags.upper():
			index_specs.append(("PRIMARY", name, 1))
		elif "UNIQUE" in flags.upper():
			index_specs.append((name, name, 1))
	for name, column, unique in index_specs:
		result["indexes"][name] = [{"sequence": 1, "column": column, "unique": unique, "prefix": None, "collation": "A", "type": "BTREE", "nullable": "YES" if result["columns"][column]["nullable"] == "YES" else ""}]
	return result


def _fulfilment_indexes(schema):
	return {name: [{"sequence": i + 1, "column": column, "unique": 0, "prefix": None, "collation": "A", "type": "BTREE", "nullable": "YES" if schema["columns"][column]["nullable"] == "YES" else ""} for i, column in enumerate(columns)] for name, columns in FULFILMENT_INDEX_COLUMNS.items()}


def _installer_source_files():
	root = Path(__file__).parent
	return {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in ("procurement_release_metadata.py", "audit_unified_purchase.py", "joint_release_guards.py")}


def _assert_no_joint_customizations():
	"""Reject effective Meta overrides before constructing the frozen contract.

	Native Meta absorbs these rows independently of the standard DocType JSON.
	Custom DocPerm is keyed by parent only, including legacy NULL parenttype.
	Unrelated Journal Entry customizations remain outside this bounded check.
	"""
	import frappe

	models = tuple(JOINT_MODELS)
	placeholders = ",".join(["%s"] * len(models))
	queries = (
		("Custom Field", "select name from `tabCustom Field` where dt in (" + placeholders + ")", models),
		("Property Setter", "select name from `tabProperty Setter` where doc_type in (" + placeholders + ") or (doc_type=%s and field_name in (" + ",".join(["%s"] * len(CUSTOM_FIELD_ORDER)) + ")) or (doc_type=%s and field_name in (" + ",".join(["%s"] * len(SOURCE_FIELD_ORDER)) + "))", (*models, "Journal Entry", *CUSTOM_FIELD_ORDER, OA_DOCTYPE, *SOURCE_FIELD_ORDER)),
		("Custom DocPerm", "select name from `tabCustom DocPerm` where parent in (" + placeholders + ")", models),
	)
	for doctype, query, values in queries:
		assert not frappe.db.sql(query, values), "Unapproved effective customization targets frozen operating metadata: " + doctype


def load_joint_contract(*, require_quiescent=True):
	import frappe
	from frappe.model.meta import Meta
	from audit_unified_purchase import table_schema, source_files
	from joint_release_guards import serialized

	assert frappe.__version__ == "16.23.0" and frappe.db.db_type == "mariadb", "Frozen native Frappe 16.23/MariaDB contract required"
	_assert_no_joint_customizations()
	root = Path(frappe.get_app_path("deeplinkerp_branding"))
	files, definitions, schemas, ddl = {}, {}, {}, {}
	base_schemas, index_ddl = {}, {}
	for name in JOINT_MODELS:
		basename = frappe.scrub(name)
		path = root / "deeplinkerp_branding/doctype" / basename / (basename + ".json")
		source = json.loads(path.read_text())
		assert source["doctype"] == "DocType" and source["name"] == name and source["module"] == "Deeplinkerp Branding" and source["custom"] == 0
		assert not source.get("is_virtual") and source.get("autoname") not in {"autoincrement", "UUID"}
		files[str(path.relative_to(root))] = hashlib.sha256(path.read_bytes()).hexdigest()
		definitions[name] = {"source": source, "native": _definition_rows(source)}
		meta_source = copy.deepcopy(source)
		from frappe.model.base_document import get_controller
		get_controller("DocType").prepare_for_import(meta_source)
		meta = Meta(frappe.get_doc(meta_source))
		if not source.get("issingle", 0):
			# Generate CREATE even for matching preexisting tables, in memory only.
			from frappe.database.mariadb.schema import MariaDBTable
			with _read_only_native_planning() as captured:
				MariaDBTable(name, meta).create()
			assert len(captured) == 1
			ddl[name] = captured[0]
			schemas[name] = _schema_from_create(captured[0])
			base_schemas[name] = copy.deepcopy(schemas[name])
			if name == FULFILMENT_MODEL:
				schemas[name]["indexes"].update(_fulfilment_indexes(schemas[name]))
				index_ddl[name] = {index: "ALTER TABLE " + _quote("tab" + name) + " ADD INDEX IF NOT EXISTS " + _quote(index) + "(" + ", ".join(columns) + ")" for index, columns in FULFILMENT_INDEX_COLUMNS.items()}
		else:
			schemas[name] = None
			base_schemas[name] = None
	for name in JOINT_PAGES:
		basename = frappe.scrub(name)
		path = root / "deeplinkerp_branding/page" / basename / (basename + ".json")
		source = json.loads(path.read_text())
		assert source["doctype"] == "Page" and source["name"] == name
		files[str(path.relative_to(root))] = hashlib.sha256(path.read_bytes()).hexdigest()
		definitions[name] = {"source": source, "native": _definition_rows(source)}
	custom_fields = _custom_fields()
	for key, definition in custom_fields.items():
		source = dict(definition, doctype="Custom Field", dt="Journal Entry", name="Journal Entry-" + key)
		definitions[source["name"]] = {"source": source, "native": _definition_rows(source, defaults=True)}
	source_fields = _source_custom_fields() if frappe.db.exists("DocType", OA_DOCTYPE) else {}
	for key, definition in source_fields.items():
		source = dict(definition, doctype="Custom Field", dt=OA_DOCTYPE, name=OA_DOCTYPE + "-" + key)
		definitions[source["name"]] = {"source": source, "native": _definition_rows(source, defaults=True)}
	for method in SCHEDULED_METHODS:
		job = {"doctype": "Scheduled Job Type", "name": method, "method": method, "frequency": "Cron", "cron_format": "*/15 * * * *"}
		definitions[method] = {"source": job, "native": _definition_rows(job, defaults=True)}
	for relative in ("operating_expense_install.py", "purchase_source_install.py", "purchase_fulfilment_install.py", "hooks.py", "operating_navigation.py", "procurement_navigation.py"):
		files[relative] = hashlib.sha256((root / relative).read_bytes()).hexdigest()
	index_calls = [node for node in ast.walk(ast.parse((root / "purchase_fulfilment_install.py").read_text())) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "add_index"]
	assert [tuple(ast.literal_eval(argument) for argument in call.args) for call in index_calls] == [(FULFILMENT_MODEL, list(columns), index) for index, columns in FULFILMENT_INDEX_COLUMNS.items()], "Fulfilment installer index drift"
	hooks = ast.parse((root / "hooks.py").read_text())
	schedules = [ast.literal_eval(node.value) for node in hooks.body if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == "scheduler_events" for target in node.targets)]
	assert len(schedules) == 1 and set(SCHEDULED_METHODS) <= set(schedules[0].get("cron", {}).get("*/15 * * * *", [])), "Frozen cron hook drift"
	if require_quiescent:
		_assert_release_sync_state({"purchase_source_sync_enabled": bool(frappe.conf.get("purchase_source_sync_enabled")), "maintenance_mode": frappe.conf.get("maintenance_mode"), "release_quiescent": os.environ.get("DEEPLINKERP_RELEASE_QUIESCENT") == "1"})
	return {"frappe_version": frappe.__version__, "files": files, "installer_files": _installer_source_files(), "definitions": definitions, "model_schemas": schemas, "model_base_schemas": base_schemas, "model_ddl": ddl, "model_index_ddl": index_ddl, "custom_fields": custom_fields, "source_custom_fields": source_fields, "native_metadata_schemas": {dt: table_schema(dt) for dt in ("DocType", "DocField", "DocPerm", "Custom Field", "Page", "Has Role", "Scheduled Job Type")}, "sources_after": {app: source_files(app) for app in ("deeplinkerp_branding", "china_finance", "crm_integration")}}


def _definition_matches(scope, name, definition):
	from joint_release_guards import semantic_row
	source = definition["source"]
	parent_dt = source["doctype"]
	if parent_dt == "Scheduled Job Type":
		parents = [row for row in scope[parent_dt] if row.get("method") == source["method"]]
		assert all(row.get("method") in SCHEDULED_METHODS and (row["name"] not in SCHEDULED_METHODS or row["name"] == row.get("method")) for row in scope[parent_dt]), "Conflicting scheduled job identity"
	else:
		parents = [row for row in scope[parent_dt] if row["name"] == name]
	children = {dt: [row for row in rows if row.get("parenttype") == parent_dt and row.get("parent") == name] for dt, rows in scope.items() if dt != parent_dt}
	if not parents:
		assert not any(children.values()), "Orphan native metadata: " + name
		return False
	actual_parents = [semantic_row(row) for row in parents]
	if parent_dt == "Scheduled Job Type":
		# Keep execution timestamps and an existing dedicated runner's logging
		# flag in the raw scope byte-for-byte. Only a native default (not an
		# explicit source policy) may accept the runner's evidenced 0/1 flag.
		# Method, frequency, cron, stopped and server_script remain exact.
		wanted_parent = definition["native"][parent_dt][0]
		for row in actual_parents:
			if "last_execution" in row:
				row["last_execution"] = wanted_parent.get("last_execution")
			if "create_log" in row:
				assert type(row["create_log"]) is int and row["create_log"] in (0, 1), "Invalid scheduled logging flag: " + name
				if "create_log" not in source and wanted_parent.get("create_log") == 0:
					row["create_log"] = 0
	if parent_dt == "Page" and "page_name" not in source:
		# Bounded legacy compatibility: NULL or exactly the approved source route.
		# Keep the complete original raw Page row; this comparison never rewrites it.
		for row in actual_parents:
			assert row.get("page_name") in {None, name}, "Conflicting native Page route: " + name
			row["page_name"] = definition["native"][parent_dt][0].get("page_name")
	assert len(parents) == 1 and actual_parents == definition["native"][parent_dt], "Conflicting full native definition: " + name
	for dt, rows in children.items():
		wanted = definition["native"].get(dt, [])
		actual = [semantic_row(row) for row in sorted(rows, key=lambda row: (row.get("idx", 0), row["name"]))]
		assert actual == wanted, "Conflicting native child definitions: " + name + "/" + dt
	return True


def _desired_navigation(scope, *, when, seed):
	import frappe
	from deeplinkerp_branding.procurement_navigation import reconcile_links, reconcile_workspace
	from deeplinkerp_branding.operating_navigation import ENTRIES, TARGETS, _anchor

	expected = copy.deepcopy(scope)
	for dt, name in JOINT_NAVIGATION:
		original = next((row for row in scope[dt] if row["name"] == name), None)
		if original is None:
			continue
		doc = frappe.get_doc(dt, name)
		before_doc = _json(doc.as_dict())
		if name == "Buying":
			changed = reconcile_workspace(doc) if dt == "Workspace" else reconcile_links(doc, "items")
		else:
			changed = reconcile_workspace(doc, entries=ENTRIES, targets=TARGETS, prefix="dlp-operating-", anchor=_anchor(doc, "links")) if dt == "Workspace" else reconcile_links(doc, "items", entries=ENTRIES, targets=TARGETS, anchor=_anchor(doc, "items"))
		if not changed:
			continue
		for item in (doc, *doc.get_all_children()):
			item_dt = item.doctype
			old = next((row for row in scope[item_dt] if row["name"] == item.name), None)
			if old is not None:
				old_doc = before_doc if item is doc else next(row for value in before_doc.values() if isinstance(value, list) for row in value if row.get("name") == item.name)
				native = _json(item.get_valid_dict(sanitize=False))
				# Preserve raw original NULLs/custom bytes; overlay only reconciliation changes.
				row = dict(old)
				for key, value in native.items():
					if key in row and _json(old_doc.get(key)) != value:
						row[key] = value
				if item is doc:
					row.update(modified=when, modified_by="Administrator")
			else:
				item.name = "dlp-ope-" + hashlib.sha256((seed + ":" + dt + ":" + name + ":" + item_dt + ":" + str(item.parentfield) + ":" + str(item.idx)).encode()).hexdigest()[:24]
				item.creation = item.modified = when
				item.owner = item.modified_by = "Administrator"
				row = _native_sql_row(item)
			expected[item_dt] = [other for other in expected[item_dt] if other["name"] != row["name"]]
			expected[item_dt].append(row)
		for field in doc.meta.get_table_fields():
			retained = {item.name for item in doc.get(field.fieldname) or []}
			expected[field.options] = [row for row in expected[field.options] if not (row.get("parenttype") == dt and row.get("parent") == name and row.get("parentfield") == field.fieldname) or row["name"] in retained]
	return {dt: sorted(rows, key=lambda row: row["name"]) for dt, rows in expected.items()}


def _assert_frozen_je_fields(meta, contract, present):
	"""Check effective fields as well as raw CF rows and their SQL definitions.

	Native field sorting changes idx. All other shared native behavior/default
	columns must still match the frozen CF, not an effective Property Setter.
	"""
	_assert_frozen_fields(meta, contract, present, "Journal Entry")


def _assert_frozen_fields(meta, contract, present, doctype):
	registration = {"name", "creation", "modified", "owner", "modified_by", "docstatus", "idx", "_comments", "_assign", "_user_tags", "_liked_by"}
	shared = set(contract["native_metadata_schemas"]["DocField"]["columns"]) - registration
	for key in present:
		fields = [field for field in meta.fields if field.fieldname == key]
		assert len(fields) == 1, "Missing/duplicate effective native field: " + doctype + "/" + key
		expected = contract["definitions"][doctype + "-" + key]["native"]["Custom Field"][0]
		assert all(fields[0].get(flag) == value for flag, value in expected.items() if flag in shared), "Conflicting effective native field behavior: " + doctype + "/" + key


def _joint_plan(before, contract, *, when, seed, require_quiescent=True):
	import frappe
	from frappe.model.meta import Meta
	from audit_unified_purchase import table_schema
	from joint_release_guards import validate_event_index

	_assert_no_joint_customizations()
	if require_quiescent:
		_assert_release_sync_state(before.get("audit", {}))
	scope = before["metadata"]["scope"]
	for row in scope["Custom Field"]:
		fields = CUSTOM_FIELD_ORDER if row.get("dt") == "Journal Entry" else SOURCE_FIELD_ORDER if row.get("dt") == OA_DOCTYPE else ()
		assert row.get("fieldname") in fields and row["name"] == row["dt"] + "-" + row["fieldname"], "Orphan/conflicting Custom Field identity"
	assert not frappe.db.sql("select name from `tabDocField` where parent='Journal Entry' and fieldname in (" + ",".join(["%s"] * len(CUSTOM_FIELD_ORDER)) + ")", CUSTOM_FIELD_ORDER), "Operating fields conflict with standard Journal Entry DocFields"
	expected = copy.deepcopy(scope)
	new = []
	page_title_updates = []
	for name, definition in contract["definitions"].items():
		page = next((row for row in scope["Page"] if row["name"] == name), None) if name == "operating-expenses" else None
		upgrade_title = page is not None and page.get("title") == "运营费用" and definition["source"].get("doctype") == "Page" and definition["source"].get("name") == name and definition["source"].get("title") == "运营支出" and definition["native"]["Page"][0].get("title") == "运营支出"
		matching_definition = definition
		if upgrade_title:
			# Only this approved same-route title transition is compatible. Reuse
			# the ordinary strict matcher for every other native parent/child field.
			matching_definition = copy.deepcopy(definition)
			matching_definition["source"]["title"] = "运营费用"
			matching_definition["native"]["Page"][0]["title"] = "运营费用"
		matching = _definition_matches(scope, name, matching_definition)
		if upgrade_title:
			assert matching
			expected["Page"] = [dict(row, title="运营支出") if row["name"] == name else row for row in expected["Page"]]
			page_title_updates.append({"name": name, "field": "title", "before": "运营费用", "after": "运营支出"})
		if name in JOINT_MODELS:
			actual = before["models"][name]["schema"]
			assert actual == contract["model_schemas"][name] if matching else actual is None, "Conflicting/orphan model SQL table: " + name
		if not matching:
			new.append(name)
			for dt, rows in _native_rows(definition["source"], when=when, seed=seed + name, defaults=definition["source"]["doctype"] in {"Custom Field", "Scheduled Job Type"}).items():
				expected[dt].extend(rows)
	columns = before["je"]["schema"]["columns"]
	indexes = before["je"]["schema"]["indexes"]
	for key in contract["custom_fields"]:
		present = "Journal Entry-" + key not in new
		assert (key in columns) == present, "Orphan/missing Journal Entry SQL column: " + key
		if present:
			assert columns[key] == _je_column(len(columns), position=columns[key]["position"]), "Conflicting Journal Entry column: " + key
		if key == "custom_operating_event_key":
			assert (key in indexes) == present, "Orphan/missing event key index"
			if present:
				validate_event_index(indexes[key])
		for index_name, rows in indexes.items():
			if any(row["column"] == key for row in rows):
				assert key == "custom_operating_event_key" and index_name == key, "Unapproved index on operating field"
	for name, definition in contract["definitions"].items():
		for dt, rows in definition["native"].items():
			for row in rows:
				if row.get("role"):
					assert frappe.db.exists("Role", row["role"]), "Required native Role missing; do not create roles"
	for name, model in before["models"].items():
		assert not model["rows"] or (model["schema"] is not None and name not in new), "Populated operating model must already match its frozen definition"
	if before["operating_singles"]:
		assert "Operating Expense Sync Settings" not in new and any(row["name"] == "Operating Expense Sync Settings" for row in scope.get("DocType", [])), "Configured operating Single requires existing exact metadata"
	expected = _desired_navigation(expected, when=when, seed=seed)
	# Inspect the native desired JE delta BEFORE registering any metadata.
	meta = copy.deepcopy(frappe.get_meta("Journal Entry", cached=False))
	_assert_frozen_je_fields(meta, contract, [key for key in contract["custom_fields"] if key in columns])
	for key, field in contract["custom_fields"].items():
		if key not in columns:
			meta.fields.append(frappe._dict(field))
	for query in _native_schema_sql("Journal Entry", meta):
		_validate_je_ddl(query, {key for key in contract["custom_fields"] if key not in columns})
	source_fields = contract.get("source_custom_fields", {})
	if source_fields:
		oa = before.get("oa")
		assert oa and oa["schema"], "Existing native OA table required; do not install an OA DocType"
		assert not frappe.db.sql("select name from `tabDocField` where parent=%s and fieldname in (" + ",".join(["%s"] * len(source_fields)) + ")", (OA_DOCTYPE, *source_fields)), "Source fields conflict with standard OA DocFields"
		for key, field in source_fields.items():
			present = OA_DOCTYPE + "-" + key not in new
			assert (key in oa["schema"]["columns"]) == present, "Orphan/missing OA source column: " + key
			if present:
				assert oa["schema"]["columns"][key] == _source_column(field, len(oa["schema"]["columns"]), position=oa["schema"]["columns"][key]["position"]), "Conflicting OA source column: " + key
			assert (key in oa["schema"]["indexes"]) == bool(present and field.get("unique")), "Orphan/missing OA source index: " + key
		for name, rows in oa["schema"]["indexes"].items():
			if any(row["column"] in source_fields for row in rows):
				assert name == "custom_purchase_source_id" and rows == _source_index(), "Unapproved OA source index"
		meta = copy.deepcopy(frappe.get_meta(OA_DOCTYPE, cached=False))
		_assert_frozen_fields(meta, contract, [key for key in source_fields if key in oa["schema"]["columns"]], OA_DOCTYPE)
		for key, field in source_fields.items():
			if key not in oa["schema"]["columns"]: meta.fields.append(frappe._dict(field))
		for query in _native_schema_sql(OA_DOCTYPE, meta):
			_validate_oa_ddl(query, {key for key in source_fields if key not in oa["schema"]["columns"]}, source_fields)
	return {"scope": expected, "new_definitions": new, "page_title_updates": page_title_updates}


def verify_current_joint_contract():
	"""Verify the live target without replaying an earlier business snapshot.

	An already-current release needs no DDL or quiescent cutover, but its native
	definitions, SQL schemas, security flags and navigation must be complete.
	The caller verifies the frozen source manifest before loading this contract.
	"""
	with _read_only_native_planning():
		contract = load_joint_contract(require_quiescent=False)
		current = _capture_joint_state()
		plan = _joint_plan(current, contract, when="current-read-only", seed="current", require_quiescent=False)
	assert not plan["new_definitions"], "Current release has missing native definitions"
	assert not plan["page_title_updates"], "Current release still needs its approved title update"
	assert plan["scope"] == current["metadata"]["scope"], "Current release navigation/metadata needs repair"
	return {"current_contract_verified": True, "source_sync_enabled": bool(current["audit"].get("purchase_source_sync_enabled")),
		"release_sources_all": current["audit"]["release_sources_all"]}


def _je_column(count, *, position=None):
	return {"position": position or count + 1, "type": "varchar(140)", "nullable": "YES", "default_value": "NULL", "charset": "utf8mb4", "collation": "utf8mb4_unicode_ci", "extra": "", "expression": None}


def _source_column(field, count, *, position=None):
	kind = field["fieldtype"]
	column = dict(_je_column(count, position=position), type={"Data": "varchar(140)", "Link": "varchar(140)", "Long Text": "longtext", "Check": "tinyint(4)", "Datetime": "datetime(6)"}[kind])
	if kind in {"Check", "Datetime"}:
		column.update(charset=None, collation=None)
	if kind == "Check":
		assert field["fieldname"] == "custom_purchase_company_confirmed" and not field.get("default"), "Only the approved zero-default Check is allowed"
		column.update(nullable="NO", default_value="0")
	return column


def _oa_nondefault_condition(fieldname):
	quoted = _quote(fieldname)
	return quoted + " is null or " + quoted + " <> 0" if fieldname == "custom_purchase_company_confirmed" else quoted + " is not null"


def _source_index():
	return [{"sequence": 1, "column": "custom_purchase_source_id", "unique": 1, "prefix": None, "collation": "A", "type": "BTREE", "nullable": "YES"}]


def _source_schema_additions(before, fields):
	missing = [key for key in SOURCE_FIELD_ORDER if key in fields and key not in before["schema"]["columns"]]
	return {"columns": {key: _source_column(fields[key], len(before["schema"]["columns"]) + i) for i, key in enumerate(missing)},
		"indexes": {"custom_purchase_source_id": _source_index()} if "custom_purchase_source_id" in missing else {}}


def _capture_joint_state(before=None):
	from audit_unified_purchase import capture_joint_state
	return capture_joint_state(original_columns=before["je"]["original_columns"] if before else None,
		original_oa_columns=before["oa"]["original_columns"] if before and before.get("oa") else None)


def _verify_operating_audit(before, after, contract, *, recorded_schemas=None):
	"""Normalize only exact-contract creation of empty absent-before schemas."""
	if "operating_models" not in before and "operating_models" not in after:
		return  # Older receipt/test format; raw state invariants still apply.
	assert set(before["operating_models"]) == set(after["operating_models"]) == set(JOINT_MODELS)
	for name, old in before["operating_models"].items():
		new = after["operating_models"][name]
		assert old["rows"] == new["rows"], "Fresh operating business audit drift: " + name
		if old["schema"] is None:
			allowed = (recorded_schemas[name],) if recorded_schemas is not None else (None, contract["model_schemas"][name])
			assert old["rows"] == digest([]) and new["schema"] in allowed, "Unexpected operating model schema creation"
		else:
			assert old["schema"] == new["schema"], "Preexisting operating model schema changed"
		new["schema"] = copy.deepcopy(old["schema"])


def _verify_operating_snapshot(audit, native):
	if "operating_models" not in audit:
		return  # Legacy receipt format; raw model equality remains mandatory.
	assert set(audit["operating_models"]) == set(native["models"]) == set(JOINT_MODELS)
	for name, model in native["models"].items():
		assert audit["operating_models"][name] == {"schema": model["schema"], "rows": digest(model["rows"])}, "Fresh operating audit differs from receipt: " + name


def _verify_new_oa_columns(before, after, original, fields):
	if "oa_new_columns" not in before and "oa_new_columns" not in after:
		return  # Legacy audit format; native boundary non-NULL checks still apply.
	assert before["oa_new_columns"] == {}, "Baseline OA projection is incomplete"
	new = set(after["schemas"][OA_DOCTYPE]["columns"]) - set(original["schema"]["columns"]) if original else set()
	assert new <= set(fields) and after["oa_new_columns"] == {key: 0 for key in new}, "Fresh new OA columns contain non-NULL data/nondefault values or escaped the receipt"
	after["oa_new_columns"] = {}


def _validate_je_ddl(query, new_columns):
	assert query.startswith("ALTER TABLE `tabJournal Entry` "), "Native plan escaped Journal Entry"
	clauses = query.split("`tabJournal Entry` ", 1)[1].split(", ")
	for clause in clauses:
		column = re.fullmatch(r"ADD COLUMN `([\w]+)` varchar\(140\)(?: UNIQUE)?", clause)
		index = re.fullmatch(r"ADD UNIQUE INDEX IF NOT EXISTS custom_operating_event_key \(`custom_operating_event_key`\)", clause)
		assert (column and column[1] in new_columns) or (index and "custom_operating_event_key" in new_columns), "Unexpected native Journal Entry schema change: " + clause


def _validate_oa_ddl(query, new_columns, fields):
	assert query.startswith("ALTER TABLE `tabOA Purchase Request` "), "Native plan escaped OA Purchase Request"
	for clause in query.split("`tabOA Purchase Request` ", 1)[1].split(", "):
		column = re.fullmatch(r"ADD COLUMN `([\w]+)` (varchar\(140\)|longtext|datetime\(6\)|tinyint\(4\) NOT NULL DEFAULT 0)( UNIQUE)?", clause)
		index = re.fullmatch(r"ADD UNIQUE INDEX IF NOT EXISTS custom_purchase_source_id \(`custom_purchase_source_id`\)", clause)
		if column:
			assert column[1] in new_columns and column[1] in fields
			assert column[2] == {"Data": "varchar(140)", "Link": "varchar(140)", "Long Text": "longtext", "Check": "tinyint(4) NOT NULL DEFAULT 0", "Datetime": "datetime(6)"}[fields[column[1]]["fieldtype"]], "Wrong native OA source column type/default"
			assert not column[3] or (column[1] == "custom_purchase_source_id" and fields[column[1]].get("unique")), "Unexpected inline OA unique constraint"
		else:
			assert index and "custom_purchase_source_id" in new_columns, "Unexpected native OA schema change: " + clause


def _write_scope(before, after):
	import frappe
	for dt in sorted(after):
		old = {row["name"]: row for row in before[dt]}
		wanted = {row["name"]: row for row in after[dt]}
		for name in sorted(set(old) - set(wanted)):
			frappe.db.sql("delete from " + _quote("tab" + dt) + " where name=%s", (name,))
		for name, row in wanted.items():
			if name in old:
				changed = [key for key in row if row[key] != old[name].get(key)]
				if changed:
					frappe.db.sql("update " + _quote("tab" + dt) + " set " + ",".join(_quote(key) + "=%s" for key in changed) + " where name=%s", tuple(row[key] for key in changed) + (name,))
			else:
				keys = sorted(row)
				frappe.db.sql("insert into " + _quote("tab" + dt) + " (" + ",".join(map(_quote, keys)) + ") values (" + ",".join(["%s"] * len(keys)) + ")", tuple(row[key] for key in keys))


def _assert_joint_invariants(receipt, current, *, scope=None, source_phase="after"):
	from joint_release_guards import assert_schema_delta, validate_event_index
	before, contract = receipt.state["before"], receipt.state["contract"]
	if "installer_files" in contract:
		assert _installer_source_files() == contract["installer_files"], "Frozen installer source drift; retain maintenance"
	assert current["metadata"]["outside"] == before["metadata"]["outside"], "Outside metadata drift; retain maintenance"
	assert current["metadata"]["outside_rows"] == before["metadata"]["outside_rows"], "Outside raw metadata drift"
	if scope is not None:
		assert current["metadata"]["scope"] == scope, "Scope differs from exact recorded rows"
	assert current["je"]["rows"] == before["je"]["rows"], "Original Journal Entry bytes changed"
	_assert_release_sync_state(before["audit"], current["audit"])
	assert current["operating_singles"] == before["operating_singles"], "Operating Expense Single bytes changed; rollback refused"
	assert set(current["models"]) == set(before["models"])
	assert all(model["rows"] == before["models"][name]["rows"] for name, model in current["models"].items()), "Operating model bytes changed; rollback refused"
	additions = {"columns": {}, "indexes": {}}
	new_column_names = [key for key in CUSTOM_FIELD_ORDER if key not in before["je"]["schema"]["columns"]]
	for key in CUSTOM_FIELD_ORDER:
		if key not in before["je"]["schema"]["columns"]:
			additions["columns"][key] = _je_column(len(before["je"]["schema"]["columns"]) + new_column_names.index(key))
	if "custom_operating_event_key" not in before["je"]["schema"]["indexes"]:
		additions["indexes"]["custom_operating_event_key"] = [{"sequence": 1, "column": "custom_operating_event_key", "unique": 1, "prefix": None, "collation": "A", "type": "BTREE", "nullable": "YES"}]
	assert_schema_delta(before["je"]["schema"], current["je"]["schema"], additions)
	import frappe
	for key in set(additions["columns"]) & set(current["je"]["schema"]["columns"]):
		assert frappe.db.sql("select count(*) from `tabJournal Entry` where " + _quote(key) + " is not null")[0][0] == 0, "New Journal Entry column contains non-NULL data: " + key
	if before.get("oa"):
		assert current.get("oa") and current["oa"]["rows"] == before["oa"]["rows"], "Original OA bytes changed"
		oa_additions = _source_schema_additions(before["oa"], contract.get("source_custom_fields", {}))
		assert_schema_delta(before["oa"]["schema"], current["oa"]["schema"], oa_additions)
		for key in set(oa_additions["columns"]) & set(current["oa"]["schema"]["columns"]):
			assert frappe.db.sql("select count(*) from `tabOA Purchase Request` where " + _oa_nondefault_condition(key))[0][0] == 0, "New OA column contains non-NULL data/nondefault values: " + key
	else:
		assert current.get("oa") is None, "OA installation escaped release scope"
	_assert_recorded_schemas(receipt, current)
	old_audit, audit = copy.deepcopy(before["audit"]), copy.deepcopy(current["audit"])
	for item, native in ((old_audit, before), (audit, current)):
		_verify_operating_snapshot(item, native)
	assert audit.pop("release_sources_all") == contract["sources_" + source_phase], "Pinned app source drift"
	old_audit.pop("release_sources_all")
	_verify_operating_audit(old_audit, audit, contract, recorded_schemas={name: model["schema"] for name, model in current["models"].items()})
	_verify_new_oa_columns(old_audit, audit, before.get("oa"), contract.get("source_custom_fields", {}))
	# Has Role is fully protected by the raw scope and outside permission audit above.
	for item in (old_audit, audit):
		item["tables"].pop("Has Role", None)
		item["schemas"].pop("Journal Entry")
		if before.get("oa"): item["schemas"].pop(OA_DOCTYPE)
	# CRM/Finance sources also have independent complete preserved-app digests.
	if source_phase == "before":
		for app in ("china_finance", "crm_integration"):
			assert audit["preserved_apps"][app] == contract["preserved_before"][app]
			old_audit["preserved_apps"][app] = audit["preserved_apps"][app]
	assert audit == old_audit, "Protected business/original schema/Single/configuration drift; retain maintenance"


def apply_joint_metadata(candidate_sha, receipt_path, *, before_audit=None):
	"""Only this joint path adds native operating DDL; no migrate or business hooks."""
	import frappe
	from frappe.model.meta import Meta
	from frappe.utils import now_datetime
	from unittest.mock import patch
	from audit_unified_purchase import table_schema
	from joint_release_guards import DDLReceipt, serialized

	assert frappe.conf.maintenance_mode == 1, "Verified maintenance required"
	contract = load_joint_contract()
	if before_audit:
		assert contract["sources_after"] == before_audit["approved_sources_after"], "Candidate source differs from frozen archive/base contract before mutation"
	identity = {"candidate_sha": candidate_sha, "contract_sha256": hashlib.sha256(serialized(contract)).hexdigest()}
	path = Path(receipt_path)
	if path.exists():
		receipt = DDLReceipt.load(path, identity)
		assert receipt.state["status"] == "applied", "Partial release requires inspected rollback; do not infer pending absence"
		current = _capture_joint_state(receipt.state["before"])
		_assert_joint_invariants(receipt, current, scope=receipt.state["after"]["metadata"]["scope"])
		assert current == receipt.state["after"], "Second apply drift"
		return {"applied": True, "unchanged": True, "first_receipt_preserved": True, "identity": identity}
	before = _capture_joint_state()
	if before_audit:
		for key in ("tables", "schemas", "singles", "configuration_sha256", "maintenance_mode", "assets_manifest_sha256", "operating_models", "purchase_source_sync_enabled"):
			assert before["audit"][key] == before_audit[key], "Pre-cutover baseline drift: " + key
		assert before["metadata"] == before_audit["joint_metadata"], "Pre-cutover raw metadata drift"
	plan = _joint_plan(before, contract, when=str(now_datetime()), seed=identity["contract_sha256"])
	contract["sources_before"] = (before_audit or before["audit"])["release_sources_all"]
	contract["preserved_before"] = (before_audit or before["audit"])["preserved_apps"]
	contract["metadata_plan"] = plan
	# Identity freezes the native contract; the complete stored receipt also hashes its plan.
	receipt = DDLReceipt.create(path, identity, before, contract)
	if before["metadata"]["scope"] != plan["scope"]:
		receipt.plan("metadata", before["metadata"]["scope"], plan["scope"], kind="metadata")
		_write_scope(before["metadata"]["scope"], plan["scope"])
		_assert_joint_invariants(receipt, _capture_joint_state(before), scope=plan["scope"])
		frappe.db.commit()
		receipt.complete("metadata", capture_joint_metadata()["scope"])
	for name in (*JOINT_MODELS, "Journal Entry", *((OA_DOCTYPE,) if before.get("oa") else ())):
		frappe.clear_cache(doctype=name)
	metas = []
	# One inspected native autocommit per nullable column, then the unique index.
	desired_meta = copy.deepcopy(frappe.get_meta("Journal Entry", cached=False))
	new_columns = [key for key in CUSTOM_FIELD_ORDER if key not in before["je"]["schema"]["columns"]]
	new_fields = {field.fieldname: field for field in desired_meta.fields if field.fieldname in new_columns}
	for count, key in enumerate(new_columns, 1):
		meta = copy.deepcopy(desired_meta)
		meta.fields = [field for field in meta.fields if field.fieldname not in new_columns] + [copy.deepcopy(new_fields[field]) for field in new_columns[:count]]
		for field in meta.fields:
			if field.fieldname == "custom_operating_event_key" and field.fieldname in new_columns:
				field.unique = 0
		metas.append(("journal-column-" + key, "Journal Entry", meta))
	for name in JOINT_MODELS:
		if name in plan["new_definitions"] and contract["model_schemas"][name]:
			metas.append(("model-" + frappe.scrub(name), name, frappe.get_meta(name, cached=False)))
	metas.append(("journal-index", "Journal Entry", frappe.get_meta("Journal Entry", cached=False)))
	if contract.get("source_custom_fields"):
		desired_meta = copy.deepcopy(frappe.get_meta(OA_DOCTYPE, cached=False))
		new_oa_columns = [key for key in SOURCE_FIELD_ORDER if key not in before["oa"]["schema"]["columns"]]
		new_fields = {field.fieldname: field for field in desired_meta.fields if field.fieldname in new_oa_columns}
		for count, key in enumerate(new_oa_columns, 1):
			meta = copy.deepcopy(desired_meta)
			meta.fields = [field for field in meta.fields if field.fieldname not in new_oa_columns] + [copy.deepcopy(new_fields[field]) for field in new_oa_columns[:count]]
			for field in meta.fields:
				if field.fieldname == "custom_purchase_source_id" and field.fieldname in new_oa_columns: field.unique = 0
			metas.append(("oa-column-" + key, OA_DOCTYPE, meta))
		metas.append(("oa-index", OA_DOCTYPE, frappe.get_meta(OA_DOCTYPE, cached=False)))
	for phase, name, meta in metas:
		queries = _native_schema_sql(name, meta)
		for query in queries:
			if name == "Journal Entry":
				_validate_je_ddl(query, {key for key in contract["custom_fields"] if key not in before["je"]["schema"]["columns"]})
			elif name == OA_DOCTYPE:
				_validate_oa_ddl(query, set(new_oa_columns), contract["source_custom_fields"])
			else:
				assert queries == [contract["model_ddl"][name]], "Native model CREATE drift"
		if not queries:
			continue
		original_ddl = frappe.db.sql_ddl
		remaining = list(queries)
		def bounded_ddl(query, **kwargs):
			assert remaining and str(query) == remaining.pop(0), "Native DDL changed after inspection"
			step_id = phase + ":" + hashlib.sha256(str(query).encode()).hexdigest()[:12]
			observed = table_schema(name)
			_assert_schema_intent(name, observed, *_recorded_schema_intents(receipt))
			expected = copy.deepcopy(observed)
			if name in JOINT_MODELS:
				expected = contract.get("model_base_schemas", contract["model_schemas"])[name]
			elif phase.startswith("journal-column-"):
				key = phase.removeprefix("journal-column-")
				assert key not in expected["columns"]
				expected["columns"][key] = _je_column(len(expected["columns"]))
			elif name == OA_DOCTYPE:
				if phase.startswith("oa-column-"):
					key = phase.removeprefix("oa-column-")
					assert key not in expected["columns"]
					expected["columns"][key] = _source_column(contract["source_custom_fields"][key], len(expected["columns"]))
				else:
					expected["indexes"]["custom_purchase_source_id"] = _source_index()
			else:
				expected["indexes"]["custom_operating_event_key"] = [{"sequence": 1, "column": "custom_operating_event_key", "unique": 1, "prefix": None, "collation": "A", "type": "BTREE", "nullable": "YES"}]
			receipt.plan(step_id, observed, expected, kind="ddl", doctype=name, sql=str(query))
			original_ddl(query, **kwargs)
			actual = table_schema(name)
			assert actual == expected, "Native DDL produced unexpected schema"
			_assert_joint_invariants(receipt, _capture_joint_state(before), scope=plan["scope"])
			receipt.complete(step_id, actual)
		with patch.object(frappe.db, "sql_ddl", bounded_ddl):
			frappe.db.updatedb(name, meta)
		assert not remaining, "Native updatedb omitted inspected DDL"
	for name, indexes in contract.get("model_index_ddl", {}).items():
		for index, query in indexes.items():
			observed = table_schema(name)
			_assert_schema_intent(name, observed, *_recorded_schema_intents(receipt))
			wanted = contract["model_schemas"][name]["indexes"][index]
			if index in observed["indexes"]:
				assert observed["indexes"][index] == wanted, "Existing fulfilment index drift"
				continue
			expected = copy.deepcopy(observed)
			expected["indexes"][index] = wanted
			step_id = "model-index-" + index
			receipt.plan(step_id, observed, expected, kind="ddl", doctype=name, sql=query)
			frappe.db.sql_ddl(query)
			actual = table_schema(name)
			assert actual == expected, "Fulfilment index DDL produced unexpected schema"
			_assert_joint_invariants(receipt, _capture_joint_state(before), scope=plan["scope"])
			receipt.complete(step_id, actual)
	after = _capture_joint_state(before)
	_assert_joint_invariants(receipt, after, scope=plan["scope"])
	for key in contract["custom_fields"]:
		assert key in after["je"]["schema"]["columns"]
	assert after["je"]["schema"]["indexes"].get("custom_operating_event_key")
	if contract.get("source_custom_fields"):
		assert set(contract["source_custom_fields"]) <= set(after["oa"]["schema"]["columns"])
		assert after["oa"]["schema"]["indexes"].get("custom_purchase_source_id") == _source_index()
	assert all(model["schema"] == contract["model_schemas"][name] for name, model in after["models"].items())
	assert _desired_navigation(plan["scope"], when=str(now_datetime()), seed="second-run") == plan["scope"], "Second navigation reconciliation is not idle"
	receipt.finish(after)
	return {"applied": True, "unchanged": not receipt.state["steps"], "identity": identity, "ddl_boundaries": len([step for step in receipt.state["steps"] if step["kind"] == "ddl"]), "protected_tables": len(after["audit"]["tables"]), "original_je_projection": digest(before["je"]["rows"]), "new_fields_at_native_defaults": True, "source_sync_enabled": bool(after["audit"].get("purchase_source_sync_enabled"))}


def _recorded_schema_intents(receipt):
	state = receipt.state
	status = state.get("status", "applying")
	assert status in {"applying", "applied", "restored"}
	basis = state["after"] if status == "applied" else state["before"]
	latest = {}
	if status != "restored":
		for step in state.get("steps", []):
			if status == "applied" and not step["kind"].startswith("rollback-"): continue
			if step["kind"] in {"ddl", "rollback-ddl"}: latest[step["doctype"]] = step
			elif step["kind"] in {"metadata", "rollback-metadata"}: latest["metadata"] = step
	return basis, latest


def _assert_schema_intent(name, actual, basis, latest):
	original = basis["je"]["schema"] if name == "Journal Entry" else basis["oa"]["schema"] if name == OA_DOCTYPE else basis["models"][name]["schema"]
	step = latest.get(name)
	allowed = [original] if step is None else [step["expected_after"]]
	if step is not None and step["status"] == "pending":
		allowed.append(step["before"])
	assert actual in allowed, "Native SQL schema differs from exact recorded intent: " + name


def _assert_recorded_schemas(receipt, current):
	"""One durable-intent index for both forward and recovery checks."""
	basis, latest = _recorded_schema_intents(receipt)
	_assert_schema_intent("Journal Entry", current["je"]["schema"], basis, latest)
	for name, model in current["models"].items():
		_assert_schema_intent(name, model["schema"], basis, latest)
	if basis.get("oa") is not None:
		_assert_schema_intent(OA_DOCTYPE, current["oa"]["schema"], basis, latest)
	return basis, latest


def _assert_recorded_rollback_state(receipt, current):
	"""Accept only states explained by the durable latest intent per component.

	The common business/source invariants run separately, including old-image
	source normalization. Here every scope row and native schema is exact; only
	a pending single DDL or per-row metadata autocommit may be on either side.
	"""
	basis, latest = _assert_recorded_schemas(receipt, current)
	step = latest.get("metadata")
	actual_scope = current["metadata"]["scope"]
	if step is None or step["status"] == "complete":
		expected = basis["metadata"]["scope"] if step is None else step["expected_after"]
		assert actual_scope == expected, "Metadata drift from exact recorded release/baseline"
	else:
		# _write_scope mutates one whole row per SQL statement. A pending
		# autocommit can contain only exact before/after rows, with shared rows
		# mandatory and newly inserted/deleted rows optional until completion.
		assert set(actual_scope) == set(step["before"]) == set(step["expected_after"])
		for doctype, rows in actual_scope.items():
			old = {row["name"]: row for row in step["before"][doctype]}
			wanted = {row["name"]: row for row in step["expected_after"][doctype]}
			assert set(old) & set(wanted) <= {row["name"] for row in rows}, "Preexisting recorded metadata disappeared"
			for row in rows:
				assert row == old.get(row["name"]) or row == wanted.get(row["name"]), "Unrecorded partial metadata drift"


def restore_joint_metadata(receipt_path, *, candidate_sha=None, source_phase="after"):
	"""Inspect actual pending state; remove only exact newly absent-before empties."""
	import frappe
	from audit_unified_purchase import table_schema
	from joint_release_guards import DDLReceipt

	assert frappe.conf.maintenance_mode == 1, "Rollback requires maintenance plus shell-held lock/quiescence"
	receipt = DDLReceipt.load(receipt_path)
	if candidate_sha:
		assert receipt.state["identity"]["candidate_sha"] == candidate_sha
	before, contract = receipt.state["before"], receipt.state["contract"]
	frappe.db.rollback()
	current = _capture_joint_state(before)
	_assert_joint_invariants(receipt, current, source_phase=source_phase)
	_assert_recorded_rollback_state(receipt, current)
	# A crash may follow the native autocommit but precede complete(). Persist
	# only the latest pending rollback intent actually observed at its result.
	latest = {}
	for step in receipt.state["steps"]:
		if step["kind"] in {"rollback-ddl", "rollback-metadata"}:
			latest[step.get("doctype", "metadata")] = step
	for name, step in latest.items():
		actual = current["metadata"]["scope"] if name == "metadata" else (current["je"]["schema"] if name == "Journal Entry" else current["oa"]["schema"] if name == OA_DOCTYPE else current["models"][name]["schema"])
		if step["status"] == "pending" and actual == step["expected_after"]:
			receipt.complete(step["id"], actual)
	for dt, rows in current["metadata"]["scope"].items():
		original = {row["name"]: row for row in before["metadata"]["scope"][dt]}
		planned = {row["name"]: row for row in contract["metadata_plan"]["scope"][dt]}
		for row in rows:
			assert row == original.get(row["name"]) or row == planned.get(row["name"]), "Unrecorded scoped metadata drift; rollback refused"
		assert set(original) <= {row["name"] for row in rows} | (set(original) - set(planned)), "Preexisting metadata disappeared"
	for name, model in current["models"].items():
		if before["models"][name]["schema"] is None and model["schema"] is not None:
			assert name in contract["metadata_plan"]["new_definitions"]
			query = "DROP TABLE " + _quote("tab" + name)
			step_id = "rollback-table-" + frappe.scrub(name)
			receipt.plan(step_id, model["schema"], None, kind="rollback-ddl", doctype=name, sql=query)
			frappe.db.sql_ddl(query)
			after = _capture_joint_state(before)
			_assert_joint_invariants(receipt, after, source_phase=source_phase)
			_assert_recorded_rollback_state(receipt, after)
			receipt.complete(step_id, table_schema(name))
	# One newly NULL column per native autocommit; dropping its new index is bounded too.
	columns = [("Journal Entry", key, "custom_operating_event_key") for key in reversed(CUSTOM_FIELD_ORDER)]
	if before.get("oa"):
		columns = [(OA_DOCTYPE, key, "custom_purchase_source_id") for key in reversed(SOURCE_FIELD_ORDER)] + columns
	for doctype, key, unique_key in columns:
		original = before["je"] if doctype == "Journal Entry" else before["oa"]
		actual = table_schema(doctype)
		if key not in original["schema"]["columns"] and key in actual["columns"]:
			expected = copy.deepcopy(actual)
			expected["columns"].pop(key)
			if key == unique_key:
				expected["indexes"].pop(key, None)
			query = "ALTER TABLE " + _quote("tab" + doctype) + " DROP COLUMN " + _quote(key)
			step_id = "rollback-column-" + key
			receipt.plan(step_id, actual, expected, kind="rollback-ddl", doctype=doctype, sql=query)
			frappe.db.sql_ddl(query)
			after = _capture_joint_state(before)
			_assert_joint_invariants(receipt, after, source_phase=source_phase)
			_assert_recorded_rollback_state(receipt, after)
			receipt.complete(step_id, table_schema(doctype))
	actual_scope = capture_joint_metadata()["scope"]
	if actual_scope != before["metadata"]["scope"]:
		pending = next((step for step in receipt.state["steps"] if step["id"] == "rollback-metadata"), None)
		# Do not replace the original durable intent with a partially recovered
		# snapshot. Its exact per-row partial state was validated on entry.
		receipt.plan("rollback-metadata", pending["before"] if pending else actual_scope, before["metadata"]["scope"], kind="rollback-metadata")
		_write_scope(actual_scope, before["metadata"]["scope"])
		_assert_joint_invariants(receipt, _capture_joint_state(before), scope=before["metadata"]["scope"], source_phase=source_phase)
		frappe.db.commit()
		receipt.complete("rollback-metadata", capture_joint_metadata()["scope"])
	for name in (*JOINT_MODELS, "Journal Entry", *((OA_DOCTYPE,) if before.get("oa") else ())):
		frappe.clear_cache(doctype=name)
	final = _capture_joint_state(before)
	_assert_joint_invariants(receipt, final, scope=before["metadata"]["scope"], source_phase=source_phase)
	_assert_recorded_rollback_state(receipt, final)
	assert final["je"] == before["je"] and final["models"] == before["models"] and final["metadata"] == before["metadata"], "Rollback did not restore exact native original state"
	assert final.get("oa") == before.get("oa") and final.get("operating_singles") == before.get("operating_singles"), "Rollback did not restore exact OA/operating original bytes"
	receipt.restored()
	return {"restored": True, "original_bytes_and_child_ids": True, "pending_inspected_from_database": True, "maintenance_retained": True}


def verify_joint_audit_delta(before, after, receipt):
	"""Host-side gate: only receipted schema additions; all original bytes stay exact."""
	from joint_release_guards import assert_schema_delta, validate_event_index
	assert receipt["status"] == "applied" and all(step["status"] == "complete" for step in receipt["steps"])
	before, after = copy.deepcopy(before), copy.deepcopy(after)
	original, current, contract = receipt["before"], receipt["after"], receipt["contract"]
	assert before.pop("joint_metadata") == receipt["before"]["metadata"]
	assert after.pop("joint_metadata") == receipt["after"]["metadata"]
	assert receipt["before"]["metadata"]["outside"] == receipt["after"]["metadata"]["outside"]
	assert original["metadata"]["outside_rows"] == current["metadata"]["outside_rows"], "Outside raw metadata changed"
	assert original["operating_singles"] == current["operating_singles"], "Operating Single bytes changed"
	assert set(original["models"]) == set(current["models"])
	assert all(model["rows"] == original["models"][name]["rows"] for name, model in current["models"].items()), "Operating model bytes changed"
	_assert_release_sync_state(before, after)
	for item, native in ((before, original), (after, current)):
		_verify_operating_snapshot(item, native)
	_verify_operating_audit(before, after, contract)
	assert before["release_sources_all"] == receipt["contract"]["sources_before"]
	assert after["release_sources_all"] == receipt["contract"]["sources_after"] == before.pop("approved_sources_after")
	if "release_sources" in before or "release_sources" in after:
		old, new = before.pop("release_sources"), after.pop("release_sources")
		assert set(old) == set(new)
		for app in old:
			assert old[app] == before["release_sources_all"][app] and new[app] == after["release_sources_all"][app]
	before.pop("release_sources_all")
	after.pop("release_sources_all")
	before_schema, after_schema = before["schemas"]["Journal Entry"], after["schemas"]["Journal Entry"]
	assert before_schema == receipt["before"]["je"]["schema"] and after_schema == receipt["after"]["je"]["schema"]
	additions = {kind: {key: value for key, value in after_schema[kind].items() if key not in before_schema[kind]} for kind in ("columns", "indexes")}
	assert set(additions["columns"]) <= set(CUSTOM_FIELD_ORDER) and set(additions["indexes"]) <= {"custom_operating_event_key"}
	assert_schema_delta(before_schema, after_schema, additions)
	validate_event_index(after_schema["indexes"]["custom_operating_event_key"])
	assert original["je"]["rows"] == current["je"]["rows"] and original["je"]["original_columns"] == current["je"]["original_columns"], "Original JE projection changed"
	for item, native in ((before, original), (after, current)):
		assert item["tables"]["Journal Entry"] == digest(native["je"]["rows"]), "Fresh original JE rows differ from receipt"
	if original.get("oa"):
		assert current.get("oa") and original["oa"]["rows"] == current["oa"]["rows"] and original["oa"]["original_columns"] == current["oa"]["original_columns"], "Original OA projection changed"
		for item, native in ((before, original), (after, current)):
			assert item["schemas"][OA_DOCTYPE] == native["oa"]["schema"] and item["tables"][OA_DOCTYPE] == digest(native["oa"]["rows"]), "Fresh original OA/schema differs from receipt"
		fields = contract.get("source_custom_fields", {})
		assert_schema_delta(original["oa"]["schema"], current["oa"]["schema"], _source_schema_additions(original["oa"], fields))
		if fields:
			assert set(fields) <= set(current["oa"]["schema"]["columns"]) and current["oa"]["schema"]["indexes"].get("custom_purchase_source_id") == _source_index()
	else:
		assert current.get("oa") is None, "OA installation escaped release scope"
	_verify_new_oa_columns(before, after, original.get("oa"), contract.get("source_custom_fields", {}))
	for item, native in ((before, receipt["before"]), (after, receipt["after"])):
		# Raw all Has Role rows are fully covered by exact scope + exact outside rows.
		roles = sorted(native["metadata"]["scope"]["Has Role"] + native["metadata"]["outside_rows"]["Has Role"], key=lambda row: row["name"])
		assert item["tables"]["Has Role"] == digest(roles)
		item["tables"].pop("Has Role")
		item["schemas"].pop("Journal Entry")
		if original.get("oa"): item["schemas"].pop(OA_DOCTYPE)
	assert before == after, "Final business, original child/schema, Singles, configuration or preserved-source drift"


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
	action = parser.add_mutually_exclusive_group(required=True)
	action.add_argument("--apply", metavar="PAGE_SOURCE")
	parser.add_argument("--before-audit")
	action.add_argument("--rollback", metavar="RECEIPT")
	action.add_argument("--joint-apply", action="store_true")
	action.add_argument("--joint-rollback", action="store_true")
	parser.add_argument("--receipt")
	parser.add_argument("--candidate-sha")
	parser.add_argument("--source-phase", choices=("before", "after"), default="after")
	args = parser.parse_args()
	bench = Path("/home/frappe/frappe-bench")
	if args.joint_apply or args.joint_rollback:
		if not args.candidate_sha or not re.fullmatch(r"[0-9a-f]{40}", args.candidate_sha) or not args.receipt:
			parser.error("Frozen candidate SHA and durable site receipt required")
		path = Path(args.receipt)
		expected = bench / "sites/deeplinkerp.com/private/release-evidence" / ("joint-" + args.candidate_sha[:12] + ".json")
		if not path.is_absolute() or path.resolve() != expected.resolve():
			parser.error("Receipt must be the exact durable private site release path")
		if args.joint_apply and not args.before_audit:
			parser.error("Joint apply requires the private pre-cutover audit")
	if args.apply and not args.before_audit:
		parser.error("Procurement apply requires the private pre-cutover audit")
	frappe.init(site="deeplinkerp.com", sites_path=str(bench / "sites"))
	frappe.connect()
	try:
		assert frappe.conf.maintenance_mode == 1, "Metadata changes require verified maintenance"
		frappe.set_user("Administrator")
		if args.joint_apply or args.joint_rollback:
			assert os.environ.get("DEEPLINKERP_RELEASE_QUIESCENT") == "1", "Shell-held release lock and verified queue/scheduler quiescence required"
			assert args.receipt and args.candidate_sha
			if args.joint_apply:
				assert args.before_audit
				result = apply_joint_metadata(args.candidate_sha, args.receipt, before_audit=json.loads(Path(args.before_audit).read_text()))
			else:
				result = restore_joint_metadata(args.receipt, candidate_sha=args.candidate_sha, source_phase=args.source_phase)
			print(json.dumps(result, ensure_ascii=False))
		elif args.apply:
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
