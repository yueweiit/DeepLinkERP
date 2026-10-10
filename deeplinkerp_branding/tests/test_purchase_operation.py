"""Durable native procurement operations, with an in-memory transactional audit DB."""

import hashlib
import json
import unittest
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import Mock, patch

import frappe

from deeplinkerp_branding.services import purchase_document_actions as actions
from deeplinkerp_branding.services import purchase_operation as kernel
from deeplinkerp_branding.tests._purchase_test_support import install_native_throw, install_request_state


class AuditDatabase:
	def __init__(self):
		self.rows = {}
		self.rollback = Mock(side_effect=self.rows.clear)
		self.begin = Mock()
		self.commit = Mock()
		self.before_commit = SimpleNamespace(add=Mock())
		self.after_rollback = SimpleNamespace(add=Mock())

	def get_values(self, doctype, filters, fields, **kwargs):
		assert doctype == "Integration Request"
		assert kwargs.get("for_update"), "Idempotency must use a current locking read"
		row = self.rows.get(filters.get("name"))
		return [row] if row else []

	def set_value(self, doctype, name, values, **kwargs):
		self.rows[name].update(values)

	def audit(self, values):
		row = frappe._dict(values)
		row.db_insert = lambda: self.rows.setdefault(row.name, row)
		return row


