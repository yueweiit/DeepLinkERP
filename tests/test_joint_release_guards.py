"""Pure receipt/schema safety tests; native DDL is tested separately on MariaDB."""

import contextlib
import copy
import hashlib
import importlib.util
import json
import os
import stat
import tempfile
import types
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).parents[1]


class JointReleaseGuardTests(unittest.TestCase):
	def module(self):
		path = ROOT / "deploy/production/joint_release_guards.py"
		self.assertTrue(path.exists(), "Durable joint release guards are missing")
		spec = importlib.util.spec_from_file_location("joint_release_guards", path)
		module = importlib.util.module_from_spec(spec)
		spec.loader.exec_module(module)
		return module

	def schema(self):
		return {"columns": {"name": {"type": "varchar(140)", "default": "NULL"}}, "indexes": {"PRIMARY": [{"column": "name", "unique": 1, "prefix": None}]}, "table": {"engine": "InnoDB"}}

	def test_native_delta_keeps_every_original_column_index_and_table_option(self):
		guard = self.module().assert_schema_delta
		before = self.schema()
		addition = {"columns": {"custom_operating_event_key": {"type": "varchar(140)", "default": "NULL"}}, "indexes": {"custom_operating_event_key": [{"column": "custom_operating_event_key", "unique": 1, "prefix": None}]}}
		after = copy.deepcopy(before)
		for kind, entries in addition.items():
			after[kind].update(entries)
		guard(before, after, addition)
		for scenario in ("column", "index", "extra", "definition", "table"):
			with self.subTest(scenario=scenario):
				changed = copy.deepcopy(after)
				if scenario == "column":
					changed["columns"]["name"]["default"] = "''"
				elif scenario == "index":
					changed["indexes"]["PRIMARY"][0]["prefix"] = 10
				elif scenario == "extra":
					changed["columns"]["unapproved"] = {}
				elif scenario == "definition":
					changed["indexes"]["custom_operating_event_key"][0]["unique"] = 0
				else:
					changed["table"]["engine"] = "MyISAM"
				with self.assertRaises(AssertionError):
					guard(before, changed, addition)

	def test_unique_event_index_must_be_full_length_single_column_and_unique(self):
		guard = self.module().validate_event_index
		row = {"column": "custom_operating_event_key", "unique": 1, "prefix": None, "type": "BTREE"}
		guard([row])
		for rows in ([dict(row, prefix=40)], [dict(row, unique=0)], [row, dict(row, column="name")], [dict(row, column="custom_operating_source")]):
			with self.subTest(rows=rows), self.assertRaises(AssertionError):
				guard(rows)

	def test_semantic_metadata_comparison_preserves_all_native_behavior_flags(self):
		semantic = self.module().semantic_row
		row = {"name": "generated", "creation": "then", "modified": "then", "owner": "Administrator", "modified_by": "Administrator", "fieldname": "custom_operating_source", "reqd": 0, "default": None, "hidden": 0, "read_only": 1, "no_copy": 1, "unique": 0, "permlevel": 0, "options": "Operating Expense Source", "idx": 0}
		self.assertEqual(semantic(row), semantic(dict(row, name="other", modified="now")))
		for field in ("reqd", "default", "hidden", "read_only", "no_copy", "unique", "permlevel", "options", "idx"):
			with self.subTest(field=field):
				self.assertNotEqual(semantic(row), semantic(dict(row, **{field: "changed"})))

	def metadata_module(self):
		guard_module = patch.dict(sys.modules, {"joint_release_guards": self.module()})
		guard_module.start()
		self.addCleanup(guard_module.stop)
		path = ROOT / "deploy/production/procurement_release_metadata.py"
		sys.path.insert(0, str(path.parent))
		try:
			spec = importlib.util.spec_from_file_location("metadata", path)
			module = importlib.util.module_from_spec(spec)
			spec.loader.exec_module(module)
			return module
		finally:
			sys.path.pop(0)

	def test_existing_page_compatibility_is_only_null_or_exact_name_and_never_rewrites_raw_rows(self):
		module = self.metadata_module()
		definition = {"source": {"doctype": "Page", "name": "operating-expenses"}, "native": {"Page": [{"page_name": None, "title": "运营费用", "idx": 0}]}}
		for route in (None, "operating-expenses", "other-page"):
			row = {"name": "operating-expenses", "page_name": route, "title": "运营费用", "idx": 0, "creation": "before", "modified": "before"}
			scope = {"Page": [row], "Has Role": []}
			before = copy.deepcopy(scope)
			if route == "other-page":
				with self.assertRaises(AssertionError):
					module._definition_matches(scope, "operating-expenses", definition)
			else:
				self.assertTrue(module._definition_matches(scope, "operating-expenses", definition))
			self.assertEqual(scope, before)

	def page_title_fixture(self, module, *, route=None, title="运营费用"):
		page = {"name": "operating-expenses", "page_name": route, "title": title, "module": "Deeplinkerp Branding", "standard": "Yes", "idx": 0, "creation": "original", "modified": "original", "owner": "original-user", "modified_by": "original-user"}
		role = {"name": "original-role-id", "parent": page["name"], "parenttype": "Page", "parentfield": "roles", "role": "System Manager", "idx": 1, "creation": "original", "modified": "original"}
		before = {"metadata": {"scope": {"Page": [page], "Has Role": [role], "Custom Field": []}}, "models": {}, "operating_singles": [], "je": {"schema": {"columns": {}, "indexes": {}}}}
		definition = {"source": {"doctype": "Page", "name": page["name"], "title": "运营支出"}, "native": {"Page": [self.module().semantic_row(dict(page, page_name=None, title="运营支出"))], "Has Role": [self.module().semantic_row(role)]}}
		contract = {"definitions": {page["name"]: definition}, "custom_fields": {}, "native_metadata_schemas": {"DocField": {"columns": {}}}}
		return before, contract

	def page_title_plan(self, module, before, contract, **kwargs):
		fake = types.SimpleNamespace(db=types.SimpleNamespace(sql=lambda *a, **kw: [], exists=lambda *a: True), get_meta=lambda *a, **kw: types.SimpleNamespace(fields=[]))
		with patch.dict(sys.modules, {"frappe": fake, "frappe.model.meta": types.SimpleNamespace(Meta=object), "audit_unified_purchase": types.SimpleNamespace(table_schema=lambda *a: None)}), patch.object(module, "_desired_navigation", lambda scope, **kw: scope), patch.object(module, "_native_schema_sql", lambda *a: []):
			return module._joint_plan(before, contract, when="frozen-now", seed="frozen", **kwargs)

	def test_joint_plan_records_only_approved_operating_title_upgrade_and_preserves_raw_parent_children(self):
		module = self.metadata_module()
		for route in (None, "operating-expenses"):
			with self.subTest(route=route):
				before, contract = self.page_title_fixture(module, route=route)
				original, frozen = copy.deepcopy(before), copy.deepcopy(contract)
				with self.assertRaisesRegex(AssertionError, "Conflicting full native definition"):
					module._definition_matches(before["metadata"]["scope"], "operating-expenses", contract["definitions"]["operating-expenses"])
				plan = self.page_title_plan(module, before, contract)
				wanted = copy.deepcopy(before["metadata"]["scope"])
				wanted["Page"][0]["title"] = "运营支出"
				self.assertEqual(plan["scope"], wanted)
				self.assertEqual(plan["new_definitions"], [])
				self.assertEqual(plan["page_title_updates"], [{"name": "operating-expenses", "field": "title", "before": "运营费用", "after": "运营支出"}])
				self.assertEqual(before, original)
				self.assertEqual(contract, frozen)

	def test_title_upgrade_rejects_other_titles_routes_parent_fields_children_and_pages(self):
		module = self.metadata_module()
		for conflict in ("other-title", "wrong-route", "module", "standard", "extra-parent-field", "role", "child-parentfield", "child-idx", "extra-child", "other-page", "wrong-source-title"):
			with self.subTest(conflict=conflict):
				before, contract = self.page_title_fixture(module)
				page, role = before["metadata"]["scope"]["Page"][0], before["metadata"]["scope"]["Has Role"][0]
				if conflict == "other-title":
					page["title"] = "自定义标题"
				elif conflict == "wrong-route":
					page["page_name"] = "other-page"
				elif conflict in {"module", "standard"}:
					page[conflict] = "unapproved"
				elif conflict == "extra-parent-field":
					page["show_title"] = 1
				elif conflict in {"role", "child-parentfield", "child-idx"}:
					role[{"role": "role", "child-parentfield": "parentfield", "child-idx": "idx"}[conflict]] = "unapproved"
				elif conflict == "extra-child":
					before["metadata"]["scope"]["Has Role"].append(dict(role, name="extra", idx=2))
				elif conflict == "wrong-source-title":
					contract["definitions"]["operating-expenses"]["source"]["title"] = "其他新标题"
					contract["definitions"]["operating-expenses"]["native"]["Page"][0]["title"] = "其他新标题"
				else:
					page["name"] = role["parent"] = "purchase-payables"
					definition = contract["definitions"].pop("operating-expenses")
					definition["source"]["name"] = "purchase-payables"
					definition["native"]["Has Role"][0]["parent"] = "purchase-payables"
					contract["definitions"]["purchase-payables"] = definition
				original = copy.deepcopy(before)
				with self.assertRaises(AssertionError):
					self.page_title_plan(module, before, contract)
				self.assertEqual(before, original)

	def test_exact_new_title_is_noop_and_never_records_an_upgrade(self):
		module = self.metadata_module()
		before, contract = self.page_title_fixture(module, route="operating-expenses", title="运营支出")
		plan = self.page_title_plan(module, before, contract)
		self.assertEqual(plan["scope"], before["metadata"]["scope"])
		self.assertEqual(plan["new_definitions"], [])
		self.assertEqual(plan.get("page_title_updates"), [])

	def test_existing_exact_scheduled_method_keeps_native_generated_row_identity(self):
		module = self.metadata_module()
		row = {"name": "native-hash-id", "method": module.OPERATING_METHOD, "frequency": "Cron", "cron_format": "*/15 * * * *", "stopped": 0, "creation": "original"}
		definition = {"source": {"doctype": "Scheduled Job Type", "name": module.OPERATING_METHOD, "method": module.OPERATING_METHOD}, "native": {"Scheduled Job Type": [self.module().semantic_row(row)]}}
		scope = {"Scheduled Job Type": [row]}
		self.assertTrue(module._definition_matches(scope, module.OPERATING_METHOD, definition))
		self.assertEqual(scope["Scheduled Job Type"][0]["name"], "native-hash-id")

	def navigation_fixture(self):
		from tests.test_procurement_navigation import Doc, Row, navigation
		class NativeRow(Row):
			def _fix_numeric_types(self):
				for key in ("docstatus", "idx", "child"):
					self[key] = int(self.get(key) or 0)
			def get_valid_dict(self, **kwargs):
				return {key: value for key, value in self.items() if key not in {"doctype", "display_depends_on"}}
		class NativeSidebar(Doc):
			@property
			def meta(self):
				return types.SimpleNamespace(get_table_fields=lambda: [types.SimpleNamespace(fieldname="items", options="Workspace Sidebar Item")])
			def as_dict(self):
				return copy.deepcopy(dict(self))
			def get_all_children(self):
				return self["items"]
			def get_valid_dict(self, **kwargs):
				return {key: value for key, value in self.items() if key not in {"doctype", "items"}}
			def append(self, table, values):
				row = NativeRow(values, doctype="Workspace Sidebar Item", name=None, docstatus="0", idx="0", child="0", parent="Accounting", parenttype="Workspace Sidebar", parentfield=table)
				self[table].append(row)
				return row
		original = NativeRow(doctype="Workspace Sidebar Item", name="custom-original", docstatus=0, idx=1, child=0, parent="Accounting", parenttype="Workspace Sidebar", parentfield="items", label="原有入口", link_to="Journal Entry", link_type="DocType", filters='{"keep":"原始字节"}', display_depends_on="eval:doc.keep_custom", creation="original", modified="original")
		doc = NativeSidebar(doctype="Workspace Sidebar", name="Accounting", creation="original", modified="original", items=[original])
		scope = {"Workspace": [], "Workspace Sidebar": [doc.get_valid_dict()], "Workspace Sidebar Item": [{key: value for key, value in original.items() if key != "doctype"}]}
		fake = types.SimpleNamespace(get_doc=lambda *args: doc)
		operating = types.SimpleNamespace(ENTRIES=(("运营费用", "Page", "operating-expenses", "receipt-text"),), TARGETS={"operating-expenses"}, _anchor=lambda doc, table: len(doc.get(table) or []))
		columns = {key: {"nullable": "YES", "type": "varchar(140)", "default_value": "NULL"} for key in scope["Workspace Sidebar Item"][0]}
		for key in ("docstatus", "idx", "child"):
			columns[key].update(nullable="NO", type="int(11)", default_value="0")
		return scope, fake, operating, navigation, columns

	def test_new_navigation_rows_pad_legacy_sql_columns_coerce_native_types_and_preserve_existing_bytes(self):
		module = self.metadata_module()
		scope, fake, operating, navigation, columns = self.navigation_fixture()
		before = copy.deepcopy(scope)
		audit = types.SimpleNamespace(table_schema=lambda doctype: {"columns": columns})
		with patch.dict(sys.modules, {"frappe": fake, "frappe.utils": types.SimpleNamespace(cint=lambda value: int(value or 0)), "audit_unified_purchase": audit, "deeplinkerp_branding.procurement_navigation": navigation, "deeplinkerp_branding.operating_navigation": operating}):
			planned = module._desired_navigation(scope, when="2026-10-06 00:00:00.000000", seed="frozen")
		old, new = sorted(planned["Workspace Sidebar Item"], key=lambda row: row["idx"])
		self.assertEqual(old, before["Workspace Sidebar Item"][0])
		self.assertIn("display_depends_on", new)
		self.assertIsNone(new["display_depends_on"])
		for key in ("docstatus", "idx", "child"):
			self.assertIs(type(new[key]), int)
		self.assertEqual(scope, before)

	def test_new_navigation_rows_reject_unknown_nonnull_physical_defaults_before_writes(self):
		module = self.metadata_module()
		scope, fake, operating, navigation, columns = self.navigation_fixture()
		columns["display_depends_on"].update(nullable="NO", default_value=None)
		before = copy.deepcopy(scope)
		audit = types.SimpleNamespace(table_schema=lambda doctype: {"columns": columns})
		with patch.dict(sys.modules, {"frappe": fake, "frappe.utils": types.SimpleNamespace(cint=lambda value: int(value or 0)), "audit_unified_purchase": audit, "deeplinkerp_branding.procurement_navigation": navigation, "deeplinkerp_branding.operating_navigation": operating}):
			with self.assertRaisesRegex(AssertionError, "Unknown non-NULL native metadata default: display_depends_on"):
				module._desired_navigation(scope, when="2026-10-06 00:00:00.000000", seed="frozen")
		self.assertEqual(scope, before)

	def test_receipt_is_private_and_preserves_first_baseline_after_identical_apply(self):
		module = self.module()
		identity = {"candidate_sha": "a" * 40, "contract_sha256": "b" * 64}
		with tempfile.TemporaryDirectory() as directory:
			path = Path(directory) / "receipt.json"
			receipt = module.DDLReceipt.create(path, identity, {"je": "original"}, {"frozen": True})
			self.assertEqual(path.stat().st_mode & 0o777, 0o600)
			with self.assertRaises(FileExistsError):
				module.DDLReceipt.create(path, identity, {"je": "different"}, {})
			receipt.plan("add-column", {"absent": True}, {"nullable": True})
			pending = module.DDLReceipt.load(path, identity)
			self.assertEqual(pending.state["steps"][0]["status"], "pending")
			receipt.complete("add-column", {"nullable": True})
			receipt.finish({"je": "original", "col": None})
			first = path.read_bytes()
			module.DDLReceipt.load(path, identity).finish({"je": "original", "col": None})
			self.assertEqual(path.read_bytes(), first)
			self.assertEqual(json.loads(first)["before"], {"je": "original"})
			self.assertEqual(json.loads(first)["before_sha256"], hashlib.sha256(module.serialized({"je": "original"})).hexdigest())

	def test_receipt_refuses_identity_baseline_or_actual_result_drift(self):
		module = self.module()
		identity = {"candidate_sha": "a" * 40, "contract_sha256": "b" * 64}
		with tempfile.TemporaryDirectory() as directory:
			path = Path(directory) / "receipt.json"
			receipt = module.DDLReceipt.create(path, identity, {}, {})
			receipt.plan("index", [], [{"unique": 1}])
			with self.assertRaises(AssertionError):
				receipt.complete("index", [{"unique": 0}])
			with self.assertRaises(AssertionError):
				module.DDLReceipt.load(path, dict(identity, candidate_sha="c" * 40))
			state = json.loads(path.read_bytes())
			state["before"] = {"tampered": True}
			path.write_text(json.dumps(state))
			with self.assertRaises(AssertionError):
				module.DDLReceipt.load(path, identity)

	def test_each_pending_intent_fsyncs_file_then_rename_then_directory_before_returning(self):
		module = self.module()
		identity = {"candidate_sha": "a" * 40, "contract_sha256": "b" * 64}
		with tempfile.TemporaryDirectory() as directory:
			path = Path(directory) / "receipt.json"
			receipt = module.DDLReceipt.create(path, identity, {}, {})
			events = []
			original_fsync, original_replace = os.fsync, os.replace
			def fsync(fd):
				events.append("directory" if stat.S_ISDIR(os.fstat(fd).st_mode) else "file")
				return original_fsync(fd)
			def replace(source, target):
				events.append("rename")
				return original_replace(source, target)
			with patch.object(module.os, "fsync", fsync), patch.object(module.os, "replace", replace):
				for number in range(9):
					events.clear()
					receipt.plan("ddl-" + str(number), {"before": number}, {"after": number})
					self.assertEqual(events, ["file", "rename", "directory"])
					self.assertEqual(json.loads(path.read_bytes())["steps"][-1]["status"], "pending")
					self.assertEqual(path.stat().st_mode & 0o777, 0o600)

	def test_installer_extends_existing_cli_and_does_not_run_broad_migration_hooks(self):
		source = (ROOT / "deploy/production/procurement_release_metadata.py").read_text()
		self.assertIn("def apply_joint_metadata(", source)
		self.assertIn("def restore_joint_metadata(", source)
		self.assertIn('"--joint-apply"', source)
		self.assertNotIn("sync_jobs(", source)
		self.assertNotIn("clear_events(", source)
		self.assertNotIn("after_migrate(", source)

	def test_frozen_receipt_contract_hashes_the_complete_installer_modules(self):
		module = self.metadata_module()
		self.assertTrue(hasattr(module, "_installer_source_files"))
		files = module._installer_source_files()
		self.assertEqual(set(files), {"procurement_release_metadata.py", "audit_unified_purchase.py", "joint_release_guards.py"})
		for name, digest in files.items():
			self.assertEqual(digest, hashlib.sha256((ROOT / "deploy/production" / name).read_bytes()).hexdigest())

	def rollback_fixture(self, module, path):
		before = {"je": {"original_columns": ["name"], "rows": [{"name": "original-je"}], "schema": self.schema()}, "models": {"Operating Expense Source": {"schema": None, "rows": []}}, "metadata": {"scope": {"Scheduled Job Type": []}}, "audit": {"release_sources_all": {"branding": "old"}, "preserved_apps": {"china_finance": "finance", "crm_integration": "crm"}}}
		after = copy.deepcopy(before)
		after["audit"]["release_sources_all"] = {"branding": "candidate"}
		after["je"]["schema"]["columns"]["custom_operating_event_key"] = {"type": "varchar(140)", "default": "NULL"}
		after["je"]["schema"]["indexes"]["custom_operating_event_key"] = [{"column": "custom_operating_event_key", "unique": 1, "prefix": None}]
		after["models"]["Operating Expense Source"]["schema"] = self.schema()
		after["metadata"]["scope"]["Scheduled Job Type"] = [{"name": "exact-new-job", "method": module.OPERATING_METHOD, "creation": "frozen"}]
		contract = {"metadata_plan": {"scope": after["metadata"]["scope"], "new_definitions": ["Operating Expense Source"]}, "sources_before": before["audit"]["release_sources_all"], "sources_after": after["audit"]["release_sources_all"], "preserved_before": before["audit"]["preserved_apps"]}
		contract.update(model_schemas={name: model["schema"] for name, model in after["models"].items()}, custom_fields=dict.fromkeys(module.CUSTOM_FIELD_ORDER))
		receipt = self.module().DDLReceipt.create(path, {"candidate_sha": "a" * 40, "contract_sha256": "b" * 64}, before, contract)
		receipt.finish(after)
		return receipt, before, after

	def mocked_rollback(self, module, path, current, events, **kwargs):
		def ddl(query):
			events.append(query)
			if query.startswith("DROP TABLE"):
				current["models"]["Operating Expense Source"]["schema"] = None
			else:
				current["je"]["schema"]["columns"].pop("custom_operating_event_key", None)
				current["je"]["schema"]["indexes"].pop("custom_operating_event_key", None)
		def write_scope(old, new):
			events.append("metadata-write")
			current["metadata"]["scope"] = copy.deepcopy(new)
		fake = types.SimpleNamespace(conf=types.SimpleNamespace(maintenance_mode=1), db=types.SimpleNamespace(rollback=lambda: None, commit=lambda: events.append("commit"), sql_ddl=ddl), scrub=lambda name: name.lower().replace(" ", "_"), clear_cache=lambda **kw: None)
		audit = types.SimpleNamespace(capture_joint_state=lambda **kw: copy.deepcopy(current), table_schema=lambda name: copy.deepcopy(current["je"]["schema"] if name == "Journal Entry" else current["models"][name]["schema"]))
		with patch.dict(sys.modules, {"frappe": fake, "audit_unified_purchase": audit}), patch.object(sys.modules["joint_release_guards"], "verified_quiescence", return_value=True), patch.object(module, "_assert_joint_invariants", lambda *a, **kw: None), patch.object(module, "capture_joint_metadata", lambda **kw: copy.deepcopy(current["metadata"])), patch.object(module, "_write_scope", write_scope):
			return module.restore_joint_metadata(path, **kwargs)

	def test_fully_applied_rollback_refuses_missing_new_metadata_column_index_or_model_before_writes(self):
		module = self.metadata_module()
		for missing in ("job", "column", "index", "model"):
			with self.subTest(missing=missing), tempfile.TemporaryDirectory() as directory:
				path = Path(directory) / "receipt.json"
				_, _, after = self.rollback_fixture(module, path)
				current = copy.deepcopy(after)
				if missing == "job":
					current["metadata"]["scope"]["Scheduled Job Type"] = []
				elif missing == "model":
					current["models"]["Operating Expense Source"]["schema"] = None
				else:
					current["je"]["schema"]["indexes"].pop("custom_operating_event_key")
					if missing == "column":
						current["je"]["schema"]["columns"].pop("custom_operating_event_key")
				original, first, events = copy.deepcopy(current), path.read_bytes(), []
				with self.assertRaisesRegex(AssertionError, "recorded|applied|drift"):
					self.mocked_rollback(module, path, current, events)
				self.assertEqual(current, original)
				self.assertEqual(path.read_bytes(), first)
				self.assertEqual(events, [])

	def test_recorded_pending_rollback_before_and_after_native_drop_are_recoverable(self):
		module = self.metadata_module()
		for applied in (False, True):
			with self.subTest(applied=applied), tempfile.TemporaryDirectory() as directory:
				path = Path(directory) / "receipt.json"
				receipt, before, after = self.rollback_fixture(module, path)
				model_schema = after["models"]["Operating Expense Source"]["schema"]
				receipt.plan("rollback-table-operating_expense_source", model_schema, None, kind="rollback-ddl", doctype="Operating Expense Source", sql="DROP TABLE `tabOperating Expense Source`")
				current = copy.deepcopy(after)
				if applied:
					current["models"]["Operating Expense Source"]["schema"] = None
				self.assertTrue(self.mocked_rollback(module, path, current, [])["restored"])
				self.assertEqual(current["je"], before["je"])
				self.assertEqual(current["models"], before["models"])
				self.assertEqual(current["metadata"], before["metadata"])

	def test_interrupted_apply_refuses_unexplained_missing_completed_ddl_and_metadata(self):
		module = self.metadata_module()
		for missing in ("job", "column", "index", "model"):
			with self.subTest(missing=missing), tempfile.TemporaryDirectory() as directory:
				path = Path(directory) / "receipt.json"
				receipt, before, after = self.rollback_fixture(module, path)
				receipt.plan("metadata", before["metadata"]["scope"], after["metadata"]["scope"], kind="metadata")
				receipt.complete("metadata", after["metadata"]["scope"])
				receipt.plan("journal", before["je"]["schema"], after["je"]["schema"], kind="ddl", doctype="Journal Entry")
				receipt.complete("journal", after["je"]["schema"])
				receipt.plan("model", None, after["models"]["Operating Expense Source"]["schema"], kind="ddl", doctype="Operating Expense Source")
				receipt.complete("model", after["models"]["Operating Expense Source"]["schema"])
				state = copy.deepcopy(receipt.state)
				state["status"] = "applying"
				state.pop("after")
				receipt._save(state)
				current = copy.deepcopy(after)
				if missing == "job":
					current["metadata"]["scope"]["Scheduled Job Type"] = []
				elif missing == "model":
					current["models"]["Operating Expense Source"]["schema"] = None
				else:
					current["je"]["schema"]["indexes"].pop("custom_operating_event_key")
					if missing == "column":
						current["je"]["schema"]["columns"].pop("custom_operating_event_key")
				first, events = path.read_bytes(), []
				with self.assertRaisesRegex(AssertionError, "recorded|drift"):
					self.mocked_rollback(module, path, current, events)
				self.assertEqual(events, [])
				self.assertEqual(path.read_bytes(), first)

	def test_pending_metadata_subset_is_recoverable_but_completed_scope_requires_exact_rows(self):
		module = self.metadata_module()
		for completed in (False, True):
			with self.subTest(completed=completed), tempfile.TemporaryDirectory() as directory:
				path = Path(directory) / "receipt.json"
				fixture, before, after = self.rollback_fixture(module, Path(directory) / "fixture.json")
				contract = copy.deepcopy(fixture.state["contract"])
				contract["metadata_plan"]["scope"]["Scheduled Job Type"].append({"name": "second-planned-job", "method": "synthetic", "creation": "frozen"})
				receipt = self.module().DDLReceipt.create(path, fixture.state["identity"], before, contract)
				receipt.plan("metadata", before["metadata"]["scope"], contract["metadata_plan"]["scope"], kind="metadata")
				current = copy.deepcopy(before)
				current["audit"]["release_sources_all"] = after["audit"]["release_sources_all"]
				current["metadata"]["scope"] = copy.deepcopy(after["metadata"]["scope"])
				if completed:
					receipt.complete("metadata", contract["metadata_plan"]["scope"])
					first, events = path.read_bytes(), []
					with self.assertRaisesRegex(AssertionError, "recorded|drift"):
						self.mocked_rollback(module, path, current, events)
					self.assertEqual(events, [])
					self.assertEqual(path.read_bytes(), first)
				else:
					self.assertTrue(self.mocked_rollback(module, path, current, [])["restored"])
					self.assertEqual(current["metadata"], before["metadata"])

	def test_pending_rollback_metadata_resumes_from_exact_recorded_partial_rows(self):
		module = self.metadata_module()
		with tempfile.TemporaryDirectory() as directory:
			fixture, before, after = self.rollback_fixture(module, Path(directory) / "fixture.json")
			after["metadata"]["scope"]["Scheduled Job Type"].append({"name": "second-planned-job", "method": "synthetic", "creation": "frozen"})
			contract = copy.deepcopy(fixture.state["contract"])
			contract["metadata_plan"]["scope"] = after["metadata"]["scope"]
			path = Path(directory) / "receipt.json"
			receipt = self.module().DDLReceipt.create(path, fixture.state["identity"], before, contract)
			receipt.finish(after)
			receipt.plan("rollback-metadata", after["metadata"]["scope"], before["metadata"]["scope"], kind="rollback-metadata")
			current = copy.deepcopy(after)
			current["metadata"]["scope"]["Scheduled Job Type"].pop()
			self.assertTrue(self.mocked_rollback(module, path, current, [])["restored"])
			self.assertEqual(current["metadata"], before["metadata"])

	def test_resumed_rollback_refuses_unrecorded_other_schema_or_metadata_loss(self):
		module = self.metadata_module()
		for missing in ("job", "index"):
			with self.subTest(missing=missing), tempfile.TemporaryDirectory() as directory:
				path = Path(directory) / "receipt.json"
				receipt, _, after = self.rollback_fixture(module, path)
				receipt.plan("rollback-table-operating_expense_source", after["models"]["Operating Expense Source"]["schema"], None, kind="rollback-ddl", doctype="Operating Expense Source")
				current = copy.deepcopy(after)
				current["models"]["Operating Expense Source"]["schema"] = None
				if missing == "job":
					current["metadata"]["scope"]["Scheduled Job Type"] = []
				else:
					current["je"]["schema"]["indexes"].pop("custom_operating_event_key")
				first, events = path.read_bytes(), []
				with self.assertRaisesRegex(AssertionError, "recorded|drift"):
					self.mocked_rollback(module, path, current, events)
				self.assertEqual(events, [])
				self.assertEqual(path.read_bytes(), first)

	def test_restored_receipt_is_noop_only_at_exact_original_baseline(self):
		module = self.metadata_module()
		for drift in (False, True):
			with self.subTest(drift=drift), tempfile.TemporaryDirectory() as directory:
				path = Path(directory) / "receipt.json"
				receipt, before, after = self.rollback_fixture(module, path)
				receipt.restored()
				current = copy.deepcopy(before)
				if drift:
					current["metadata"]["scope"] = copy.deepcopy(after["metadata"]["scope"])
				first, events = path.read_bytes(), []
				if drift:
					with self.assertRaisesRegex(AssertionError, "recorded|baseline|drift"):
						self.mocked_rollback(module, path, current, events, source_phase="before")
				else:
					self.assertTrue(self.mocked_rollback(module, path, current, events, source_phase="before")["restored"])
				self.assertEqual(events, [])
				self.assertEqual(path.read_bytes(), first)

	def test_applied_rollback_on_old_image_normalizes_only_pinned_source_maps(self):
		module = self.metadata_module()
		with tempfile.TemporaryDirectory() as directory:
			path = Path(directory) / "receipt.json"
			_, before, after = self.rollback_fixture(module, path)
			current = copy.deepcopy(after)
			current["audit"] = copy.deepcopy(before["audit"])
			self.assertTrue(self.mocked_rollback(module, path, current, [], source_phase="before")["restored"])

	def test_contract_rejects_effective_model_customizations_before_native_meta_absorption(self):
		module = self.metadata_module()
		self.assertTrue(hasattr(module, "_assert_no_joint_customizations"), "Read-only effective-metadata preflight is missing")
		cases = [("Custom Field", {"dt": name, "fieldname": "unapproved"}) for name in module.JOINT_MODELS]
		cases += [("Property Setter", {"doc_type": name, "field_name": "amount"}) for name in module.JOINT_MODELS]
		cases += [("Custom DocPerm", {"parent": name, "parenttype": None, "role": "All"}) for name in module.JOINT_MODELS]
		cases += [("Property Setter", {"doc_type": "Journal Entry", "field_name": key, "property": "read_only", "value": "0"}) for key in module.CUSTOM_FIELD_ORDER]
		for doctype, row in cases:
			with self.subTest(doctype=doctype, row=row):
				events = []
				def sql(query, values=(), **kwargs):
					self.assertTrue(str(query).lstrip().lower().startswith("select"))
					return [dict(row, name="unapproved-metadata")] if "`tab" + doctype + "`" in str(query) else []
				fake = types.SimpleNamespace(db=types.SimpleNamespace(sql=sql, commit=lambda: events.append("commit"), sql_ddl=lambda *a: events.append("DDL")))
				with patch.dict(sys.modules, {"frappe": fake}), self.assertRaisesRegex(AssertionError, "customization"):
					module._assert_no_joint_customizations()
				self.assertEqual(events, [])

	def test_existing_effective_journal_fields_preserve_all_frozen_native_behavior(self):
		module = self.metadata_module()
		self.assertTrue(hasattr(module, "_assert_frozen_je_fields"), "Effective frozen JE field comparison is missing")
		field = {"fieldname": "custom_operating_source", "fieldtype": "Link", "options": "Operating Expense Source", "reqd": 0, "default": None, "hidden": 0, "read_only": 1, "no_copy": 1, "unique": 0, "permlevel": 0, "search_index": 0, "fetch_from": None, "description": None, "idx": 0, "dt": "Journal Entry", "docstatus": 0}
		contract = {"definitions": {"Journal Entry-custom_operating_source": {"native": {"Custom Field": [field]}}}, "native_metadata_schemas": {"DocField": {"columns": {flag: {} for flag in field if flag != "dt"}}}}
		class Field(dict):
			__getattr__ = dict.__getitem__
		original = dict(field, idx=151, is_custom_field=1)
		module._assert_frozen_je_fields(types.SimpleNamespace(fields=[Field(original)]), contract, (field["fieldname"],))
		for flag in ("reqd", "default", "hidden", "read_only", "no_copy", "unique", "permlevel", "options", "search_index", "fetch_from", "description"):
			with self.subTest(flag=flag), self.assertRaisesRegex(AssertionError, "effective|behavior"):
				module._assert_frozen_je_fields(types.SimpleNamespace(fields=[Field(dict(original, **{flag: "changed"}))]), contract, (field["fieldname"],))

	def test_unrelated_customizations_remain_read_only_and_outside_frozen_scope(self):
		module = self.metadata_module()
		self.assertTrue(hasattr(module, "_assert_no_joint_customizations"))
		events = []
		def sql(query, values=(), **kwargs):
			self.assertTrue(str(query).lstrip().lower().startswith("select"))
			events.append((str(query), tuple(values)))
			return []
		with patch.dict(sys.modules, {"frappe": types.SimpleNamespace(db=types.SimpleNamespace(sql=sql))}):
			module._assert_no_joint_customizations()
		self.assertEqual(len(events), 4)
		self.assertTrue(all("Journal Entry" not in values or set(module.CUSTOM_FIELD_ORDER) <= set(values) for _, values in events))

	def test_native_planning_virtualizes_cache_fills_but_forbids_real_cache_sql_and_commit_mutations(self):
		module = self.metadata_module()
		events = []
		cache = types.SimpleNamespace(**{name: lambda *a, **kw: events.append("real-cache") for name in ("get_value", "set_value", "delete_value", "set", "delete", "hset", "hdel", "sadd", "srem", "publish", "flushdb", "flushall")})
		fake = types.SimpleNamespace(get_meta=lambda *a, **kw: "meta", cache=cache, client_cache=types.SimpleNamespace(get_value=cache.get_value, set_value=cache.set_value, delete_value=cache.delete_value), db=types.SimpleNamespace(sql=lambda query, *a, **kw: [query], sql_ddl=lambda *a, **kw: events.append("real-ddl"), commit=lambda: events.append("commit"), rollback=lambda: events.append("rollback")))
		with patch.dict(sys.modules, {"frappe": fake}), module._read_only_native_planning() as queries:
			fake.cache.set_value("columns", ["name"])
			self.assertEqual(fake.cache.get_value("columns"), ["name"])
			self.assertEqual(fake.cache.get_value("generated", generator=lambda: 2), 2)
			fake.client_cache.set_value("native-meta", "value")
			self.assertEqual(fake.client_cache.get_value("native-meta"), "value")
			self.assertEqual(fake.db.sql("select 1"), ["select 1"])
			fake.db.sql_ddl("captured-only")
			for action in (lambda: fake.db.sql("update anything"), fake.db.commit, fake.db.rollback, lambda: fake.cache.set("key", "value"), fake.cache.flushdb):
				with self.assertRaises(AssertionError):
					action()
			self.assertEqual(queries, ["captured-only"])
		self.assertEqual(events, [])

	def test_frozen_overlay_preserves_only_pinned_inventory_assets_and_appledouble_bytes(self):
		module = self.module()
		self.assertTrue(hasattr(module, "merge_frozen_branding_sources"))
		assets = ("public/dist/css-rtl/inventory_detail.bundle.YQO3JEGB.css", "public/dist/css/inventory_detail.bundle.TGF3MUFO.css", "public/dist/js/inventory_detail.bundle.KYKUWWJK.js")
		legacy = {name + suffix: "pinned-" + name + suffix for name in assets for suffix in ("", ".map")}
		legacy.update({"services/._legacy.py": "appledouble", "._directory/source.py": "nested-appledouble"})
		base = dict(legacy, **{"hooks.py": "old", "services/original.py": "same"})
		candidate = {"hooks.py": "new", "services/original.py": "same", "page/new.js": "approved-new"}
		self.assertEqual(module.merge_frozen_branding_sources(base, candidate), dict(legacy, **candidate))
		for change in ("deleted-tracked", "unknown-base-extra", "replaced-dist", "replaced-appledouble", "new-appledouble", "incomplete-dist"):
			with self.subTest(change=change):
				old, new = dict(base), dict(candidate)
				if change == "deleted-tracked":
					new.pop("services/original.py")
				elif change == "unknown-base-extra":
					old["untracked-live.py"] = "do-not-ignore"
				elif change == "replaced-dist":
					new[assets[0]] = "different"
				elif change == "replaced-appledouble":
					new["services/._legacy.py"] = "different"
				elif change == "new-appledouble":
					new["._unapproved"] = "new"
				else:
					old.pop(assets[0] + ".map")
				with self.assertRaises(AssertionError):
					module.merge_frozen_branding_sources(old, new)

	def test_audit_includes_journal_entry_and_native_original_projection(self):
		source = (ROOT / "deploy/production/audit_unified_purchase.py").read_text()
		self.assertIn('"Journal Entry"', source)
		self.assertIn("def table_schema(", source)
		self.assertIn("def capture_joint_state(", source)
		self.assertIn("release_sources_all", source)

	def test_missing_uninstalled_preserved_app_is_recorded_and_installed_missing_source_aborts(self):
		path = ROOT / "deploy/production/audit_unified_purchase.py"
		with patch.dict(sys.modules, {"frappe": types.SimpleNamespace(get_installed_apps=lambda: [])}):
			spec = importlib.util.spec_from_file_location("audit", path)
			module = importlib.util.module_from_spec(spec)
			spec.loader.exec_module(module)
			with tempfile.TemporaryDirectory() as directory:
				module.BENCH = Path(directory)
				self.assertIsNone(module.source_digest("mobile_operations"))
				module.frappe.get_installed_apps = lambda: ["mobile_operations"]
				with self.assertRaises(AssertionError):
					module.source_digest("mobile_operations")
				for app in ("deeplinkerp_branding", "china_finance", "crm_integration"):
					with self.subTest(app=app), self.assertRaises(AssertionError):
						module.source_digest(app)

	def test_shell_quiesces_workers_before_new_image_and_keeps_durable_receipt_in_sites_volume(self):
		source = (ROOT / "deploy/production/deploy_unified_purchase.sh").read_text()
		self.assertIn("quiesce_release_workers() {", source)
		self.assertIn('--host-drain', source)
		self.assertNotIn('"${dc[@]}" stop ', source)
		self.assertIn("--joint-apply", source)
		self.assertIn("--joint-rollback", source)
		self.assertIn("/home/frappe/frappe-bench/sites/deeplinkerp.com/private/release-evidence/", source)
		self.assertLess(source.index("quiesce_release_workers\n"), source.index('# All six containers are staged stopped.'))

	def test_cli_refuses_ambiguous_actions_or_non_durable_receipt_before_connecting(self):
		module = self.metadata_module()
		fake = types.SimpleNamespace(init=lambda **kwargs: self.fail("Invalid CLI must not initialize a site"))
		cases = (("--joint-apply", "--joint-rollback"), ("--joint-apply",), ("--joint-rollback", "--candidate-sha", "a" * 40, "--receipt", "/tmp/non-durable.json"))
		for args in cases:
			with self.subTest(args=args), patch.dict(sys.modules, {"frappe": fake}), patch.object(sys, "argv", ["metadata", *args]), self.assertRaises(SystemExit):
				module.main()


