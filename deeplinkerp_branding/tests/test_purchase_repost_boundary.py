"""Session leases: native callback ordering is not the release authority."""
import importlib
import sys
import unittest
from unittest.mock import patch
from types import SimpleNamespace

import frappe
from frappe.utils import CallbackManager


class Connection:
    def __init__(self, identity):
        self.identity = identity
        self.pings = []
        self.closed = False
        self.rollbacks = 0

    def thread_id(self):
        return self.identity

    def ping(self, reconnect):
        self.pings.append(reconnect)

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        self.closed = True


class Database:
    owners = {}

    def __init__(self, identity):
        self._conn = Connection(identity)
        self._cursor = type("Cursor", (), {"connection": self._conn})()
        self.transaction_writes = 0
        self.value_cache = {}
        self.cur_db_name = "qa"
        self.queries = []
        for name in ("before_commit", "after_commit", "before_rollback", "after_rollback"):
            setattr(self, name, CallbackManager())

    def sql(self, query, values=(), **kwargs):
        self.queries.append(query)
        if "CONNECTION_ID" in query:
            return [(self._conn.identity,)]
        key = values[0] if values else None
        if "GET_LOCK" in query:
            owner = self.owners.setdefault(key, self._conn.identity)
            return [(int(owner == self._conn.identity),)]
        if "IS_USED_LOCK" in query:
            return [tuple(self.owners.get(value) for value in values)]
        if "RELEASE_LOCK" in query:
            if self.owners.get(key) == self._conn.identity:
                self.owners.pop(key)
                return [(1,)]
            return [(0,)]
        return []

    def commit(self, chain=False):
        self.before_rollback.reset(); self.after_rollback.reset()
        self.before_commit.run()
        self.sql("commit")
        self.sql("START TRANSACTION")
        self.after_commit.run()

    def rollback(self, save_point=None, chain=False):
        if save_point:
            self.sql("rollback to savepoint " + save_point)
            return
        self.before_commit.reset(); self.after_commit.reset()
        self.before_rollback.run()
        self.sql("rollback")
        self.sql("START TRANSACTION")
        self.after_rollback.run()

    def close(self):
        self._conn.close()
        self._conn = self._cursor = None


