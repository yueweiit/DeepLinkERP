"""Cleanup-owned request and validation collaborators for site-free unit tests."""
from unittest.mock import patch

import frappe


def native_throw(message, exc=frappe.ValidationError, **kwargs):
    """Keep Frappe's actual exception classes without its request message UI."""
    raise exc(message)


def install_native_throw(test):
    guard = patch.object(frappe, "throw", side_effect=native_throw)
    guard.start()
    test.addCleanup(guard.stop)


def install_request_state(test):
    """Give each method fresh mutable state; restore even when setUp fails."""
    for name, value in (("flags", frappe._dict()), ("response", frappe._dict()), ("message_log", [])):
        guard = patch.object(frappe, name, value)
        guard.start()
        test.addCleanup(guard.stop)
