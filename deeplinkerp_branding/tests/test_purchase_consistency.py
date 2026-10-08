"""Procurement checks run after native controller and China Finance hooks."""
import importlib.util
import json
import unittest
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import Mock, patch

import frappe


class ConsistencyTests(unittest.TestCase):
    def setUp(self):
        path = "deeplinkerp_branding.services.purchase_consistency"
        self.assertIsNotNone(importlib.util.find_spec(path), "Shared native procurement consistency guard is missing")
        self.guard = __import__(path, fromlist=["guard"])
        for method in ("execution", "initialize"):
            guard = patch("deeplinkerp_branding.services.purchase_repost_boundary." + method,
                return_value=nullcontext() if method == "execution" else None)
            guard.start(); self.addCleanup(guard.stop)
        flags = patch.object(frappe, "flags", frappe._dict())
        flags.start(); self.addCleanup(flags.stop)
        session = patch.object(frappe, "session", SimpleNamespace(user="QA"))
        session.start(); self.addCleanup(session.stop)

    def doc(self, doctype="Purchase Receipt", **values):
        posting_date = "2026-01-15"  # unit fixture must not consult patched DB/settings
        doc = SimpleNamespace(**{"doctype": doctype, "name": "PR", "company": "C", "docstatus": 1,
            "items": [], "references": [], "posting_date": posting_date,
            "fiscal_year": posting_date[:4], "accounting_period": posting_date[:7],
            "meta": SimpleNamespace(has_field=lambda field: field == "posting_date"), **values})
        doc.get = lambda field, default=None: getattr(doc, field, default)
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

    def test_native_old_subcontract_po_supplied_bin_is_bound_without_sle(self):
        order = frappe.get_doc({"doctype": "Purchase Order", "name": "PO", "is_old_subcontracting_flow": 1,
            "items": [], "supplied_items": [{"rm_item_code": "RM", "reserve_warehouse": "Supplier WH"}]})
        quantities = {"reserved_qty_for_sub_contract": 4}
        native_values = frappe.db.get_values
        def bins(doctype, filters, *args, **kwargs):
            if doctype != "Bin":
                return native_values(doctype, filters, *args, **kwargs)
            self.assertEqual((doctype, filters), ("Bin", {"item_code": "RM", "warehouse": "Supplier WH"}))
            return [frappe._dict(quantities)]
        with patch.object(self.guard, "_ledger", return_value=[]), \
                patch.object(frappe.db, "get_values", side_effect=bins):
            before = self.guard.artifact_evidence(order)
            quantities["reserved_qty_for_sub_contract"] += 1
            self.assertNotEqual(self.guard.artifact_evidence(order), before)

    def test_native_rounding_policy_applies_to_fields_and_gl(self):
        key = ("A", "", "", "CNY", "", "", "", "", "")
        for policy, rounded in (("Banker's Rounding", ".002"), ("Commercial Rounding", ".003")):
            with self.subTest(policy=policy), patch.object(frappe, "get_system_settings", return_value=policy), \
                 patch.object(self.guard, "_gl_precision", return_value=3):
                self.guard.equal(self.doc(), "grand_total", ".0025", rounded, "native rounding")
                self.guard._compare_gl(self.doc(), {key: [rounded, 0, rounded, 0]}, {key: [".0025", 0, ".0025", 0]}, "native rounding")

    def test_received_guard_uses_native_received_quantity_including_rejected(self):
        order = self.doc("Purchase Order", items=[self.doc("Purchase Order Item", name="ROW", received_qty=5,
            conversion_factor=1, stock_uom="Nos")])
        receipt = self.doc(items=[frappe._dict(purchase_order="PO")])
        rows = [frappe._dict(purchase_order_item="ROW", qty=3, received_qty=5, conversion_factor=1, stock_uom="Nos")]
        with patch.object(self.guard.service, "_current", return_value=order), \
             patch.object(frappe, "db", SimpleNamespace(get_values=Mock(side_effect=[rows, []]))):
            self.guard.check_order_received(receipt)

    def test_before_commit_preserves_original_error_when_rollback_also_fails(self):
        original = frappe.ValidationError("private source detail")
        state = {"context": {"operation_id": "ID", "user": "QA", "documents": []}}
        logger = Mock()
        with patch.object(self.guard, "check_registered", side_effect=original), \
             patch.object(frappe, "db", SimpleNamespace(rollback=Mock(side_effect=ConnectionError("private DB detail")))), \
             patch.object(frappe, "local", SimpleNamespace()), patch.object(frappe, "logger", return_value=logger):
            with self.assertRaises(frappe.ValidationError) as caught:
                self.guard._before_commit(state)
        self.assertIs(caught.exception, original)
        self.assertIn("ConnectionError", logger.error.call_args.args[0])
        self.assertNotIn("private", logger.error.call_args.args[0])

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
        with patch.object(self.guard, "_gl_precision", side_effect=[2, 2, 4, 4]), \
             patch.object(frappe, "throw", side_effect=frappe.ValidationError):
            with self.assertRaises(frappe.ValidationError):
                self.guard._compare_gl(self.doc(), {key: [10, 0, "1.0001", 0]}, {key: [10, 0, "1.0002", 0]}, "currency")

    def test_same_net_changes_to_any_gl_amount_columns_are_rejected(self):
        original = frappe._dict(account="A", account_currency="USD", debit=10, credit=0,
            debit_in_account_currency=2, credit_in_account_currency=0)
        for fields in (("debit", "credit"), ("debit_in_account_currency", "credit_in_account_currency")):
            altered = frappe._dict(original)
            for field in fields:
                altered[field] += 1
            with self.subTest(fields=fields), patch.object(self.guard, "_gl_precision", return_value=4):
                with self.assertRaises(frappe.ValidationError):
                    self.guard._compare_gl(self.doc(), self.guard._gl_map([altered]),
                        self.guard._gl_map([original]), "four-column integrity")
        negative = frappe._dict(original, debit=-10, credit=0, debit_in_account_currency=-2)
        reverse = frappe._dict(original, debit=0, credit=10, debit_in_account_currency=0, credit_in_account_currency=2)
        with patch.object(self.guard, "_gl_precision", return_value=4):
            self.guard._compare_gl(self.doc(), self.guard._gl_map([negative]), self.guard._gl_map([reverse]), "native negative")
            self.guard._compare_gl(self.doc(), self.guard._gl_map([reverse]), self.guard._gl_map([original]), "native reversal", reverse=True)

    def test_gl_allocation_accepts_native_mapping_and_voucher_child_documents(self):
        values = dict(account="A", account_currency="USD", debit=10, credit=0,
            debit_in_account_currency=2, credit_in_account_currency=0)
        voucher = frappe.get_doc({"doctype": "China Accounting Voucher"})
        child = voucher.append("entries", values)
        key = ("A", "", "", "USD", "", "", "", "", "", "{}")
        for row in (frappe._dict(values), child):
            with self.subTest(row_type=type(row).__name__):
                self.assertEqual(self.guard._gl_map([row]), {key: [10, 0, 2, 0]})
                self.assertEqual([row.get(field) for field in (
                    "debit", "credit", "debit_in_account_currency", "credit_in_account_currency")], [10, 0, 2, 0])

    def test_accounting_dimensions_must_match_native_gl_and_payment_allocations(self):
        native = frappe._dict(account="A", account_currency="CNY", debit=10, credit=0,
            debit_in_account_currency=10, credit_in_account_currency=0, qa_department="A")
        voucher = frappe._dict(native)
        voucher.pop("qa_department")
        voucher.dimensions_json = json.dumps({"qa_department": "A"})
        with patch("erpnext.accounts.doctype.accounting_dimension.accounting_dimension.get_accounting_dimensions", return_value=["qa_department"]), \
                patch.object(self.guard, "_gl_precision", return_value=2):
            self.assertEqual(self.guard._gl_map([native]), self.guard._gl_map([voucher]))
            voucher.dimensions_json = json.dumps({"qa_department": "B"})
            with self.assertRaises(frappe.ValidationError):
                self.guard._compare_gl(self.doc(), self.guard._gl_map([voucher]), self.guard._gl_map([native]), "native dimension")
            original = frappe._dict(company="C", account="A", account_currency="CNY", amount=10,
                amount_in_account_currency=10, qa_department="A")
            changed = frappe._dict(original, qa_department="B")
            with patch.object(frappe, "get_cached_value", return_value="CNY"), self.assertRaises(frappe.ValidationError):
                self.guard._compare_payment_ledger(self.doc(), "Payment Ledger Entry", [changed], [original], "native dimension")

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

    def test_shared_source_resolution_is_read_only_and_keeps_prepare_lock_order(self):
        order = self.doc("Purchase Order", name="PO", items=[])
        receipt = self.doc("Purchase Receipt", name="PR", items=[frappe._dict(purchase_order="PO")])
        invoice = self.doc("Purchase Invoice", name="PI", items=[frappe._dict(purchase_receipt="PR")])
        entry = self.doc("Payment Entry", name="PE", references=[frappe._dict(reference_doctype="Purchase Invoice", reference_name="PI")])
        docs = {(doc.doctype, doc.name): doc for doc in (order, receipt, invoice)}
        reader = Mock(side_effect=lambda dt, name: docs[dt, name])
        with patch.object(self.guard.service, "_current", side_effect=AssertionError("read resolver must not lock")), \
                patch.object(self.guard, "acknowledge_effect", side_effect=AssertionError("read resolver must not audit")):
            identities, native = self.guard.resolve_source_documents(entry, reader=reader)
        self.assertEqual(identities, set(docs))
        self.assertEqual(native, set())
        with patch.object(self.guard.service, "_read", side_effect=reader), \
                patch.object(self.guard.service, "_current", side_effect=reader) as current:
            self.guard.prepare_document(entry)
        self.assertEqual([call.args for call in current.call_args_list],
            [("Purchase Order", "PO"), ("Purchase Receipt", "PR"), ("Purchase Invoice", "PI")])

    def test_pending_finance_cancellation_rejects_native_commit(self):
        finance = SimpleNamespace(process_cancellation_snapshot=Mock(return_value={"status": "pending", "error": "private"}))
        with patch.object(self.guard, "finance_service", return_value=finance), \
             patch.object(frappe, "throw", side_effect=frappe.ValidationError):
            with self.assertRaises(frappe.ValidationError):
                self.guard.check_cancellation(self.doc(docstatus=2), [frappe._dict(debit=1, credit=1)])
        finance.process_cancellation_snapshot.assert_called_once_with("Purchase Receipt", "PR")

    def test_posting_voucher_must_match_the_exact_source_event(self):
        voucher = self.doc("China Accounting Voucher", total_debit=10, total_credit=10,
            source_doctype="Purchase Receipt", source_name="OTHER", source_event="Posting", entries=[])
        source = self.doc("Purchase Invoice", get_gl_entries=lambda: [], company="C")
        finance = SimpleNamespace(create_voucher_from_source=lambda *args: "V")
        with patch.object(self.guard, "_balanced"), patch.object(self.guard, "_compare_gl"), \
             patch.object(self.guard, "finance_service", return_value=finance), patch.object(frappe, "get_doc", return_value=voucher):
            with self.assertRaises(frappe.ValidationError):
                self.guard.check_finance(source, [frappe._dict(debit=10, credit=10)])

    def test_auto_invoice_permission_checks_ignore_hook_bypass_flags(self):
        source = self.doc(is_return=0, _action="submit")
        invoice = self.doc("Purchase Invoice", docstatus=0, flags=frappe._dict(ignore_permissions=True))
        db = SimpleNamespace(exists=lambda *args: True, get_value=lambda *args: 0,
            get_values=lambda *args, **kwargs: [frappe._dict(parent="PI", docstatus=0)])
        with patch.object(frappe, "db", db), patch.object(frappe, "get_doc", return_value=invoice), \
             patch("china_finance.services.auto_invoice._enabled", return_value=True), \
             patch.object(frappe, "has_permission", side_effect=lambda doctype, ptype="read", **kw: ptype != "submit"):
            self.assertTrue(callable(getattr(self.guard, "prepare_auto_invoice", None)), "Automatic invoice permission preflight missing")
            with self.assertRaises(frappe.PermissionError):
                self.guard.prepare_auto_invoice(source)

    def test_auto_invoice_partial_posted_result_is_not_success(self):
        source = self.doc(is_return=0, supplier="S", items=[self.doc("Purchase Receipt Item", name="R", qty=3,
            received_qty=5, rejected_qty=2, item_code="I", stock_uom="Nos")])
        invoice = self.doc("Purchase Invoice", name="PI", supplier="S",
            items=[frappe._dict(pr_detail="R", purchase_receipt="PR", qty=1, item_code="I", stock_uom="Nos")])
        with patch.object(frappe, "db", SimpleNamespace(exists=lambda *args: True,
                get_values=lambda *args, **kwargs: [frappe._dict(parent="PI", docstatus=1)], get_single_value=lambda *args: 0)), \
             patch("china_finance.services.auto_invoice._enabled", return_value=True), \
             patch("erpnext.stock.doctype.purchase_receipt.purchase_receipt.get_returned_qty_map", return_value={}), \
             patch.object(frappe, "get_doc", return_value=invoice), patch.object(frappe, "has_permission", return_value=True):
            self.assertTrue(callable(getattr(self.guard, "check_auto_invoice", None)), "Automatic invoice completeness missing")
            with self.assertRaises(frappe.ValidationError):
                self.guard.check_auto_invoice(source)

    def test_balanced_reversal_with_wrong_amount_cannot_commit(self):
        finance = SimpleNamespace(process_cancellation_snapshot=lambda *args: {"status": "resolved", "voucher": "RV"})
        original = self.doc("China Accounting Voucher", reversed_by="RV", status="Reversed",
            total_debit=10, total_credit=10, currency="CNY", source_key="Posting|Purchase Receipt|PR",
            source_doctype="Purchase Receipt", source_name="PR", source_event="Posting",
            entries=[frappe._dict(account="A", debit=10), frappe._dict(account="B", credit=10)])
        reversal = self.doc("China Accounting Voucher", reversal_of="PR", total_debit=100, total_credit=100,
            status="Posted", currency="CNY", source_key="Cancellation|Purchase Receipt|PR",
            source_doctype="Purchase Receipt", source_name="PR", source_event="Cancellation",
            entries=[frappe._dict(account="A", credit=100), frappe._dict(account="B", debit=100)])
        reversal.name = "RV"
        with patch.object(self.guard, "finance_service", return_value=finance), \
             patch.object(frappe, "get_doc", side_effect=[reversal, original]), \
             patch.object(frappe, "get_cached_value", return_value="CNY"), \
             patch.object(self.guard, "_gl_precision", return_value=3), \
             patch.object(frappe, "throw", side_effect=frappe.ValidationError):
            with self.assertRaises(frappe.ValidationError) as caught:
                self.guard.check_cancellation(self.doc(docstatus=2), original.entries)
        self.assertEqual(caught.exception.purchase_invariant, "冲销凭证与原凭证反向金额")

    def test_drafts_cannot_have_native_stock_or_financial_ledgers(self):
        for ledger in ("Stock Ledger Entry", "GL Entry", "Payment Ledger Entry", "Advance Payment Ledger Entry"):
            with self.subTest(ledger=ledger), patch.object(frappe, "db", SimpleNamespace(
                exists=lambda doctype, filters: doctype == ledger)), \
                patch.object(frappe, "throw", side_effect=frappe.ValidationError):
                with self.assertRaises(frappe.ValidationError):
                    self.guard.check_draft(self.doc(docstatus=0))

    def test_native_sales_row_association_cannot_be_reported_as_not_applicable(self):
        cases = [("Purchase Order", {"items": [frappe._dict(sales_order="SO", **{field: "SO-ROW"})]})
            for field in ("sales_order_item", "sales_order_packed_item")]
        cases += [("Purchase Receipt", {"items": [frappe._dict(delivery_note_item="DN-ROW")]}),
            ("Purchase Receipt", {"inter_company_reference": "DN"}),
            ("Purchase Order", {"inter_company_order_reference": "SO"}),
            ("Purchase Invoice", {"inter_company_invoice_reference": "SI"}),
            ("Purchase Invoice", {"items": [frappe._dict(sales_invoice_item="SI-ROW")]})]
        for doctype, values in cases:
            with self.subTest(doctype=doctype, values=values):
                doc = self.doc(doctype, **values)
                with patch.object(frappe, "db", SimpleNamespace(get_value=lambda *args: "SO", exists=lambda *args: False)):
                    with self.assertRaises(frappe.ValidationError) as caught:
                        self.guard.invalidate_reviews(doc)
                self.assertEqual(caught.exception.purchase_error_id, "sales_dependency_unsupported")

    def test_native_sales_delivery_receipt_source_is_read_authorized_through_invoice_and_payment(self):
        receipt = self.doc(inter_company_reference="DN", items=[frappe._dict(delivery_note_item="DN-ROW")])
        invoice = self.doc("Purchase Invoice", name="PI", items=[frappe._dict(purchase_receipt="PR")])
        payment = self.doc("Payment Entry", references=[frappe._dict(reference_doctype="Purchase Invoice", reference_name="PI")])
        for doc in (invoice, payment):
            for permitted in (True, False):
                with self.subTest(doctype=doc.doctype, permitted=permitted):
                    def source(doctype, name):
                        if doctype == "Purchase Receipt":
                            self.assertEqual(name, "PR")
                            if not permitted:
                                raise frappe.PermissionError
                            return receipt
                        self.assertEqual((doctype, name), ("Purchase Invoice", "PI"))
                        return invoice
                    with patch.object(self.guard.service, "_current", side_effect=source) as current, \
                            patch.object(frappe, "db", SimpleNamespace(exists=lambda *args: False)):
                        expected = frappe.ValidationError if permitted else frappe.PermissionError
                        with self.assertRaises(expected) as caught:
                            self.guard.check_sales_dependencies(doc)
                        current.assert_any_call("Purchase Receipt", "PR")
                        if permitted:
                            self.assertEqual(caught.exception.purchase_error_id, "sales_dependency_unsupported")

    def test_native_controller_checks_persisted_and_proposed_sales_identity_before_write(self):
        for old_link, new_link in (("SO", None), (None, "SO"), (None, None)):
            with self.subTest(old_link=old_link, new_link=new_link):
                old = frappe.get_doc({"doctype": "Purchase Order", "name": "PO", "company": "C", "docstatus": 0,
                    "inter_company_order_reference": old_link})
                incoming = frappe.get_doc({"doctype": "Purchase Order", "name": "PO", "company": "C", "docstatus": 0,
                    "inter_company_order_reference": new_link})
                writes = []
                def _save():
                    writes.append(True)
                    return incoming
                context = {"operation_id": "TEST", "user": "QA", "documents": [], "before": {}, "after": {}}
                with patch.object(self.guard.operation, "current", return_value=context), \
                        patch.object(self.guard.service, "_current", return_value=old):
                    if old_link or new_link:
                        with self.assertRaises(frappe.ValidationError) as caught:
                            self.guard.ProcurementControllerBoundary._procurement_call(incoming, _save)
                        self.assertEqual(caught.exception.purchase_error_id, "sales_dependency_unsupported")
                        self.assertEqual(writes, [])
                    else:
                        self.guard.ProcurementControllerBoundary._procurement_call(incoming, _save)
                        self.assertEqual(writes, [True])

    def test_cancel_requires_advance_payment_ledger_to_be_delinked_too(self):
        doc = self.doc("Payment Entry", docstatus=2)
        context = {"gl_before": {"Payment Entry:PR": []}, "payment_before": {"Payment Entry:PR": {
            "Payment Ledger Entry": [], "Advance Payment Ledger Entry": []}}}
        with patch.object(self.guard.operation, "current", return_value=context), \
             patch.object(self.guard, "_payment_gl_plan", return_value=[]), \
             patch.object(self.guard, "_ledger", side_effect=lambda doc, doctype, **kw:
                [frappe._dict(delinked=0)] if doctype == "Advance Payment Ledger Entry" else []):
            with self.assertRaises(frappe.ValidationError) as caught:
                self.guard.check_cancelled_ledgers(doc)
        self.assertEqual(caught.exception.purchase_error_id, "cancellation_payment_ledger_active")

    def test_native_background_submission_is_refused_before_queueing(self):
        with patch.object(self.guard, "_form_operation", side_effect=lambda key, payload, native: native()), \
             patch.object(frappe, "get_meta", return_value=SimpleNamespace(queue_in_background=True)), \
             patch("frappe.utils.scheduler.is_scheduler_inactive", return_value=False), \
             patch("frappe.desk.form.save.savedocs") as native:
            for key in (None, "12345678-12345678"):
                with self.subTest(request_id=key), self.assertRaises(frappe.ValidationError) as caught:
                    self.guard.savedocs(json.dumps({"doctype": "Purchase Order"}), "Submit", request_id=key)
                self.assertEqual(caught.exception.purchase_error_id, "native_background_submission_unsupported")
            self.guard.savedocs(json.dumps({"doctype": "Sales Order"}), "Submit")
        native.assert_called_once()

    def test_native_form_scope_preserves_old_identity_without_adding_read_acl(self):
        for doctype in ("Purchase Invoice", "Payment Entry"):
            for old_scope, incoming_scope in ((False, False), (True, False), (False, True), (True, True)):
                def document(procurement):
                    return frappe._dict(doctype=doctype, name="EXISTING", party_type="Supplier",
                        items=[frappe._dict(purchase_order="PO" if procurement else None)],
                        references=[frappe._dict(reference_doctype="Purchase Order", reference_name="PO")] if procurement else [])
                old, incoming = document(old_scope), document(incoming_scope)
                incoming["__islocal"] = 1  # incoming bookkeeping cannot hide a stored purchase identity
                for key in (None, "12345678-12345678"):
                    for endpoint in ("savedocs", "cancel"):
                        with self.subTest(doctype=doctype, old_scope=old_scope, incoming_scope=incoming_scope,
                                request_id=key, endpoint=endpoint):
                            with patch.object(frappe.db, "exists", return_value=True), \
                                    patch.object(frappe, "get_doc", side_effect=lambda value, *args: old if isinstance(value, str) else incoming), \
                                    patch.object(self.guard.service, "_current", side_effect=AssertionError("No procurement read ACL before native passthrough")), \
                                    patch.object(self.guard, "_form_operation", side_effect=RuntimeError("durable procurement boundary")), \
                                    patch("frappe.desk.form.save.savedocs", return_value="native"), \
                                    patch("frappe.desk.form.save.cancel", return_value="native"):
                                invoke = lambda: self.guard.savedocs(json.dumps(incoming), "Save", key) if endpoint == "savedocs" else \
                                    self.guard.cancel(doctype, "EXISTING", request_id=key, doc=json.dumps(incoming))
                                if key and (old_scope or incoming_scope):
                                    with self.assertRaisesRegex(RuntimeError, "durable procurement boundary"):
                                        invoke()
                                else:
                                    self.assertEqual(invoke(), "native")

    def test_unproved_skipped_native_repost_cannot_acknowledge_operation(self):
        context = {"operation_id": "ID", "user": "QA", "documents": []}
        doc = self.doc("Repost Item Valuation", status="Skipped")
        with patch.object(self.guard.operation, "current", return_value=context), \
                patch.object(frappe, "logger", return_value=Mock()), \
                patch.object(self.guard, "acknowledge_effect") as acknowledge, \
                patch.object(frappe, "get_doc", return_value=doc):
            with self.assertRaises(frappe.ValidationError) as caught:
                self.guard.check_native_repost(doc)
        self.assertEqual(caught.exception.purchase_error_id, "native_stock_repost_incomplete")
        acknowledge.assert_not_called()


if __name__ == "__main__":
    unittest.main()