class PurchaseSourceReleaseCompatibilityTests(unittest.TestCase):
	module = JointReleaseGuardTests.module
	metadata_module = JointReleaseGuardTests.metadata_module
	schema = JointReleaseGuardTests.schema
	page_title_fixture = JointReleaseGuardTests.page_title_fixture
	page_title_plan = JointReleaseGuardTests.page_title_plan

	def active_plan_fixture(self, module):
		before, contract = self.page_title_fixture(module, title="运营支出")
		before["metadata"]["scope"]["DocType"] = []
		contract["model_schemas"] = {}
		for name, single in (("Operating Expense Source", 0), ("Operating Expense Sync Settings", 1)):
			row = {"name": name, "issingle": single, "idx": 0, "creation": "original"}
			before["metadata"]["scope"]["DocType"].append(row)
			contract["definitions"][name] = {"source": {"doctype": "DocType", "name": name}, "native": {"DocType": [self.module().semantic_row(row)]}}
			contract["model_schemas"][name] = None if single else self.schema()
			before["models"][name] = {"schema": contract["model_schemas"][name], "rows": [] if single else [{"name": f"source-{i}", "original_evidence": '{"manual": 1 }'} for i in range(372)]}
		before["operating_singles"] = [{"doctype": "Operating Expense Sync Settings", "field": "sync_enabled", "value": "0"}]
		return before, contract

	def test_joint_plan_preserves_372_existing_operating_rows_and_configured_single(self):
		module = self.metadata_module()
		before, contract = self.active_plan_fixture(module)
		original = copy.deepcopy(before)
		plan = self.page_title_plan(module, before, contract)
		self.assertEqual(plan["new_definitions"], [])
		self.assertEqual(plan["scope"], before["metadata"]["scope"])
		self.assertEqual(before, original)

	def test_current_contract_validation_is_read_only_and_does_not_replay_historical_business_state(self):
		module = self.metadata_module()
		before, contract = self.active_plan_fixture(module)
		before["audit"] = {"purchase_source_sync_enabled": True, "maintenance_mode": 0, "release_quiescent": False,
			"release_sources_all": {"deeplinkerp_branding": {"existing.py": "frozen"}}}
		with self.assertRaisesRegex(AssertionError, "quiescence"):
			self.page_title_plan(module, before, contract)
		self.assertTrue(hasattr(module, "verify_current_joint_contract"))
		original = copy.deepcopy(before)
		matching = {"scope": before["metadata"]["scope"], "new_definitions": [], "page_title_updates": []}
		with patch.object(module, "_capture_joint_state", return_value=before), patch.object(module, "load_joint_contract", return_value=contract) as load_contract, patch.object(module, "_read_only_native_planning", contextlib.nullcontext), patch.object(module, "_joint_plan", return_value=matching) as plan:
			result = module.verify_current_joint_contract()
			self.assertTrue(result["current_contract_verified"])
			self.assertEqual(result["source_sync_enabled"], True)
			self.assertEqual(result["release_sources_all"], before["audit"]["release_sources_all"])
			self.assertFalse(plan.call_args.kwargs["require_quiescent"])
			self.assertEqual(plan.call_args.args, (before, contract))
			load_contract.assert_called_once_with(require_quiescent=False)
		self.assertEqual(before, original)
		self.assertEqual(self.page_title_plan(module, before, contract, require_quiescent=False)["new_definitions"], [])

	def test_current_contract_refuses_missing_definitions_title_or_navigation_repairs(self):
		module = self.metadata_module()
		self.assertTrue(hasattr(module, "verify_current_joint_contract"))
		before, contract = self.active_plan_fixture(module)
		for kind in ("definition", "title", "navigation"):
			with self.subTest(kind=kind):
				plan = {"scope": copy.deepcopy(before["metadata"]["scope"]), "new_definitions": [], "page_title_updates": []}
				if kind == "definition": plan["new_definitions"] = ["Purchase Fulfilment Link"]
				elif kind == "title": plan["page_title_updates"] = [{"name": "operating-expenses", "field": "title"}]
				else: plan["scope"]["Page"][0]["title"] = "unrecorded"
				with patch.object(module, "_capture_joint_state", return_value=before), patch.object(module, "load_joint_contract", return_value=contract), patch.object(module, "_read_only_native_planning", contextlib.nullcontext), patch.object(module, "_joint_plan", return_value=plan), self.assertRaises(AssertionError):
					module.verify_current_joint_contract()

	def test_active_model_and_single_cannot_be_recreated_without_matching_existing_metadata(self):
		module = self.metadata_module()
		before, contract = self.active_plan_fixture(module)
		before["metadata"]["scope"]["DocType"] = []
		with self.assertRaises(AssertionError):
			self.page_title_plan(module, before, contract)

	def invariant_fixture(self, module):
		je = self.schema()
		for field in module.CUSTOM_FIELD_ORDER:
			je["columns"][field] = module._je_column(len(je["columns"]))
		je["indexes"]["custom_operating_event_key"] = [{"sequence": 1, "column": "custom_operating_event_key", "unique": 1, "prefix": None, "collation": "A", "type": "BTREE", "nullable": "YES"}]
		metadata = {"scope": {"Has Role": [], "Custom Field": []}, "outside": {"Custom Field": module.digest([{"name": "Purchase Order-custom_oa_purchase_expense", "fieldtype": "Data"}])}, "outside_rows": {"Custom Field": [{"name": "Purchase Order-custom_oa_purchase_expense", "fieldtype": "Data"}], "Has Role": []}}
		rows = [{"name": f"source-{i}", "original_evidence": '{"manual": 1 }'} for i in range(372)]
		before = {"metadata": metadata, "je": {"schema": je, "rows": [{"name": "old-je"}], "original_columns": list(je["columns"])}, "models": {"Operating Expense Source": {"schema": self.schema(), "rows": rows}}, "operating_singles": [{"doctype": "Operating Expense Sync Settings", "field": "sync_enabled", "value": "0"}], "audit": {"release_sources_all": {"branding": "candidate"}, "tables": {"Has Role": module.digest([]), "OA Purchase Request": module.digest([{"name": "OA-old", "manual": "keep"}])}, "schemas": {"Journal Entry": je}, "singles": "same", "configuration_sha256": "same"}}
		contract = {"sources_after": before["audit"]["release_sources_all"], "model_schemas": {"Operating Expense Source": self.schema()}, "custom_fields": dict.fromkeys(module.CUSTOM_FIELD_ORDER)}
		return types.SimpleNamespace(state={"before": before, "contract": contract}), copy.deepcopy(before)

	def assert_invariants(self, module, receipt, current):
		fake = types.SimpleNamespace(db=types.SimpleNamespace(sql=lambda *a, **kw: [[0]]))
		with patch.dict(sys.modules, {"frappe": fake}):
			module._assert_joint_invariants(receipt, current)

	def test_joint_invariants_accept_exact_active_business_rows_and_single(self):
		module = self.metadata_module()
		receipt, current = self.invariant_fixture(module)
		self.assert_invariants(module, receipt, current)

	def test_active_row_or_single_drift_is_rejected_without_normalization(self):
		module = self.metadata_module()
		for changed in ("row", "removed", "added", "single", "outside"):
			with self.subTest(changed=changed):
				receipt, current = self.invariant_fixture(module)
				if changed == "row": current["models"]["Operating Expense Source"]["rows"][-1]["original_evidence"] = '{"manual":1}'
				elif changed == "removed": current["models"]["Operating Expense Source"]["rows"].pop()
				elif changed == "added": current["models"]["Operating Expense Source"]["rows"].append({"name": "new"})
				elif changed == "single": current["operating_singles"][0]["value"] = "1"
				else: current["metadata"]["outside_rows"]["Custom Field"][0]["fieldtype"] = "Link"
				with self.assertRaises(AssertionError): self.assert_invariants(module, receipt, current)

	def test_only_contract_oa_fields_are_in_scope_not_existing_po_or_native_oa_flags(self):
		module = self.metadata_module()
		fields = module.SOURCE_FIELD_ORDER
		self.assertEqual(len(fields), 12)
		fake = types.SimpleNamespace(get_app_path=lambda app, filename: str(ROOT / app / filename))
		with patch.dict(sys.modules, {"frappe": fake}):
			for field in fields:
				self.assertTrue(module._in_joint_scope("Custom Field", {"name": "OA Purchase Request-" + field, "dt": "OA Purchase Request", "fieldname": field}))
				self.assertTrue(module._in_joint_scope("Custom Field", {"name": "orphan-alias", "dt": "OA Purchase Request", "fieldname": field}))
			for dt, field in (("Purchase Order", "custom_oa_purchase_expense"), ("OA Purchase Request", "source_stale"), ("OA Purchase Request", "target_company")):
				self.assertFalse(module._in_joint_scope("Custom Field", {"name": dt + "-" + field, "dt": dt, "fieldname": field}))

	def test_source_cf_definitions_reuse_installer_without_invoking_it_and_keep_security(self):
		module = self.metadata_module()
		self.assertTrue(hasattr(module, "_source_custom_fields"))
		fake = types.SimpleNamespace(get_app_path=lambda app, filename: str(ROOT / app / filename))
		with patch.dict(sys.modules, {"frappe": fake}): fields = module._source_custom_fields()
		self.assertEqual(len(fields), 12)
		for name, field in fields.items():
			visible = name in {"custom_purchase_beneficiary_company", "custom_purchase_company_proposal", "custom_purchase_project", "custom_purchase_pending_reason"}
			self.assertEqual((field.get("hidden", 0), field["read_only"], field["no_copy"]), (int(not visible), 1, 1))
			self.assertFalse(field.get("default") or field.get("reqd"))
			self.assertEqual(field.get("unique", 0), int(name == "custom_purchase_source_id"))
			self.assertEqual(field.get("permlevel", 0), 9 if field["fieldtype"] == "Long Text" else 0)

	def test_scheduled_definitions_match_only_their_own_method_and_preserve_original_identity(self):
		module = self.metadata_module()
		source_method = "deeplinkerp_branding.services.purchase_source_service.scheduled_sync"
		rows = [{"name": "old-native-id", "method": module.OPERATING_METHOD, "frequency": "Cron", "cron_format": "*/15 * * * *", "creation": "original"}, {"name": source_method, "method": source_method, "frequency": "Cron", "cron_format": "*/15 * * * *", "creation": "new"}]
		scope = {"Scheduled Job Type": rows}
		for row in rows:
			definition = {"source": {"doctype": "Scheduled Job Type", "name": row["method"], "method": row["method"]}, "native": {"Scheduled Job Type": [self.module().semantic_row(row)]}}
			self.assertTrue(module._definition_matches(scope, row["method"], definition))
		self.assertEqual(rows[0]["name"], "old-native-id")
		scope["Scheduled Job Type"].append(dict(rows[1], name="duplicate"))
		with self.assertRaises(AssertionError): module._definition_matches(scope, source_method, definition)

	def test_scheduled_runtime_is_preserved_but_definition_and_security_drift_is_rejected(self):
		module = self.metadata_module()
		row = {"name": "original-job-id", "method": module.OPERATING_METHOD, "frequency": "Cron", "cron_format": "*/15 * * * *", "stopped": 0, "server_script": None, "last_execution": "2026-10-06 08:00:00"}
		definition = {"source": {"doctype": "Scheduled Job Type", "method": module.OPERATING_METHOD}, "native": {"Scheduled Job Type": [self.module().semantic_row(dict(row, last_execution=None))]}}
		scope = {"Scheduled Job Type": [row]}
		original = copy.deepcopy(scope)
		self.assertTrue(module._definition_matches(scope, module.OPERATING_METHOD, definition))
		self.assertEqual(scope, original)
		for flag in ("stopped", "server_script", "frequency", "cron_format"):
			with self.subTest(flag=flag), self.assertRaises(AssertionError):
				module._definition_matches({"Scheduled Job Type": [dict(row, **{flag: "unapproved"})]}, module.OPERATING_METHOD, definition)

	def test_existing_dedicated_source_logging_flags_are_preserved_without_rewriting_jobs(self):
		module = self.metadata_module()
		for method in module.SCHEDULED_METHODS:
			for logging in (0, 1):
				with self.subTest(method=method, create_log=logging):
					row = {"name": "original-job-id", "method": method, "frequency": "Cron", "cron_format": "*/15 * * * *", "stopped": 0, "server_script": None, "create_log": logging, "last_execution": "2026-10-07 08:45:03.082272", "creation": "original", "modified": "original"}
					definition = {"source": {"doctype": "Scheduled Job Type", "method": method}, "native": {"Scheduled Job Type": [self.module().semantic_row(dict(row, create_log=0, last_execution=None))]}}
					scope = {"Scheduled Job Type": [row]}
					original = copy.deepcopy(scope)
					self.assertTrue(module._definition_matches(scope, method, definition))
					self.assertEqual(scope, original)
					for flag in ("stopped", "server_script", "frequency", "cron_format"):
						with self.subTest(flag=flag), self.assertRaises(AssertionError):
							module._definition_matches({"Scheduled Job Type": [dict(row, **{flag: "unapproved"})]}, method, definition)

	def test_scheduled_logging_compatibility_rejects_invalid_flags_and_explicit_policy_changes(self):
		module = self.metadata_module()
		for method in module.SCHEDULED_METHODS:
			row = {"name": "original-job-id", "method": method, "frequency": "Cron", "cron_format": "*/15 * * * *", "create_log": 0}
			definition = {"source": {"doctype": "Scheduled Job Type", "method": method}, "native": {"Scheduled Job Type": [self.module().semantic_row(row)]}}
			for invalid in (None, -1, 2, "1", True, False, 0.0, 1.0):
				with self.subTest(method=method, create_log=invalid), self.assertRaises(AssertionError):
					module._definition_matches({"Scheduled Job Type": [dict(row, create_log=invalid)]}, method, definition)
			for required in (0, 1):
				with self.subTest(method=method, explicit=required):
					policy = copy.deepcopy(definition)
					policy["source"]["create_log"] = required
					policy["native"]["Scheduled Job Type"][0]["create_log"] = required
					self.assertTrue(module._definition_matches({"Scheduled Job Type": [dict(row, create_log=required)]}, method, policy))
					with self.assertRaises(AssertionError):
						module._definition_matches({"Scheduled Job Type": [dict(row, create_log=1-required)]}, method, policy)

	def test_oa_ddl_guard_allows_exact_role_native_types_defaults_and_full_unique_identity(self):
		module = self.metadata_module()
		self.assertTrue(hasattr(module, "_validate_oa_ddl"))
		fields = self.source_fields(module)
		for name, field in fields.items():
			kind = {"Data": "varchar(140)", "Link": "varchar(140)", "Long Text": "longtext", "Small Text": "text", "Check": "tinyint(4) NOT NULL DEFAULT 0", "Datetime": "datetime(6)"}[field["fieldtype"]]
			module._validate_oa_ddl(f"ALTER TABLE `tabOA Purchase Request` ADD COLUMN `{name}` {kind}", set(fields), fields)
		module._validate_oa_ddl("ALTER TABLE `tabOA Purchase Request` ADD UNIQUE INDEX IF NOT EXISTS custom_purchase_source_id (`custom_purchase_source_id`)", set(fields), fields)
		for sql in ("ALTER TABLE `tabPurchase Order` ADD COLUMN `custom_purchase_source_id` varchar(140)", "ALTER TABLE `tabOA Purchase Request` MODIFY COLUMN `currency` varchar(140)", "ALTER TABLE `tabOA Purchase Request` ADD COLUMN `custom_purchase_source_json` varchar(140)", "ALTER TABLE `tabOA Purchase Request` ADD COLUMN `custom_purchase_source_id` varchar(140) NOT NULL", "ALTER TABLE `tabOA Purchase Request` ADD UNIQUE INDEX IF NOT EXISTS custom_purchase_source_id (`custom_purchase_source_id`(40))"):
			with self.subTest(sql=sql), self.assertRaises(AssertionError): module._validate_oa_ddl(sql, set(fields), fields)
		for kind in ("tinyint", "tinyint NOT NULL DEFAULT 0", "tinyint(1) NOT NULL DEFAULT 0", "tinyint(4) NOT NULL DEFAULT 1", "varchar(140)", "tinyint(4) NOT NULL DEFAULT 0 UNIQUE"):
			with self.subTest(kind=kind), self.assertRaises(AssertionError):
				module._validate_oa_ddl("ALTER TABLE `tabOA Purchase Request` ADD COLUMN `custom_purchase_company_confirmed` " + kind, set(fields), fields)

	def test_pending_oa_schema_intent_accepts_only_exact_recorded_before_or_after(self):
		module = self.metadata_module()
		for state in ("before", "after", "foreign"):
			with self.subTest(state=state), tempfile.TemporaryDirectory() as directory:
				before = {"metadata": {"scope": {}}, "je": {"schema": self.schema()}, "models": {}, "oa": {"schema": self.schema()}}
				after_schema = copy.deepcopy(before["oa"]["schema"])
				after_schema["columns"]["custom_purchase_source_json"] = {"type": "longtext"}
				receipt = self.module().DDLReceipt.create(Path(directory) / "receipt.json", {"candidate_sha": "a" * 40, "contract_sha256": "b" * 64}, before, {})
				receipt.plan("oa-column", before["oa"]["schema"], after_schema, kind="ddl", doctype="OA Purchase Request")
				current = copy.deepcopy(before)
				if state != "before": current["oa"]["schema"] = copy.deepcopy(after_schema)
				if state == "foreign": current["oa"]["schema"]["columns"]["unapproved"] = {}
				if state == "foreign":
					with self.assertRaises(AssertionError): module._assert_recorded_rollback_state(receipt, current)
				else: module._assert_recorded_rollback_state(receipt, current)

	def source_fields(self, module):
		with patch.dict(sys.modules, {"frappe": types.SimpleNamespace(get_app_path=lambda app, filename: str(ROOT / app / filename))}):
			return module._source_custom_fields()

	def test_source_schema_additions_keep_check_zero_datetime_and_nullable_links(self):
		module = self.metadata_module()
		self.assertTrue(hasattr(module, "_source_schema_additions"))
		before = {"schema": self.schema()}
		fields = self.source_fields(module)
		additions = module._source_schema_additions(before, fields)
		self.assertEqual(set(additions["columns"]), set(fields))
		self.assertEqual(set(additions["indexes"]), {"custom_purchase_source_id"})
		for name, definition in additions["columns"].items():
			kind = fields[name]["fieldtype"]
			self.assertEqual(definition["type"], {"Data": "varchar(140)", "Link": "varchar(140)", "Long Text": "longtext", "Small Text": "text", "Check": "tinyint(4)", "Datetime": "datetime(6)"}[kind])
			self.assertEqual((definition["nullable"], definition["default_value"]), ("NO", "0") if kind == "Check" else ("YES", "NULL"))
			if kind in {"Check", "Datetime"}:
				self.assertIsNone(definition["charset"])
				self.assertIsNone(definition["collation"])
		index = additions["indexes"]["custom_purchase_source_id"]
		self.assertEqual((len(index), index[0]["unique"], index[0]["prefix"]), (1, 1, None))
		after = copy.deepcopy(before)
		for kind in additions: after["schema"][kind].update(additions[kind])
		self.assertEqual(module._source_schema_additions(after, fields), {"columns": {}, "indexes": {}})

	def test_original_oa_projection_is_held_in_snapshot_after_new_null_columns(self):
		queries = []
		fake = types.SimpleNamespace(db=types.SimpleNamespace(sql=lambda query, **kw: queries.append(query) or ([{"name": "OA-old", "manual": "keep"}] if "tabOA Purchase Request`" in query else [])))
		with patch.dict(sys.modules, {"frappe": fake}):
			spec = importlib.util.spec_from_file_location("audit", ROOT / "deploy/production/audit_unified_purchase.py")
			audit = importlib.util.module_from_spec(spec)
			spec.loader.exec_module(audit)
		module = self.metadata_module()
		schema = self.schema()
		with patch.dict(sys.modules, {"procurement_release_metadata": module}), patch.object(audit, "table_schema", side_effect=lambda dt: schema if dt in {"Journal Entry", "OA Purchase Request"} else None), patch.object(audit, "capture_audit", return_value={}), patch.object(module, "capture_joint_metadata", return_value={}), patch.object(module, "_native_reversal_contract", return_value={"tables": []}):
			state = audit.capture_joint_state(original_columns=["name"], original_oa_columns=["name", "manual"])
		self.assertEqual(state["oa"]["original_columns"], ["name", "manual"])
		self.assertEqual(state["oa"]["rows"], [{"name": "OA-old", "manual": "keep"}])
		self.assertIn("select `name`,`manual` from `tabOA Purchase Request` order by name", queries)

	def test_oa_guard_preserves_original_rows_and_refuses_non_null_new_fields(self):
		module = self.metadata_module()
		receipt, current = self.invariant_fixture(module)
		fields = self.source_fields(module)
		before_oa = {"schema": self.schema(), "rows": [{"name": "OA-old", "manual": "keep"}], "original_columns": ["name", "manual"]}
		receipt.state["before"]["oa"] = before_oa
		receipt.state["contract"]["source_custom_fields"] = fields
		current["oa"] = copy.deepcopy(before_oa)
		for kind, values in module._source_schema_additions(before_oa, fields).items(): current["oa"]["schema"][kind].update(values)
		receipt.state["steps"] = [{"id": "recorded-oa-schema", "kind": "ddl", "doctype": module.OA_DOCTYPE,
			"status": "complete", "before": before_oa["schema"], "expected_after": current["oa"]["schema"]}]
		for snapshot in (receipt.state["before"], current): snapshot["audit"]["schemas"]["OA Purchase Request"] = snapshot["oa"]["schema"]
		self.assert_invariants(module, receipt, current)
		current["oa"]["rows"][0]["manual"] = "changed"
		with self.assertRaises(AssertionError): self.assert_invariants(module, receipt, current)
		current["oa"]["rows"][0]["manual"] = "keep"
		with patch.dict(sys.modules, {"frappe": types.SimpleNamespace(db=types.SimpleNamespace(sql=lambda *a, **kw: [[1]]))}), self.assertRaisesRegex(AssertionError, "non-NULL"):
			module._assert_joint_invariants(receipt, current)

	def test_common_invariant_rejects_even_approved_schema_changes_without_exact_latest_intent(self):
		module = self.metadata_module()
		fields = self.source_fields(module)
		for scenario in ("oa_without_intent", "oa_pending_extra", "oa_completed_missing", "je_without_intent"):
			with self.subTest(scenario=scenario):
				receipt, current = self.invariant_fixture(module)
				receipt.state.update(status="applying", steps=[])
				if scenario == "je_without_intent":
					key = module.CUSTOM_FIELD_ORDER[-1]
					receipt.state["before"]["je"]["schema"]["columns"].pop(key)
				else:
					original = {"schema": self.schema(), "rows": [], "original_columns": ["name"]}
					for key in module.SOURCE_FIELD_ORDER[:5]:
						original["schema"]["columns"][key] = module._source_column(fields[key], len(original["schema"]["columns"]))
					original["schema"]["indexes"]["custom_purchase_source_id"] = module._source_index()
					receipt.state["before"]["oa"] = original
					receipt.state["contract"]["source_custom_fields"] = fields
					current["oa"] = copy.deepcopy(original)
					first, second = module.SOURCE_FIELD_ORDER[5:7]
					expected = copy.deepcopy(original["schema"])
					expected["columns"][first] = module._source_column(fields[first], len(expected["columns"]))
					if scenario != "oa_completed_missing": current["oa"]["schema"] = copy.deepcopy(expected)
					if scenario == "oa_pending_extra":
						current["oa"]["schema"]["columns"][second] = module._source_column(fields[second], len(expected["columns"]))
					if scenario != "oa_without_intent":
						receipt.state["steps"] = [{"id": "first-role", "kind": "ddl", "doctype": module.OA_DOCTYPE,
							"status": "pending" if scenario == "oa_pending_extra" else "complete",
							"before": original["schema"], "expected_after": expected}]
					for snapshot in (receipt.state["before"], current):
						snapshot["audit"]["schemas"][module.OA_DOCTYPE] = snapshot["oa"]["schema"]
				with self.assertRaisesRegex(AssertionError, "schema.*intent"):
					self.assert_invariants(module, receipt, current)

	def test_enabled_source_sync_requires_recorded_quiescence_and_unchanged_flag(self):
		module = self.metadata_module()
		receipt, current = self.invariant_fixture(module)
		current["audit"]["purchase_source_sync_enabled"] = True
		receipt.state["before"]["audit"]["purchase_source_sync_enabled"] = True
		with self.assertRaisesRegex(AssertionError, "sync|quiescence"):
			self.assert_invariants(module, receipt, current)
		for audit in (receipt.state["before"]["audit"], current["audit"]):
			audit.update(maintenance_mode=1, release_quiescent=True)
		self.assert_invariants(module, receipt, current)
		for drift in ("flag", "maintenance", "quiescence"):
			with self.subTest(drift=drift):
				changed = copy.deepcopy(current)
				changed["audit"][{"flag": "purchase_source_sync_enabled", "maintenance": "maintenance_mode", "quiescence": "release_quiescent"}[drift]] = False
				with self.assertRaises(AssertionError): self.assert_invariants(module, receipt, changed)

	def native_oa_boundary(self, module, path, *, crash=None):
		"""Real apply/receipt/rollback guards, with only native IO/DDL substituted."""
		receipt, current = self.invariant_fixture(module)
		fields = self.source_fields(module)
		current["oa"] = {"schema": self.schema(), "rows": [{"name": "OA-old", "manual": "keep"}], "original_columns": ["name", "manual"]}
		current["oa"]["schema"]["columns"]["manual"] = module._je_column(1)
		current["audit"]["schemas"]["OA Purchase Request"] = current["oa"]["schema"]
		current["audit"]["preserved_apps"] = {"china_finance": "finance", "crm_integration": "crm"}
		current["audit"]["tables"]["Journal Entry"] = module.digest(current["je"]["rows"])
		current["audit"]["purchase_source_sync_enabled"] = False
		current["audit"]["oa_new_columns"] = {}
		for name in module.JOINT_MODELS:
			current["models"].setdefault(name, {"schema": None, "rows": []})
		current["audit"]["operating_models"] = {name: {"schema": model["schema"], "rows": module.digest(model["rows"])} for name, model in current["models"].items()}
		before = copy.deepcopy(current)
		contract = dict(receipt.state["contract"], custom_fields={}, source_custom_fields=fields, model_schemas={name: model["schema"] for name, model in current["models"].items()})
		plan = {"scope": copy.deepcopy(current["metadata"]["scope"]), "new_definitions": [], "page_title_updates": []}
		plan["scope"]["Custom Field"] = [dict(field, name="OA Purchase Request-" + key, dt="OA Purchase Request") for key, field in fields.items()]
		plan["scope"]["Scheduled Job Type"] = [{"name": "preserved-operating-job", "method": module.OPERATING_METHOD}, {"name": module.PURCHASE_SOURCE_METHOD, "method": module.PURCHASE_SOURCE_METHOD}]
		before["metadata"]["scope"]["Scheduled Job Type"] = [plan["scope"]["Scheduled Job Type"][0]]
		current["metadata"]["scope"]["Scheduled Job Type"] = copy.deepcopy(before["metadata"]["scope"]["Scheduled Job Type"])
		events, control = [], {"crash": crash, "added": 0, "nonnull": False}
		class Field(dict):
			def __getattr__(self, name):
				try:
					return self[name]
				except KeyError:
					raise AttributeError(name) from None
			__setattr__ = dict.__setitem__
		meta = types.SimpleNamespace(fields=[Field(field) for field in fields.values()])
		def schema(name): return copy.deepcopy(current["oa"]["schema"] if name == "OA Purchase Request" else current["je"]["schema"])
		def native_sql(name, wanted):
			if name != "OA Purchase Request": return []
			result = []
			for field in wanted.fields:
				if field.fieldname not in current["oa"]["schema"]["columns"]:
					kind = {"Data": "varchar(140)", "Link": "varchar(140)", "Long Text": "longtext", "Small Text": "text", "Check": "tinyint(4) NOT NULL DEFAULT 0", "Datetime": "datetime(6)"}[field.fieldtype]
					result.append(f"ALTER TABLE `tabOA Purchase Request` ADD COLUMN `{field.fieldname}` {kind}")
			if any(field.fieldname == "custom_purchase_source_id" and field.get("unique") for field in wanted.fields) and "custom_purchase_source_id" not in current["oa"]["schema"]["indexes"]:
				result.append("ALTER TABLE `tabOA Purchase Request` ADD UNIQUE INDEX IF NOT EXISTS custom_purchase_source_id (`custom_purchase_source_id`)")
			return result
		def ddl(query, **kwargs):
			stored = self.module().DDLReceipt.load(path)
			self.assertEqual(stored.state["steps"][-1]["status"], "pending")
			self.assertEqual(stored.state["steps"][-1]["sql"], query)
			events.append(query)
			columns, indexes = current["oa"]["schema"]["columns"], current["oa"]["schema"]["indexes"]
			if " ADD COLUMN " in query:
				key = query.split(" ADD COLUMN `")[1].split("`")[0]
				columns[key] = module._source_column(fields[key], len(columns))
			elif " ADD UNIQUE INDEX " in query: indexes["custom_purchase_source_id"] = module._source_index()
			elif " DROP COLUMN " in query:
				key = query.rsplit("`", 2)[1]
				self.assertEqual(columns[key]["position"], max(value.get("position", 0) for value in columns.values()), "Reverse native append order prevents ordinal drift")
				columns.pop(key)
				if key == "custom_purchase_source_id": indexes.pop(key, None)
			else: self.fail("DDL escaped narrow OA scope: " + query)
			if " ADD " in query:
				control["added"] += 1
				if control["crash"] == control["added"]: raise RuntimeError("crash after native autocommit")
		def write_scope(old, wanted): current["metadata"]["scope"] = copy.deepcopy(wanted)
		fake = types.SimpleNamespace(conf=types.SimpleNamespace(maintenance_mode=1), get_meta=lambda name, **kw: meta if name == "OA Purchase Request" else types.SimpleNamespace(fields=[]), clear_cache=lambda **kw: None, scrub=lambda name: name.lower().replace(" ", "_"))
		fake.db = types.SimpleNamespace(sql=lambda *a, **kw: [[int(control["nonnull"])]], commit=lambda: events.append("commit"), rollback=lambda: None, sql_ddl=ddl)
		fake.db.updatedb = lambda name, wanted: [fake.db.sql_ddl(query) for query in native_sql(name, wanted)]
		def capture_state(**kwargs):
			current["audit"]["oa_new_columns"] = {key: int(control["nonnull"]) for key in current["oa"]["schema"]["columns"] if key not in before["oa"]["schema"]["columns"]}
			return copy.deepcopy(current)
		audit = types.SimpleNamespace(capture_joint_state=capture_state, table_schema=schema)
		stack = __import__("contextlib").ExitStack()
		self.addCleanup(stack.close)
		stack.enter_context(patch.dict(sys.modules, {"frappe": fake, "frappe.model.meta": types.SimpleNamespace(Meta=object), "frappe.utils": types.SimpleNamespace(now_datetime=lambda: "2026-10-06"), "audit_unified_purchase": audit}))
		stack.enter_context(patch.object(sys.modules["joint_release_guards"], "verified_quiescence", return_value=True))
		stack.enter_context(patch.object(module, "load_joint_contract", side_effect=lambda: copy.deepcopy(contract)))
		stack.enter_context(patch.object(module, "_joint_plan", return_value=plan))
		stack.enter_context(patch.object(module, "_native_schema_sql", side_effect=native_sql))
		stack.enter_context(patch.object(module, "_write_scope", side_effect=write_scope))
		stack.enter_context(patch.object(module, "capture_joint_metadata", side_effect=lambda **kw: copy.deepcopy(current["metadata"])))
		stack.enter_context(patch.object(module, "_desired_navigation", side_effect=lambda scope, **kw: scope))
		return before, current, events, control

	def test_contract_oa_column_intents_and_unique_index_are_durable_and_second_apply_is_idle(self):
		module = self.metadata_module()
		with tempfile.TemporaryDirectory() as directory:
			path = Path(directory) / "receipt.json"
			before, current, events, _ = self.native_oa_boundary(module, path)
			result = module.apply_joint_metadata("a" * 40, path)
			self.assertEqual(result["ddl_boundaries"], len(module.SOURCE_FIELD_ORDER) + 1)
			self.assertEqual(current["models"], before["models"])
			self.assertEqual(current["operating_singles"], before["operating_singles"])
			first = path.read_bytes(); events.clear()
			self.assertTrue(module.apply_joint_metadata("a" * 40, path)["unchanged"])
			self.assertEqual(events, [])
			self.assertEqual(path.read_bytes(), first)
			self.assertTrue(module.restore_joint_metadata(path)["restored"])
			self.assertEqual(current, before)

	def test_each_interrupted_oa_autocommit_rolls_back_only_new_null_columns_and_job(self):
		for crash in range(1, len(self.metadata_module().SOURCE_FIELD_ORDER) + 2):
			with self.subTest(crash=crash), tempfile.TemporaryDirectory() as directory:
				module = self.metadata_module()
				path = Path(directory) / "receipt.json"
				before, current, events, control = self.native_oa_boundary(module, path, crash=crash)
				with self.assertRaisesRegex(RuntimeError, "autocommit"): module.apply_joint_metadata("a" * 40, path)
				self.assertEqual(self.module().DDLReceipt.load(path).state["steps"][-1]["status"], "pending")
				control["crash"] = None
				self.assertTrue(module.restore_joint_metadata(path, candidate_sha="a" * 40)["restored"])
				self.assertEqual(current, before)

	def test_fulfilment_index_contract_is_exact_and_pending_receipt_rejects_extra_indexes(self):
		module = self.metadata_module()
		self.assertIn("Purchase Fulfilment Link", module.JOINT_MODELS)
		schema = self.schema()
		schema["columns"].update(external_order=module._je_column(1), internal_order=module._je_column(2), active={"nullable": "NO"})
		indexes = module._fulfilment_indexes(schema)
		self.assertEqual(set(indexes), {"fulfilment_external_active", "fulfilment_internal_active"})
		self.assertEqual([row["column"] for row in indexes["fulfilment_external_active"]], ["external_order", "active"])
		self.assertEqual([row["nullable"] for row in indexes["fulfilment_external_active"]], ["YES", ""])
		for rows in indexes.values(): self.assertTrue(all(row["unique"] == 0 and row["prefix"] is None for row in rows))
		with tempfile.TemporaryDirectory() as directory:
			before = {"metadata": {"scope": {}}, "je": {"schema": self.schema()}, "models": {"Purchase Fulfilment Link": {"schema": None}}}
			receipt = self.module().DDLReceipt.create(Path(directory) / "receipt.json", {"candidate_sha": "a" * 40, "contract_sha256": "b" * 64}, before, {})
			receipt.plan("model-create", None, schema, kind="ddl", doctype="Purchase Fulfilment Link")
			receipt.complete("model-create", schema)
			indexed = copy.deepcopy(schema)
			indexed["indexes"]["fulfilment_external_active"] = indexes["fulfilment_external_active"]
			receipt.plan("model-index", schema, indexed, kind="ddl", doctype="Purchase Fulfilment Link")
			for actual in (schema, indexed):
				current = copy.deepcopy(before); current["models"]["Purchase Fulfilment Link"]["schema"] = actual
				module._assert_recorded_rollback_state(receipt, current)
			current["models"]["Purchase Fulfilment Link"]["schema"] = copy.deepcopy(indexed)
			current["models"]["Purchase Fulfilment Link"]["schema"]["indexes"]["unapproved"] = []
			with self.assertRaises(AssertionError): module._assert_recorded_rollback_state(receipt, current)

	def test_full_joint_final_gate_allows_only_receipted_oa_schema_with_old_rows_and_outside_metadata(self):
		module = self.metadata_module()
		with tempfile.TemporaryDirectory() as directory:
			path = Path(directory) / "receipt.json"
			before, current, _, _ = self.native_oa_boundary(module, path)
			module.apply_joint_metadata("a" * 40, path)
			receipt = self.module().DDLReceipt.load(path).state
			old, new = copy.deepcopy(before["audit"]), copy.deepcopy(current["audit"])
			old.update(joint_metadata=before["metadata"], approved_sources_after=receipt["contract"]["sources_after"])
			new["joint_metadata"] = copy.deepcopy(current["metadata"])
			module.verify_joint_audit_delta(old, new, receipt)

	def test_final_gate_rejects_raw_active_data_and_fresh_outside_or_original_oa_drift(self):
		module = self.metadata_module()
		with tempfile.TemporaryDirectory() as directory:
			path = Path(directory) / "receipt.json"
			before, current, _, _ = self.native_oa_boundary(module, path)
			module.apply_joint_metadata("a" * 40, path)
			receipt = self.module().DDLReceipt.load(path).state
			old, new = copy.deepcopy(before["audit"]), copy.deepcopy(current["audit"])
			old.update(joint_metadata=before["metadata"], approved_sources_after=receipt["contract"]["sources_after"])
			new["joint_metadata"] = copy.deepcopy(current["metadata"])
			for drift in ("oa-row", "oa-hash", "oa-new-nonnull", "oa-column", "oa-index", "operating-row", "operating-hash", "operating-single", "outside-po-data", "sync"):
				with self.subTest(drift=drift):
					bad, native = copy.deepcopy(new), copy.deepcopy(receipt)
					if drift == "oa-row": native["after"]["oa"]["rows"][0]["manual"] = "changed"
					elif drift == "oa-hash": bad["tables"]["OA Purchase Request"] = module.digest([])
					elif drift == "oa-new-nonnull": bad["oa_new_columns"]["custom_purchase_source_json"] = 1
					elif drift in {"oa-column", "oa-index"}:
						kind, key = ("columns", "currency") if drift == "oa-column" else ("indexes", "custom_purchase_source_id")
						value = {} if drift == "oa-column" else [dict(module._source_index()[0], prefix=40)]
						bad["schemas"][module.OA_DOCTYPE][kind][key] = value
						native["after"]["oa"]["schema"][kind][key] = value
					elif drift == "operating-row": native["after"]["models"]["Operating Expense Source"]["rows"][-1]["original_evidence"] = '{"manual":1}'
					elif drift == "operating-hash": bad["operating_models"]["Operating Expense Source"]["rows"] = module.digest([])
					elif drift == "operating-single": native["after"]["operating_singles"][0]["value"] = "1"
					elif drift == "outside-po-data":
						bad["joint_metadata"]["outside_rows"]["Custom Field"][0]["fieldtype"] = "Link"
						native["after"]["metadata"] = copy.deepcopy(bad["joint_metadata"])
					else: bad["purchase_source_sync_enabled"] = True
					with self.assertRaises(AssertionError): module.verify_joint_audit_delta(copy.deepcopy(old), bad, native)

	def test_rollback_refuses_new_nonnull_oa_evidence_before_any_destructive_ddl(self):
		module = self.metadata_module()
		with tempfile.TemporaryDirectory() as directory:
			path = Path(directory) / "receipt.json"
			_, _, events, control = self.native_oa_boundary(module, path, crash=1)
			with self.assertRaises(RuntimeError): module.apply_joint_metadata("a" * 40, path)
			control.update(crash=None, nonnull=True)
			events.clear()
			with self.assertRaisesRegex(AssertionError, "non-NULL"): module.restore_joint_metadata(path)
			self.assertEqual(events, [])


