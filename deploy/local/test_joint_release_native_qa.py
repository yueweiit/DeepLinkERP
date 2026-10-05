"""Real MariaDB/Frappe rehearsal, ONLY the dedicated maintenance-mode site.

Run in dlp-operating-release-qa-backend-1 with the reviewed package mounted.
The helper never submits a voucher, invokes source sync, or contacts production.
"""

import copy
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
		cls.run_prefix = str(os.getpid())

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
		return capture_joint_state(original_columns=self.baseline["je"]["original_columns"])

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


if __name__ == "__main__":
	unittest.main(verbosity=2)
