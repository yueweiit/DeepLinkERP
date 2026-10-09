"""Session leases: native callback ordering is not the release authority."""
import importlib
import json
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

    @property
    def open(self):
        return not self.closed  # same close observation as native mysqlclient


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

    def sql(self, query, values=(), *, as_dict=0, as_list=0, debug=0, ignore_ddl=0,
            auto_commit=0, update=None, explain=False, run=True, pluck=False, as_iterator=False):
        # Match the installed native signature and its early preview returns.
        if not run:
            return str(query)
        if explain:
            return None
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
        if self._conn is not None:
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

    def receipts(self, state):
        """A transaction participant, not a business-ownership switch."""
        class Participant:
            def __init__(self):
                self.pending = []
                self.events = []
            def prepare(self, identity):
                receipt = {**identity, "effects": list(self.pending)}
                self.events.append(("prepare", receipt))
                state.db.sql("UPDATE own_receipt SET output=%s", (str(receipt),))
                return receipt
            def promote(self, receipt):
                self.events.append(("promote", receipt, state.epoch))
                self.pending.clear()
            def invalidate(self):
                self.events.append(("invalidate",))
                self.pending.clear()
            def resolve(self, identity, candidate):
                self.events.append(("resolve", identity, state.poisoned, state.connection.closed, candidate))
                return candidate
        participant = Participant()
        state.receipt_participant = participant
        return participant

    def test_partial_receipt_uses_physical_seam_after_callbacks_before_epoch_advance(self):
        with self.boundary.execution(db=self.db), self.lease():
            state = self.db._purchase_session
            receipts = self.receipts(state)
            receipts.pending.append("gl")
            self.db.before_commit.add(lambda: receipts.pending.append("before"))
            self.db.after_commit.reset()
            self.db.commit()
            self.assertEqual(len(receipts.events), 2, "Actual physical commit must prepare and promote a receipt")
            prepared, promoted = receipts.events
            self.assertEqual(prepared[1]["effects"], ["gl", "before"])
            self.assertEqual(prepared[1]["epoch"], 0)
            self.assertEqual(prepared[1]["execution_id"], state.execution_id)
            self.assertEqual(prepared[1]["connection_id"], 101)
            self.assertEqual(promoted[2], 0)
            self.assertLess(self.db.queries.index("UPDATE own_receipt SET output=%s"), self.db.queries.index("commit"))
            self.assertEqual(state.epoch, 1)

    def test_nested_raw_boundary_and_callback_writes_have_distinct_receipt_epochs(self):
        with self.boundary.execution(db=self.db), self.lease():
            state = self.db._purchase_session
            receipts = self.receipts(state)
            receipts.pending.append("first")
            def before():
                self.db.sql("COMMIT")
                receipts.pending.append("second")
            self.db.before_commit.add(before)
            self.db.after_commit.add(lambda: receipts.pending.append("third"))
            self.db.commit()
            self.db.commit()
            prepared = [event[1] for event in receipts.events if event[0] == "prepare"]
            self.assertEqual([(row["epoch"], row["effects"]) for row in prepared], [(0, ["first"]), (1, ["second"]), (2, ["third"])])

    def test_receipt_previews_are_not_boundaries_and_owned_savepoints_refuse(self):
        with self.boundary.execution(db=self.db), self.lease():
            receipts = self.receipts(self.db._purchase_session)
            for query in ("COMMIT", "ROLLBACK", "SAVEPOINT owned", "ROLLBACK TO SAVEPOINT owned"):
                for options in ({"run": False}, {"explain": True}):
                    with self.subTest(query=query, options=options):
                        self.db.sql(query, **options)
                        self.assertEqual(receipts.events, [])
            for query in ("SAVEPOINT owned", "ROLLBACK TO SAVEPOINT owned", "RELEASE SAVEPOINT owned"):
                with self.subTest(query=query), self.assertRaises(frappe.ValidationError):
                    self.db.sql(query)
                self.assertNotIn(query, self.db.queries)

    def test_rollback_discards_gl_witness_before_later_failure_status_commit(self):
        for rollback in ("native", "physical", "raw"):
            with self.subTest(rollback=rollback):
                db = Database(303)
                try:
                    with self.boundary.execution(db=db), self.lease(db=db):
                        state = db._purchase_session
                        receipts = self.receipts(state)
                        receipts.pending.append("rolled_back_gl")
                        if rollback == "native": db.rollback()
                        elif rollback == "raw": db.sql("ROLLBACK")
                        else: state.physical_rollback()
                        db.commit()
                        prepared = [event[1] for event in receipts.events if event[0] == "prepare"]
                        self.assertEqual([row["effects"] for row in prepared], [[]])
                finally:
                    db.close()

    def test_receipt_write_failure_rolls_back_business_before_any_commit(self):
        with self.boundary.execution(db=self.db), self.lease():
            state = self.db._purchase_session
            receipts = self.receipts(state)
            receipts.pending.append("gl")
            native_sql = state.native_sql
            def fail(query, *args, **kwargs):
                if query == "UPDATE own_receipt SET output=%s":
                    raise RuntimeError("receipt write failed")
                return native_sql(query, *args, **kwargs)
            with patch.object(state, "native_sql", side_effect=fail), self.assertRaisesRegex(RuntimeError, "receipt write failed"):
                self.db.commit()
            self.assertNotIn("commit", self.db.queries)
            self.assertEqual(state.connection.rollbacks, 1)
            self.assertFalse(receipts.pending)
            self.db.commit()
            self.assertEqual([event[1]["effects"] for event in receipts.events if event[0] == "promote"], [[]])

    def test_commit_response_unknown_poisons_before_receipt_resolution_never_retries(self):
        with self.boundary.execution(db=self.db), self.lease():
            state = self.db._purchase_session
            receipts = self.receipts(state)
            receipts.pending.append("gl")
            prepare = receipts.prepare
            def aliased(identity):
                receipt = prepare(identity)
                receipt["effects"] = receipts.pending
                return receipt
            receipts.prepare = aliased
            native_sql = state.native_sql
            calls = []
            def uncertain(query, *args, **kwargs):
                if str(query).lower() == "commit":
                    calls.append(query)
                    native_sql(query, *args, **kwargs)
                    raise RuntimeError("response unknown")
                return native_sql(query, *args, **kwargs)
            with patch.object(state, "native_sql", side_effect=uncertain), self.assertRaisesRegex(RuntimeError, "response unknown"):
                self.db.commit()
            resolved = [event for event in receipts.events if event[0] == "resolve"]
            self.assertEqual(len(resolved), 1)
            self.assertEqual(resolved[0][2:4], (True, True))
            self.assertEqual(resolved[0][1]["epoch"], 0)
            self.assertEqual(json.loads(resolved[0][4])["effects"], ["gl"])
            self.assertEqual(state.receipt_resolution["result"], "durable")
            self.assertEqual(calls, ["commit"])
            self.assertEqual(state.connection.rollbacks, 0)
            self.assertFalse(any(event[0] == "promote" for event in receipts.events))

    def test_physical_close_invalidates_pending_receipt_and_future_boundary(self):
        with self.boundary.execution(db=self.db), self.lease():
            state = self.db._purchase_session
            receipts = self.receipts(state)
            receipts.pending.append("gl")
            self.db.close()
            self.assertFalse(receipts.pending)
            with self.assertRaises(frappe.ValidationError): self.db.commit()

    def test_unknown_commit_never_accepts_only_matching_identity_as_durable(self):
        for resolution in ("absent", "mismatch", "error", "close_failure"):
            with self.subTest(resolution=resolution):
                db = Database(303)
                try:
                    with self.boundary.execution(db=db), self.lease(db=db):
                        state = db._purchase_session
                        receipts = self.receipts(state)
                        receipts.pending.append("synthetic_effect")
                        observed = []
                        def resolve(identity, candidate):
                            observed.append(json.loads(candidate))
                            self.assertFalse(receipts.pending)
                            if resolution == "error": raise RuntimeError("resolver unavailable")
                            if resolution == "absent": return None
                            return json.dumps({**identity, "effects": ["wrong_same_identity"]}).encode()
                        receipts.resolve = resolve
                        native_sql = state.native_sql
                        native_close = state.connection.close
                        def close():
                            if resolution == "close_failure": raise RuntimeError("physical close failed")
                            return native_close()
                        def uncertain(query, *args, **kwargs):
                            if str(query).lower() == "commit":
                                native_sql(query, *args, **kwargs)
                                raise RuntimeError("original commit response lost")
                            return native_sql(query, *args, **kwargs)
                        with patch.object(state.connection, "close", side_effect=close), patch.object(state, "native_sql", side_effect=uncertain), self.assertRaisesRegex(RuntimeError, "original commit response lost"):
                            db.commit()
                        self.assertEqual(len(observed), 0 if resolution == "close_failure" else 1)
                        if observed: self.assertEqual(observed[0]["effects"], ["synthetic_effect"])
                        self.assertEqual(state.receipt_resolution["result"], "unknown" if resolution in ("error", "close_failure") else resolution)
                        self.assertEqual(state.connection.open, resolution == "close_failure")
                        self.assertEqual(state.connection.rollbacks, 0)
                finally:
                    db.close()

    def test_invalid_or_oversize_candidate_rolls_back_prepare_without_physical_commit(self):
        for kind in ("identity", "mutates_identity", "bytes", "unserializable"):
            with self.subTest(kind=kind):
                db = Database(303)
                try:
                    with self.boundary.execution(db=db), self.lease(db=db):
                        state = db._purchase_session
                        receipts = self.receipts(state)
                        original = receipts.prepare
                        def invalid(identity):
                            receipt = original(identity)
                            if kind == "identity": receipt["epoch"] += 1
                            elif kind == "mutates_identity":
                                identity["epoch"] += 1
                                receipt["epoch"] = identity["epoch"]
                            elif kind == "bytes": receipt["large"] = "界" * 100
                            else: receipt["opaque"] = object()
                            return receipt
                        receipts.prepare = invalid
                        with patch.object(self.boundary, "MAX_EPOCH_RECEIPT_BYTES", 256, create=True), self.assertRaises((frappe.ValidationError, TypeError)):
                            db.commit()
                        self.assertNotIn("commit", db.queries)
                        self.assertEqual(state.connection.rollbacks, 1)
                        self.assertIsNone(state.receipt_resolution)
                finally:
                    db.close()

    def test_promote_failure_after_known_commit_preserves_commit_and_closes_owner(self):
        with self.boundary.execution(db=self.db), self.lease():
            state = self.db._purchase_session
            receipts = self.receipts(state)
            def fail(receipt):
                raise RuntimeError("original promotion failure")
            receipts.promote = fail
            with self.assertRaisesRegex(RuntimeError, "original promotion failure"):
                self.db.commit()
            self.assertIn("commit", self.db.queries)
            self.assertEqual(state.connection.rollbacks, 0)
            self.assertTrue(state.poisoned)

    def test_preparing_receipt_cannot_end_or_replace_its_physical_transaction(self):
        for command in ("COMMIT", "ROLLBACK", "START TRANSACTION"):
            with self.subTest(command=command):
                db = Database(303)
                try:
                    with self.boundary.execution(db=db), self.lease(db=db):
                        state = db._purchase_session
                        receipts = self.receipts(state)
                        original = receipts.prepare
                        def boundary_in_prepare(identity):
                            result = original(identity)
                            db.sql(command)
                            return result
                        receipts.prepare = boundary_in_prepare
                        with self.assertRaises(frappe.ValidationError): db.commit()
                        self.assertNotIn(command, db.queries)
                        self.assertNotIn("commit", db.queries)
                        self.assertEqual(state.connection.rollbacks, 1)
                finally:
                    db.close()

    def test_physical_rollback_before_callback_commit_preserves_old_epoch_receipt_only(self):
        with self.boundary.execution(db=self.db), self.lease():
            state = self.db._purchase_session
            receipts = self.receipts(state)
            receipts.pending.append("before_callback_committed")
            def before():
                self.db.commit()
                receipts.pending.append("after_callback_rolled_back")
            self.db.before_rollback.add(before)
            state.physical_rollback()
            self.assertEqual([event[1]["effects"] for event in receipts.events if event[0] == "promote"], [["before_callback_committed"]])
            self.assertFalse(receipts.pending)
            self.db.commit()
            self.assertEqual([event[1]["effects"] for event in receipts.events if event[0] == "promote"], [["before_callback_committed"], []])

    def test_promote_and_invalidate_cannot_reenter_sql_or_transaction_methods(self):
        for phase in ("promote", "invalidate"):
            for action in ("sql", "method", "initialize", "execution", "acquire"):
                with self.subTest(phase=phase, action=action):
                    db = Database(303)
                    try:
                        with self.boundary.execution(db=db), self.lease(db=db):
                            state = db._purchase_session
                            receipts = self.receipts(state)
                            entered = []
                            reentry_queries = []
                            def reenter(*args):
                                if not entered:
                                    entered.append(True)
                                    before = len(db.queries)
                                    try:
                                        if action == "method": db.commit()
                                        elif action == "sql": db.sql("UPDATE unexpected_business SET value=1")
                                        elif action == "initialize": self.boundary.initialize(db)
                                        elif action == "execution":
                                            with self.boundary.execution(db=db): pass
                                        else:
                                            with self.lease(db=db): pass
                                    finally:
                                        reentry_queries.extend(db.queries[before:])
                            setattr(receipts, phase, reenter)
                            with self.assertRaises(frappe.ValidationError):
                                if phase == "promote": db.commit()
                                else: db.sql("ROLLBACK")
                            self.assertTrue(state.poisoned)
                            self.assertEqual(reentry_queries, [], "Memory-only callbacks must not even query lease authority")
                            self.assertNotIn("UPDATE unexpected_business SET value=1", db.queries)
                            self.assertEqual(db.queries.count("commit"), 1 if phase == "promote" else 0)
                            self.assertEqual(state.connection.rollbacks, 0)
                    finally:
                        db.close()

    def test_raw_rollback_error_closes_owner_before_later_writes_can_commit_without_receipt(self):
        with self.boundary.execution(db=self.db), self.lease():
            state = self.db._purchase_session
            receipts = self.receipts(state)
            receipts.pending.append("synthetic_pending")
            native_sql = state.native_sql
            def failed(query, *args, **kwargs):
                if str(query).lower() == "rollback": raise RuntimeError("original raw rollback failure")
                return native_sql(query, *args, **kwargs)
            with patch.object(state, "native_sql", side_effect=failed), self.assertRaisesRegex(RuntimeError, "original raw rollback failure"):
                self.db.sql("ROLLBACK")
            self.assertTrue(state.poisoned)
            self.assertTrue(state.connection.closed)
            with self.assertRaises(frappe.ValidationError): self.db.commit()
            self.assertFalse(receipts.pending)

    def test_owned_auto_commit_sql_is_explicitly_refused_but_previews_remain_native(self):
        with self.boundary.execution(db=self.db), self.lease():
            state = self.db._purchase_session
            receipts = self.receipts(state)
            for query in ("COMMIT", "ROLLBACK", "UPDATE own_business SET value=1"):
                for options in ({"run": False}, {"explain": True}):
                    with self.subTest(query=query, options=options):
                        self.db.sql(query, auto_commit=True, **options)
                        self.assertFalse(receipts.events)
                with self.subTest(query=query), self.assertRaises(frappe.ValidationError):
                    self.db.sql(query, auto_commit=True)
                self.assertNotIn(query, self.db.queries)

    def test_caught_prepare_failure_then_new_callback_writes_and_error_reclean_new_epoch(self):
        with self.boundary.execution(db=self.db), self.lease():
            state = self.db._purchase_session
            receipts = self.receipts(state)
            prepare = receipts.prepare
            def failed(identity):
                raise RuntimeError("first prepare error")
            receipts.prepare = failed
            def callback():
                with self.assertRaisesRegex(RuntimeError, "first prepare error"): self.db.sql("COMMIT")
                receipts.prepare = prepare
                self.db.sql("UPDATE new_epoch_business SET value=1")
                receipts.pending.append("new_rolled_back_marker")
                raise RuntimeError("original later callback error")
            self.db.before_commit.add(callback)
            with self.assertRaisesRegex(RuntimeError, "original later callback error"): self.db.commit()
            self.assertEqual(state.connection.rollbacks, 2)
            self.assertFalse(receipts.pending)
            self.db.commit()
            self.assertEqual([event[1]["effects"] for event in receipts.events if event[0] == "promote"], [[]])

    def test_invalidation_close_cannot_execute_old_raw_sql_or_advance_its_epoch(self):
        with self.boundary.execution(db=self.db), self.lease():
            state = self.db._purchase_session
            receipts = self.receipts(state)
            entered = []
            def close():
                if not entered:
                    entered.append(True)
                    self.db.close()
            receipts.invalidate = close
            with self.assertRaises(frappe.ValidationError): self.db.sql("ROLLBACK")
            self.assertTrue(state.poisoned)
            self.assertIsNone(self.db._conn)
            self.assertEqual(state.epoch, 0)
            self.assertNotIn("ROLLBACK", self.db.queries)

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

    def test_sql_previews_preserve_dormant_authority_and_native_argument_semantics(self):
        for query in ("COMMIT", "ROLLBACK", "BEGIN", "CREATE TABLE preview_only (name int)"):
            for option in ({"run": False}, {"explain": True}):
                for positional in (False, True):
                    for expected_begin in (False, True):
                        with self.subTest(query=query, option=option, positional=positional, expected_begin=expected_begin):
                            db = Database(303)
                            try:
                                with self.boundary.execution(db=db), self.lease(db=db): pass
                                state = db._purchase_session
                                state.begin_expected = expected_begin
                                before = (state.epoch, state.begin_expected, dict(state.locks), dict(state.references), db._conn.rollbacks)
                                result = db.sql(query, (), **option) if positional else db.sql(query=query, values=(), **option)
                                self.assertEqual(result, query if "run" in option else None)
                                self.assertEqual((state.epoch, state.begin_expected, state.locks, state.references, db._conn.rollbacks), before)
                                self.assert_locked(owner=303)
                                self.assertNotIn(query, db.queries)
                                with self.assertRaises(frappe.ValidationError):
                                    with self.boundary.execution(db=self.other), self.lease(db=self.other): pass
                            finally:
                                db.rollback()
                                db.close()
        with self.boundary.execution(db=self.db), self.lease(): pass
        state = self.db._purchase_session
        before = (state.epoch, state.begin_expected, dict(state.locks))
        for args, kwargs in ((("COMMIT", (), False), {}), (("COMMIT",), {"unknown_sql_option": True})):
            with self.subTest(args=args, kwargs=kwargs), self.assertRaises(TypeError):
                self.db.sql(*args, **kwargs)
            self.assertEqual((state.epoch, state.begin_expected, state.locks), before)
            self.assert_locked()

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

    def test_owned_pointer_is_not_new_identity_authority_even_when_incoming_name_matches(self):
        for doctype in self.boundary.POINTER_TYPES:
            with self.subTest(doctype=doctype):
                old = frappe._dict(doctype=doctype, name="OLD", custom_purchase_reversal_operation="OWNER")
                proposed = frappe._dict(old)
                self.boundary.check_pointer(proposed, old)  # ordinary same identity is unchanged
                with self.assertRaises(frappe.PermissionError):
                    self.boundary.check_pointer(proposed, old, creating=True)
                for empty in (None, ""):
                    proposed.custom_purchase_reversal_operation = empty
                    self.boundary.check_pointer(proposed, old, creating=True)
                for value in (0, False):
                    with self.subTest(pointer_type=type(value).__name__):
                        proposed.custom_purchase_reversal_operation = value
                        with self.assertRaises(frappe.PermissionError):
                            self.boundary.check_pointer(proposed, old, creating=True)
                        unowned = frappe._dict(doctype=doctype, name="OLD", custom_purchase_reversal_operation=None)
                        with self.assertRaises(frappe.PermissionError):
                            self.boundary.check_pointer(proposed, unowned)

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
                self.boundary, "_known_database", return_value=True), patch(
                "deeplinkerp_branding.services.purchase_native_intent.install", return_value=False):
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
