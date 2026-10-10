"""Legal-company saves against actual MariaDB locks on the synthetic QA site."""

import copy
import json
import threading
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import frappe

from deeplinkerp_branding.services import operating_expenses as service


class OperatingCompanyConcurrencyQA(unittest.TestCase):
	def setUp(self):
		if frappe.local.site != "operating-expenses-qa.localhost" or frappe.conf.db_host != "db":
			raise RuntimeError("Dedicated synthetic site only")
		frappe.set_user("Administrator")
		frappe.db.rollback()
		self.before = (frappe.db.count("GL Entry"), frappe.db.count("Payment Entry"))
		self.settings = service._settings().as_dict()
		self.names = ["qa-company-" + uuid.uuid4().hex for _ in range(2)]
		raw = json.loads(frappe.get_doc(service.SOURCE, "1001").source_json)
		self.items = []
		for name in self.names:
			item = {**raw, "source_id": name, "source_company": "QA unknown company", "version": "qa-company-v1"}
			self.items.append(item)
			service._upsert(item, {})
		settings = service._settings()
		settings.enabled = 1
		settings.cursor = None
		settings.until = None
		settings.changed_since = "2026-10-01T00:00:00Z"
		service._save(settings)
		frappe.db.commit()

	def tearDown(self):
		frappe.db.rollback()
		with service.managed_write():
			for name in self.names:
				frappe.delete_doc(service.SOURCE, name, ignore_permissions=True)
			settings = service._settings()
			settings.update({key: self.settings.get(key) for key in (
				"enabled", "company_mappings", "cursor", "until", "changed_since",
				"last_sync_at", "last_error", "preview_fingerprint",
			)})
			service._save(settings)
		frappe.db.commit()
		self.assertEqual((frappe.db.count("GL Entry"), frappe.db.count("Payment Entry")), self.before)

	def page(self, item=None):
		return {"items": [copy.deepcopy(item or self.items[0])], "end": True,
			"next_cursor": None, "until": "2026-10-10T00:00:00Z"}

	def worker(self, function):
		frappe.init(site="operating-expenses-qa.localhost", sites_path="/home/frappe/frappe-bench/sites")
		frappe.connect()
		frappe.set_user("Administrator")
		try:
			result = function()
			frappe.db.commit()
			return result
		finally:
			frappe.db.rollback()
			frappe.destroy()

	def test_remote_fetch_precedes_write_locks_and_source_is_saved_once(self):
		from frappe.model.document import Document

		locks, saves = [], []
		sql, run_method = frappe.db.sql, Document.run_method

		def observed_sql(query, *args, **kwargs):
			if "FOR UPDATE" in str(query).upper():
				locks.append(str(query))
			return sql(query, *args, **kwargs)

		def remote(params):
			self.assertFalse(locks, "External source IO must not hold database write locks")
			return self.page()

		def saved(doc, method, *args, **kwargs):
			if doc.doctype == service.SOURCE and doc.name == self.names[0] and method == "on_update":
				saves.append(doc.name)
			return run_method(doc, method, *args, **kwargs)

		with patch.object(frappe.db, "sql", side_effect=observed_sql), patch.object(service, "_source_page", side_effect=remote), patch.object(Document, "run_method", new=saved):
			result = service.save_source_company(self.names[0], "QA Operating China", "qa-company-v1")
		self.assertEqual(result, {"source_id": self.names[0], "company": "QA Operating China"})
		self.assertIn("tabSingles", locks[0])
		self.assertEqual(saves, [self.names[0]])

	def test_sync_and_company_save_complete_without_inverse_lock_deadlock(self):
		sync_locked, manual_fetched = threading.Event(), threading.Event()
		item = {**self.items[0], "version": "qa-company-v2"}

		def remote(params):
			if params.get("source_id"):
				manual_fetched.set()
			else:
				sync_locked.set()
				self.assertTrue(manual_fetched.wait(10))
			return self.page(item)

		with patch.object(service, "_source_page", side_effect=remote), patch.object(service, "_source_mode", return_value="cashier"), ThreadPoolExecutor(max_workers=1) as pool:
			future = pool.submit(self.worker, service._sync_page)
			self.assertTrue(sync_locked.wait(10))
			try:
				result = service.save_source_company(self.names[0], "QA Operating China", item["version"])
				frappe.db.commit()
			finally:
				frappe.db.rollback()
				manual_fetched.set()
			future.result(timeout=20)
		self.assertEqual(result["company"], "QA Operating China")
		self.assertEqual(service._maps(service._settings())["source:" + self.names[0]], result["company"])
		self.assertEqual(service._settings().changed_since, "2026-10-10T00:00:00Z")

	def test_two_saves_from_old_snapshots_preserve_both_company_overrides(self):
		barrier = threading.Barrier(2)
		first_request = threading.local()
		items = {item["source_id"]: item for item in self.items}

		def remote(params):
			if not getattr(first_request, "seen", False):
				first_request.seen = True
				barrier.wait(timeout=10)
			return self.page(items[params["source_id"]])

		with patch.object(service, "_source_page", side_effect=remote), ThreadPoolExecutor(max_workers=2) as pool:
			futures = [pool.submit(self.worker, lambda name=name: service.save_source_company(name, "QA Operating China", "qa-company-v1")) for name in self.names]
			results = [future.result(timeout=20) for future in futures]
		frappe.db.rollback()
		maps = service._maps(service._settings())
		for result in results:
			self.assertEqual(maps["source:" + result["source_id"]], "QA Operating China")
			self.assertEqual(frappe.db.get_value(service.SOURCE, result["source_id"], "company"), "QA Operating China")

	def test_postcondition_failure_rolls_back_company_and_mapping(self):
		original = service._upsert

		def fail_after_save(*args, **kwargs):
			original(*args, **kwargs)
			raise RuntimeError("synthetic failure after both writes")

		with patch.object(service, "_source_page", return_value=self.page()), patch.object(service, "_upsert", side_effect=fail_after_save):
			with self.assertRaisesRegex(RuntimeError, "synthetic failure"):
				service.save_source_company(self.names[0], "QA Operating China", "qa-company-v1")
		self.assertFalse(frappe.db.get_value(service.SOURCE, self.names[0], "company"))
		self.assertNotIn("source:" + self.names[0], service._maps(service._settings()))

	def test_deadlock_retries_full_transaction_and_rechecks_version(self):
		original, calls = service._save, []
		messages = list(frappe.message_log)

		def deadlock_once(doc):
			calls.append(doc.doctype)
			result = original(doc)
			if calls.count(service.SOURCE) == 1 and doc.doctype == service.SOURCE:
				frappe.message_log.append({"message": "rolled-back attempt must not reach client"})
				raise frappe.QueryDeadlockError(Exception(1213, "synthetic deadlock"))
			return result

		with patch.object(service, "_source_page", return_value=self.page()) as remote, patch.object(service, "_save", side_effect=deadlock_once):
			result = service.save_source_company(self.names[0], "QA Operating China", "qa-company-v1")
		self.assertEqual(result["company"], "QA Operating China")
		self.assertEqual(remote.call_count, 2)
		self.assertEqual(frappe.message_log, messages)
		self.assertEqual(service._maps(service._settings())["source:" + self.names[0]], result["company"])

	def test_exhausted_deadlocks_leave_no_mapping_or_source_company(self):
		with patch.object(service, "_source_page", return_value=self.page()) as remote, patch.object(service, "_save", side_effect=frappe.QueryDeadlockError("synthetic conflict")):
			with self.assertRaisesRegex(frappe.ValidationError, "法律公司未保存"):
				service.save_source_company(self.names[0], "QA Operating China", "qa-company-v1")
		self.assertEqual(remote.call_count, 3)
		self.assertFalse(frappe.db.get_value(service.SOURCE, self.names[0], "company"))
		self.assertNotIn("source:" + self.names[0], service._maps(service._settings()))

	def test_company_save_rechecks_committed_source_version_after_remote_fetch(self):
		updated = {**self.items[0], "version": "qa-newer"}
		calls = 0

		def remote(params):
			nonlocal calls
			calls += 1
			if calls == 1:
				with ThreadPoolExecutor(max_workers=1) as pool:
					pool.submit(self.worker, lambda: service._upsert(updated, {})).result(timeout=10)
				return self.page()
			return self.page(updated)

		with patch.object(service, "_source_page", side_effect=remote) as request:
			with self.assertRaisesRegex(frappe.ValidationError, "来源版本已变化"):
				service.save_source_company(self.names[0], "QA Operating China", "qa-company-v1")
		self.assertEqual(request.call_count, 2)
		self.assertEqual(frappe.db.get_value(service.SOURCE, self.names[0], "source_version"), "qa-newer")
		self.assertNotIn("source:" + self.names[0], service._maps(service._settings()))

	def test_persisted_company_mismatch_triggers_full_rollback(self):
		original = service._save

		def corrupt(doc):
			result = original(doc)
			if doc.doctype == service.SOURCE:
				frappe.db.set_value(service.SOURCE, doc.name, "company", "QA Operating Mexico")
			return result

		with patch.object(service, "_source_page", return_value=self.page()), patch.object(service, "_save", side_effect=corrupt):
			with self.assertRaisesRegex(frappe.ValidationError, "保存结果不一致"):
				service.save_source_company(self.names[0], "QA Operating China", "qa-company-v1")
		self.assertFalse(frappe.db.get_value(service.SOURCE, self.names[0], "company"))
		self.assertNotIn("source:" + self.names[0], service._maps(service._settings()))

	def test_settings_editor_preserves_overrides_saved_after_it_was_opened(self):
		with patch.object(service, "_source_page", return_value=self.page()):
			service.save_source_company(self.names[0], "QA Operating China", "qa-company-v1")
		service.save_sync_settings({"QA Operating China": "QA Operating China"})
		self.assertEqual(service._maps(service._settings())["source:" + self.names[0]], "QA Operating China")

	def test_denied_manager_does_not_fetch_source_or_retry(self):
		with patch.object(service, "_manager", side_effect=frappe.PermissionError("synthetic denied")) as permission, patch.object(service, "_source_page") as remote:
			with self.assertRaises(frappe.PermissionError):
				service.save_source_company(self.names[0], "QA Operating China", "qa-company-v1")
		permission.assert_called_once()
		remote.assert_not_called()

	def test_existing_financial_confirmation_rejects_company_change(self):
		original = frappe.db.get_value
		for doctype in (service.MAPPING, service.EVENT, "Operating Expense Takeover", "Operating Expense Payment"):
			with self.subTest(doctype=doctype):
				def existing(kind, *args, **kwargs):
					if kind == doctype:
						self.assertTrue(kwargs.get("for_update"))
						return "confirmed-id"
					return original(kind, *args, **kwargs)
				with patch.object(service, "_source_page", return_value=self.page()), patch.object(frappe.db, "get_value", side_effect=existing):
					with self.assertRaisesRegex(frappe.ValidationError, "已有财务确认"):
						service.save_source_company(self.names[0], "QA Operating China", "qa-company-v1")
				self.assertFalse(frappe.db.get_value(service.SOURCE, self.names[0], "company"))

	def test_new_financial_mapping_committed_during_fetch_blocks_company_save(self):
		def confirm():
			service._source(self.names[0], write=True)
			with service.managed_write():
				frappe.get_doc({"doctype": service.MAPPING, "source": self.names[0],
					"company": "QA Operating Mexico", "mapping_json": "{}"}).insert(ignore_permissions=True)

		def remote(params):
			with ThreadPoolExecutor(max_workers=1) as pool:
				pool.submit(self.worker, confirm).result(timeout=10)
			return self.page()

		# Current reads must work even where RR does not reject older snapshots.
		frappe.db.sql("SET SESSION innodb_snapshot_isolation = OFF")
		try:
			with patch.object(service, "_source_page", side_effect=remote) as request:
				with self.assertRaisesRegex(frappe.ValidationError, "已有财务确认"):
					service.save_source_company(self.names[0], "QA Operating China", "qa-company-v1")
			self.assertEqual(request.call_count, 1)
			self.assertFalse(frappe.db.get_value(service.SOURCE, self.names[0], "company"))
			self.assertNotIn("source:" + self.names[0], service._maps(service._settings()))
		finally:
			frappe.db.rollback()
			frappe.db.sql("SET SESSION innodb_snapshot_isolation = ON")
			with service.managed_write():
				frappe.delete_doc(service.MAPPING, self.names[0], ignore_permissions=True)
			frappe.db.commit()

	def test_changed_source_credential_during_fetch_blocks_company_save(self):
		token_key = {"doctype": service.SETTINGS, "name": service.SETTINGS,
			"fieldname": "api_token", "encrypted": 1}
		original_token = frappe.db.get_value("__Auth", token_key, "password", order_by=None)

		def rotate():
			settings = service._settings(for_update=True)
			settings.api_token = "qa-rotated-" + uuid.uuid4().hex
			service._save(settings)

		def remote(params):
			with ThreadPoolExecutor(max_workers=1) as pool:
				pool.submit(self.worker, rotate).result(timeout=10)
			return self.page()

		frappe.db.sql("SET SESSION innodb_snapshot_isolation = OFF")
		try:
			with patch.object(service, "_source_page", side_effect=remote) as request:
				with self.assertRaisesRegex(frappe.ValidationError, "同步设置已变化"):
					service.save_source_company(self.names[0], "QA Operating China", "qa-company-v1")
			self.assertEqual(request.call_count, 1)
			self.assertFalse(frappe.db.get_value(service.SOURCE, self.names[0], "company"))
			self.assertNotIn("source:" + self.names[0], service._maps(service._settings()))
		finally:
			frappe.db.rollback()
			frappe.db.sql("SET SESSION innodb_snapshot_isolation = ON")
			frappe.db.sql("UPDATE __Auth SET password=%s WHERE doctype=%s AND name=%s AND fieldname='api_token' AND encrypted=1",
				(original_token, service.SETTINGS, service.SETTINGS))
			frappe.db.commit()

	def test_stale_source_is_not_retried_and_manual_company_survives_sync(self):
		with patch.object(service, "_source_page", return_value=self.page()) as remote:
			with self.assertRaises(frappe.ValidationError):
				service.save_source_company(self.names[0], "QA Operating China", "stale-version")
			self.assertEqual(remote.call_count, 1)
			service.save_source_company(self.names[0], "QA Operating China", "qa-company-v1")
		updated = service._upsert({**self.items[0], "version": "qa-company-v2"}, {})
		self.assertEqual(updated.company, "QA Operating China")


def run():
	result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(OperatingCompanyConcurrencyQA))
	if not result.wasSuccessful():
		raise AssertionError("Legal-company native regression failed")
	return {"tests": result.testsRun, "failures": 0, "errors": 0}
