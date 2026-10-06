"""Background synchronization retains committed source pages and reports failures."""

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import frappe
from deeplinkerp_branding.services import operating_expenses as service


class OperatingExpenseSchedulingTests(unittest.TestCase):
    def setUp(self):
        self.db = Mock()
        self.settings = SimpleNamespace(enabled=1, cursor="completed-page", last_error=None)
        self.db.set_single_value.side_effect = lambda doctype, field, value: setattr(self.settings, field, value)
        patches = [patch.object(frappe, "db", self.db),
                   patch.object(frappe, "flags", frappe._dict()),
                   patch.object(service, "_settings", return_value=self.settings),
                   patch.object(service, "_save")]
        for item in patches:
            item.start()
            self.addCleanup(item.stop)

    def test_failure_is_durable_sanitized_and_propagates(self):
        with patch.object(service, "_sync_page", side_effect=ValueError("Bearer secret; source payload")):
            with self.assertRaisesRegex(RuntimeError, "同步失败"):
                service.scheduled_sync()
        self.assertEqual(self.settings.last_error, "同步失败，请管理员重试")
        self.assertEqual(self.settings.cursor, "completed-page")
        self.db.rollback.assert_called_once_with()
        self.db.commit.assert_called_once_with()

    def test_all_successful_pages_are_committed_before_next_page(self):
        events = []
        pages = iter([{"end": False, "count": 500}, {"end": False, "count": 500}, {"end": True, "count": 1}])
        def page():
            events.append("page")
            return next(pages)
        self.db.commit.side_effect = lambda: events.append("commit")
        with patch.object(service, "_sync_page", side_effect=page) as sync:
            service.scheduled_sync()
        self.assertEqual(sync.call_count, 3)
        self.assertEqual(events, ["page", "commit"] * 3)

    def test_later_failure_rolls_back_only_unfinished_page(self):
        with patch.object(service, "_sync_page", side_effect=[{"end": False}, TimeoutError("remote token")]):
            with self.assertRaisesRegex(RuntimeError, "同步失败"):
                service.scheduled_sync()
        self.assertEqual(self.db.commit.call_count, 2)  # Successful page, then safe error.
        self.db.rollback.assert_called_once_with()
        self.assertEqual(self.settings.cursor, "completed-page")

    def test_disabled_flag_skips_background_sync(self):
        self.settings.enabled = 0
        with patch.object(service, "_sync_page") as sync:
            service.scheduled_sync()
        sync.assert_not_called()
        self.db.commit.assert_not_called()

    def test_manual_sync_still_handles_one_page_without_commit(self):
        with patch.object(service, "_manager"), patch.object(service, "_sync_page", return_value={"end": False}) as sync:
            self.assertEqual(service.sync_operating_expenses(), {"end": False})
        sync.assert_called_once_with()
        self.db.commit.assert_not_called()

    def test_failure_writes_only_error_field_without_resaving_a_stale_cursor(self):
        with patch.object(service, "_sync_page", side_effect=ValueError("secret")), patch.object(service, "_save") as save:
            with self.assertRaises(RuntimeError):
                service.scheduled_sync()
        save.assert_not_called()
        self.db.set_single_value.assert_called_once_with(service.SETTINGS, "last_error", "同步失败，请管理员重试")
