import unittest
from unittest.mock import patch

import frappe

from china_finance.services.cash_flow_assignment import cancel_assignments_for_source
from china_finance.services.voucher import _ensure_cancellation_sync_issue, on_gl_source_cancel, process_cancellation_snapshot


class TestCancellationSync(unittest.TestCase):
	def setUp(self):
		self.prefix = "CF_CANCEL_" + frappe.generate_hash(length=10)
		frappe.db.savepoint(self.prefix)
		self.addCleanup(frappe.db.rollback, save_point=self.prefix)
		self.company = self.insert("Company", company_name=self.prefix, abbr=self.prefix[-5:], default_currency="CNY")
		self.source = self.insert("Payment Entry", company=self.company, posting_date="2026-07-01", docstatus=2)
		self.voucher = self.insert(
			"China Accounting Voucher", company=self.company, posting_date="2026-07-01",
			source_doctype="Payment Entry", source_name=self.source, source_event="Posting",
			source_key=f"Posting|Payment Entry|{self.source}", docstatus=1, status="Posted",
		)
		self.account = self.insert("Account", company=self.company, account_name=self.prefix)
		self.issue = self.insert(
			"China Voucher Sync Issue", company=self.company, source_doctype="Payment Entry",
			source_name=self.source, issue_key=self.prefix + "|Cancellation", status="Pending", retry_count=0,
		)

	def insert(self, doctype, **values):
		doc = frappe.get_doc({"doctype": doctype, "name": self.prefix + "-" + frappe.generate_hash(length=8), **values})
		doc.db_insert()
		return doc.name

	def assignment(self, docstatus=0, missing_gl=True):
		gl_entry = self.prefix + "-historical-gl"
		if not missing_gl:
			gl_entry = self.insert("GL Entry", company=self.company, voucher_type="Payment Entry", voucher_no=self.source, is_cancelled=1)
		name = self.insert(
			"China Cash Flow Assignment", company=self.company, currency="CNY", posting_date="2026-07-01",
			naming_series="CCFA-.YYYY.-.#####", china_accounting_voucher=self.voucher,
			source_doctype="Payment Entry", source_name=self.source, revision=1,
			status="Confirmed" if docstatus else "Draft", docstatus=docstatus,
		)
		self.insert(
			"China Cash Flow Assignment Item", parent=name, parenttype="China Cash Flow Assignment",
			parentfield="items", idx=1, gl_entry=gl_entry, cash_account=self.account,
			cash_direction="付款", cash_amount=100, assigned_amount=100,
			cash_flow_row_code="CASH_TEST", remarks="Historical allocation evidence",
		)
		return name

	def test_cancel_draft_with_deleted_gl_preserves_audit_items(self):
		name = self.assignment()
		before = frappe.get_doc("China Cash Flow Assignment", name).items[0].as_dict()
		cancel_assignments_for_source(frappe.get_doc("Payment Entry", self.source))
		doc = frappe.get_doc("China Cash Flow Assignment", name)
		self.assertEqual(doc.status, "Cancelled")
		self.assertEqual(doc.docstatus, 0)
		for field in ("name", "gl_entry", "cash_flow_row_code", "assigned_amount", "remarks"):
			self.assertEqual(doc.items[0].get(field), before[field])
		stamp = doc.cancelled_on
		cancel_assignments_for_source(frappe.get_doc("Payment Entry", self.source))
		self.assertEqual(frappe.get_doc("China Cash Flow Assignment", name).cancelled_on, stamp)

	def test_cancel_draft_with_cancelled_source_link(self):
		name = self.assignment(missing_gl=False)
		cancel_assignments_for_source(frappe.get_doc("Payment Entry", self.source))
		self.assertEqual(frappe.db.get_value("China Cash Flow Assignment", name, "status"), "Cancelled")

	def test_submitted_assignment_uses_native_cancel(self):
		name = self.assignment(docstatus=1)
		cancel_assignments_for_source(frappe.get_doc("Payment Entry", self.source))
		self.assertEqual(frappe.db.get_value("China Cash Flow Assignment", name, ["status", "docstatus"]), ("Cancelled", 2))

	def test_service_rejects_fake_cancelled_source(self):
		name = self.assignment(docstatus=1)
		frappe.db.set_value("Payment Entry", self.source, "docstatus", 1)
		with self.assertRaises(frappe.ValidationError):
			cancel_assignments_for_source(frappe._dict(doctype="Payment Entry", name=self.source, docstatus=2))
		self.assertEqual(frappe.db.get_value("China Cash Flow Assignment", name, "status"), "Confirmed")

	def test_service_rejects_unsupported_source(self):
		with self.assertRaises(frappe.ValidationError):
			cancel_assignments_for_source(frappe._dict(doctype="Company", name=self.company, docstatus=2))

	def test_snapshot_failure_rolls_back_assignment_and_snapshot_changes(self):
		name = self.assignment(docstatus=1)
		draft = self.assignment()
		def fail_snapshot(*args):
			frappe.db.set_value("China Accounting Voucher", self.voucher, "status", "Reversed")
			raise frappe.ValidationError("snapshot failure after partial write")
		with patch("china_finance.services.voucher.create_voucher_from_source", side_effect=fail_snapshot):
			result = process_cancellation_snapshot("Payment Entry", self.source, self.issue)
		self.assertEqual(result["status"], "pending")
		self.assertEqual(frappe.db.get_value("China Cash Flow Assignment", name, ["status", "docstatus"]), ("Confirmed", 1))
		self.assertEqual(frappe.db.get_value("China Cash Flow Assignment", draft, "status"), "Draft")
		self.assertEqual(frappe.db.get_value("China Accounting Voucher", self.voucher, "status"), "Posted")
		issue = frappe.get_doc("China Voucher Sync Issue", self.issue)
		self.assertEqual(issue.retry_count, 1)
		self.assertIn("snapshot failure", issue.last_error)

	def test_regular_draft_save_still_rejects_missing_links(self):
		doc = frappe.get_doc("China Cash Flow Assignment", self.assignment())
		doc.flags.ignore_permissions = True
		with self.assertRaisesRegex(frappe.LinkValidationError, "historical-gl"):
			doc.save()

	def test_regular_draft_save_still_rejects_cancelled_source(self):
		doc = frappe.get_doc("China Cash Flow Assignment", self.assignment(missing_gl=False))
		doc.flags.ignore_permissions = True
		with self.assertRaisesRegex(frappe.CancelledLinkError, "Cannot link cancelled document"):
			doc.save()

	def test_process_creates_its_own_issue_for_cancelled_source(self):
		self.snapshot_entries()
		with patch("china_finance.services.voucher.get_company_settings", return_value=frappe._dict(activation_date="2026-01-01")):
			result = process_cancellation_snapshot("Payment Entry", self.source)
		self.assertEqual(result["status"], "resolved", result)
		self.assertEqual(frappe.db.get_value("China Voucher Sync Issue", result["issue"], "source_name"), self.source)

	def test_cancel_hook_creates_pending_issue_and_enqueues_after_commit(self):
		with patch("china_finance.services.voucher.get_company_settings", return_value=frappe._dict(activation_date="2026-01-01")), patch("frappe.enqueue") as enqueue:
			on_gl_source_cancel(frappe.get_doc("Payment Entry", self.source))
		issue = frappe.db.get_value("China Voucher Sync Issue", {"issue_key": f"Cancellation|Payment Entry|{self.source}"}, ["name", "status"])
		self.assertEqual(issue[1], "Pending")
		self.assertTrue(enqueue.call_args.kwargs["enqueue_after_commit"])
		self.assertEqual(enqueue.call_args.kwargs["issue_name"], issue[0])

	def test_issue_creation_requires_persisted_supported_cancelled_source(self):
		frappe.db.set_value("Payment Entry", self.source, "docstatus", 1)
		doc = frappe.get_doc("Payment Entry", self.source)
		doc.docstatus = 2
		with self.assertRaises(frappe.ValidationError):
			_ensure_cancellation_sync_issue(doc)
		with self.assertRaises(frappe.ValidationError):
			_ensure_cancellation_sync_issue(frappe.get_doc("Company", self.company))

	def test_cancel_hook_issue_creation_failure_cannot_undo_native_cancellation(self):
		def fail_issue(*args):
			frappe.db.set_value("China Accounting Voucher", self.voucher, "status", "Reversed")
			raise frappe.ValidationError("issue insertion failed")
		with patch("china_finance.services.voucher.get_company_settings", return_value=frappe._dict(activation_date="2026-01-01")), patch("china_finance.services.voucher._ensure_cancellation_sync_issue", side_effect=fail_issue), patch("frappe.enqueue") as enqueue, patch("frappe.log_error") as log:
			on_gl_source_cancel(frappe.get_doc("Payment Entry", self.source))
		self.assertEqual(frappe.db.get_value("Payment Entry", self.source, "docstatus"), 2)
		self.assertEqual(frappe.db.get_value("China Accounting Voucher", self.voucher, "status"), "Posted")
		enqueue.assert_not_called()
		self.assertIn("创建失败", log.call_args.kwargs["title"])

	def test_cancel_hook_enqueue_failure_preserves_retry_issue(self):
		with patch("china_finance.services.voucher.get_company_settings", return_value=frappe._dict(activation_date="2026-01-01")), patch("frappe.enqueue", side_effect=RuntimeError("queue unavailable")), patch("frappe.log_error") as log:
			on_gl_source_cancel(frappe.get_doc("Payment Entry", self.source))
		issue = frappe.get_doc("China Voucher Sync Issue", {"issue_key": f"Cancellation|Payment Entry|{self.source}"})
		self.assertEqual(issue.status, "Pending")
		self.assertEqual(issue.last_error, "queue unavailable")
		self.assertIn("排队失败", log.call_args.kwargs["title"])

	def test_cancel_hook_retryable_creation_error_is_not_shadowed_by_savepoint_cleanup(self):
		for error_type in (frappe.QueryDeadlockError, frappe.QueryTimeoutError):
			with patch("china_finance.services.voucher.get_company_settings", return_value=frappe._dict(activation_date="2026-01-01")), patch("china_finance.services.voucher._ensure_cancellation_sync_issue", side_effect=lambda *args: frappe.throw("original retryable creation error", error_type)), patch.object(frappe.db, "rollback", side_effect=RuntimeError("missing savepoint")) as rollback, patch.object(frappe.db, "release_savepoint", side_effect=RuntimeError("missing savepoint")) as release:
				with self.assertRaisesRegex(error_type, "original retryable creation error"):
					on_gl_source_cancel(frappe.get_doc("Payment Entry", self.source))
			rollback.assert_not_called()
			release.assert_not_called()

	def test_cancel_hook_retryable_enqueue_error_propagates_without_recording_pending(self):
		with patch("china_finance.services.voucher.get_company_settings", return_value=frappe._dict(activation_date="2026-01-01")), patch("frappe.enqueue", side_effect=lambda *args, **kwargs: frappe.throw("retryable queue database error", frappe.QueryDeadlockError)), patch("china_finance.services.voucher._record_sync_failure") as record:
			with self.assertRaisesRegex(frappe.QueryDeadlockError, "retryable queue database error"):
				on_gl_source_cancel(frappe.get_doc("Payment Entry", self.source))
		record.assert_not_called()

	def test_cancel_hook_retryable_failure_while_recording_queue_error_propagates(self):
		error = frappe.QueryTimeoutError("retryable issue update timeout")
		with patch("china_finance.services.voucher.get_company_settings", return_value=frappe._dict(activation_date="2026-01-01")), patch("frappe.enqueue", side_effect=RuntimeError("queue unavailable")), patch("china_finance.services.voucher._record_sync_failure", side_effect=error):
			with self.assertRaises(frappe.QueryTimeoutError) as raised:
				on_gl_source_cancel(frappe.get_doc("Payment Entry", self.source))
		self.assertIs(raised.exception, error)

	def test_handled_audit_failures_do_not_emit_error_dialogs(self):
		before = list(frappe.local.message_log)
		previous = frappe.flags.mute_messages
		for target, callback in (
			("china_finance.services.voucher._ensure_cancellation_sync_issue", lambda: on_gl_source_cancel(frappe.get_doc("Payment Entry", self.source))),
			("frappe.enqueue", lambda: on_gl_source_cancel(frappe.get_doc("Payment Entry", self.source))),
			("china_finance.services.voucher.create_voucher_from_source", self.process_with_settings),
		):
			with patch("china_finance.services.voucher.get_company_settings", return_value=frappe._dict(activation_date="2026-01-01")), patch(target, side_effect=lambda *args, **kwargs: frappe.throw("handled audit error")), patch("frappe.log_error"):
				callback()
			self.assertEqual(list(frappe.local.message_log), before)
			self.assertEqual(frappe.flags.mute_messages, previous)
		with self.assertRaises(frappe.ValidationError):
			frappe.throw("native validation outside audit")
		self.assertEqual(len(frappe.local.message_log), len(before) + 1)
		frappe.local.message_log[:] = before

	def test_handled_failure_restores_preexisting_message_mute_flag(self):
		previous = frappe.flags.mute_messages
		frappe.flags.mute_messages = True
		try:
			with patch("china_finance.services.voucher.create_voucher_from_source", side_effect=lambda *args: frappe.throw("muted error")), patch("frappe.log_error"):
				self.process_with_settings()
			self.assertTrue(frappe.flags.mute_messages)
		finally:
			frappe.flags.mute_messages = previous

	def test_retryable_snapshot_failure_preserves_exception_for_transaction_owner(self):
		for error_type in (frappe.QueryDeadlockError, frappe.QueryTimeoutError):
			error = error_type("retryable database concurrency error")
			with patch("china_finance.services.voucher.create_voucher_from_source", side_effect=error), patch("china_finance.services.voucher._record_sync_failure") as record:
				with self.assertRaises(error_type) as raised:
					self.process_with_settings()
			self.assertIs(raised.exception, error)
			record.assert_not_called()

	def test_background_adapter_uses_existing_bounded_worker_retry(self):
		from china_finance.services import voucher
		self.assertTrue(hasattr(voucher, "process_cancellation_snapshot_job"))
		error = frappe.QueryDeadlockError("Maria 1020")
		with patch("china_finance.services.voucher.process_cancellation_snapshot", side_effect=error), patch.object(frappe.db, "commit") as commit, patch.object(frappe.db, "rollback") as rollback:
			with self.assertRaises(frappe.RetryBackgroundJobError) as raised:
				voucher.process_cancellation_snapshot_job("Payment Entry", self.source, self.issue)
		self.assertIs(raised.exception.__cause__, error)
		commit.assert_not_called()
		rollback.assert_not_called()

	def test_snapshot_failure_handler_preserves_retryable_errors(self):
		for target in ("rollback", "record", "log"):
			error = frappe.QueryDeadlockError("original failure handler deadlock")
			if target == "rollback":
				failure = patch.object(frappe.db, "rollback", side_effect=error)
			elif target == "record":
				failure = patch("china_finance.services.voucher._record_sync_failure", side_effect=error)
			else:
				failure = patch("frappe.log_error", side_effect=error)
			with patch("china_finance.services.voucher.create_voucher_from_source", side_effect=frappe.ValidationError("ordinary snapshot failure")), failure, patch.object(frappe.db, "release_savepoint", side_effect=RuntimeError("missing savepoint")) as release:
				with self.assertRaises(frappe.QueryDeadlockError) as raised:
					self.process_with_settings()
			self.assertIs(raised.exception, error)
			release.assert_not_called()

	def test_failure_handler_deadlock_reaches_background_retry_adapter(self):
		from china_finance.services.voucher import process_cancellation_snapshot_job
		error = frappe.QueryDeadlockError("issue failure recording deadlock")
		with patch("china_finance.services.voucher.get_company_settings", return_value=frappe._dict(activation_date="2026-01-01")), patch("china_finance.services.voucher.create_voucher_from_source", side_effect=frappe.ValidationError("ordinary snapshot failure")), patch("china_finance.services.voucher._record_sync_failure", side_effect=error), patch.object(frappe.db, "release_savepoint", side_effect=RuntimeError("missing savepoint")) as release:
			with self.assertRaises(frappe.RetryBackgroundJobError) as raised:
				process_cancellation_snapshot_job("Payment Entry", self.source, self.issue)
		self.assertIs(raised.exception.__cause__, error)
		release.assert_not_called()

	def test_native_hook_failure_handler_preserves_retryable_errors(self):
		for target in ("rollback", "log"):
			error = frappe.QueryTimeoutError("original native hook handler timeout")
			failure = patch.object(frappe.db, "rollback", side_effect=error) if target == "rollback" else patch("frappe.log_error", side_effect=error)
			with patch("china_finance.services.voucher.get_company_settings", return_value=frappe._dict(activation_date="2026-01-01")), patch("china_finance.services.voucher._ensure_cancellation_sync_issue", side_effect=frappe.ValidationError("ordinary issue creation failure")), failure, patch.object(frappe.db, "release_savepoint", side_effect=RuntimeError("missing savepoint")) as release:
				with self.assertRaises(frappe.QueryTimeoutError) as raised:
					on_gl_source_cancel(frappe.get_doc("Payment Entry", self.source))
			self.assertIs(raised.exception, error)
			release.assert_not_called()

	def snapshot_entries(self):
		for idx, values in enumerate(({"debit": 100, "credit": 0}, {"debit": 0, "credit": 100}), 1):
			self.insert(
				"China Accounting Voucher Entry", parent=self.voucher, parenttype="China Accounting Voucher",
				parentfield="entries", idx=idx, account=self.account, account_currency="CNY", **values,
			)

	def process_with_settings(self):
		# No settings are written. Only this fixture company's lookup is patched.
		with patch("china_finance.services.voucher.get_company_settings", return_value=frappe._dict(activation_date="2026-01-01")):
			return process_cancellation_snapshot("Payment Entry", self.source, self.issue)

	def test_real_snapshot_retry_is_idempotent_after_historical_gl_removal(self):
		self.snapshot_entries()
		name = self.assignment()
		before_gl = frappe.db.count("GL Entry")
		before_sequence = frappe.db.count("China Voucher Sequence")
		first = self.process_with_settings()
		self.assertEqual(first["status"], "resolved", first)
		second = self.process_with_settings()
		self.assertEqual(second["voucher"], first["voucher"])
		self.assertEqual(frappe.db.count("China Accounting Voucher", {"source_key": f"Cancellation|Payment Entry|{self.source}"}), 1)
		self.assertEqual(frappe.db.get_value("China Accounting Voucher", self.voucher, ["status", "reversed_by"]), ("Reversed", first["voucher"]))
		self.assertEqual(frappe.db.get_value("China Cash Flow Assignment", name, "status"), "Cancelled")
		self.assertEqual(frappe.db.get_value("Payment Entry", self.source, "docstatus"), 2)
		self.assertEqual(frappe.db.count("GL Entry"), before_gl)
		self.assertEqual(frappe.db.count("China Voucher Sequence"), before_sequence)
		self.assertEqual(frappe.db.get_value("China Accounting Voucher", first["voucher"], ["docstatus", "sequence_number"]), (1, 0))
		self.assertEqual(frappe.db.get_value("China Voucher Sync Issue", self.issue, "retry_count"), 1)

	def test_resolved_issue_with_active_assignment_does_not_skip_cleanup(self):
		self.snapshot_entries()
		first = self.process_with_settings()
		name = self.assignment()
		second = self.process_with_settings()
		self.assertEqual(second["status"], "resolved", second)
		self.assertEqual(second["voucher"], first["voucher"])
		self.assertEqual(frappe.db.get_value("China Cash Flow Assignment", name, "status"), "Cancelled")
		self.assertEqual(frappe.db.get_value("China Voucher Sync Issue", self.issue, "retry_count"), 2)

	def test_resolved_issue_with_draft_snapshot_stays_pending(self):
		self.snapshot_entries()
		first = self.process_with_settings()
		frappe.db.set_value("China Accounting Voucher", first["voucher"], "docstatus", 0)
		result = self.process_with_settings()
		self.assertEqual(result["status"], "pending", result)
		self.assertEqual(frappe.db.get_value("China Voucher Sync Issue", self.issue, "status"), "Pending")

	def test_snapshot_with_missing_or_wrong_reversal_origin_stays_pending(self):
		self.snapshot_entries()
		first = self.process_with_settings()
		for invalid_origin in (None, self.prefix + "-Foreign Posting"):
			frappe.db.set_value("China Accounting Voucher", first["voucher"], "reversal_of", invalid_origin)
			result = self.process_with_settings()
			self.assertEqual(result["status"], "pending", result)
			self.assertEqual(frappe.db.get_value("China Voucher Sync Issue", self.issue, "status"), "Pending")
		frappe.db.set_value("China Accounting Voucher", first["voucher"], "reversal_of", self.voucher)
		self.assertEqual(self.process_with_settings()["status"], "resolved")

	def test_snapshot_without_original_requires_empty_reversal_origin(self):
		frappe.db.delete("China Accounting Voucher", {"name": self.voucher})
		for debit, credit in ((0, 100), (100, 0)):
			self.insert("GL Entry", company=self.company, voucher_type="Payment Entry", voucher_no=self.source, account=self.account, account_currency="CNY", is_cancelled=1, debit=debit, credit=credit)
		first = self.process_with_settings()
		self.assertEqual(first["status"], "resolved", first)
		self.assertIsNone(frappe.db.get_value("China Accounting Voucher", first["voucher"], "reversal_of"))
		self.assertEqual(self.process_with_settings()["status"], "resolved")
		frappe.db.set_value("China Accounting Voucher", first["voucher"], "reversal_of", self.prefix + "-Foreign Posting")
		self.assertEqual(self.process_with_settings()["status"], "pending")

	def test_pending_existing_snapshot_retry_remains_correct(self):
		self.snapshot_entries()
		first = self.process_with_settings()
		frappe.db.set_value("China Voucher Sync Issue", self.issue, "status", "Pending")
		result = self.process_with_settings()
		self.assertEqual(result["status"], "resolved", result)
		self.assertEqual(result["voucher"], first["voucher"])
		self.assertEqual(frappe.db.get_value("China Voucher Sync Issue", self.issue, "retry_count"), 2)

	def test_missing_reversal_entries_remains_pending_without_partial_cleanup(self):
		name = self.assignment()
		result = self.process_with_settings()
		self.assertEqual(result["status"], "pending")
		self.assertEqual(frappe.db.get_value("China Cash Flow Assignment", name, "status"), "Draft")
		self.assertEqual(frappe.db.get_value("China Accounting Voucher", self.voucher, "status"), "Posted")
		self.assertEqual(frappe.db.get_value("Payment Entry", self.source, "docstatus"), 2)

	def test_retained_cancelled_gl_rows_are_read_without_reposting(self):
		gl_names = [
			self.insert(
				"GL Entry", company=self.company, voucher_type="Payment Entry", voucher_no=self.source,
				account=self.account, account_currency="CNY", is_cancelled=1, debit=debit, credit=credit,
			)
			for debit, credit in ((0, 100), (100, 0))
		]
		before = [frappe.get_doc("GL Entry", name).as_dict() for name in gl_names]
		count = frappe.db.count("GL Entry")
		result = self.process_with_settings()
		self.assertEqual(result["status"], "resolved", result)
		self.assertEqual([frappe.get_doc("GL Entry", name).as_dict() for name in gl_names], before)
		self.assertEqual(frappe.db.count("GL Entry"), count)
		doc = frappe.get_doc("China Accounting Voucher", result["voucher"])
		self.assertEqual({row.gl_entry for row in doc.entries}, set(gl_names))

	def test_uncancelled_source_retry_remains_pending_without_audit_writes(self):
		name = self.assignment(docstatus=1)
		frappe.db.set_value("Payment Entry", self.source, "docstatus", 1)
		result = self.process_with_settings()
		self.assertEqual(result["status"], "pending")
		self.assertEqual(frappe.db.get_value("China Cash Flow Assignment", name, ["status", "docstatus"]), ("Confirmed", 1))
		self.assertEqual(frappe.db.get_value("China Accounting Voucher", self.voucher, "status"), "Posted")

	def test_unrelated_sync_issue_cannot_be_resolved(self):
		self.snapshot_entries()
		frappe.db.set_value("China Voucher Sync Issue", self.issue, "source_name", "unrelated-source")
		with self.assertRaises(frappe.ValidationError):
			self.process_with_settings()
		self.assertEqual(frappe.db.get_value("China Voucher Sync Issue", self.issue, ["status", "retry_count"]), ("Pending", 0))

	def test_failure_after_real_snapshot_creation_rolls_back_snapshot(self):
		from china_finance.services.voucher import create_voucher_from_source
		self.snapshot_entries()
		name = self.assignment()
		def fail_after_creation(*args):
			create_voucher_from_source(*args)
			raise frappe.ValidationError("failure after snapshot insertion")
		with patch("china_finance.services.voucher.create_voucher_from_source", side_effect=fail_after_creation):
			result = self.process_with_settings()
		self.assertEqual(result["status"], "pending")
		self.assertFalse(frappe.db.exists("China Accounting Voucher", {"source_key": f"Cancellation|Payment Entry|{self.source}"}))
		self.assertEqual(frappe.db.get_value("China Accounting Voucher", self.voucher, ["status", "reversed_by"]), ("Posted", None))
		self.assertEqual(frappe.db.get_value("China Cash Flow Assignment", name, "status"), "Draft")
		self.assertEqual(self.process_with_settings()["status"], "resolved")
