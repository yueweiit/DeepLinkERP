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
JOINT_MODELS = ("Operating Expense Company Map", "Operating Expense Source", "Operating Expense Mapping", "Operating Expense Event", "Operating Expense Sync Settings")
JOINT_PAGES = (PAGE, "operating-expenses")
JOINT_NAVIGATION = tuple((dt, name) for name in ("Buying", "Accounting", "China Finance") for dt in ("Workspace", "Workspace Sidebar"))
OPERATING_METHOD = "deeplinkerp_branding.services.operating_expenses.scheduled_sync"
CUSTOM_FIELD_ORDER = ("custom_operating_event_key", "custom_operating_source", "custom_operating_recognition", "custom_operating_fingerprint")


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
		"Custom Field": [("name", tuple("Journal Entry-" + field for field in CUSTOM_FIELD_ORDER))],
		"Page": [("name", JOINT_PAGES)],
		"Workspace": [("name", ("Buying", "Accounting", "China Finance"))],
		"Workspace Sidebar": [("name", ("Buying", "Accounting", "China Finance"))],
		"Scheduled Job Type": [("method", (OPERATING_METHOD,))],
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
		return row["name"] in {"Journal Entry-" + key for key in CUSTOM_FIELD_ORDER} or (row.get("dt") == "Journal Entry" and row.get("fieldname") in CUSTOM_FIELD_ORDER)
	if doctype == "Page":
		return row["name"] in JOINT_PAGES
	if doctype in {"Workspace", "Workspace Sidebar"}:
		return row["name"] in {"Buying", "Accounting", "China Finance"}
	if doctype == "Scheduled Job Type":
		return row.get("method") == OPERATING_METHOD or row.get("name") == OPERATING_METHOD
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
	assert query.lstrip().lower().startswith("create table `tabOperating Expense ".lower())
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
		("Property Setter", "select name from `tabProperty Setter` where doc_type in (" + placeholders + ") or (doc_type=%s and field_name in (" + ",".join(["%s"] * len(CUSTOM_FIELD_ORDER)) + "))", (*models, "Journal Entry", *CUSTOM_FIELD_ORDER)),
		("Custom DocPerm", "select name from `tabCustom DocPerm` where parent in (" + placeholders + ")", models),
	)
	for doctype, query, values in queries:
		assert not frappe.db.sql(query, values), "Unapproved effective customization targets frozen operating metadata: " + doctype


def load_joint_contract():
	import frappe
	from frappe.model.meta import Meta
	from audit_unified_purchase import table_schema, source_files
	from joint_release_guards import serialized

	assert frappe.__version__ == "16.23.0" and frappe.db.db_type == "mariadb", "Frozen native Frappe 16.23/MariaDB contract required"
	_assert_no_joint_customizations()
	root = Path(frappe.get_app_path("deeplinkerp_branding"))
	files, definitions, schemas, ddl = {}, {}, {}, {}
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
		if not source["issingle"]:
			# Generate CREATE even for matching preexisting tables, in memory only.
			from frappe.database.mariadb.schema import MariaDBTable
			with _read_only_native_planning() as captured:
				MariaDBTable(name, meta).create()
			assert len(captured) == 1
			ddl[name] = captured[0]
			schemas[name] = _schema_from_create(captured[0])
		else:
			schemas[name] = None
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
	job = {"doctype": "Scheduled Job Type", "name": OPERATING_METHOD, "method": OPERATING_METHOD, "frequency": "Cron", "cron_format": "*/15 * * * *"}
	definitions[OPERATING_METHOD] = {"source": job, "native": _definition_rows(job, defaults=True)}
	for relative in ("operating_expense_install.py", "hooks.py", "operating_navigation.py", "procurement_navigation.py"):
		files[relative] = hashlib.sha256((root / relative).read_bytes()).hexdigest()
	hooks = ast.parse((root / "hooks.py").read_text())
	schedules = [ast.literal_eval(node.value) for node in hooks.body if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == "scheduler_events" for target in node.targets)]
	assert len(schedules) == 1 and OPERATING_METHOD in schedules[0].get("cron", {}).get("*/15 * * * *", []), "Frozen cron hook drift"
	return {"frappe_version": frappe.__version__, "files": files, "installer_files": _installer_source_files(), "definitions": definitions, "model_schemas": schemas, "model_ddl": ddl, "custom_fields": custom_fields, "native_metadata_schemas": {dt: table_schema(dt) for dt in ("DocType", "DocField", "DocPerm", "Custom Field", "Page", "Has Role", "Scheduled Job Type")}, "sources_after": {app: source_files(app) for app in ("deeplinkerp_branding", "china_finance", "crm_integration")}}


