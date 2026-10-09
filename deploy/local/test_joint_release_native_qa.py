"""Real MariaDB/Frappe rehearsal, ONLY the dedicated maintenance-mode site.

Run in dlp-operating-release-qa-backend-1 with the reviewed package mounted.
The helper never submits a voucher, invokes source sync, or contacts production.
"""

import copy
import hashlib
import importlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import frappe

SITE = "operating-release-qa.localhost"
ROOT = Path("/workspace")
sys.path.insert(0, str(ROOT / "deploy/production"))
release = importlib.import_module("procurement_release_metadata")
CANDIDATE_SHA = os.environ.get("OPERATING_RELEASE_QA_CANDIDATE_SHA", "a" * 40)


def planned_ddl_boundaries(before, contract):
	"""Count the same bounded additions, not a frozen old column total."""
	count = len(set(contract["custom_fields"]) - set(before["je"]["schema"]["columns"]))
	count += int("custom_operating_event_key" in contract["custom_fields"] and "custom_operating_event_key" not in before["je"]["schema"]["indexes"])
	for name in contract["model_schemas"]:
		model = before["models"][name]
		count += int(model["schema"] is None and contract["model_schemas"][name] is not None)
		for index in contract.get("model_index_ddl", {}).get(name, {}):
			count += int(model["schema"] is None or index not in model["schema"]["indexes"])
	if before.get("oa") and contract["source_custom_fields"]:
		count += len(set(contract["source_custom_fields"]) - set(before["oa"]["schema"]["columns"]))
		count += int("custom_purchase_source_id" not in before["oa"]["schema"]["indexes"])
	for name, table in before.get("native_tables", {}).items():
		count += sum(map(len, release._native_schema_additions(table, contract["native_reversal"], name).values()))
	return count


