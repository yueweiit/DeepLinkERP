"""Pure receipt/schema safety tests; native DDL is tested separately on MariaDB."""

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
		with patch.dict(sys.modules, {"frappe": fake, "audit_unified_purchase": audit}), patch.object(module, "_assert_joint_invariants", lambda *a, **kw: None), patch.object(module, "capture_joint_metadata", lambda: copy.deepcopy(current["metadata"])), patch.object(module, "_write_scope", write_scope):
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
		self.assertEqual(len(events), 3)
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
		self.assertIn('"${dc[@]}" stop queue-long queue-short scheduler', source)
		self.assertIn("--joint-apply", source)
		self.assertIn("--joint-rollback", source)
		self.assertIn("/home/frappe/frappe-bench/sites/deeplinkerp.com/private/release-evidence/", source)
		self.assertLess(source.index("quiesce_release_workers\n"), source.index("switched=1"))

	def test_cli_refuses_ambiguous_actions_or_non_durable_receipt_before_connecting(self):
		module = self.metadata_module()
		fake = types.SimpleNamespace(init=lambda **kwargs: self.fail("Invalid CLI must not initialize a site"))
		cases = (("--joint-apply", "--joint-rollback"), ("--joint-apply",), ("--joint-rollback", "--candidate-sha", "a" * 40, "--receipt", "/tmp/non-durable.json"))
		for args in cases:
			with self.subTest(args=args), patch.dict(sys.modules, {"frappe": fake}), patch.object(sys, "argv", ["metadata", *args]), self.assertRaises(SystemExit):
				module.main()


if __name__ == "__main__":
	unittest.main()