def _definition_matches(scope, name, definition):
	from joint_release_guards import semantic_row
	source = definition["source"]
	parent_dt = source["doctype"]
	if parent_dt == "Scheduled Job Type":
		parents = [row for row in scope[parent_dt] if row.get("method") == source["method"]]
		assert all(row.get("method") == source["method"] for row in scope[parent_dt]), "Conflicting scheduled job identity"
	else:
		parents = [row for row in scope[parent_dt] if row["name"] == name]
	children = {dt: [row for row in rows if row.get("parenttype") == parent_dt and row.get("parent") == name] for dt, rows in scope.items() if dt != parent_dt}
	if not parents:
		assert not any(children.values()), "Orphan native metadata: " + name
		return False
	actual_parents = [semantic_row(row) for row in parents]
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
	registration = {"name", "creation", "modified", "owner", "modified_by", "docstatus", "idx", "_comments", "_assign", "_user_tags", "_liked_by"}
	shared = set(contract["native_metadata_schemas"]["DocField"]["columns"]) - registration
	for key in present:
		fields = [field for field in meta.fields if field.fieldname == key]
		assert len(fields) == 1, "Missing/duplicate effective operating Journal Entry field"
		expected = contract["definitions"]["Journal Entry-" + key]["native"]["Custom Field"][0]
		assert all(fields[0].get(flag) == value for flag, value in expected.items() if flag in shared), "Conflicting effective native Journal Entry field behavior: " + key


def _joint_plan(before, contract, *, when, seed):
	import frappe
	from frappe.model.meta import Meta
	from audit_unified_purchase import table_schema
	from joint_release_guards import validate_event_index

	_assert_no_joint_customizations()
	scope = before["metadata"]["scope"]
	for row in scope["Custom Field"]:
		assert row.get("dt") == "Journal Entry" and row.get("fieldname") in CUSTOM_FIELD_ORDER and row["name"] == "Journal Entry-" + row["fieldname"], "Orphan/conflicting Custom Field identity"
	assert not frappe.db.sql("select name from `tabDocField` where parent='Journal Entry' and fieldname in (" + ",".join(["%s"] * len(CUSTOM_FIELD_ORDER)) + ")", CUSTOM_FIELD_ORDER), "Operating fields conflict with standard Journal Entry DocFields"
	expected = copy.deepcopy(scope)
	new = []
	for name, definition in contract["definitions"].items():
		matching = _definition_matches(scope, name, definition)
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
	assert not before["operating_singles"] and all(not model["rows"] for model in before["models"].values()), "Operating models/Single must be empty; installation must not import source activity"
	expected = _desired_navigation(expected, when=when, seed=seed)
	# Inspect the native desired JE delta BEFORE registering any metadata.
	meta = copy.deepcopy(frappe.get_meta("Journal Entry", cached=False))
	_assert_frozen_je_fields(meta, contract, [key for key in contract["custom_fields"] if key in columns])
	for key, field in contract["custom_fields"].items():
		if key not in columns:
			meta.fields.append(frappe._dict(field))
	for query in _native_schema_sql("Journal Entry", meta):
		_validate_je_ddl(query, {key for key in contract["custom_fields"] if key not in columns})
	return {"scope": expected, "new_definitions": new}


def _je_column(count, *, position=None):
	return {"position": position or count + 1, "type": "varchar(140)", "nullable": "YES", "default_value": "NULL", "charset": "utf8mb4", "collation": "utf8mb4_unicode_ci", "extra": "", "expression": None}