class RepostBoundarySessionTests(unittest.TestCase):
    def setUp(self):
        self.boundary = importlib.import_module("deeplinkerp_branding.services.purchase_repost_boundary")
        Database.owners.clear()
        self.db, self.other = Database(101), Database(202)
        def throw(message, exception=frappe.ValidationError, **kwargs):
            raise exception(message)
        # Pure database doubles do not initialize native request/message state.
        # NativeAtomic tests own the real throw, logging and physical evidence.
        messages = patch.object(frappe, "throw", side_effect=throw)
        messages.start(); self.addCleanup(messages.stop)
        guard = patch.object(self.boundary, "_supported", return_value=True)
        guard.start(); self.addCleanup(guard.stop)
        self.addCleanup(self.db.close)
        self.addCleanup(self.other.close)

    def lease(self, keys=("a",), db=None):
        return self.boundary.acquire(keys, db=db or self.db)

    def assert_locked(self, key="a", owner=101):
        self.assertEqual(Database.owners.get(key), owner)

    def test_real_ping_false_once_before_any_query_and_deeper_calls_verify_only(self):
        state = self.boundary.initialize(self.db)
        self.assertEqual(self.db._conn.pings, [False])
        self.assertEqual(state.connection_id, 101)
        self.assertIs(state.connection, self.db._conn)
        self.boundary.initialize(self.db)
        self.assertEqual(self.db._conn.pings, [False])

    def test_late_handshake_rejects_instead_of_rolling_back_business_writes(self):
        self.db.transaction_writes = 1
        with self.assertRaises(frappe.ValidationError): self.boundary.initialize(self.db)
        self.assertEqual(self.db._conn.pings, [])

    def test_partial_failure_releases_new_locks_but_retains_borrowed_refs(self):
        with self.boundary.execution(db=self.db), self.lease():
            with self.boundary.execution(db=self.other), self.lease(("c",), self.other):
                with self.assertRaises(frappe.ValidationError):
                    with self.lease(("a", "b", "c")): pass
                self.assert_locked(); self.assert_locked("c", 202)
                self.assertNotIn("b", Database.owners)
            self.assert_locked()
        self.assert_locked()
        self.db.commit()
        self.assertNotIn("a", Database.owners)

    def test_active_lease_survives_native_commits_rollback_and_savepoint(self):
        with self.boundary.execution(db=self.db), self.lease():
            self.db.commit(); self.assert_locked()
            self.db.rollback(); self.assert_locked()
            self.db.rollback(save_point="safe"); self.assert_locked()
            self.db.commit(); self.assert_locked()
        self.assert_locked()
        self.db.rollback(save_point="safe"); self.assert_locked()
        self.db.rollback()
        self.assertNotIn("a", Database.owners)

    def test_earlier_before_commit_failure_cannot_orphan_dormant_lease(self):
        self.db.before_commit.add(lambda: (_ for _ in ()).throw(RuntimeError("earlier")))
        with self.boundary.execution(db=self.db), self.lease(): pass
        with self.assertRaisesRegex(RuntimeError, "earlier"): self.db.commit()
        self.assertNotIn("a", Database.owners)
        self.assertEqual(self.db._conn.rollbacks, 1)

    def test_before_rollback_failure_uses_physical_rollback_preserves_original(self):
        with self.boundary.execution(db=self.db), self.lease(): pass
        self.db.before_rollback.add(lambda: (_ for _ in ()).throw(RuntimeError("rollback callback")))
        with self.assertRaisesRegex(RuntimeError, "rollback callback"): self.db.rollback()
        self.assertEqual(self.db._conn.rollbacks, 1)
        self.assertNotIn("a", Database.owners)

    def test_after_commit_new_lease_waits_for_next_actual_commit(self):
        with self.boundary.execution(db=self.db), self.lease(): pass
        def later():
            with self.boundary.execution(db=self.db), self.lease(("later",)): pass
            raise RuntimeError("after real commit")
        self.db.after_commit.add(later)
        with self.assertRaisesRegex(RuntimeError, "after real commit"): self.db.commit()
        self.assertNotIn("a", Database.owners)
        self.assert_locked("later")
        self.assertEqual(self.db._conn.rollbacks, 0)
        self.db.commit()
        self.assertNotIn("later", Database.owners)

    def test_replaced_connection_poison_before_connection_id_or_business_sql(self):
        self.boundary.initialize(self.db)
        self.db._conn = Connection(303)
        queries = list(self.db.queries)
        with self.assertRaises(frappe.ValidationError): self.db.sql("UPDATE business SET value=1")
        self.assertEqual(self.db.queries, queries)
        with self.assertRaises(frappe.ValidationError): self.boundary.initialize(self.db)

    def test_lost_authoritative_lock_fails_before_business_sql(self):
        with self.boundary.execution(db=self.db), self.lease():
            Database.owners["a"] = 202
            with self.assertRaises(frappe.ValidationError): self.db.sql("UPDATE business SET value=1")
        self.assertNotIn("UPDATE business SET value=1", self.db.queries)

    def test_raw_transaction_sql_uses_same_dormant_epoch_barrier(self):
        with self.boundary.execution(db=self.db), self.lease(): pass
        self.db.sql("ROLLBACK TO SAVEPOINT safe"); self.assert_locked()
        self.db.sql("COMMIT")
        self.assertNotIn("a", Database.owners)

    def test_raw_implicit_begin_and_session_autocommit_are_refused_while_leased(self):
        with self.boundary.execution(db=self.db), self.lease():
            for query in ("START TRANSACTION", "BEGIN", "SET SESSION autocommit=1", "LOCK TABLES business WRITE"):
                with self.subTest(query=query), self.assertRaises(frappe.ValidationError):
                    self.db.sql(query)
                self.assertNotIn(query, self.db.queries)
            self.db.commit()  # native begin immediately after own SQL is allowed
            self.assert_locked()

    def test_comment_prefixed_real_commit_releases_same_dormant_epoch(self):
        with self.boundary.execution(db=self.db), self.lease(): pass
        self.db.sql("/* audited internal caller */ COMMIT;")
        self.assertNotIn("a", Database.owners)

    def test_acquire_rejects_outside_execution_so_dormant_commit_cannot_release_mid_method(self):
        with self.assertRaises(frappe.ValidationError):
            with self.lease(): pass

    def test_pointer_guard_rejects_client_flags_and_ignore_permissions_before_native_write(self):
        doc = frappe._dict(doctype="Bin", name="BIN", custom_purchase_reversal_operation="CLIENT",
            flags=frappe._dict(ignore_permissions=True, purchase_reversal_internal=True))
        with self.assertRaises(frappe.PermissionError):
            self.boundary.check_pointer(doc, None)

    def test_pointer_guard_never_accepts_clear_of_persisted_owner(self):
        old = frappe._dict(doctype="Purchase Receipt", custom_purchase_reversal_operation="OWNER")
        new = frappe._dict(doctype="Purchase Receipt", custom_purchase_reversal_operation=None)
        with self.assertRaises(frappe.PermissionError): self.boundary.check_pointer(new, old)

    def test_full_authority_is_batched_and_acquisition_has_no_quadratic_rechecks(self):
        for count in (2500, 7500):  # maximum pairs plus typed document budget
            with self.subTest(count=count):
                keys = tuple("scale-" + str(i) for i in range(count))
                with self.boundary.execution(db=self.db), self.lease(keys):
                    start = len(self.db.queries)
                    self.db.sql("UPDATE business SET value=1")
                    batches = (count + 127) // 128
                    self.assertEqual(len(self.db.queries) - start, batches + 1)
                    authority = [query for query in self.db.queries[start:] if "IS_USED_LOCK" in query]
                    self.assertEqual(len(authority), batches)
                self.db.rollback()

    def test_callback_observer_preserves_installed_deque_alias_add_reset_and_drain(self):
        aliases = (self.db.before_commit, self.db.before_rollback)
        self.boundary.initialize(self.db)
        for old, observed in zip(aliases, (self.db.before_commit, self.db.before_rollback)):
            self.assertIs(old._functions, observed._functions)
            marker = []
            old.add(lambda: marker.append("original"))
            observed.run()
            self.assertEqual(marker, ["original"])
            observed.add(lambda: marker.append("cleared"))
            old.reset()
            observed.run()
            self.assertEqual(marker, ["original"])

    def test_logger_failure_cannot_prevent_close_or_replace_original_error(self):
        with self.boundary.execution(db=self.db), self.lease(): pass
        original = self.db._conn
        with patch.object(frappe, "logger", side_effect=RuntimeError("log failure")):
            self.db._conn = Connection(303)
            with self.assertRaises(frappe.ValidationError): self.db.sql("UPDATE business SET value=1")
        self.assertTrue(original.closed)

    def test_native_material_request_without_mes_app_has_no_opaque_import_dependency(self):
        doc = frappe._dict(doctype="Material Request", name="MR", items=[], packed_items=[])
        with patch.object(frappe, "get_hooks", return_value={}), patch.object(
                frappe, "get_meta", return_value=type("Meta", (), {"has_field": lambda self, field: False})()), patch.dict(
                sys.modules, {"mes_integration.mes_integration.material_request": None}), patch(
                "deeplinkerp_branding.services.purchase_payment_service._require_fields"):
            self.assertFalse(self.boundary._opaque(doc))

    def test_unknown_adapter_unrelated_global_hook_does_not_connect_ping_or_install(self):
        with patch.object(frappe, "db", self.db), patch.object(frappe, "local", SimpleNamespace(db=self.db)), patch.object(
                self.boundary, "_supported", return_value=False):
            self.boundary.before_execution()
        self.assertEqual(self.db.queries, [])
        self.assertEqual(self.db._conn.pings, [])
        self.assertIsNone(getattr(self.db, "_purchase_session", None))

    def test_unknown_adapter_protected_entry_refuses_before_any_lock_or_business_write(self):
        with patch.object(self.boundary, "_supported", return_value=False), self.assertRaises(frappe.ValidationError):
            with self.boundary.execution(db=self.db):
                self.db.sql("SELECT business FOR UPDATE")
        self.assertEqual(self.db.queries, [])
        self.assertEqual(self.db._conn.pings, [])

    def test_known_global_hook_initializes_before_queries_and_never_repeats_ping(self):
        with patch.object(frappe, "db", self.db), patch.object(frappe, "local", SimpleNamespace(db=self.db)), patch.object(
                self.boundary, "_known_database", return_value=True):
            self.boundary.before_execution()
            self.boundary.before_execution()
        self.assertEqual(self.db._conn.pings, [False])
        self.assertEqual(self.db.queries, ["SELECT CONNECTION_ID()"])

    def test_first_handshake_failure_poisoned_before_same_context_retry(self):
        with patch.object(self.db._conn, "ping", side_effect=OSError("physical gone")) as ping:
            with self.assertRaisesRegex(OSError, "physical gone"):
                self.boundary.initialize(self.db)
            self.assertTrue(self.db._purchase_session.poisoned)
            with self.assertRaises(frappe.ValidationError): self.boundary.initialize(self.db)
            ping.assert_called_once_with(False)
        self.assertTrue(self.db._conn.closed)