class CombinedReleaseContractTests(unittest.TestCase):
	module = JointReleaseGuardTests.module
	metadata_module = JointReleaseGuardTests.metadata_module
	def test_native_only_scope_keeps_optional_metadata_and_old_jobs_outside(self):
		module = self.metadata_module()
		import inspect
		self.assertIn("native_only", inspect.signature(module.capture_joint_metadata).parameters)
		fake = types.SimpleNamespace(get_app_path=lambda app, name: str(ROOT / app / name), get_meta=lambda dt, **kw: types.SimpleNamespace(fields=[]))
		with patch.dict(sys.modules, {"frappe": fake}):
			native = module._native_reversal_contract()
		rows = {dt: [] for dt in ("DocType", "Custom Field", "Page", "Workspace", "Workspace Sidebar", "Scheduled Job Type", "Property Setter", "Custom DocPerm")}
		rows["Custom Field"] = [{"name": dt + "-" + native["fieldname"], "dt": dt, "fieldname": native["fieldname"]} for dt in native["targets"]] + [{"name": "Journal Entry-" + module.CUSTOM_FIELD_ORDER[0], "dt": "Journal Entry", "fieldname": module.CUSTOM_FIELD_ORDER[0]}]
		rows["DocType"] = [{"name": name} for name in module.JOINT_MODELS]
		rows["Workspace"] = [{"name": "Buying", "custom": "原始字节"}]
		rows["Scheduled Job Type"] = [{"name": "native-" + str(i), "method": method} for i, method in enumerate(module.SCHEDULED_METHODS)]
		with patch.dict(sys.modules, {"frappe": fake}), patch.object(module, "_rows", side_effect=lambda dt: copy.deepcopy(rows[dt])):
			result = module.capture_joint_metadata(native_only=True)
		self.assertEqual(len(result["scope"]["Custom Field"]), 6)
		self.assertEqual(result["scope"]["Scheduled Job Type"], [rows["Scheduled Job Type"][-1]])
		for dt in ("DocType", "Page", "Workspace", "Workspace Sidebar"):
			self.assertEqual(result["scope"][dt], [])
			self.assertEqual(result["outside_rows"][dt], rows[dt])
		self.assertEqual(result["outside_rows"]["Scheduled Job Type"], rows["Scheduled Job Type"][:2])
		before = {"metadata": {"scope": {dt: [] for dt in rows}}, "je": {"schema": {"columns": {}, "indexes": {}}}, "models": {}, "operating_singles": []}
		definitions = {row["name"]: {"source": dict(row, doctype="Custom Field"), "native": {"Custom Field": [row]}} for row in rows["Custom Field"][:6]}
		contract = {"native_only": True, "native_reversal": native, "definitions": definitions, "custom_fields": {}, "model_schemas": {}, "native_metadata_schemas": {"DocField": {"columns": {}}}}
		fake.db = types.SimpleNamespace(sql=lambda *a, **kw: [], exists=lambda *a: True)
		with patch.dict(sys.modules, {"frappe": fake, "frappe.model.meta": types.SimpleNamespace(Meta=object), "audit_unified_purchase": types.SimpleNamespace(table_schema=None)}), patch.object(module, "_native_rows", side_effect=lambda source, **kw: {"Custom Field": [{k: v for k, v in source.items() if k != "doctype"}]}), patch.object(module, "_native_reversal_plan", return_value={}), patch.object(module, "_desired_navigation", side_effect=AssertionError("Native-only touched navigation")):
			plan = module._joint_plan(before, contract, when="frozen", seed="frozen", require_quiescent=False)
		self.assertEqual([row["name"] for row in plan["scope"]["Custom Field"]], sorted(definitions))

	def test_native_only_rollback_uses_shared_first_writer_marker(self):
		module, guard = self.metadata_module(), self.module()
		fake = types.SimpleNamespace(conf=types.SimpleNamespace(maintenance_mode=1))
		with tempfile.TemporaryDirectory() as directory:
			shared = Path(directory) / "main.resume.json"
			guard.record_resume(shared, {"candidate_sha": "a" * 40, "image_id": "sha256:" + "b" * 64}, "candidate-serving")
			with patch.dict(sys.modules, {"frappe": fake, "audit_unified_purchase": types.SimpleNamespace(table_schema=None)}), patch.dict(os.environ, {"DEEPLINKERP_RELEASE_RESUME_RECEIPT": str(shared)}), patch("joint_release_guards.verified_quiescence", return_value=True), patch("joint_release_guards.DDLReceipt.load", side_effect=AssertionError("Secondary receipt was loaded before the shared marker gate")):
				with self.assertRaisesRegex(AssertionError, "forward|HOLD"):
					module.restore_joint_metadata(Path(directory) / "secondary.json")

	def test_twelfth_source_field_reuses_visible_readonly_native_text(self):
		module = self.metadata_module()
		fake = types.SimpleNamespace(get_app_path=lambda app, name: str(ROOT / app / name))
		with patch.dict(sys.modules, {"frappe": fake}):
			fields = module._source_custom_fields()
		self.assertEqual(len(fields), 12)
		field = fields["custom_purchase_pending_reason"]
		self.assertEqual((field["fieldtype"], field.get("hidden", 0), field["read_only"], field["no_copy"], field.get("permlevel", 0)), ("Small Text", 0, 1, 1, 0))
		self.assertEqual(module._source_column(field, 20)["type"], "text")
		module._validate_oa_ddl("ALTER TABLE `tabOA Purchase Request` ADD COLUMN `custom_purchase_pending_reason` text", {field["fieldname"]}, fields)

	def test_native_reversal_contract_is_separate_from_drop_table_models(self):
		module = self.metadata_module()
		self.assertTrue(hasattr(module, "_native_reversal_contract"), "Native contract must reuse the existing installer")
		fake = types.SimpleNamespace(get_app_path=lambda app, name: str(ROOT / app / name))
		with patch.dict(sys.modules, {"frappe": fake}):
			contract = module._native_reversal_contract()
		self.assertEqual(set(contract["tables"]), {"Bin", "Purchase Order", "Purchase Receipt", "Purchase Invoice", "Payment Entry", "Repost Item Valuation", "Integration Request"})
		self.assertFalse(set(contract["tables"]) & set(module.JOINT_MODELS))
		self.assertEqual(contract["definition"]["options"], "Integration Request")
		self.assertEqual(contract["activity_index_columns"], ["integration_request_service", contract["activity_column"], "name"])
		self.assertIn("'Completed'", contract["activity_expression"])
		self.assertEqual(contract["recover_method"], module.REVERSAL_METHOD)

	def test_first_resume_marker_is_durable_idempotent_and_blocks_rollback(self):
		guard = self.module()
		self.assertTrue(hasattr(guard, "assert_pre_resume"), "Pre-resume rollback guard required")
		with tempfile.TemporaryDirectory() as directory:
			path = Path(directory) / "resume.json"
			guard.assert_pre_resume(path)
			with patch.object(guard.DDLReceipt, "_sync_directory", wraps=guard.DDLReceipt._sync_directory) as sync:
				guard.record_resume(path, {"candidate_sha": "a" * 40, "image_id": "sha256:" + "b" * 64}, "candidate-web")
				sync.assert_called_once_with(path.parent)
			first = path.read_bytes()
			guard.record_resume(path, {"candidate_sha": "a" * 40, "image_id": "sha256:" + "b" * 64}, "candidate-web")
			self.assertEqual(path.read_bytes(), first)
			for corrupt in (False, True):
				with self.subTest(corrupt=corrupt):
					if corrupt: path.write_text("broken")
					with self.assertRaisesRegex(AssertionError, "forward|HOLD"):
						guard.assert_pre_resume(path)

	def test_budget_uses_actual_same_filesystem_sum_and_refuses_unknown(self):
		guard = self.module()
		self.assertTrue(hasattr(guard, "filesystem_budget"), "Actual filesystem budget required")
		with tempfile.TemporaryDirectory() as directory:
			path = Path(directory)
			with patch.object(guard.os, "statvfs", return_value=types.SimpleNamespace(f_bavail=10, f_frsize=10)):
				self.assertEqual(guard.filesystem_budget({"extract": (path, 20), "build": (path, 30)}, reserve_bytes=10)[0]["required_bytes"], 60)
				with self.assertRaisesRegex(AssertionError, "space"):
					guard.filesystem_budget({"extract": (path, 60), "backup": (path, 50)}, reserve_bytes=0)
			for amount in (None, 0, -1):
				with self.subTest(amount=amount), self.assertRaises(AssertionError):
					guard.filesystem_budget({"backup": (path, amount)})

	def test_raw_rq_snapshot_preserves_queue_order_without_native_cleanup_calls(self):
		guard = self.module()
		self.assertTrue(hasattr(guard, "raw_rq_snapshot"), "Read-only raw RQ inventory required")
		class Redis:
			worker = None
			def scan(self, cursor, **kwargs): return 0, [b"rq:queues", b"rq:workers", b"rq:queue:bench:short", b"rq:job:queued"] + ([b"rq:worker:old"] if self.worker is not None else [])
			def type(self, key): return b"set" if key in {"rq:queues", "rq:workers"} else b"list" if key == "rq:queue:bench:short" else b"hash" if key == "rq:job:queued" or key == "rq:worker:old" and self.worker is not None else b"none"
			def scard(self, key): return len(self.smembers(key))
			def smembers(self, key): return {b"rq:queue:bench:short"} if key == "rq:queues" else set()
			def llen(self, key): return 2 if key == "rq:queue:bench:short" else 0
			def lrange(self, key, *args): return [b"queued", b"queued"] if key == "rq:queue:bench:short" else []
			def zcard(self, key): return 0
			def zrange(self, key, *args, **kwargs): return []
			def hlen(self, key): return 4
			def hstrlen(self, key, field): return 4
			def hmget(self, key, fields): return [{"status": b"queued", "origin": b"bench:short"}.get(field) for field in fields]
			def hexists(self, key, field): return True
			def hkeys(self, key): return list(self.worker)
			def hgetall(self, key): return self.worker
		snapshot = guard.raw_rq_snapshot(Redis())
		self.assertEqual(snapshot["queues"]["bench:short"], ["queued", "queued"])
		self.assertEqual(snapshot["workers"], {})
		self.assertEqual(snapshot["jobs"]["queued"]["status"], "queued")
		redis = Redis()
		redis.worker = dict(pid="1", hostname="native", birth="2026-10-09T00:00:00Z", state="idle", queues="bench:short")
		with self.assertRaisesRegex(AssertionError, "Orphan/stale"):
			guard.raw_rq_snapshot(redis)
		redis.worker["death"] = "2026-10-09T00:01:00Z"
		after = guard.raw_rq_snapshot(redis)
		before = copy.deepcopy(snapshot)
		before["workers"] = {"rq:worker:old": {key: value for key, value in redis.worker.items() if key != "death"}}
		guard.verify_rq_drain(before, after, {})
		after["tombstones"]["rq:worker:old"]["birth"] = "old-unmatched"
		with self.assertRaisesRegex(AssertionError, "identity"):
			guard.verify_rq_drain(before, after, {})

	def test_owned_build_cleanup_rejects_drift_shared_mount_or_asset_without_deleting(self):
		guard = self.module()
		for scenario in ("exact", "extra-file", "changed-file", "extra-directory", "hardlink", "special", "shared-mount", "asset-url", "asset-origin", "asset-body", "redis-pre", "redis-post", "post-health"):
			with self.subTest(scenario=scenario), tempfile.TemporaryDirectory(prefix="unified-purchase-build.", dir="/tmp") as build_name, tempfile.TemporaryDirectory() as evidence_name:
				build, evidence = Path(build_name), Path(evidence_name)
				(build / "release-source-manifest.json").write_bytes(b"{}")
				(build / "raw.js").write_bytes(b"raw")
				files = {item.name: hashlib.sha256(item.read_bytes()).hexdigest() for item in build.iterdir()}
				stats = build.stat(); image = "sha256:" + "b" * 64
				owned = {"path": str(build), "identity": [stats.st_dev, stats.st_ino, stats.st_uid], "files": files, "directories": [], "manifest_sha256": files["release-source-manifest.json"], "max_bytes": 100, "candidate_sha": "a" * 40, "image_id": image, "rollback_image_id": "sha256:" + "c" * 64, "raw_assets": {"/assets/raw.js?v=1": files["raw.js"]}}
				(evidence / "build-ownership.json").write_text(json.dumps(owned))
				accepted = {"browser_accepted": True, "candidate_sha": owned["candidate_sha"], "image_id": image, "loaded_assets": [{"url": "https://deeplinkerp.com/assets/raw.js?v=" + ("0" if scenario == "asset-url" else "1"), "body_sha256": "d" * 64 if scenario == "asset-body" else files["raw.js"]}]}
				if scenario == "asset-origin": accepted["loaded_assets"][0]["url"] = "http://localhost/assets/raw.js?v=1"
				(evidence / "acceptance.json").write_text(json.dumps(accepted))
				if scenario == "extra-file": (build / "not-this-release.txt").write_text("keep")
				if scenario == "changed-file": (build / "raw.js").write_text("new")
				if scenario == "extra-directory": (build / "unowned").mkdir()
				if scenario == "hardlink": os.link(build / "raw.js", evidence / "shared.js")
				if scenario == "special": os.mkfifo(build / "unowned-pipe")
				calls = []
				def host_call(args):
					calls.append(args)
					if args == ["docker", "ps", "-aq"]: return "container-id"
					if args[:2] == ["docker", "inspect"]: return json.dumps([{"Mounts": [{"Source": str(build.resolve())}]}] if scenario == "shared-mount" else [{"Mounts": []}])
					if args[:3] == ["docker", "image", "inspect"]: return json.dumps([{"Id": args[-1]}])
					if args[:2] == ["docker", "run"]: return json.dumps({"redis_ping": not (scenario == "redis-pre" or scenario == "redis-post" and not build.exists()), "queues": {"bench:short": ["preserved"]}, "workers": {}, "executions": {}, "jobs": {}, "registries": {}})
					return "pong"
				def inspect(service):
					return {"Image": image, "State": {"Running": not (scenario == "post-health" and not build.exists())}, "Mounts": [{"Destination": "/home/frappe/frappe-bench/sites", "Type": "volume", "Name": "sites"}], "HostConfig": {"NetworkMode": "release-net"}}
				with patch.object(guard, "_host_call", side_effect=host_call), patch.object(guard, "_container_inspect", side_effect=inspect), patch.object(guard.subprocess, "run", return_value=types.SimpleNamespace(stdout=b"raw")):
					if scenario == "exact":
						result = guard.cleanup_owned_build(evidence, evidence / "acceptance.json")
						self.assertEqual(result["removed_bytes"], 5)
						self.assertEqual(result["redis_rq"]["queues"], {"bench:short": ["preserved"]})
						self.assertFalse(build.exists())
					elif scenario in {"post-health", "redis-post"}:
						with self.assertRaisesRegex(AssertionError, "forward HOLD"): guard.cleanup_owned_build(evidence, evidence / "acceptance.json")
						self.assertFalse(build.exists())
						self.assertEqual(guard.DDLReceipt.load(evidence / "cache-cleanup.json").state["status"], "applying")
					else:
						with self.assertRaises(AssertionError): guard.cleanup_owned_build(evidence, evidence / "acceptance.json")
						self.assertTrue(build.exists())
					self.assertFalse(any("prune" in call or "rm" in call for call in calls))

	def test_native_generated_column_and_pointer_schema_keep_case_and_original_projection(self):
		module = self.metadata_module()
		self.assertTrue(hasattr(module, "_native_schema_additions"))
		fake = types.SimpleNamespace(get_app_path=lambda app, name: str(ROOT / app / name))
		with patch.dict(sys.modules, {"frappe": fake}): native = module._native_reversal_contract()
		schema = JointReleaseGuardTests.schema(self)
		schema["columns"]["name"] = module._je_column(0)
		for key in ("integration_request_service", "status", "request_description"):
			schema["columns"][key] = module._je_column(len(schema["columns"]))
		for dt in native["tables"]:
			with self.subTest(dt=dt):
				original = {"schema": copy.deepcopy(schema), "original_columns": list(schema["columns"]), "rows": [{"name": "original", "status": "Completed"}]}
				delta = module._native_schema_additions(original, native, dt)
				self.assertEqual(len(delta["columns"]), 1)
				self.assertEqual(len(delta["indexes"]), 1)
				self.assertEqual(original["schema"], schema)
				if dt == "Integration Request":
					column = delta["columns"][native["activity_column"]]
					self.assertEqual((column["type"], column["extra"]), ("tinyint(4)", "VIRTUAL GENERATED"))
					self.assertIn("'Completed'", column["expression"])
					self.assertEqual([row["column"] for row in delta["indexes"][native["activity_index"]]], native["activity_index_columns"])


if __name__ == "__main__":
	unittest.main()
