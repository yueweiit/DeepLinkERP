"""Procurement checks run after native controller and China Finance hooks."""
import importlib.util
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import frappe


class ConsistencyTests(unittest.TestCase):
    def setUp(self):
        path = "deeplinkerp_branding.services.purchase_consistency"
        self.assertIsNotNone(importlib.util.find_spec(path), "Shared native procurement consistency guard is missing")
        self.guard = __import__(path, fromlist=["guard"])
        flags = patch.object(frappe, "flags", frappe._dict())
        flags.start(); self.addCleanup(flags.stop)
        session = patch.object(frappe, "session", SimpleNamespace(user="QA"))
        session.start(); self.addCleanup(session.stop)

    def doc(self, doctype="Purchase Receipt", **values):
        doc = frappe._dict({"doctype": doctype, "name": "PR", "company": "C", "docstatus": 1,
            "items": [], "references": [], **values})
        doc.get_doc_before_save = lambda: None
        doc.precision = lambda field: 3
        return doc

    def test_native_submit_defers_checks_until_whole_hook_chain_finishes(self):
        callbacks = []
        db = SimpleNamespace(before_commit=SimpleNamespace(add=callbacks.append), after_rollback=SimpleNamespace(add=Mock()))
        with patch.object(frappe, "db", db), patch.object(frappe, "local", SimpleNamespace()), \
             patch.object(frappe, "get_doc", return_value=self.doc()), \
             patch.object(self.guard, "check_document") as check:
            self.guard.register_document(self.doc(), "on_submit")
            check.assert_not_called()
            self.assertEqual(len(callbacks), 1)
            with patch.object(self.guard, "finish_native_audit"):
                callbacks[0]()
            check.assert_called_once()

    def test_business_precision_is_used_instead_of_two_display_decimals(self):
        with patch.object(frappe, "throw", side_effect=frappe.ValidationError):
            with self.assertRaises(frappe.ValidationError):
                self.guard.equal(self.doc(), "grand_total", "10.001", "10.002", "native amount")
        self.guard.equal(self.doc(), "grand_total", "10.0011", "10.0012", "native amount")

    def test_registered_document_keeps_first_native_terms_for_review_invalidation(self):
        callbacks = []
        db = SimpleNamespace(before_commit=SimpleNamespace(add=callbacks.append), after_rollback=SimpleNamespace(add=Mock()))
        old, intermediate, final = self.doc(grand_total=10), self.doc(grand_total=20), self.doc(grand_total=20)
        intermediate.get_doc_before_save = lambda: old
        final.get_doc_before_save = lambda: final.get("_doc_before_save", intermediate)
        with patch.object(frappe, "db", db), patch.object(frappe, "local", SimpleNamespace()), \
             patch.object(frappe, "get_doc", return_value=final), \
             patch.object(self.guard, "check_document", return_value=[]) as check:
            self.guard.register_document(intermediate)
            self.guard.register_document(final)
            self.guard.check_registered()
            self.assertIs(check.call_args.args[0].get_doc_before_save(), old)

    def test_account_currency_precision_is_separate_from_company_currency(self):
        key = ("A", "", "", "USD", "", "", "", "", "")
        with patch.object(self.guard, "_gl_precision", side_effect=[2, 4]), \
             patch.object(frappe, "throw", side_effect=frappe.ValidationError):
            with self.assertRaises(frappe.ValidationError):
                self.guard._compare_gl(self.doc(), {key: [10, "1.0001"]}, {key: [10, "1.0002"]}, "currency")

    def test_customer_and_unrelated_operating_payments_are_outside_procurement(self):
        doc = self.doc("Payment Entry", party_type="Customer", payment_type="Receive")
        self.assertFalse(self.guard.is_procurement(doc))
        with patch.object(self.guard, "check_document") as check, patch.object(frappe, "local", SimpleNamespace()):
            self.guard.register_document(doc, "on_submit")
        check.assert_not_called()

    def test_native_controller_prepares_source_locks_before_saving(self):
        self.assertTrue(callable(getattr(self.guard, "prepare_document", None)), "Native controller source locks are missing")
        order = SimpleNamespace(doctype="Purchase Order", name="PO", company="C", supplier="S", items=[])
        row = frappe._dict(purchase_order="PO")
        doc = SimpleNamespace(doctype="Purchase Receipt", items=[row], get=lambda key: getattr(doc, key, None))
        with patch.object(self.guard.service, "_current", return_value=order) as current:
            self.guard.prepare_document(doc)
        current.assert_called_once_with("Purchase Order", "PO")

    def test_pending_finance_cancellation_rejects_native_commit(self):
        finance = SimpleNamespace(process_cancellation_snapshot=Mock(return_value={"status": "pending", "error": "private"}))
        with patch.object(self.guard, "finance_service", return_value=finance), \
             patch.object(frappe, "throw", side_effect=frappe.ValidationError):
            with self.assertRaises(frappe.ValidationError):
                self.guard.check_cancellation(self.doc(docstatus=2), [frappe._dict(debit=1, credit=1)])
        finance.process_cancellation_snapshot.assert_called_once_with("Purchase Receipt", "PR")

    def test_balanced_reversal_with_wrong_amount_cannot_commit(self):
        finance = SimpleNamespace(process_cancellation_snapshot=lambda *args: {"status": "resolved", "voucher": "RV"})
        original = self.doc("China Accounting Voucher", reversed_by="RV", status="Reversed",
            source_doctype="Purchase Receipt", source_name="PR", source_event="Posting",
            entries=[frappe._dict(account="A", debit=10), frappe._dict(account="B", credit=10)])
        reversal = self.doc("China Accounting Voucher", reversal_of="PR", total_debit=100, total_credit=100,
            source_doctype="Purchase Receipt", source_name="PR", source_event="Cancellation",
            entries=[frappe._dict(account="A", credit=100), frappe._dict(account="B", debit=100)])
        reversal.name = "RV"
        with patch.object(self.guard, "finance_service", return_value=finance), \
             patch.object(frappe, "get_doc", side_effect=[reversal, original]), \
             patch.object(self.guard, "_gl_precision", return_value=3), \
             patch.object(frappe, "throw", side_effect=frappe.ValidationError):
            with self.assertRaises(frappe.ValidationError):
                self.guard.check_cancellation(self.doc(docstatus=2), [frappe._dict(debit=10, credit=10)])

    def test_drafts_cannot_have_native_stock_or_financial_ledgers(self):
        for ledger in ("Stock Ledger Entry", "GL Entry", "Payment Ledger Entry"):
            with self.subTest(ledger=ledger), patch.object(frappe, "db", SimpleNamespace(
                exists=lambda doctype, filters: doctype == ledger)), \
                patch.object(frappe, "throw", side_effect=frappe.ValidationError):
                with self.assertRaises(frappe.ValidationError):
                    self.guard.check_draft(self.doc(docstatus=0))


if __name__ == "__main__":
    unittest.main()