def _validate_je_ddl(query, new_columns):
	assert query.startswith("ALTER TABLE `tabJournal Entry` "), "Native plan escaped Journal Entry"
	clauses = query.split("`tabJournal Entry` ", 1)[1].split(", ")
	for clause in clauses:
		column = re.fullmatch(r"ADD COLUMN `([\w]+)` varchar\(140\)(?: UNIQUE)?", clause)
		index = re.fullmatch(r"ADD UNIQUE INDEX IF NOT EXISTS custom_operating_event_key \(`custom_operating_event_key`\)", clause)
		assert (column and column[1] in new_columns) or (index and "custom_operating_event_key" in new_columns), "Unexpected native Journal Entry schema change: " + clause


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
	assert not current["operating_singles"], "New Operating Expense Single activity; rollback refused"
	assert all(not model["rows"] for model in current["models"].values()), "New operating model activity; rollback refused"
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
	for name, model in current["models"].items():
		if model["schema"]:
			assert model["schema"] == contract["model_schemas"][name], "Model SQL schema drift: " + name
	old_audit, audit = copy.deepcopy(before["audit"]), copy.deepcopy(current["audit"])
	assert audit.pop("release_sources_all") == contract["sources_" + source_phase], "Pinned app source drift"
	old_audit.pop("release_sources_all")
	# Has Role is fully protected by the raw scope and outside permission audit above.
	for item in (old_audit, audit):
		item["tables"].pop("Has Role", None)
		item["schemas"].pop("Journal Entry")
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
	from audit_unified_purchase import capture_joint_state, table_schema
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
		current = capture_joint_state(original_columns=receipt.state["before"]["je"]["original_columns"])
		_assert_joint_invariants(receipt, current, scope=receipt.state["after"]["metadata"]["scope"])
		assert current == receipt.state["after"], "Second apply drift"
		return {"applied": True, "unchanged": True, "first_receipt_preserved": True, "identity": identity}
	before = capture_joint_state()
	if before_audit:
		for key in ("tables", "schemas", "singles", "configuration_sha256", "maintenance_mode", "assets_manifest_sha256"):
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
		_assert_joint_invariants(receipt, capture_joint_state(original_columns=before["je"]["original_columns"]), scope=plan["scope"])
		frappe.db.commit()
		receipt.complete("metadata", capture_joint_metadata()["scope"])
	for name in (*JOINT_MODELS, "Journal Entry"):
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
	for phase, name, meta in metas:
		queries = _native_schema_sql(name, meta)
		for query in queries:
			if name == "Journal Entry":
				_validate_je_ddl(query, {key for key in contract["custom_fields"] if key not in before["je"]["schema"]["columns"]})
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
			expected = copy.deepcopy(observed)
			if name in JOINT_MODELS:
				expected = contract["model_schemas"][name]
			elif phase.startswith("journal-column-"):
				key = phase.removeprefix("journal-column-")
				assert key not in expected["columns"]
				expected["columns"][key] = _je_column(len(expected["columns"]))
			else:
				expected["indexes"]["custom_operating_event_key"] = [{"sequence": 1, "column": "custom_operating_event_key", "unique": 1, "prefix": None, "collation": "A", "type": "BTREE", "nullable": "YES"}]
			receipt.plan(step_id, observed, expected, kind="ddl", doctype=name, sql=str(query))
			original_ddl(query, **kwargs)
			actual = table_schema(name)
			assert actual == expected, "Native DDL produced unexpected schema"
			_assert_joint_invariants(receipt, capture_joint_state(original_columns=before["je"]["original_columns"]), scope=plan["scope"])
			receipt.complete(step_id, actual)
		with patch.object(frappe.db, "sql_ddl", bounded_ddl):
			frappe.db.updatedb(name, meta)
		assert not remaining, "Native updatedb omitted inspected DDL"
	after = capture_joint_state(original_columns=before["je"]["original_columns"])
	_assert_joint_invariants(receipt, after, scope=plan["scope"])
	for key in contract["custom_fields"]:
		assert key in after["je"]["schema"]["columns"]
	assert after["je"]["schema"]["indexes"].get("custom_operating_event_key")
	assert all(model["schema"] == contract["model_schemas"][name] for name, model in after["models"].items())
	assert _desired_navigation(plan["scope"], when=str(now_datetime()), seed="second-run") == plan["scope"], "Second navigation reconciliation is not idle"
	receipt.finish(after)
	return {"applied": True, "unchanged": not receipt.state["steps"], "identity": identity, "ddl_boundaries": len([step for step in receipt.state["steps"] if step["kind"] == "ddl"]), "protected_tables": len(after["audit"]["tables"]), "original_je_projection": digest(before["je"]["rows"]), "new_fields_all_null": True, "source_sync_enabled": False}