class JointNativeRehearsal(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		frappe.init(site=SITE, sites_path="/home/frappe/frappe-bench/sites")
		frappe.connect()
		assert frappe.local.site == SITE and frappe.conf.db_host == "db", "Dedicated site required"
		assert frappe.conf.maintenance_mode == 1 and frappe.__version__ == "16.23.0"
		assert frappe.db.db_type == "mariadb"
		frappe.set_user("Administrator")
		assert frappe.db.count("GL Entry") == frappe.db.count("Payment Entry") == 0
		assert hasattr(release, "load_joint_contract"), "Frozen native contract is missing"
		cls.contract = release.load_joint_contract()
		cls.evidence = Path(frappe.get_site_path("private", "release-evidence", "joint-native-qa"))
		cls.evidence.mkdir(parents=True, exist_ok=True)
		cls.je_name = "DLP-OPERATING-RELEASE-QA-SYNTHETIC-JE"
		if not frappe.db.exists("Journal Entry", cls.je_name):
			assert frappe.db.count("Journal Entry") == 0, "Unexpected baseline vouchers; preserve and stop"
			frappe.db.sql("insert into `tabJournal Entry` (name, creation, modified, modified_by, owner, docstatus, idx, user_remark, total_debit, total_credit) values (%s, '2000-01-01', '2000-01-01', 'Administrator', 'Administrator', 0, 0, %s, 17.25, 17.25)", (cls.je_name, "Synthetic DDL rehearsal only\n原始字节测试"))
			for index in (1, 2):
				frappe.db.sql("insert into `tabJournal Entry Account` (name, creation, modified, modified_by, owner, docstatus, idx, parent, parenttype, parentfield, account, debit_in_account_currency, credit_in_account_currency) values (%s, '2000-01-01', '2000-01-01', 'Administrator', 'Administrator', 0, %s, %s, 'Journal Entry', 'accounts', %s, %s, %s)", (cls.je_name + "-" + str(index), index, cls.je_name, "SYNTHETIC-NATIVE-ACCOUNT-" + str(index), 17.25 if index == 1 else 0, 17.25 if index == 2 else 0))
			frappe.db.commit()
		assert frappe.db.count("Journal Entry") == 1
		assert frappe.db.count("Journal Entry Account") == 2
		# Seed identical native Page plus custom nav children as a durable baseline.
		for name in ("operating-expenses",):
			if not frappe.db.exists("Page", name):
				rows = release._native_rows(cls.contract["definitions"][name]["source"], when="2000-01-01 00:00:00.000000", seed="qa-original-page")
				for dt, values in rows.items():
					for row in values:
						keys = sorted(row)
						frappe.db.sql("insert into " + release._quote("tab" + dt) + " (" + ",".join(map(release._quote, keys)) + ") values (" + ",".join(["%s"] * len(keys)) + ")", tuple(row[key] for key in keys))
		for dt, name in release.JOINT_NAVIGATION:
			if not frappe.db.exists(dt, name):
				continue
			child = "Workspace Link" if dt == "Workspace" else "Workspace Sidebar Item"
			parentfield = "links" if dt == "Workspace" else "items"
			identity = "DLP-NATIVE-CUSTOM-" + dt.replace(" ", "-") + "-" + name.replace(" ", "-")
			if not frappe.db.exists(child, identity):
				count = frappe.db.sql("select count(*) from " + release._quote("tab" + child) + " where parent=%s and parenttype=%s", (name, dt))[0][0]
				custom_field = "description" if dt == "Workspace" else "filters"
				frappe.db.sql("insert into " + release._quote("tab" + child) + " (name, creation, modified, owner, modified_by, docstatus, idx, parent, parenttype, parentfield, type, label, link_to, link_type, " + custom_field + ") values (%s, '2000-01-01', '2000-01-01', 'Administrator', 'Administrator', 0, %s, %s, %s, %s, 'Link', %s, 'Journal Entry', 'DocType', %s)", (identity, count + 1, name, dt, parentfield, "原有自定义入口", '{"synthetic":"preserve bytes"}'))
		frappe.db.commit()
		frappe.clear_cache()
		from audit_unified_purchase import capture_joint_state
		cls.baseline = capture_joint_state()
		assert all(model["schema"] is None for model in cls.baseline["models"].values()), "Rehearsal needs original pre-operating schema"
		assert not set(release.CUSTOM_FIELD_ORDER) & set(cls.baseline["je"]["schema"]["columns"])
		cls.run_prefix = CANDIDATE_SHA[:12] + "-" + str(os.getpid())

	@classmethod
	def tearDownClass(cls):
		frappe.db.rollback()
		frappe.destroy()

	def test_native_joint_installation_entry_is_available(self):
		self.assertTrue(hasattr(release, "apply_joint_metadata"), "Bounded native installer is missing")

	def setUp(self):
		self.receipt = self.evidence / (self.run_prefix + "-" + self.id().rsplit(".", 1)[-1] + ".json")
		assert not self.receipt.exists(), "Preserve prior evidence; use a new process"
		self.original = self.capture()
		self.assert_state_equal(self.original, self.baseline)

	def assert_state_equal(self, actual, expected):
		self.assertTrue(actual == expected, "Private native state differs in: " + ",".join(key for key in set(actual) | set(expected) if actual.get(key) != expected.get(key)))

	def capture(self):
		from audit_unified_purchase import capture_joint_state
		return capture_joint_state(original_columns=self.baseline["je"]["original_columns"], original_oa_columns=self.baseline["oa"]["original_columns"] if self.baseline.get("oa") else None,
			original_native_columns={name: value["original_columns"] for name, value in self.baseline.get("native_tables", {}).items()}, native_only=getattr(self, "native_only", False))

	def restore(self):
		result = release.restore_joint_metadata(self.receipt, candidate_sha=CANDIDATE_SHA)
		self.assertTrue(result["restored"])
		self.assert_state_equal(self.capture(), self.original)
		self.assertEqual(frappe.db.count("GL Entry"), 0)
		self.assertEqual(frappe.db.count("Payment Entry"), 0)
		self.assertEqual(frappe.conf.maintenance_mode, 1)

	def test_apply_preserves_populated_original_je_children_and_second_apply_is_byte_noop(self):
		result = release.apply_joint_metadata(CANDIDATE_SHA, self.receipt)
		self.assertTrue(result["applied"])
		self.assertEqual(result["ddl_boundaries"], 9)
		after = self.capture()
		self.assertEqual(after["je"]["rows"], self.original["je"]["rows"])
		self.assertEqual(after["audit"]["tables"]["Journal Entry Account"], self.original["audit"]["tables"]["Journal Entry Account"])
		self.assertEqual(after["metadata"]["outside"], self.original["metadata"]["outside"])
		first = self.receipt.read_bytes()
		self.assertTrue(release.apply_joint_metadata(CANDIDATE_SHA, self.receipt)["unchanged"])
		self.assertEqual(self.receipt.read_bytes(), first)
		self.assert_state_equal(self.capture(), after)
		original_page = [row for row in self.original["metadata"]["scope"]["Page"] if row["name"] == "operating-expenses"]
		self.assertEqual([row for row in after["metadata"]["scope"]["Page"] if row["name"] == "operating-expenses"], original_page)
		self.restore()

	def test_installed_page_title_upgrade_has_zero_ddl_strict_children_noop_and_exact_rollback(self):
		from joint_release_guards import serialized

		baseline, baseline_receipt = self.original, self.receipt
		self.assertEqual(self.contract["definitions"]["operating-expenses"]["source"]["title"], "运营费用", "Use the immutable old package for the installation fixture")
		installed = None
		title_receipt = self.evidence / (self.run_prefix + "-page-title-upgrade.json")
		try:
			# Fixture only: establish the already-installed 41ba-style metadata.
			# The actual title release below must perform no native DDL at all.
			self.assertEqual(release.apply_joint_metadata(CANDIDATE_SHA, baseline_receipt)["ddl_boundaries"], 9)
			installed = self.capture()
			candidate = release.load_joint_contract()
			# Exercise the exact new Page literal on the native DB while keeping
			# the mounted old app/source map immutable; no source-sync invocation.
			candidate["definitions"]["operating-expenses"]["source"]["title"] = "运营支出"
			candidate["definitions"]["operating-expenses"]["native"]["Page"][0]["title"] = "运营支出"
			with patch.object(release, "load_joint_contract", lambda: copy.deepcopy(candidate)), patch.object(frappe.db, "sql_ddl", side_effect=AssertionError("Title release must not execute DDL")):
				# A real child definition conflict must stop before receipt/writes.
				role = next(row for row in installed["metadata"]["scope"]["Has Role"] if row["parent"] == "operating-expenses")
				frappe.db.sql("update `tabHas Role` set idx=idx+10 where name=%s", (role["name"],))
				conflicted = self.capture()
				conflict_receipt = self.evidence / (self.run_prefix + "-page-title-child-conflict.json")
				with patch.object(frappe.db, "commit", side_effect=AssertionError("Conflicting title release attempted commit")), self.assertRaisesRegex(AssertionError, "Conflicting native child definitions"):
					release.apply_joint_metadata(CANDIDATE_SHA, conflict_receipt)
				self.assertFalse(conflict_receipt.exists())
				self.assert_state_equal(self.capture(), conflicted)
				frappe.db.rollback()
				self.assert_state_equal(self.capture(), installed)

				result = release.apply_joint_metadata(CANDIDATE_SHA, title_receipt)
				self.assertEqual(result["ddl_boundaries"], 0)
				after = self.capture()
				wanted = copy.deepcopy(installed)
				for row in wanted["metadata"]["scope"]["Page"]:
					if row["name"] == "operating-expenses":
						row["title"] = "运营支出"
				self.assert_state_equal(after, wanted)
				state = json.loads(title_receipt.read_bytes())
				self.assertEqual(state["contract"]["metadata_plan"]["page_title_updates"], [{"name": "operating-expenses", "field": "title", "before": "运营费用", "after": "运营支出"}])
				self.assertEqual([(step["kind"], step["status"]) for step in state["steps"]], [("metadata", "complete")])
				first = title_receipt.read_bytes()
				with patch.object(frappe.db, "commit", side_effect=AssertionError("Repeated title release attempted commit")), patch.object(release, "_write_scope", side_effect=AssertionError("Repeated title release attempted metadata write")):
					self.assertTrue(release.apply_joint_metadata(CANDIDATE_SHA, title_receipt)["unchanged"])
					noop = self.evidence / (self.run_prefix + "-page-title-new-receipt-noop.json")
					self.assertTrue(release.apply_joint_metadata(CANDIDATE_SHA, noop)["unchanged"])
					self.assertEqual(json.loads(noop.read_bytes())["contract"]["metadata_plan"]["page_title_updates"], [])
					self.assertTrue(release.restore_joint_metadata(noop, candidate_sha=CANDIDATE_SHA)["restored"])
				self.assertEqual(title_receipt.read_bytes(), first)
				self.assert_state_equal(self.capture(), after)
				self.assertTrue(release.restore_joint_metadata(title_receipt, candidate_sha=CANDIDATE_SHA)["restored"])
				self.assert_state_equal(self.capture(), installed)
		finally:
			# Do not erase a newer row or ignore drift; both durable receipts use
			# the production exact rollback gates before fixture DDL is removed.
			if title_receipt.exists() and json.loads(title_receipt.read_bytes())["status"] != "restored":
				self.assertTrue(release.restore_joint_metadata(title_receipt, candidate_sha=CANDIDATE_SHA)["restored"])
			if installed is not None:
				self.assert_state_equal(self.capture(), installed)
			if baseline_receipt.exists():
				self.assertTrue(release.restore_joint_metadata(baseline_receipt, candidate_sha=CANDIDATE_SHA)["restored"])
			self.assert_state_equal(self.capture(), baseline)
			print("page-title fixture restored:", json.dumps({"candidate_base_sha": CANDIDATE_SHA, "receipt": title_receipt.name, "title_phase_ddl": 0, "original_and_final_full_state_sha256": hashlib.sha256(serialized(baseline)).hexdigest(), "maintenance": frappe.conf.maintenance_mode, "GL": frappe.db.count("GL Entry"), "PE": frappe.db.count("Payment Entry")}), flush=True)

	def test_legacy_nullable_sidebar_column_preserves_bytes_through_nine_ddl_noop_and_restore(self):
		from audit_unified_purchase import table_schema
		from joint_release_guards import serialized

		doctype = "Workspace Sidebar Item"
		physical_before = table_schema(doctype)
		self.assertNotIn("display_depends_on", physical_before["columns"], "Preserve an existing legacy column; do not replace it")
		self.assertIsNone(frappe.get_meta(doctype, cached=False).get_field("display_depends_on"))
		baseline = self.original
		identity = "DLP-NATIVE-CUSTOM-Workspace-Sidebar-China-Finance"
		self.assertTrue(frappe.db.exists(doctype, identity), "Only the existing synthetic fixture can hold test bytes")
		frappe.db.sql_ddl("ALTER TABLE `tabWorkspace Sidebar Item` ADD COLUMN `display_depends_on` LONGTEXT NULL")
		frappe.db.sql("update `tabWorkspace Sidebar Item` set display_depends_on=%s where name=%s", ("eval:doc.synthetic_legacy\n原始旧列字节", identity))
		frappe.db.commit()
		frappe.clear_cache(doctype=doctype)
		self.original = self.capture()
		legacy_schema = table_schema(doctype)
		self.assertEqual(legacy_schema["columns"]["display_depends_on"]["type"], "longtext")
		self.assertEqual(legacy_schema["columns"]["display_depends_on"]["nullable"], "YES")
		try:
			self.assertIn(legacy_schema["columns"]["display_depends_on"]["default_value"], {None, "NULL"})
			self.assertEqual(legacy_schema["columns"]["display_depends_on"]["collation"], "utf8mb4_unicode_ci")
			result = release.apply_joint_metadata(CANDIDATE_SHA, self.receipt)
			self.assertEqual(result["ddl_boundaries"], 9)
			after = self.capture()
			self.assertEqual(after["je"]["rows"], self.original["je"]["rows"])
			self.assertEqual(after["audit"]["tables"]["Journal Entry Account"], self.original["audit"]["tables"]["Journal Entry Account"])
			self.assertEqual(after["metadata"]["outside_rows"], self.original["metadata"]["outside_rows"])
			old_rows = {row["name"]: row for row in self.original["metadata"]["scope"][doctype]}
			new_rows = [row for row in after["metadata"]["scope"][doctype] if row["name"] not in old_rows]
			self.assertTrue(new_rows)
			for row in new_rows:
				self.assertEqual(set(row), set(legacy_schema["columns"]))
				self.assertIsNone(row["display_depends_on"])
			self.assertEqual(next(row for row in after["metadata"]["scope"][doctype] if row["name"] == identity), old_rows[identity])
			first = self.receipt.read_bytes()
			with patch.object(frappe.db, "sql_ddl", side_effect=AssertionError("No-op attempted DDL")), patch.object(frappe.db, "commit", side_effect=AssertionError("No-op attempted commit")), patch.object(release, "_write_scope", side_effect=AssertionError("No-op attempted metadata write")):
				self.assertTrue(release.apply_joint_metadata(CANDIDATE_SHA, self.receipt)["unchanged"])
			self.assertEqual(self.receipt.read_bytes(), first)
			self.assert_state_equal(self.capture(), after)
			self.assertEqual(table_schema(doctype), legacy_schema)
			self.restore()
		finally:
			# Recover the original implementation's pre-commit failure too. Never
			# remove the fixture while any actual release delta or drift remains.
			if self.receipt.exists() and json.loads(self.receipt.read_bytes())["status"] != "restored":
				self.restore()
			self.assert_state_equal(self.capture(), self.original)
			self.assertEqual(table_schema(doctype), legacy_schema)
			self.assertEqual([tuple(row) for row in frappe.db.sql("select name, display_depends_on from `tabWorkspace Sidebar Item` where display_depends_on is not null")], [(identity, "eval:doc.synthetic_legacy\n原始旧列字节")])
			frappe.db.sql("update `tabWorkspace Sidebar Item` set display_depends_on=null where name=%s", (identity,))
			frappe.db.commit()
			self.assertEqual(frappe.db.sql("select count(*) from `tabWorkspace Sidebar Item` where display_depends_on is not null")[0][0], 0)
			frappe.db.sql_ddl("ALTER TABLE `tabWorkspace Sidebar Item` DROP COLUMN `display_depends_on`")
			frappe.clear_cache(doctype=doctype)
			self.original = baseline
			self.assert_state_equal(self.capture(), baseline)
			self.assertEqual(table_schema(doctype), physical_before)
			print("legacy-column fixture restored:", json.dumps({"candidate_sha": CANDIDATE_SHA, "receipt": self.receipt.name, "legacy_column_schema": legacy_schema["columns"]["display_depends_on"], "original_and_final_full_state_sha256": hashlib.sha256(serialized(baseline)).hexdigest(), "physical_schema_sha256": hashlib.sha256(serialized(physical_before)).hexdigest(), "maintenance": frappe.conf.maintenance_mode, "GL": frappe.db.count("GL Entry"), "PE": frappe.db.count("Payment Entry")}), flush=True)

	def test_pending_native_column_index_and_model_ddl_failures_restore_exact_baseline(self):
		boundaries = [("column-" + key, "ADD COLUMN `" + key + "`") for key in release.CUSTOM_FIELD_ORDER]
		boundaries += [("index", "ADD UNIQUE INDEX")]
		boundaries += [("model-" + frappe.scrub(name), "create table `tab" + name + "`") for name in release.JOINT_MODELS if not self.contract["definitions"][name]["source"]["issingle"]]
		for boundary, marker in boundaries:
			with self.subTest(boundary=boundary):
				self.receipt = self.evidence / (self.run_prefix + "-pending-" + boundary + ".json")
				original_ddl = frappe.db.sql_ddl
				def failure(query, **kwargs):
					# Read the durable intent from disk BEFORE actual native autocommit.
					state = json.loads(self.receipt.read_bytes())
					self.assertEqual(state["steps"][-1]["sql"], str(query))
					self.assertEqual(state["steps"][-1]["status"], "pending")
					self.assertEqual(state["before"]["je"]["rows"], self.original["je"]["rows"])
					original_ddl(query, **kwargs)
					if marker in query:
						raise RuntimeError("Synthetic failure AFTER native DDL " + boundary)
				with patch.object(frappe.db, "sql_ddl", failure), self.assertRaisesRegex(RuntimeError, "AFTER native DDL"):
					release.apply_joint_metadata(CANDIDATE_SHA, self.receipt)
				state = json.loads(self.receipt.read_bytes())
				self.assertTrue(any(step["status"] == "pending" for step in state["steps"]))
				self.restore()

	def test_both_native_existing_page_routes_and_job_identities_are_preserved_and_other_route_refused(self):
		baseline = self.original
		job_source = self.contract["definitions"][release.OPERATING_METHOD]["source"]
		job = release._native_rows(job_source, when="2000-01-01 00:00:00.000000", seed="qa-original-job", defaults=True)["Scheduled Job Type"][0]
		job["name"] = "DLP-NATIVE-ORIGINAL-OPERATING-JOB"
		keys = sorted(job)
		frappe.db.sql("insert into `tabScheduled Job Type` (" + ",".join(map(release._quote, keys)) + ") values (" + ",".join(["%s"] * len(keys)) + ")", tuple(job[key] for key in keys))
		frappe.db.commit()
		for route in (None, "operating-expenses", "DLP-NATIVE-UNAPPROVED-ROUTE"):
			with self.subTest(route=route):
				frappe.db.sql("update `tabPage` set page_name=%s where name='operating-expenses'", (route,))
				frappe.db.commit()
				self.original = self.capture()
				self.receipt = self.evidence / (self.run_prefix + "-page-route-" + str(route) + ".json")
				if route == "DLP-NATIVE-UNAPPROVED-ROUTE":
					with self.assertRaisesRegex(AssertionError, "Page route"):
						release.apply_joint_metadata(CANDIDATE_SHA, self.receipt)
					self.assertFalse(self.receipt.exists())
					self.assert_state_equal(self.capture(), self.original)
					continue
				release.apply_joint_metadata(CANDIDATE_SHA, self.receipt)
				after = self.capture()
				for dt in ("Page", "Has Role", "Scheduled Job Type"):
					self.assertEqual(after["metadata"]["scope"][dt], self.original["metadata"]["scope"][dt])
				first = self.receipt.read_bytes()
				second_receipt = self.evidence / (self.run_prefix + "-page-existing-noop-" + str(route) + ".json")
				self.assertTrue(release.apply_joint_metadata(CANDIDATE_SHA, second_receipt)["unchanged"])
				self.assert_state_equal(self.capture(), after)
				self.assertEqual(self.receipt.read_bytes(), first)
				self.assertTrue(release.restore_joint_metadata(second_receipt)["restored"])
				self.assert_state_equal(self.capture(), after)
				self.restore()
		frappe.db.sql("update `tabPage` set page_name=NULL where name='operating-expenses' and page_name='DLP-NATIVE-UNAPPROVED-ROUTE'")
		frappe.db.sql("delete from `tabScheduled Job Type` where name='DLP-NATIVE-ORIGINAL-OPERATING-JOB' and method=%s", (release.OPERATING_METHOD,))
		frappe.db.commit()
		self.original = baseline
		self.assert_state_equal(self.capture(), baseline)

	def test_native_planning_rejects_original_je_column_and_index_changes_before_writes(self):
		original_get_meta = frappe.get_meta
		for kind in ("column", "index"):
			with self.subTest(kind=kind):
				meta = copy.deepcopy(original_get_meta("Journal Entry", cached=False))
				field = next(field for field in meta.fields if field.fieldname == ("user_remark" if kind == "column" else "bill_no"))
				if kind == "column":
					field.fieldtype = "Data"
				else:
					field.search_index = 1
				def changed_meta(name, *args, **kwargs):
					return meta if name == "Journal Entry" else original_get_meta(name, *args, **kwargs)
				self.receipt = self.evidence / (self.run_prefix + "-original-plan-" + kind + ".json")
				with patch.object(frappe, "get_meta", changed_meta), self.assertRaisesRegex(AssertionError, "Unexpected native Journal Entry schema change"):
					release.apply_joint_metadata(CANDIDATE_SHA, self.receipt)
				self.assertFalse(self.receipt.exists())
				self.assert_state_equal(self.capture(), self.original)

	def test_partial_metadata_autocommit_is_detected_from_raw_database_and_restored(self):
		original_sql, original_commit = frappe.db.sql, frappe.db.commit
		def failure(query, *args, **kwargs):
			result = original_sql(query, *args, **kwargs)
			if str(query).startswith("insert into `tabDocField`"):
				original_commit()
				raise RuntimeError("Synthetic failure AFTER partial metadata autocommit")
			return result
		with patch.object(frappe.db, "sql", failure), self.assertRaisesRegex(RuntimeError, "partial metadata"):
			release.apply_joint_metadata(CANDIDATE_SHA, self.receipt)
		self.restore()

	def test_applied_drift_is_refused_and_pending_native_rollback_resumes(self):
		release.apply_joint_metadata(CANDIDATE_SHA, self.receipt)
		after = self.capture()
		state = json.loads(self.receipt.read_bytes())
		first = self.receipt.read_bytes()
		self.assertTrue(release.apply_joint_metadata(CANDIDATE_SHA, self.receipt)["unchanged"])
		second_receipt = self.evidence / (self.run_prefix + "-applied-gate-existing-noop.json")
		self.assertTrue(release.apply_joint_metadata(CANDIDATE_SHA, second_receipt)["unchanged"])
		self.assertTrue(release.restore_joint_metadata(second_receipt)["restored"])
		self.assert_state_equal(self.capture(), after)
		self.assertEqual(self.receipt.read_bytes(), first)
		job = next(row for row in after["metadata"]["scope"]["Scheduled Job Type"] if row["method"] == release.OPERATING_METHOD)
		for missing in ("job", "index", "model", "column"):
			with self.subTest(missing=missing):
				if missing == "job":
					frappe.db.sql("delete from `tabScheduled Job Type` where name=%s and method=%s", (job["name"], release.OPERATING_METHOD))
					frappe.db.commit()
				elif missing == "index":
					frappe.db.sql_ddl("ALTER TABLE `tabJournal Entry` DROP INDEX custom_operating_event_key")
				elif missing == "model":
					self.assertEqual(frappe.db.count("Operating Expense Source"), 0)
					frappe.db.sql_ddl("DROP TABLE `tabOperating Expense Source`")
				else:
					self.assertEqual(frappe.db.sql("select count(*) from `tabJournal Entry` where custom_operating_fingerprint is not null")[0][0], 0)
					frappe.db.sql_ddl("ALTER TABLE `tabJournal Entry` DROP COLUMN custom_operating_fingerprint")
				changed = self.capture()
				def forbidden(*args, **kwargs):
					self.fail("Drifted rollback must refuse before any DDL/metadata commit")
				with patch.object(frappe.db, "sql_ddl", forbidden), patch.object(frappe.db, "commit", forbidden), patch.object(release, "_write_scope", forbidden), self.assertRaisesRegex(AssertionError, "recorded|drift"):
					release.restore_joint_metadata(self.receipt)
				self.assert_state_equal(self.capture(), changed)
				self.assertEqual(self.receipt.read_bytes(), first)
				self.assertEqual(frappe.conf.maintenance_mode, 1)
				# Repair only the exact introduced synthetic fault, not business data.
				if missing == "job":
					keys = sorted(job)
					frappe.db.sql("insert into `tabScheduled Job Type` (" + ",".join(map(release._quote, keys)) + ") values (" + ",".join(["%s"] * len(keys)) + ")", tuple(job[key] for key in keys))
					frappe.db.commit()
				else:
					marker = "ADD UNIQUE INDEX" if missing == "index" else ("create table `tabOperating Expense Source`" if missing == "model" else "ADD COLUMN `custom_operating_fingerprint`")
					query = next(step["sql"] for step in state["steps"] if step.get("kind") == "ddl" and marker in step["sql"])
					frappe.db.sql_ddl(query)
				self.assert_state_equal(self.capture(), after)
		# Crash after a recorded native DROP but before complete(); resume must
		# inspect its actual result, complete the intent, and restore exactly.
		original_ddl = frappe.db.sql_ddl
		def failure(query, **kwargs):
			original_ddl(query, **kwargs)
			if str(query) == "DROP TABLE `tabOperating Expense Company Map`":
				raise RuntimeError("Synthetic failure AFTER pending native rollback")
		with patch.object(frappe.db, "sql_ddl", failure), self.assertRaisesRegex(RuntimeError, "pending native rollback"):
			release.restore_joint_metadata(self.receipt)
		self.assertTrue(any(step["kind"] == "rollback-ddl" and step["status"] == "pending" for step in json.loads(self.receipt.read_bytes())["steps"]))
		self.restore()
		self.assertTrue(all(step["status"] == "complete" for step in json.loads(self.receipt.read_bytes())["steps"] if step["kind"].startswith("rollback-")))
		# Exercise a genuinely committed partial rollback-metadata write too.
		self.receipt = self.evidence / (self.run_prefix + "-pending-rollback-metadata.json")
		release.apply_joint_metadata(CANDIDATE_SHA, self.receipt)
		original_sql, original_commit = frappe.db.sql, frappe.db.commit
		def metadata_failure(query, *args, **kwargs):
			result = original_sql(query, *args, **kwargs)
			if str(query).startswith("delete from `tabCustom Field`"):
				original_commit()
				raise RuntimeError("Synthetic failure AFTER pending rollback metadata autocommit")
			return result
		with patch.object(frappe.db, "sql", metadata_failure), self.assertRaisesRegex(RuntimeError, "rollback metadata autocommit"):
			release.restore_joint_metadata(self.receipt)
		self.assertTrue(any(step["kind"] == "rollback-metadata" and step["status"] == "pending" for step in json.loads(self.receipt.read_bytes())["steps"]))
		self.restore()

	def test_native_customization_overrides_abort_before_contract_receipt_or_writes(self):
		cases = [("Custom Field", {"dt": name, "fieldname": "custom_dlp_native_unapproved", "fieldtype": "Data", "reqd": 1}) for name in release.JOINT_MODELS]
		cases += [("Property Setter", {"doc_type": name, "doctype_or_field": "DocField", "field_name": self.contract["definitions"][name]["source"]["fields"][0]["fieldname"], "property": "reqd", "property_type": "Check", "value": "1"}) for name in release.JOINT_MODELS]
		cases += [("Custom DocPerm", {"parent": name, "parenttype": None, "role": "All", "read": 1, "write": 1}) for name in release.JOINT_MODELS]
		cases += [("Property Setter", {"doc_type": "Journal Entry", "doctype_or_field": "DocField", "field_name": key, "property": "reqd", "property_type": "Check", "value": "1"}) for key in release.CUSTOM_FIELD_ORDER]
		cases += [("Property Setter", {"doc_type": "Journal Entry", "doctype_or_field": "DocField", "field_name": "custom_operating_source", "property": flag, "property_type": "Check", "value": "0"}) for flag in ("read_only", "no_copy")]
		for index, (doctype, values) in enumerate(cases):
			with self.subTest(doctype=doctype, target=values):
				identity = "DLP-NATIVE-OVERRIDE-FIXTURE-" + str(index)
				row = release._native_rows(dict(values, doctype=doctype, name=identity), when="2000-01-01 00:00:00.000000", seed="qa-override", defaults=True)[doctype][0]
				keys = sorted(row)
				frappe.db.sql("insert into " + release._quote("tab" + doctype) + " (" + ",".join(map(release._quote, keys)) + ") values (" + ",".join(["%s"] * len(keys)) + ")", tuple(row[key] for key in keys))
				frappe.db.commit()
				changed = self.capture()
				original_sql = frappe.db.sql
				def readonly(query, *args, **kwargs):
					self.assertTrue(str(query).lstrip().lower().startswith(("select", "show", "describe", "explain")), "Override preflight must not issue SQL writes")
					return original_sql(query, *args, **kwargs)
				def forbidden(*args, **kwargs):
					self.fail("Override preflight must not commit or run native DDL")
				with patch.object(frappe.db, "sql", readonly), patch.object(frappe.db, "commit", forbidden), patch.object(frappe.db, "sql_ddl", forbidden), self.assertRaisesRegex(AssertionError, "customization"):
					release.apply_joint_metadata(CANDIDATE_SHA, self.receipt)
				self.assertFalse(self.receipt.exists())
				self.assert_state_equal(self.capture(), changed)
				frappe.db.sql("delete from " + release._quote("tab" + doctype) + " where name=%s", (identity,))
				frappe.db.commit()
				self.assert_state_equal(self.capture(), self.original)

	def test_rollback_refuses_new_model_single_nonnull_column_or_outside_activity(self):
		for activity in ("model", "single", "nonnull", "outside"):
			with self.subTest(activity=activity):
				self.receipt = self.evidence / (self.run_prefix + "-refuse-" + activity + ".json")
				release.apply_joint_metadata(CANDIDATE_SHA, self.receipt)
				if activity == "model":
					frappe.db.sql("insert into `tabOperating Expense Event` (name, event_key) values ('DLP-NATIVE-NEW-ACTIVITY', 'DLP-NATIVE-NEW-ACTIVITY')")
				elif activity == "single":
					frappe.db.sql("insert into `tabSingles` (doctype, field, value) values ('Operating Expense Sync Settings', 'enabled', '1')")
				elif activity == "nonnull":
					# Even empty string is activity: SQL NULL is the rollback requirement.
					frappe.db.sql("update `tabJournal Entry` set custom_operating_fingerprint='' where name=%s", (self.je_name,))
				else:
					old_title = frappe.db.get_value("Page", "purchase-payment-records", "title")
					frappe.db.sql("update `tabPage` set title='DLP-NATIVE-OUTSIDE-DRIFT' where name='purchase-payment-records'")
				frappe.db.commit()
				changed = self.capture()
				with self.assertRaises(AssertionError):
					release.restore_joint_metadata(self.receipt)
				self.assert_state_equal(self.capture(), changed)
				self.assertEqual(frappe.conf.maintenance_mode, 1)
				# Exact introduced synthetic targets only; never general restoration/deletion.
				if activity == "model":
					frappe.db.sql("delete from `tabOperating Expense Event` where name='DLP-NATIVE-NEW-ACTIVITY' and event_key='DLP-NATIVE-NEW-ACTIVITY'")
				elif activity == "single":
					frappe.db.sql("delete from `tabSingles` where doctype='Operating Expense Sync Settings' and field='enabled' and value='1'")
				elif activity == "nonnull":
					frappe.db.sql("update `tabJournal Entry` set custom_operating_fingerprint=NULL where name=%s and custom_operating_fingerprint=''", (self.je_name,))
				else:
					frappe.db.sql("update `tabPage` set title=%s where name='purchase-payment-records' and title='DLP-NATIVE-OUTSIDE-DRIFT'", (old_title,))
				frappe.db.commit()
				self.restore()

	def test_orphan_column_and_behavioral_metadata_conflicts_abort_before_any_installer_write(self):
		behavior = {"reqd": 1, "default": "unapproved-default", "hidden": 1, "read_only": 0, "no_copy": 0, "permlevel": 1, "options": "Customer", "unique": 1}
		conflicts = ("orphan-column", "matching-column-wrong-type", "prefix-index", "composite-index", "nonunique-index", "orphan-model-table", "orphan-model-child", "scheduled-definition") + tuple("flag-" + field for field in behavior)
		for conflict in conflicts:
			with self.subTest(conflict=conflict):
				self.receipt = self.evidence / (self.run_prefix + "-conflict-" + conflict + ".json")
				inserted = []
				def insert(dt, row):
					keys = sorted(row)
					frappe.db.sql("insert into " + release._quote("tab" + dt) + " (" + ",".join(map(release._quote, keys)) + ") values (" + ",".join(["%s"] * len(keys)) + ")", tuple(row[key] for key in keys))
					inserted.append((dt, row["name"]))
				if conflict == "orphan-column":
					frappe.db.sql_ddl("ALTER TABLE `tabJournal Entry` ADD COLUMN `custom_operating_source` varchar(141)")
				elif conflict.startswith("flag-") or conflict == "matching-column-wrong-type":
					source = dict(self.contract["definitions"]["Journal Entry-custom_operating_source"]["source"])
					if conflict.startswith("flag-"):
						field = conflict.removeprefix("flag-")
						source[field] = behavior[field]
					insert("Custom Field", release._native_rows(source, when="2000-01-01 00:00:00.000000", seed="qa-conflict", defaults=True)["Custom Field"][0])
					if conflict == "matching-column-wrong-type":
						frappe.db.sql_ddl("ALTER TABLE `tabJournal Entry` ADD COLUMN `custom_operating_source` varchar(141)")
				elif conflict.endswith("index"):
					source = self.contract["definitions"]["Journal Entry-custom_operating_event_key"]["source"]
					insert("Custom Field", release._native_rows(source, when="2000-01-01 00:00:00.000000", seed="qa-conflict", defaults=True)["Custom Field"][0])
					frappe.db.sql_ddl("ALTER TABLE `tabJournal Entry` ADD COLUMN `custom_operating_event_key` varchar(140)")
					columns = "`custom_operating_event_key`(40)" if conflict == "prefix-index" else "`custom_operating_event_key`, `name`" if conflict == "composite-index" else "`custom_operating_event_key`"
					frappe.db.sql_ddl("ALTER TABLE `tabJournal Entry` ADD " + ("" if conflict == "nonunique-index" else "UNIQUE ") + "INDEX custom_operating_event_key (" + columns + ")")
				elif conflict == "orphan-model-table":
					frappe.db.sql_ddl("CREATE TABLE `tabOperating Expense Mapping` (name varchar(140) primary key) ENGINE=InnoDB")
				elif conflict == "orphan-model-child":
					source = self.contract["definitions"]["Operating Expense Mapping"]["source"]
					insert("DocField", release._native_rows(source, when="2000-01-01 00:00:00.000000", seed="qa-conflict")["DocField"][0])
				else:
					source = dict(self.contract["definitions"][release.OPERATING_METHOD]["source"], cron_format="*/10 * * * *")
					insert("Scheduled Job Type", release._native_rows(source, when="2000-01-01 00:00:00.000000", seed="qa-conflict", defaults=True)["Scheduled Job Type"][0])
				frappe.db.commit()
				frappe.clear_cache(doctype="Journal Entry")
				changed = self.capture()
				with self.assertRaises(AssertionError):
					release.apply_joint_metadata(CANDIDATE_SHA, self.receipt)
				self.assertFalse(self.receipt.exists(), "Conflict must abort before receipt/mutation")
				self.assert_state_equal(self.capture(), changed)
				if conflict in {"orphan-column", "matching-column-wrong-type"}:
					frappe.db.sql_ddl("ALTER TABLE `tabJournal Entry` DROP COLUMN `custom_operating_source`")
				elif conflict.endswith("index"):
					# MariaDB rejects dropping a column while a composite index still
					# names it. Remove only this exact introduced fixture index first.
					frappe.db.sql_ddl("ALTER TABLE `tabJournal Entry` DROP INDEX custom_operating_event_key")
					frappe.db.sql_ddl("ALTER TABLE `tabJournal Entry` DROP COLUMN `custom_operating_event_key`")
				elif conflict == "orphan-model-table":
					self.assertEqual(frappe.db.sql("select count(*) from `tabOperating Expense Mapping`")[0][0], 0)
					frappe.db.sql_ddl("DROP TABLE `tabOperating Expense Mapping`")
				for dt, name in inserted:
					frappe.db.sql("delete from " + release._quote("tab" + dt) + " where name=%s", (name,))
				frappe.db.commit()
				frappe.clear_cache(doctype="Journal Entry")
				self.assert_state_equal(self.capture(), self.original)


class CrossborderUpgradeNativeRehearsal(unittest.TestCase):
	"""Upgrade the installed old release; reuse the same raw snapshot and rollback gates."""
	setUp = JointNativeRehearsal.setUp
	assert_state_equal = JointNativeRehearsal.assert_state_equal
	capture = JointNativeRehearsal.capture
	restore = JointNativeRehearsal.restore

	@classmethod
	def setUpClass(cls):
		frappe.init(site=SITE, sites_path="/home/frappe/frappe-bench/sites")
		frappe.connect()
		assert frappe.local.site == SITE and frappe.conf.db_host == "db" and frappe.conf.maintenance_mode == 1
		assert os.environ.get("DEEPLINKERP_RELEASE_QUIESCENT") == "1" and frappe.__version__ == "16.23.0"
		assert frappe.db.sql("select version()")[0][0].startswith("11.8.6-"), "Fresh logical-restored MariaDB 11.8.6 required"
		frappe.set_user("Administrator")
		assert frappe.db.count("GL Entry") == frappe.db.count("Payment Entry") == frappe.db.count("Purchase Order") == 0
		assert frappe.db.count("Journal Entry") == 1 and frappe.db.count("Journal Entry Account") == 2
		assert frappe.db.get_value("Journal Entry", "DLP-OPERATING-RELEASE-QA-SYNTHETIC-JE", "docstatus") == 0
		cls.contract = release.load_joint_contract()
		from audit_unified_purchase import capture_joint_state
		cls.unseeded = capture_joint_state()
		assert cls.unseeded["models"][release.FULFILMENT_MODEL]["schema"] is None
		new_models={release.FULFILMENT_MODEL,"Operating Expense Sync Settings","Operating Expense Takeover","Operating Expense Payment"}
		assert all(model["schema"] is None for name,model in cls.unseeded["models"].items() if name in new_models)
		assert all(model["schema"] is not None for name, model in cls.unseeded["models"].items() if name not in new_models)
		assert set(release.CUSTOM_FIELD_ORDER) <= set(cls.unseeded["je"]["schema"]["columns"])
		assert set(release.SOURCE_FIELD_ORDER[:5]) <= set(cls.unseeded["oa"]["schema"]["columns"])
		assert not set(release.SOURCE_FIELD_ORDER[5:]) & set(cls.unseeded["oa"]["schema"]["columns"])
		assert frappe.db.count(release.OA_DOCTYPE) == 0
		# Fail once, before seeding, if bootstrap metadata differs from the
		# production-controlled baseline. Do not repeat a known preflight failure.
		release._joint_plan(cls.unseeded, cls.contract, when="2000-01-01 00:00:00.000000", seed="qa-baseline-preflight")
		cls.oa_name = "DLP-CROSSBORDER-RELEASE-QA-OA"
		frappe.db.sql("insert into `tabOA Purchase Request` (name, creation, modified, owner, modified_by, docstatus, custom_purchase_source_id, custom_purchase_source_json) values (%s, '2000-01-01', '2000-01-01', 'Administrator', 'Administrator', 0, %s, %s)", (cls.oa_name, "DLP-CROSSBORDER-RELEASE-QA-SOURCE", '{"manual":"原始 来源字节"}'))
		frappe.db.commit()
		cls.baseline = capture_joint_state()
		cls.ddl_boundaries = planned_ddl_boundaries(cls.baseline, cls.contract)
		cls.original_jobs = copy.deepcopy(cls.baseline["metadata"]["scope"]["Scheduled Job Type"])
		assert len(cls.original_jobs) == 2 and {row["method"] for row in cls.original_jobs} == set(release.SCHEDULED_METHODS) - {release.REVERSAL_METHOD}
		cls.evidence = Path(frappe.get_site_path("private", "release-evidence", "crossborder-native-qa"))
		cls.evidence.mkdir(parents=True, exist_ok=True)
		cls.run_prefix = CANDIDATE_SHA[:12] + "-" + str(os.getpid())

	@classmethod
	def tearDownClass(cls):
		frappe.db.rollback()
		from audit_unified_purchase import capture_joint_state
		current = capture_joint_state(original_columns=cls.baseline["je"]["original_columns"], original_oa_columns=cls.baseline["oa"]["original_columns"],
			original_native_columns={name: value["original_columns"] for name, value in cls.baseline["native_tables"].items()})
		assert current == cls.baseline, "Retain the fixture and receipt if any upgrade drift remains"
		frappe.db.sql("delete from `tabOA Purchase Request` where name=%s and custom_purchase_source_id=%s and custom_purchase_source_json=%s", (cls.oa_name, "DLP-CROSSBORDER-RELEASE-QA-SOURCE", '{"manual":"原始 来源字节"}'))
		frappe.db.commit()
		assert capture_joint_state() == cls.unseeded, "QA fixture cleanup must restore every original byte"
		print("crossborder upgrade restored:", json.dumps({"full_state_sha256": hashlib.sha256(json.dumps(cls.unseeded, sort_keys=True).encode()).hexdigest(), "maintenance": frappe.conf.maintenance_mode, "GL": frappe.db.count("GL Entry"), "PE": frappe.db.count("Payment Entry"), "scheduler": frappe.utils.cint(frappe.db.get_single_value("System Settings", "enable_scheduler"))}), flush=True)
		frappe.destroy()

	def tearDown(self):
		frappe.db.rollback()
		if self.receipt.exists() and json.loads(self.receipt.read_bytes())["status"] != "restored":
			self.restore()
		self.assert_state_equal(self.capture(), self.original)

	def test_contract_ddl_boundaries_keep_old_records_check_defaults_and_reapply_noop(self):
		# The same adapter/receipt verifies secondary scope first; every non-native
		# byte remains outside, without installing optional apps or another site.
		full_original, full_receipt = self.original, self.receipt
		self.native_only = True
		self.original = self.capture()
		native_contract = release.load_joint_contract(native_only=True)
		self.receipt = self.evidence / (self.run_prefix + "-native-only-apply.json")
		result = release.apply_joint_metadata(CANDIDATE_SHA, self.receipt, native_only=True)
		self.assertEqual(result["ddl_boundaries"], planned_ddl_boundaries(self.original, native_contract))
		after = self.capture()
		for key in ("je", "oa", "models", "operating_singles"):
			self.assertEqual(after[key], self.original[key])
		self.assertEqual(after["metadata"]["outside_rows"], self.original["metadata"]["outside_rows"])
		self.assertEqual({row["method"] for row in after["metadata"]["scope"]["Scheduled Job Type"]}, {release.REVERSAL_METHOD})
		first = self.receipt.read_bytes()
		with patch.object(frappe.db, "sql_ddl", side_effect=AssertionError("Native-only noop attempted DDL")), patch.object(release, "_write_scope", side_effect=AssertionError("Native-only noop attempted metadata")):
			self.assertTrue(release.apply_joint_metadata(CANDIDATE_SHA, self.receipt, native_only=True)["unchanged"])
		self.assertEqual(self.receipt.read_bytes(), first)
		self.assertTrue(release.verify_current_joint_contract(native_only=True)["current_contract_verified"])
		self.verify_final_gate(after)
		self.restore()
		self.native_only = False
		self.original, self.receipt = full_original, full_receipt
		with self.assertRaises(AssertionError):
			release.verify_current_joint_contract()
		result = release.apply_joint_metadata(CANDIDATE_SHA, self.receipt)
		self.assertEqual(result["ddl_boundaries"], self.ddl_boundaries)
		self.assertTrue(result["new_fields_at_native_defaults"])
		after = self.capture()
		self.assertEqual(after["oa"]["rows"], self.original["oa"]["rows"])
		self.assertEqual(after["native_tables"], {name: dict(table, schema=after["native_tables"][name]["schema"]) for name, table in self.original["native_tables"].items()})
		self.assertEqual([row for row in after["metadata"]["scope"]["Scheduled Job Type"] if row["method"] != release.REVERSAL_METHOD], self.original_jobs)
		self.assertEqual({row["method"] for row in after["metadata"]["scope"]["Scheduled Job Type"]}, set(release.SCHEDULED_METHODS))
		self.assertEqual(after["audit"]["tables"]["Journal Entry Account"], self.original["audit"]["tables"]["Journal Entry Account"])
		self.assertEqual(frappe.db.get_value(release.OA_DOCTYPE, self.oa_name, "custom_purchase_company_confirmed"), 0)
		self.assertEqual(after["models"][release.FULFILMENT_MODEL]["schema"], self.contract["model_schemas"][release.FULFILMENT_MODEL])
		first = self.receipt.read_bytes()
		with patch.object(frappe.db, "sql_ddl", side_effect=AssertionError("Repeated apply attempted DDL")), patch.object(release, "_write_scope", side_effect=AssertionError("Repeated apply attempted metadata write")):
			self.assertTrue(release.apply_joint_metadata(CANDIDATE_SHA, self.receipt)["unchanged"])
		self.assertEqual(self.receipt.read_bytes(), first)
		with patch.object(frappe.db, "commit", side_effect=AssertionError("Read-only current verification attempted commit")):
			self.assertTrue(release.verify_current_joint_contract()["current_contract_verified"])
		# Current verification does not require pretending normal live sync is
		# quiescent, unlike a metadata cutover. It never compares old business rows.
		with patch.dict(frappe.conf, {"maintenance_mode": 0, "purchase_source_sync_enabled": True}), patch.dict(os.environ, {"DEEPLINKERP_RELEASE_QUIESCENT": "0"}):
			self.assertTrue(release.verify_current_joint_contract()["source_sync_enabled"])
		self.verify_final_gate(after)
		self.restore()

	def verify_final_gate(self, after):
		state = json.loads(self.receipt.read_bytes())
		before, fresh = copy.deepcopy(self.original["audit"]), copy.deepcopy(after["audit"])
		before.update(joint_metadata=self.original["metadata"], approved_sources_after=state["contract"]["sources_after"])
		fresh["joint_metadata"] = after["metadata"]
		release.verify_joint_audit_delta(before, fresh, state)

	def test_every_new_column_create_and_composite_index_autocommit_restores_exact_baseline(self):
		# Full apply/noop above checks every derived boundary. Inject only the
		# two new independent autocommit risks, not the old identical DDL matrix:
		# visible native TEXT and the final generated-activity composite index.
		ir_marker = "ADD INDEX `" + self.contract["native_reversal"]["activity_index"] + "`"
		cutpoints = ((True, ir_marker), (False, "ADD COLUMN `custom_purchase_pending_reason`"), (False, ir_marker))
		full_original = self.original
		for native_only, marker in cutpoints:
			with self.subTest(native_only=native_only, marker=marker):
				self.native_only = native_only
				self.original = self.capture()
				self.receipt = self.evidence / (self.run_prefix + "-crash-" + str(native_only) + "-" + hashlib.sha256(marker.encode()).hexdigest()[:12] + ".json")
				original_ddl = frappe.db.sql_ddl
				counter = [0]
				def failure(query, **kwargs):
					state = json.loads(self.receipt.read_bytes())
					self.assertEqual((state["steps"][-1]["status"], state["steps"][-1]["sql"]), ("pending", str(query)))
					original_ddl(query, **kwargs)
					counter[0] += 1
					if marker in str(query): raise RuntimeError("Synthetic crash after native autocommit")
				with patch.object(frappe.db, "sql_ddl", failure), self.assertRaisesRegex(RuntimeError, "autocommit"):
					release.apply_joint_metadata(CANDIDATE_SHA, self.receipt, native_only=native_only)
				self.restore()
		self.native_only = False
		self.original = full_original

	def test_partial_custom_field_metadata_autocommit_is_recovered_from_recorded_rows(self):
		original_sql, original_commit = frappe.db.sql, frappe.db.commit
		def failure(query, *args, **kwargs):
			result = original_sql(query, *args, **kwargs)
			if str(query).startswith("insert into `tabCustom Field`"):
				original_commit()
				raise RuntimeError("Synthetic partial metadata autocommit")
			return result
		with patch.object(frappe.db, "sql", failure), self.assertRaisesRegex(RuntimeError, "partial metadata"):
			release.apply_joint_metadata(CANDIDATE_SHA, self.receipt)
		self.restore()

	def test_confirmed_flag_or_new_link_activity_refuses_destructive_rollback(self):
		for activity in ("check", "link"):
			with self.subTest(activity=activity):
				self.receipt = self.evidence / (self.run_prefix + "-activity-" + activity + ".json")
				release.apply_joint_metadata(CANDIDATE_SHA, self.receipt)
				if activity == "check":
					frappe.db.sql("update `tabOA Purchase Request` set custom_purchase_company_confirmed=1 where name=%s", (self.oa_name,))
				else:
					frappe.db.sql("insert into `tabPurchase Fulfilment Link` (name, external_order, active) values ('DLP-CROSSBORDER-ROLLBACK-REFUSAL', 'DLP-SYNTHETIC-PO', 1)")
				frappe.db.commit()
				changed = self.capture()
				self.assertTrue(release.verify_current_joint_contract()["current_contract_verified"])
				with patch.object(frappe.db, "sql_ddl", side_effect=AssertionError("Destructive rollback with new activity")) as forbidden, self.assertRaises(AssertionError):
					release.restore_joint_metadata(self.receipt)
				forbidden.assert_not_called()
				self.assert_state_equal(self.capture(), changed)
				if activity == "check":
					frappe.db.sql("update `tabOA Purchase Request` set custom_purchase_company_confirmed=0 where name=%s and custom_purchase_company_confirmed=1", (self.oa_name,))
				else:
					frappe.db.sql("delete from `tabPurchase Fulfilment Link` where name='DLP-CROSSBORDER-ROLLBACK-REFUSAL' and external_order='DLP-SYNTHETIC-PO' and active=1")
				frappe.db.commit()
				self.restore()

	def test_enabled_sync_keeps_flag_with_locked_quiescence_and_rejects_no_proof(self):
		original = self.original
		jobs = original["metadata"]["scope"]["Scheduled Job Type"]
		self.assertEqual({row["method"] for row in jobs}, set(release.SCHEDULED_METHODS) - {release.REVERSAL_METHOD})
		self.assertEqual(len(jobs), 2)
		stamp = "2026-10-07 08:45:03.082272"
		# Reuse this enabled-sync rehearsal with the real dedicated runner's
		# logging state. Preserve every raw job byte through apply/noop/rollback.
		for job in jobs:
			frappe.db.sql("update `tabScheduled Job Type` set create_log=1, last_execution=%s where name=%s and method=%s", (stamp, job["name"], job["method"]))
		frappe.db.commit()
		logged = self.capture()
		try:
			with patch.dict(frappe.conf, {"purchase_source_sync_enabled": True}):
				self.original = self.capture()
				try:
					with patch.dict(os.environ, {"DEEPLINKERP_RELEASE_QUIESCENT": "0"}), self.assertRaisesRegex(AssertionError, "quiescence"):
						release.apply_joint_metadata(CANDIDATE_SHA, self.receipt)
					self.assertFalse(self.receipt.exists())
					self.assertTrue(release.apply_joint_metadata(CANDIDATE_SHA, self.receipt)["source_sync_enabled"])
					after = self.capture()
					self.assertEqual([row for row in after["metadata"]["scope"]["Scheduled Job Type"] if row["method"] != release.REVERSAL_METHOD], self.original["metadata"]["scope"]["Scheduled Job Type"])
					with patch.object(frappe.db, "commit", side_effect=AssertionError("Current/noop verification attempted commit")):
						self.assertTrue(release.apply_joint_metadata(CANDIDATE_SHA, self.receipt)["unchanged"])
						self.assertTrue(release.verify_current_joint_contract()["source_sync_enabled"])
					self.verify_final_gate(after)
					self.restore()
				finally:
					if self.receipt.exists() and json.loads(self.receipt.read_bytes())["status"] != "restored":
						self.restore()
		finally:
			# Never erase a retained failure or newer metadata activity.
			self.assert_state_equal(self.capture(), logged)
			for job in jobs:
				frappe.db.sql("update `tabScheduled Job Type` set create_log=%s, last_execution=%s where name=%s and method=%s and create_log=1 and last_execution=%s", (job["create_log"], job["last_execution"], job["name"], job["method"], stamp))
			frappe.db.commit()
			self.original = original
			self.assert_state_equal(self.capture(), original)


if __name__ == "__main__":
	unittest.main(verbosity=2)