class DurableOperationTests(unittest.TestCase):
	def setUp(self):
		install_request_state(self)
		install_native_throw(self)
		self.db = AuditDatabase()
		# Audit storage is intentionally in-memory; do not infer physical
		# session evidence from it. Dedicated session/native tests own that.
		guard = patch(
			"deeplinkerp_branding.services.purchase_repost_boundary.execution", return_value=nullcontext()
		)
		guard.start()
		self.addCleanup(guard.stop)
		self.cache_values = {}
		self.cache = SimpleNamespace(
			lock=lambda *a, **kw: nullcontext(),
			get_value=self.cache_values.get,
			set_value=lambda key, value, **kw: self.cache_values.update({key: value}),
			delete_value=lambda key: self.cache_values.pop(key, None),
		)
		self.doc = frappe._dict(
			doctype="Payment Entry",
			name="PE",
			docstatus=0,
			company="C",
			paid_amount=10,
			paid_from_account_currency="CNY",
			references=[],
		)
		self.doc.check_permission = Mock()
		self.result = {
			"document": {
				"doctype": "Payment Entry",
				"name": "PE",
				"docstatus": 0,
				"amount": 10,
				"currency": "CNY",
			}
		}
		self.stack = [
			patch.object(frappe, "session", SimpleNamespace(user="QA")),
			patch.object(frappe, "db", self.db),
			patch.object(frappe, "cache", return_value=self.cache),
			patch.object(frappe, "get_doc", side_effect=self.db.audit),
			patch.object(frappe, "logger", return_value=Mock()),
			patch.object(actions, "_locked", return_value=self.doc),
			patch.object(actions, "_payment", side_effect=lambda doc: dict(self.result)),
		]
		for item in self.stack:
			item.start()
			self.addCleanup(item.stop)
		self.key = "12345678-1234-1234-1234-123456789abc"

	def test_redis_loss_replays_database_success_without_native_write(self):
		operation = Mock(return_value=self.result)
		first = actions._native_request(self.key, ["PE", "original"], operation)
		self.assertEqual(len(self.db.rows), 1, "Success needs a durable Integration Request")
		audit = next(iter(self.db.rows.values()))
		self.assertEqual(audit.status, "Completed")
		self.assertEqual(
			audit.name, "DLP-PURCHASE-" + hashlib.sha256(("QA:" + self.key).encode()).hexdigest()
		)
		self.cache_values.clear()
		with patch.object(frappe, "cache", side_effect=ConnectionError("Redis unavailable")):
			second = actions._native_request(self.key, ["PE", "original"], operation)
		self.assertTrue(second["reused"])
		self.assertEqual(first["document"]["name"], second["document"]["name"])
		operation.assert_called_once()
		self.db.commit.assert_not_called()
		self.doc.check_permission.assert_any_call("write")

	def test_same_durable_key_rejects_changed_payload_after_cache_loss(self):
		actions._native_request(self.key, ["PE"], Mock(return_value=self.result))
		self.db.rollback.side_effect = None  # the original acknowledged transaction is committed
		original = next(iter(self.db.rows.values())).copy()
		self.cache_values.clear()
		changed = Mock(return_value=self.result)
		result = actions._native_request(self.key, ["different"], changed)
		self.assertTrue(result["failed"])
		self.assertEqual(next(iter(self.db.rows.values())), original)
		changed.assert_not_called()

	def test_completed_replay_rejection_is_acknowledged_but_queued_remains_unknown(self):
		kernel.run(self.key, [], lambda: {"documents": []}, lambda receipt: receipt)
		self.db.rollback.side_effect = None
		audit = next(iter(self.db.rows.values()))
		original = audit.copy()
		denied = Mock(side_effect=frappe.ValidationError("Current source changed; recheck"))
		result = kernel.run(self.key, [], Mock(), denied, acknowledge_validation=True)
		self.assertTrue(result["failed"])
		self.assertEqual(audit, original)
		audit.status = "Queued"
		denied.reset_mock()
		with self.assertRaisesRegex(frappe.ValidationError, "尚未完成"):
			kernel.run(self.key, [], Mock(), denied, acknowledge_validation=True)
		denied.assert_not_called()
		self.assertEqual(audit.status, "Queued")

	def test_zero_or_many_document_receipts_keep_primitive_result_and_source_acknowledgements(self):
		for documents in (
			[],
			[
				{"doctype": "Purchase Order", "name": "PO-1", "docstatus": 0},
				{"doctype": "Purchase Order", "name": "PO-2", "docstatus": 0},
			],
		):
			with self.subTest(count=len(documents)):
				self.db.rows.clear()
				result = {
					"documents": documents,
					"result": {"created": len(documents), "pending": 1, "until": "snapshot"},
					"acknowledgements": [{"doctype": "OA Purchase Request", "name": "OA", "version": "v1"}],
				}
				kernel.run(self.key, [], lambda: result, lambda receipt: receipt)
				receipt = json.loads(next(iter(self.db.rows.values())).output)
				self.assertEqual(receipt["result"], result["result"])
				self.assertEqual(receipt["acknowledgements"], result["acknowledgements"])
				self.assertEqual(
					[row["name"] for row in receipt["documents"]], [row["name"] for row in documents]
				)
				if not documents:
					self.assertIsNone(next(iter(self.db.rows.values())).reference_doctype)

	def test_deadlock_retries_at_most_three_whole_transactions(self):
		calls = []
		frappe.response.update(docs=[{"name": "ORIGINAL"}], marker="before")
		frappe.message_log.append("original message")

		def write():
			context = kernel.current()
			self.assertFalse(context["documents"], "Rolled-back artifacts must not survive a retry")
			self.assertFalse(context["after"])
			self.assertEqual(frappe.response, {"docs": [{"name": "ORIGINAL"}], "marker": "before"})
			self.assertEqual(frappe.message_log, ["original message"])
			calls.append(context)
			if len(calls) < 3:
				context["documents"].append({"doctype": "Payment Entry", "name": "ROLLED-BACK"})
				context["after"]["Payment Entry:ROLLED-BACK"] = {"docstatus": 0}
				frappe.response["docs"].append({"name": "ROLLED-BACK"})
				frappe.response["marker"] = "phantom success"
				frappe.message_log.append("phantom success")
				raise (
					frappe.QueryDeadlockError(Exception(1213, "deadlock"))
					if len(calls) == 1
					else frappe.QueryTimeoutError(Exception(1205, "lock timeout"))
				)
			return self.result

		operation = Mock(side_effect=write)
		result = actions._native_request(self.key, [], operation)
		self.assertEqual(result["document"]["name"], "PE")
		self.assertEqual(operation.call_count, 3)
		self.assertEqual(self.db.rollback.call_count, 2)
		self.assertEqual(len(self.db.rows), 1)
		self.db.commit.assert_not_called()

	def test_validation_rolls_back_audit_and_business_once_without_retry(self):
		operation = Mock(side_effect=frappe.ValidationError("Native rejected"))
		result = actions._native_request(self.key, [], operation)
		self.assertEqual(result, {"failed": True, "error": "Native rejected"})
		operation.assert_called_once()
		self.db.rollback.assert_called_once_with()
		self.assertEqual(self.db.rows, {})

	def test_acknowledged_permission_denial_never_returns_private_exception_text(self):
		result = actions._native_request(
			self.key, [], Mock(side_effect=frappe.PermissionError("private inaccessible record"))
		)
		self.assertTrue(result["failed"])
		self.assertNotIn("private", result["error"])

	def test_unexpected_failure_rolls_back_and_logs_only_redacted_error_type(self):
		logger = Mock()
		with patch.object(frappe, "logger", return_value=logger):
			with self.assertRaises(RuntimeError):
				actions._native_request(
					self.key, ["password=private"], Mock(side_effect=RuntimeError("password=private"))
				)
		self.db.rollback.assert_called_once_with()
		line = logger.error.call_args.args[0]
		self.assertNotIn("private", line)
		self.assertIn("RuntimeError", line)
		self.assertIn("operation_id", json.loads(line))
		self.assertEqual(json.loads(line)["error_id"], "native_runtime_failure")

	def test_rollback_failure_logs_both_types_without_shadowing_original(self):
		original = RuntimeError("private operation detail")
		logger = Mock()
		self.db.rollback.side_effect = ConnectionError("private DB detail")
		with patch.object(frappe, "logger", return_value=logger):
			with self.assertRaises(RuntimeError) as caught:
				actions._native_request(self.key, [], Mock(side_effect=original))
		self.assertIs(caught.exception, original)
		event = json.loads(logger.error.call_args.args[0])
		self.assertEqual(event["error"], "RuntimeError")
		self.assertEqual(event["rollback_error"], "ConnectionError")
		self.assertNotIn("private", logger.error.call_args.args[0])

	def test_known_invariant_failure_has_a_safe_stable_error_identifier(self):
		error = frappe.ValidationError("private operation detail")
		error.purchase_error_id = "auto_pi_permission_missing"
		logger = Mock()
		with patch.object(frappe, "logger", return_value=logger):
			kernel.runtime_log({"operation_id": "ID", "user": "QA"}, "rolled_back", error)
		self.assertEqual(json.loads(logger.error.call_args.args[0])["error_id"], "auto_pi_permission_missing")
		self.assertNotIn("private", logger.error.call_args.args[0])

	def test_initial_lock_timeout_is_retried_before_any_native_write(self):
		existing = Mock(side_effect=[Exception(1205, "timeout"), None])
		write = Mock(return_value=self.result)
		with patch.object(kernel, "_existing", existing):
			actions._native_request(self.key, [], write)
		write.assert_called_once()
		self.db.rollback.assert_called_once()

	def test_business_duplicate_is_not_retried(self):
		write = Mock(side_effect=frappe.DuplicateEntryError("business duplicate"))
		with self.assertRaises(frappe.DuplicateEntryError):
			actions._native_request(self.key, [], write)
		write.assert_called_once()

	def test_audit_primary_key_collision_replays_winner_after_full_rollback(self):
		write = Mock(return_value=self.result)
		digest = hashlib.sha256(json.dumps([], sort_keys=True, default=str).encode()).hexdigest()
		previous = frappe._dict(
			status="Completed",
			data=json.dumps({"digest": digest, "user": "QA"}),
			output=json.dumps({"doctype": "Payment Entry", "name": "PE", "permission": "write"}),
		)
		with (
			patch.object(kernel, "_existing", side_effect=[None, previous]),
			patch.object(kernel, "_reserve", side_effect=frappe.DuplicateEntryError("audit PK race")),
		):
			result = actions._native_request(self.key, [], write)
		self.assertTrue(result["reused"])
		write.assert_not_called()
		self.db.rollback.assert_called_once()

	def test_business_audit_cannot_be_deleted_or_renamed(self):
		with self.assertRaises(frappe.PermissionError):
			kernel.protect_audit(frappe._dict(integration_request_service=kernel.SERVICE))
		with patch(
			"deeplinkerp_branding.services.purchase_native_intent._namespace_identity", return_value=False
		):
			kernel.protect_audit(frappe._dict(integration_request_service="other integration"))

	def test_cross_module_trace_survives_exception_without_private_text(self):
		self.assertTrue(callable(getattr(kernel, "trace", None)), "Per-module runtime trace is missing")
		logger = Mock()
		context = {
			"operation_id": "ID",
			"user": "QA",
			"documents": [{"doctype": "Purchase Receipt", "name": "PR"}],
			"modules": [],
		}
		with patch.object(frappe, "logger", return_value=logger):
			with self.assertRaises(RuntimeError):
				kernel.trace(
					context, "Inventory", lambda: (_ for _ in ()).throw(RuntimeError("password=private"))
				)
		event = json.loads(logger.error.call_args.args[0])
		self.assertEqual(event["module"], "Inventory")
		self.assertEqual(event["result"], "failed")
		self.assertIn("elapsed_ms", event)
		self.assertNotIn("private", logger.error.call_args.args[0])

	def test_artifact_replay_checks_every_produced_document_and_ledger(self):
		from deeplinkerp_branding.services import purchase_consistency as guard

		pi = frappe._dict(doctype="Purchase Invoice", name="PI", docstatus=1, modified="version")
		receipt = {
			"artifacts": [
				{
					"doctype": "Purchase Invoice",
					"name": "PI",
					"docstatus": 1,
					"modified": "version",
					"permission": "submit",
					"evidence": "saved-evidence",
				}
			]
		}
		with (
			patch.object(frappe, "get_doc", return_value=pi),
			patch.object(frappe, "has_permission", return_value=True),
			patch.object(guard, "artifact_evidence", return_value="changed-ledger"),
		):
			with self.assertRaises(frappe.ValidationError):
				kernel.replay_artifacts(receipt)
		with (
			patch.object(frappe, "get_doc", return_value=pi),
			patch.object(
				frappe, "has_permission", side_effect=lambda doctype, ptype, **kwargs: ptype != "submit"
			),
		):
			with self.assertRaises(frappe.PermissionError):
				kernel.replay_artifacts(receipt)


if __name__ == "__main__":
	unittest.main()
