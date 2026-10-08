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
        self.db = AuditDatabase()
        self.cache_values = {}
        self.cache = SimpleNamespace(lock=lambda *a, **kw: nullcontext(),
            get_value=self.cache_values.get, set_value=lambda key, value, **kw: self.cache_values.update({key: value}),
            delete_value=lambda key: self.cache_values.pop(key, None))
        self.doc = frappe._dict(doctype="Payment Entry", name="PE", docstatus=0, company="C",
            paid_amount=10, paid_from_account_currency="CNY", references=[])
        self.doc.check_permission = Mock()
        self.result = {"document": {"doctype": "Payment Entry", "name": "PE", "docstatus": 0, "amount": 10, "currency": "CNY"}}
        self.stack = [patch.object(frappe, "session", SimpleNamespace(user="QA")),
            patch.object(frappe, "flags", frappe._dict()), patch.object(frappe, "db", self.db),
            patch.object(frappe, "cache", return_value=self.cache),
            patch.object(frappe, "get_doc", side_effect=self.db.audit),
            patch.object(frappe, "logger", return_value=Mock()),
            patch.object(actions, "_locked", return_value=self.doc),
            patch.object(actions, "_payment", side_effect=lambda doc: dict(self.result)),
            patch.object(frappe, "throw", side_effect=lambda message, exc=frappe.ValidationError: (_ for _ in ()).throw(exc(message)))]
        for item in self.stack:
            item.start(); self.addCleanup(item.stop)
        self.key = "12345678-1234-1234-1234-123456789abc"

    def test_redis_loss_replays_database_success_without_native_write(self):
        operation = Mock(return_value=self.result)
        first = actions._native_request(self.key, ["PE", "original"], operation)
        self.assertEqual(len(self.db.rows), 1, "Success needs a durable Integration Request")
        audit = next(iter(self.db.rows.values()))
        self.assertEqual(audit.status, "Completed")
        self.assertEqual(audit.name, "DLP-PURCHASE-" + hashlib.sha256(("QA:" + self.key).encode()).hexdigest())
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
        self.cache_values.clear()
        changed = Mock(return_value=self.result)
        with self.assertRaises(frappe.ValidationError):
            actions._native_request(self.key, ["different"], changed)
        changed.assert_not_called()

    def test_deadlock_retries_at_most_three_whole_transactions(self):
        operation = Mock(side_effect=[frappe.QueryDeadlockError(Exception(1213, "deadlock")),
            frappe.QueryTimeoutError(Exception(1205, "lock timeout")), self.result])
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

    def test_unexpected_failure_rolls_back_and_logs_only_redacted_error_type(self):
        logger = Mock()
        with patch.object(frappe, "logger", return_value=logger):
            with self.assertRaises(RuntimeError):
                actions._native_request(self.key, ["password=private"], Mock(side_effect=RuntimeError("password=private")))
        self.db.rollback.assert_called_once_with()
        line = logger.error.call_args.args[0]
        self.assertNotIn("private", line)
        self.assertIn("RuntimeError", line)
        self.assertIn("operation_id", json.loads(line))

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
        previous = frappe._dict(status="Completed", data=json.dumps({"digest": digest, "user": "QA"}),
            output=json.dumps({"doctype": "Payment Entry", "name": "PE", "permission": "write"}))
        with patch.object(kernel, "_existing", side_effect=[None, previous]), \
             patch.object(kernel, "_reserve", side_effect=frappe.DuplicateEntryError("audit PK race")):
            result = actions._native_request(self.key, [], write)
        self.assertTrue(result["reused"])
        write.assert_not_called()
        self.db.rollback.assert_called_once()

    def test_business_audit_cannot_be_deleted_or_renamed(self):
        with self.assertRaises(frappe.PermissionError):
            kernel.protect_audit(frappe._dict(integration_request_service=kernel.SERVICE))
        kernel.protect_audit(frappe._dict(integration_request_service="other integration"))

    def test_cross_module_trace_survives_exception_without_private_text(self):
        self.assertTrue(callable(getattr(kernel, "trace", None)), "Per-module runtime trace is missing")
        logger = Mock()
        context = {"operation_id": "ID", "user": "QA", "documents": [{"doctype": "Purchase Receipt", "name": "PR"}], "modules": []}
        with patch.object(frappe, "logger", return_value=logger):
            with self.assertRaises(RuntimeError):
                kernel.trace(context, "Inventory", lambda: (_ for _ in ()).throw(RuntimeError("password=private")))
        event = json.loads(logger.error.call_args.args[0])
        self.assertEqual(event["module"], "Inventory")
        self.assertEqual(event["result"], "failed")
        self.assertIn("elapsed_ms", event)
        self.assertNotIn("private", logger.error.call_args.args[0])


if __name__ == "__main__":
    unittest.main()