def _assert_recorded_rollback_state(receipt, current):
	"""Accept only states explained by the durable latest intent per component.

	The common business/source invariants run separately, including old-image
	source normalization. Here every scope row and native schema is exact; only
	a pending single DDL or per-row metadata autocommit may be on either side.
	"""
	state = receipt.state
	assert state["status"] in {"applying", "applied", "restored"}
	basis = state["after"] if state["status"] == "applied" else state["before"]
	if state["status"] == "restored":
		basis = state["before"]
	latest = {}
	if state["status"] != "restored":
		for step in state["steps"]:
			if state["status"] == "applied" and not step["kind"].startswith("rollback-"):
				continue
			if step["kind"] in {"ddl", "rollback-ddl"}:
				latest[step["doctype"]] = step
			elif step["kind"] in {"metadata", "rollback-metadata"}:
				latest["metadata"] = step
	for name, actual in (("Journal Entry", current["je"]["schema"]), *((name, model["schema"]) for name, model in current["models"].items())):
		original = basis["je"]["schema"] if name == "Journal Entry" else basis["models"][name]["schema"]
		step = latest.get(name)
		allowed = [original] if step is None else [step["expected_after"]]
		if step is not None and step["status"] == "pending":
			allowed.append(step["before"])
		assert actual in allowed, "Native schema drift from recorded release/rollback intent: " + name
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
	from audit_unified_purchase import capture_joint_state, table_schema
	from joint_release_guards import DDLReceipt

	assert frappe.conf.maintenance_mode == 1, "Rollback requires maintenance plus shell-held lock/quiescence"
	receipt = DDLReceipt.load(receipt_path)
	if candidate_sha:
		assert receipt.state["identity"]["candidate_sha"] == candidate_sha
	before, contract = receipt.state["before"], receipt.state["contract"]
	frappe.db.rollback()
	current = capture_joint_state(original_columns=before["je"]["original_columns"])
	_assert_joint_invariants(receipt, current, source_phase=source_phase)
	_assert_recorded_rollback_state(receipt, current)
	# A crash may follow the native autocommit but precede complete(). Persist
	# only the latest pending rollback intent actually observed at its result.
	latest = {}
	for step in receipt.state["steps"]:
		if step["kind"] in {"rollback-ddl", "rollback-metadata"}:
			latest[step.get("doctype", "metadata")] = step
	for name, step in latest.items():
		actual = current["metadata"]["scope"] if name == "metadata" else (current["je"]["schema"] if name == "Journal Entry" else current["models"][name]["schema"])
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
			after = capture_joint_state(original_columns=before["je"]["original_columns"])
			_assert_joint_invariants(receipt, after, source_phase=source_phase)
			_assert_recorded_rollback_state(receipt, after)
			receipt.complete(step_id, table_schema(name))
	# One newly NULL column per native autocommit; dropping its new index is bounded too.
	for key in reversed(CUSTOM_FIELD_ORDER):
		actual = table_schema("Journal Entry")
		if key not in before["je"]["schema"]["columns"] and key in actual["columns"]:
			expected = copy.deepcopy(actual)
			expected["columns"].pop(key)
			if key == "custom_operating_event_key":
				expected["indexes"].pop(key, None)
			query = "ALTER TABLE `tabJournal Entry` DROP COLUMN " + _quote(key)
			step_id = "rollback-column-" + key
			receipt.plan(step_id, actual, expected, kind="rollback-ddl", doctype="Journal Entry", sql=query)
			frappe.db.sql_ddl(query)
			after = capture_joint_state(original_columns=before["je"]["original_columns"])
			_assert_joint_invariants(receipt, after, source_phase=source_phase)
			_assert_recorded_rollback_state(receipt, after)
			receipt.complete(step_id, table_schema("Journal Entry"))
	actual_scope = capture_joint_metadata()["scope"]
	if actual_scope != before["metadata"]["scope"]:
		pending = next((step for step in receipt.state["steps"] if step["id"] == "rollback-metadata"), None)
		# Do not replace the original durable intent with a partially recovered
		# snapshot. Its exact per-row partial state was validated on entry.
		receipt.plan("rollback-metadata", pending["before"] if pending else actual_scope, before["metadata"]["scope"], kind="rollback-metadata")
		_write_scope(actual_scope, before["metadata"]["scope"])
		_assert_joint_invariants(receipt, capture_joint_state(original_columns=before["je"]["original_columns"]), scope=before["metadata"]["scope"], source_phase=source_phase)
		frappe.db.commit()
		receipt.complete("rollback-metadata", capture_joint_metadata()["scope"])
	for name in (*JOINT_MODELS, "Journal Entry"):
		frappe.clear_cache(doctype=name)
	final = capture_joint_state(original_columns=before["je"]["original_columns"])
	_assert_joint_invariants(receipt, final, scope=before["metadata"]["scope"], source_phase=source_phase)
	_assert_recorded_rollback_state(receipt, final)
	assert final["je"] == before["je"] and final["models"] == before["models"] and final["metadata"] == before["metadata"], "Rollback did not restore exact native original state"
	receipt.restored()
	return {"restored": True, "original_bytes_and_child_ids": True, "pending_inspected_from_database": True, "maintenance_retained": True}


def verify_joint_audit_delta(before, after, receipt):
	"""Host-side final gate: full sources, raw scoped metadata and original JE schema."""
	from joint_release_guards import assert_schema_delta, validate_event_index
	assert receipt["status"] == "applied" and all(step["status"] == "complete" for step in receipt["steps"])
	assert before.pop("joint_metadata") == receipt["before"]["metadata"]
	assert after.pop("joint_metadata") == receipt["after"]["metadata"]
	assert receipt["before"]["metadata"]["outside"] == receipt["after"]["metadata"]["outside"]
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
	for item, native in ((before, receipt["before"]), (after, receipt["after"])):
		# Raw all Has Role rows are fully covered by exact scope + exact outside rows.
		roles = sorted(native["metadata"]["scope"]["Has Role"] + native["metadata"]["outside_rows"]["Has Role"], key=lambda row: row["name"])
		assert item["tables"]["Has Role"] == digest(roles)
		item["tables"].pop("Has Role")
		item["schemas"].pop("Journal Entry")
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
