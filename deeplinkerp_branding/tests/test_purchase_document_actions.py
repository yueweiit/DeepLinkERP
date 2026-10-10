"""Current native quantity caps and protected mapping fields."""
import unittest
import hashlib
import json
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import Mock, patch

import frappe

from deeplinkerp_branding.services import purchase_document_actions as actions
from deeplinkerp_branding.tests._purchase_test_support import install_request_state, native_throw


def document(doctype, name="PO", **values):
    values = {"company": "C", "supplier": "S", "docstatus": 1, "modified": "source-v1", "status": "To Receive and Bill",
              "items": [], **values}
    doc = SimpleNamespace(doctype=doctype, name=name, **values)
    doc.get = lambda field, default=None: getattr(doc, field, default)
    doc.set = lambda field, value: setattr(doc, field, value)
    doc.is_new = lambda: not bool(doc.name)
    doc.flags = frappe._dict()
    doc.as_dict = lambda **kwargs: {key: value for key, value in vars(doc).items()
        if key != "flags" and not callable(value)}
    doc.has_permission = lambda permission: True
    doc.check_permission = Mock()
    return doc


class QuantityCapTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(callable(getattr(actions, "_current_maximum", None)), "Current locking quantity guard is missing")
        flags = patch.object(frappe, "flags", frappe._dict())
        flags.start(); self.addCleanup(flags.stop)

    def test_invoice_caps_use_current_reads_and_native_rejected_return_rules(self):
        source = SimpleNamespace(name="PR", doctype="Purchase Receipt", items=[
            frappe._dict(name="ITEM", qty=4, received_qty=5, rejected_qty=1)])
        for bill_rejected, returned, expected in ((False, 0, 2), (False, 2, 1), (True, 2, 3)):
            with self.subTest(bill_rejected=bill_rejected, returned=returned):
                values = Mock(side_effect=[[frappe._dict(pr_detail="ITEM", qty=2)],
                    [frappe._dict(name="RETURN")], [frappe._dict(purchase_receipt_item="ITEM", qty=-returned)]])
                db = SimpleNamespace(get_values=values, get_single_value=lambda *args: bill_rejected)
                with patch.object(frappe, "db", db), patch.object(actions.service, "_require_fields"):
                    self.assertEqual(actions._current_maximum(source, "Purchase Invoice"), {"ITEM": expected})
                self.assertTrue(all(call.kwargs.get("for_update") for call in values.call_args_list))

    def test_receipt_caps_use_locked_order_received_quantity(self):
        source = SimpleNamespace(doctype="Purchase Order", items=[
            frappe._dict(name="ITEM", qty=10, received_qty=4, delivered_by_supplier=0)])
        self.assertEqual(actions._current_maximum(source, "Purchase Receipt"), {"ITEM": 6})

    def test_order_invoice_identity_uses_native_po_detail(self):
        row = frappe._dict(po_detail="PO-ITEM", pr_detail="PR-ITEM", purchase_order_item="RECEIPT-ITEM")
        self.assertEqual(actions._key(row, "Purchase Invoice", document("Purchase Order")), "PO-ITEM")
        self.assertEqual(actions._key(row, "Purchase Invoice", document("Purchase Receipt")), "PR-ITEM")
        self.assertEqual(actions._key(row, "Purchase Receipt", document("Purchase Order")), "RECEIPT-ITEM")

    def test_order_invoice_cap_batches_all_native_signed_billed_rows(self):
        source = document("Purchase Order", items=[frappe._dict(name="A", qty=10), frappe._dict(name="B", qty=7)])
        values = Mock(return_value=[frappe._dict(po_detail="A", qty=4), frappe._dict(po_detail="A", qty=-1),
                                   frappe._dict(po_detail="B", qty=7)])
        with patch.object(frappe, "db", SimpleNamespace(get_values=values)), patch.object(actions.service, "_require_fields"):
            self.assertEqual(actions._current_maximum(source, "Purchase Invoice"), {"A": 7, "B": 0})
        self.assertEqual(values.call_count, 1)
        self.assertEqual(values.call_args.args[:2], ("Purchase Invoice Item", {"purchase_order": "PO", "docstatus": 1}))
        self.assertTrue(values.call_args.kwargs["for_update"])

    def test_order_invoice_orphan_item_identity_cannot_restore_available_quantity(self):
        source = document("Purchase Order", items=[frappe._dict(name="A", qty=10)])
        with patch.object(frappe, "db", SimpleNamespace(get_values=lambda *args, **kwargs: [frappe._dict(po_detail="ORPHAN", qty=4)])), \
             patch.object(actions.service, "_require_fields"), patch.object(frappe, "throw", side_effect=frappe.ValidationError):
            with self.assertRaises(frappe.ValidationError): actions._current_maximum(source, "Purchase Invoice")

    def test_receipt_cap_also_respects_earlier_order_invoice_without_duplicate_allocation(self):
        source = document("Purchase Receipt", "PR", items=[
            frappe._dict(name="R1", qty=5, received_qty=5, rejected_qty=0, purchase_order="PO", purchase_order_item="A"),
            frappe._dict(name="R2", qty=5, received_qty=5, rejected_qty=0, purchase_order="PO", purchase_order_item="A")])
        order = document("Purchase Order", items=[frappe._dict(name="A", qty=10)])
        def values(doctype, filters, fields, **kwargs):
            self.assertTrue(kwargs["for_update"])
            if doctype == "Purchase Invoice Item" and "purchase_order" in filters:
                return [frappe._dict(po_detail="A", qty=6)]
            return []
        with patch.object(frappe, "db", SimpleNamespace(get_values=Mock(side_effect=values), get_single_value=lambda *args: 0)), \
             patch.object(actions.service, "_require_fields"), patch.object(actions, "_locked", return_value=order):
            self.assertEqual(actions._current_maximum(source, "Purchase Invoice"), {"R1": 4, "R2": 0})

    def test_duplicate_guard_uses_requested_target_not_receipt_draft_for_order_invoice(self):
        source = document("Purchase Order")
        values = Mock(return_value=[])
        with patch.object(frappe, "db", SimpleNamespace(get_values=values)), patch.object(actions.service, "_require_fields"):
            self.assertFalse(actions._current_drafts(source, "Purchase Invoice"))
        self.assertEqual(values.call_args.args[:2], ("Purchase Invoice Item", {"purchase_order": "PO", "docstatus": 0}))

    def test_later_receipt_also_requires_explicit_confirmation_for_an_order_invoice_draft(self):
        source = document("Purchase Receipt", "PR", items=[frappe._dict(purchase_order="PO")])
        target = document("Purchase Invoice", "PI", docstatus=0)
        values = Mock(side_effect=[[], [frappe._dict(parent="PI")]])
        with patch.object(frappe, "db", SimpleNamespace(get_values=values)), patch.object(actions.service, "_require_fields"), \
             patch.object(actions, "_locked", return_value=target):
            self.assertTrue(actions._current_drafts(source, "Purchase Invoice"))

    def test_receipt_with_different_native_uom_uses_native_fallback(self):
        source = document("Purchase Receipt", "PR", items=[frappe._dict(name="R1", qty=5, received_qty=5,
            rejected_qty=0, purchase_order="PO", purchase_order_item="A", uom="Nos", conversion_factor=1)])
        order = document("Purchase Order", items=[frappe._dict(name="A", qty=1, uom="Box", conversion_factor=10)])
        with patch.object(frappe, "db", SimpleNamespace(get_values=lambda *args, **kwargs: [], get_single_value=lambda *args: 0)), \
             patch.object(actions.service, "_require_fields"), patch.object(actions, "_locked", return_value=order), \
             patch.object(frappe, "throw", side_effect=frappe.ValidationError):
            with self.assertRaises(frappe.ValidationError): actions._current_maximum(source, "Purchase Invoice")


class OrderInvoiceMappingTests(unittest.TestCase):
    def setUp(self):
        install_request_state(self)
        for method in ("execution", "initialize"):
            guard = patch("deeplinkerp_branding.services.purchase_repost_boundary." + method,
                return_value=nullcontext() if method == "execution" else None)
            guard.start(); self.addCleanup(guard.stop)
        self.fields = patch.object(actions, "_fields", side_effect=lambda dt, fields, *args, **kwargs: fields)
        self.fields.start(); self.addCleanup(self.fields.stop)
        permission = patch.object(frappe, "has_permission", return_value=True)
        permission.start(); self.addCleanup(permission.stop)

    def test_native_order_mapper_is_used_once_and_sets_no_stock(self):
        source = document("Purchase Order", items=[frappe._dict(name="A", qty=2)])
        target = document("Purchase Invoice", None, items=[frappe._dict(po_detail="A", purchase_order="PO", qty=2)])
        with patch.object(actions, "_invoice_source_reason", return_value=""), \
             patch.object(actions.service, "order_execution_reason", return_value=""), \
             patch("erpnext.buying.doctype.purchase_order.purchase_order.make_purchase_invoice", return_value=target) as mapper, \
             patch("erpnext.buying.doctype.purchase_order.purchase_order.make_purchase_invoice_from_portal") as portal:
            result = actions._native(source, "Purchase Invoice")
        self.assertIs(result, target)
        self.assertEqual(result.update_stock, 0)
        mapper.assert_called_once_with("PO"); portal.assert_not_called()

    def test_required_receipt_warns_only_for_stock_or_assets_without_supplier_override(self):
        source = document("Purchase Order", items=[frappe._dict(name="A", item_code="ITEM")])
        for stock, asset, override, blocked in ((1, 0, 0, True), (0, 1, 0, True), (1, 0, 1, False), (0, 0, 0, False)):
            with self.subTest(stock=stock, asset=asset, override=override):
                def read(dt, name, fields=()):
                    return frappe._dict(allow_purchase_invoice_creation_without_purchase_receipt=override) if dt == "Supplier" else frappe._dict(is_stock_item=stock, is_fixed_asset=asset)
                with patch.object(actions.service, "order_execution_reason", return_value=""), \
                     patch.object(actions.service, "_read", side_effect=read), \
                     patch.object(frappe, "db", SimpleNamespace(get_single_value=lambda *args: "Yes")):
                    reason = actions._invoice_source_reason(source)
                self.assertEqual(bool(reason), blocked)
                if blocked: self.assertIn("原生", reason)

    def test_mapping_field_permissions_are_checked_before_mapper(self):
        source = document("Purchase Order")
        for protected in ("Purchase Order", "Purchase Order Item", "Purchase Invoice", "Purchase Invoice Item", "Purchase Taxes and Charges"):
            def fields(dt, names, *args, **kwargs):
                if dt == protected: raise frappe.PermissionError
                return names
            with self.subTest(protected=protected), patch.object(actions, "_fields", side_effect=fields), \
                 patch.object(actions.service, "order_execution_reason", return_value=""), \
                 patch("erpnext.buying.doctype.purchase_order.purchase_order.make_purchase_invoice") as mapper:
                with self.assertRaises(frappe.PermissionError): actions._native(source, "Purchase Invoice")
            mapper.assert_not_called()

    def test_receipt_invoice_locks_orders_before_receipt_in_stable_order(self):
        source = document("Purchase Receipt", "PR", items=[frappe._dict(purchase_order="B"), frappe._dict(purchase_order="A")])
        locked = Mock(side_effect=lambda dt, name: source if dt == "Purchase Receipt" else document(dt, name))
        with patch.object(actions.service, "_source", return_value=source), patch.object(actions, "_locked", locked), \
             patch.object(actions.service, "_require_fields"), patch.object(actions.service, "_source_links", return_value=["B", "A"]):
            self.assertIs(actions._locked_source("Purchase Receipt", "PR", "Purchase Invoice"), source)
        self.assertEqual([call.args for call in locked.call_args_list], [("Purchase Order", "A"), ("Purchase Order", "B"), ("Purchase Receipt", "PR")])

    def test_receipt_preview_reuses_order_loaded_by_source_lock_pass(self):
        source = document("Purchase Receipt", "PR", items=[frappe._dict(name="R1", item_code="ITEM", qty=5,
            received_qty=5, rejected_qty=0, purchase_order="PO", purchase_order_item="A")])
        order = document("Purchase Order", items=[frappe._dict(name="A", item_code="ITEM", qty=10)])
        target = document("Purchase Invoice", None, items=[frappe._dict(pr_detail="R1", qty=5)])
        locked = Mock(side_effect=lambda dt, name: source if dt == "Purchase Receipt" else order)
        values = Mock(return_value=[])
        with patch.object(actions, "_source", return_value=(source, {"draft_invoices": []})), \
             patch.object(actions.service, "_source", return_value=source), \
             patch.object(actions.service, "_source_links", return_value=["PO"]), \
             patch.object(actions.service, "_require_fields"), patch.object(actions, "_locked", locked), \
             patch.object(frappe, "db", SimpleNamespace(get_values=values, get_single_value=lambda *args: 0)), \
             patch.object(actions, "_native", return_value=target) as mapper, \
             patch.object(actions, "_advanced", return_value=False), \
             patch.object(actions, "_projection", return_value={}):
            actions.preview_document("Purchase Receipt", "PR", "Purchase Invoice")
        self.assertEqual([call.args for call in locked.call_args_list], [("Purchase Order", "PO"), ("Purchase Receipt", "PR")])
        mapper.assert_called_once_with(source, "Purchase Invoice")
        self.assertEqual(sum(call.args[1].get("purchase_order") == "PO" for call in values.call_args_list), 1)

    def test_execution_gate_runs_before_native_mapper(self):
        source = document("Purchase Order")
        with patch.object(actions.service, "order_execution_reason", return_value="采购来源已更新"), \
             patch("erpnext.buying.doctype.purchase_order.purchase_order.make_purchase_invoice") as mapper, \
             patch.object(frappe, "throw", side_effect=frappe.ValidationError):
            with self.assertRaises(frappe.ValidationError): actions._native(source, "Purchase Invoice")
        mapper.assert_not_called()

    def test_advanced_direct_order_invoice_rejects_stock_and_mixed_source(self):
        source = document("Purchase Order", items=[frappe._dict(name="A", item_code="ITEM")])
        for update_stock, link, key, receipt in ((1, "PO", "A", None), (0, "OTHER", "A", None),
                                                 (0, "PO", "OTHER-ITEM", None), (0, "PO", "A", "PR")):
            with self.subTest(update_stock=update_stock, link=link, key=key, receipt=receipt):
                target = document("Purchase Invoice", items=[frappe._dict(purchase_order=link, po_detail=key,
                    purchase_receipt=receipt, item_code="ITEM")], update_stock=update_stock)
                self.assertTrue(actions._advanced(target, source))

    def test_target_cannot_reinterpret_source_quantity_in_a_different_native_unit(self):
        source = document("Purchase Order", items=[frappe._dict(name="A", item_code="ITEM", uom="Nos", conversion_factor=1)])
        for unit, factor in (("Box", 10), ("Nos", 2)):
            target = document("Purchase Invoice", items=[frappe._dict(purchase_order="PO", po_detail="A",
                item_code="ITEM", uom=unit, conversion_factor=factor)], update_stock=0)
            with self.subTest(unit=unit, factor=factor): self.assertTrue(actions._advanced(target, source))

    def test_projection_carries_source_version_and_po_item_identity(self):
        source = document("Purchase Order")
        target = document("Purchase Invoice", "PI", docstatus=0, items=[frappe._dict(po_detail="A", qty=2)])
        with patch.object(actions, "_workflow_actions", return_value=[]), patch.object(actions, "_editable_fields", return_value=[]), \
             patch.object(actions, "_advanced", return_value=False):
            result = actions._projection(target, {"A": 3}, source)
        self.assertEqual(result["source_modified"], "source-v1")
        self.assertEqual(result["document"]["source_modified"], "source-v1")
        self.assertEqual(result["document"]["items"][0]["key"], "A")
        self.assertEqual(result["document"]["items"][0]["max_qty"], 3)

    def test_new_order_invoice_requires_source_version_before_mapping(self):
        source = document("Purchase Order")
        cache = SimpleNamespace(lock=lambda *args, **kwargs: nullcontext(), get_value=lambda key: None)
        rollback = Mock()
        with patch.object(frappe, "session", SimpleNamespace(user="QA")), patch.object(frappe, "cache", return_value=cache), \
             patch.object(frappe, "db", SimpleNamespace(rollback=rollback)), patch.object(frappe, "logger", return_value=Mock()), \
             patch.object(actions.purchase_operation, "_existing", return_value=None), \
             patch.object(actions.purchase_operation, "_reserve") as reserve, \
             patch.object(actions, "_locked_source", return_value=source), patch.object(actions, "_source", return_value=(source, {})), \
             patch.object(actions, "_native") as mapper, patch.object(frappe, "throw", side_effect=native_throw):
            with self.assertRaises(frappe.ValidationError):
                actions.save_document_draft("Purchase Order", "PO", "Purchase Invoice", {}, "12345678-1234-1234")
        mapper.assert_not_called()
        reserve.assert_called_once(); rollback.assert_called_once_with()

    def test_stale_source_version_is_rejected_before_mapping(self):
        source = document("Purchase Order")
        cache = SimpleNamespace(lock=lambda *args, **kwargs: nullcontext(), get_value=lambda key: None)
        rollback = Mock()
        with patch.object(frappe, "session", SimpleNamespace(user="QA")), patch.object(frappe, "cache", return_value=cache), \
             patch.object(frappe, "db", SimpleNamespace(rollback=rollback)), patch.object(frappe, "logger", return_value=Mock()), \
             patch.object(actions.purchase_operation, "_existing", return_value=None), \
             patch.object(actions.purchase_operation, "_reserve") as reserve, \
             patch.object(actions, "_locked_source", return_value=source), patch.object(actions, "_source", return_value=(source, {})), \
             patch.object(actions, "_native") as mapper, patch.object(frappe, "throw", side_effect=native_throw):
            with self.assertRaises(frappe.ValidationError):
                actions.save_document_draft("Purchase Order", "PO", "Purchase Invoice", {}, "12345678-1234-1234", expected_source_modified="old")
        mapper.assert_not_called()
        reserve.assert_called_once(); rollback.assert_called_once_with()

    def test_legacy_retry_digest_is_unchanged_when_source_token_absent(self):
        source = document("Purchase Receipt", "PR")
        saved = document("Purchase Invoice", "PI", items=[frappe._dict(purchase_receipt="PR", pr_detail="R1")])
        payload = ["Purchase Receipt", "PR", "Purchase Invoice", None, None, {}]
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()
        cache = SimpleNamespace(lock=lambda *args, **kwargs: nullcontext(), get_value=lambda key: {"name": "PI", "digest": digest})
        previous = frappe._dict(status="Completed", data=json.dumps({"user": "QA", "digest": digest}),
            output=json.dumps({"name": "PI", "doctype": "Purchase Invoice", "permission": "write"}))
        with patch.object(frappe, "session", SimpleNamespace(user="QA")), \
             patch.object(actions.purchase_operation, "_existing", return_value=previous), \
             patch.object(actions, "_locked", return_value=saved), \
             patch.object(actions, "_source", return_value=(source, {})), patch.object(actions.service, "_read", return_value=saved), \
             patch.object(actions, "_advanced", return_value=False), patch.object(actions, "_projection", return_value={"document": {"name": "PI"}}), \
             patch.object(actions, "_native") as mapper:
            result = actions.save_document_draft("Purchase Receipt", "PR", "Purchase Invoice", {}, "12345678-1234-1234", expected_source_modified=None)
        self.assertTrue(result["reused"]); mapper.assert_not_called()

    def test_direct_order_invoice_submit_checks_po_cap_and_native_action(self):
        source = document("Purchase Order", items=[frappe._dict(name="A", item_code="ITEM", qty=5)])
        target = document("Purchase Invoice", "PI", docstatus=0, update_stock=0,
            items=[frappe._dict(purchase_order="PO", po_detail="A", qty=2, rate=0, item_code="ITEM")])
        target.submit = Mock()
        with patch.object(actions.service, "_read", return_value=target), patch.object(actions, "_locked", return_value=target), \
             patch.object(actions, "_locked_source", return_value=source), patch.object(actions, "_source", return_value=(source, {})), \
             patch.object(actions.service, "_require_fields"), patch.object(actions, "_invoice_source_reason", return_value=""), \
             patch.object(actions, "_current_maximum", return_value={"A": 3}), patch.object(actions, "_workflow_actions", return_value=["Submit"]), \
             patch("frappe.model.workflow.get_workflow_name", return_value=""), \
             patch.object(actions, "_projection", return_value={"document": {"name": "PI"}}), \
             patch.object(actions, "_native") as mapper:
            actions._submit_document("Purchase Invoice", "PI", "source-v1")
        target.submit.assert_called_once(); mapper.assert_not_called()

    def test_acknowledged_order_invoice_submit_replay_keeps_source_identity_without_writing(self):
        source = document("Purchase Order", items=[frappe._dict(name="A", item_code="ITEM", qty=5)])
        target = document("Purchase Invoice", "PI", update_stock=0,
            items=[frappe._dict(purchase_order="PO", po_detail="A", qty=2, rate=0, item_code="ITEM")])
        payload = ["Purchase Invoice", "PI", "source-v1", None]
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()
        cache = SimpleNamespace(lock=lambda *args, **kwargs: nullcontext(),
            get_value=lambda key: {"name": "PI", "doctype": "Purchase Invoice", "digest": digest})
        operation = Mock()
        previous = frappe._dict(status="Completed", data=json.dumps({"user": "QA", "digest": digest}),
            output=json.dumps({"name": "PI", "doctype": "Purchase Invoice", "permission": "submit"}))
        with patch.object(frappe, "session", SimpleNamespace(user="QA")), \
             patch.object(actions.purchase_operation, "_existing", return_value=previous), \
             patch.object(actions, "_locked", return_value=target), patch.object(actions, "_source", return_value=(source, {})) as read_source, \
             patch.object(actions, "_workflow_actions", return_value=[]), patch.object(actions, "_editable_fields", return_value=[]):
            result = actions._native_request("12345678-1234-1234", payload, operation)
        self.assertTrue(result["reused"])
        self.assertEqual(result["document"]["items"][0]["key"], "A")
        self.assertEqual(result["source_modified"], "source-v1")
        read_source.assert_called_once_with("Purchase Order", "PO")
        operation.assert_not_called()

    def test_acknowledged_order_invoice_submit_replay_rechecks_source_permission(self):
        target = document("Purchase Invoice", "PI", update_stock=0,
            items=[frappe._dict(purchase_order="PO", po_detail="A", qty=2, rate=0, item_code="ITEM")])
        payload = ["Purchase Invoice", "PI", "source-v1", None]
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()
        operation = Mock()
        previous = frappe._dict(status="Completed", data=json.dumps({"user": "QA", "digest": digest}),
            output=json.dumps({"name": "PI", "doctype": "Purchase Invoice", "permission": "submit"}))
        original_receipt = dict(previous)
        rollback = Mock()
        with patch.object(frappe, "session", SimpleNamespace(user="QA")), \
             patch.object(frappe, "db", SimpleNamespace(rollback=rollback)), patch.object(frappe, "logger", return_value=Mock()), \
             patch.object(actions.purchase_operation, "_existing", return_value=previous), \
             patch.object(actions, "_locked", return_value=target), patch.object(actions, "_source", side_effect=frappe.PermissionError) as source_acl, \
             patch.object(actions, "_workflow_actions", return_value=[]), patch.object(actions, "_editable_fields", return_value=[]):
            result = actions._native_request("12345678-1234-1234", payload, operation)
        self.assertEqual(result, {"failed": True, "error": "采购操作权限不足，请联系管理员核对", "error_id": "native_permission_denied"})
        source_acl.assert_called_once_with("Purchase Order", "PO")
        rollback.assert_called_once_with()
        self.assertEqual(dict(previous), original_receipt)
        operation.assert_not_called()

    def test_remaining_cap_limits_native_receipt_mapping_and_recalculates_native_schedule(self):
        source = document("Purchase Receipt", "PR")
        target = document("Purchase Invoice", None, items=[frappe._dict(pr_detail="R1", qty=10), frappe._dict(pr_detail="R2", qty=2)])
        target.run_method = Mock(); target.set_payment_schedule = Mock()
        actions._limit_native(target, {"R1": 4, "R2": 0}, source)
        self.assertEqual([(row.pr_detail, row.qty) for row in target.items], [("R1", 4)])
        target.run_method.assert_called_once_with("calculate_taxes_and_totals")
        target.set_payment_schedule.assert_called_once()

    def test_internal_transfer_missing_native_sale_uses_clear_fallback(self):
        source = document("Purchase Order", is_internal_supplier=1, represents_company="C")
        source.is_internal_transfer = lambda: True
        with patch.object(actions.service, "order_execution_reason", return_value=""), \
             patch.object(frappe, "db", SimpleNamespace(get_single_value=lambda *args: "No")):
            self.assertIn("原生", actions._invoice_source_reason(source))


class WorkflowActionTests(unittest.TestCase):
    def test_new_batch_invoice_confirmation_uses_native_submit_capability_and_workflow(self):
        doc = SimpleNamespace(doctype="Purchase Invoice", docstatus=0, is_new=lambda: True, has_permission=lambda permission: True)
        for workflow, expected in (("", ["Submit"]), ("Approval", [])):
            with self.subTest(workflow=workflow), patch("frappe.model.workflow.get_workflow_name", return_value=workflow):
                self.assertEqual(actions._workflow_actions(doc), expected)

    def test_purchase_receipt_uses_only_native_permitted_workflow_transitions(self):
        doc = SimpleNamespace(doctype="Purchase Receipt", docstatus=0, is_new=lambda: False)
        with patch("frappe.model.workflow.get_workflow_name", return_value="Active"), patch("frappe.model.workflow.get_workflow", return_value=SimpleNamespace(workflow_state_field="workflow_state")), patch.object(actions, "_fields"), patch("frappe.model.workflow.get_transitions", return_value=[]) as transitions:
            self.assertEqual(actions._workflow_actions(doc), [])
        transitions.assert_called_once_with(doc)

    def test_inactive_workflow_uses_native_submit_permission_without_transitions(self):
        doc = SimpleNamespace(doctype="Payment Entry", docstatus=0, is_new=lambda: False, has_permission=lambda permission: True)
        with patch("frappe.model.workflow.get_workflow_name", return_value=""), patch("frappe.model.workflow.get_transitions") as transitions:
            self.assertEqual(actions._workflow_actions(doc), ["Submit"])
        transitions.assert_not_called()

    def test_active_workflow_returns_only_native_transitions_with_approval_access(self):
        doc = SimpleNamespace(doctype="Payment Entry", docstatus=0, is_new=lambda: False)
        rows = [frappe._dict(action="Review"), frappe._dict(action="Approve")]
        with patch("frappe.model.workflow.get_workflow_name", return_value="Workflow"), patch("frappe.model.workflow.get_workflow", return_value=SimpleNamespace(workflow_state_field="workflow_state")), patch.object(actions, "_fields"), patch.object(frappe, "session", SimpleNamespace(user="QA")), patch("frappe.model.workflow.get_transitions", return_value=rows), patch("frappe.model.workflow.has_approval_access", side_effect=[False, True]):
            self.assertEqual(actions._workflow_actions(doc), ["Approve"])


class NativeQueryTests(unittest.TestCase):
    def test_foreign_qualified_tables_and_sort_expressions_are_rejected(self):
        for expression in ("`tabPayment Entry`.`posting_date` desc", "sum(grand_total) desc", "posting_date desc; select 1"):
            with self.subTest(expression=expression), patch.object(frappe, "throw", side_effect=frappe.ValidationError):
                with self.assertRaises(frappe.ValidationError):
                    actions.service._order_by("Purchase Receipt", expression, {"posting_date", "name"})

    def test_metadata_query_fields_preserve_owner_and_exclude_tables_and_virtual_fields(self):
        meta = SimpleNamespace(default_fields=["name", "owner"], fields=[
            frappe._dict(fieldname="remarks", fieldtype="Small Text"),
            frappe._dict(fieldname="items", fieldtype="Table"),
            frappe._dict(fieldname="computed", fieldtype="Data", is_virtual=1)],
            get_valid_columns=lambda: {"name", "owner", "remarks", "items", "computed"})
        with patch.object(frappe, "get_meta", return_value=meta):
            self.assertEqual(actions.service._query_fields("Purchase Receipt"), {"name", "owner", "remarks"})

    def test_same_doctype_qualified_sort_preserves_name_tie_breaker(self):
        for doctype in ("Purchase Receipt", "Payment Entry"):
            with self.subTest(doctype=doctype), patch.object(actions.service, "_require_fields"):
                self.assertEqual(actions.service._order_by(doctype, "`tab" + doctype + "`.`posting_date` desc", {"posting_date", "name"}), "posting_date desc, name asc")


class PaymentCompletionTests(unittest.TestCase):
    def setUp(self):
        install_request_state(self)
        guard = patch("deeplinkerp_branding.services.purchase_repost_boundary.execution", return_value=nullcontext())
        guard.start(); self.addCleanup(guard.stop)

    def test_configured_workflow_never_guesses_a_submit_action(self):
        doc = SimpleNamespace(name="PE", modified="v1")
        with patch("frappe.model.workflow.get_workflow_name", return_value="Approval"), patch.object(actions, "_payment", return_value={"document": {"docstatus": 0}}), patch.object(actions, "submit_document") as submit:
            self.assertEqual(actions._confirm_payment(doc)["document"]["docstatus"], 0)
        submit.assert_not_called()

    def test_batch_validation_acknowledges_only_after_rollback_but_runtime_failure_stays_unknown(self):
        for error in (frappe.ValidationError("Stale source"), RuntimeError("Unknown response")):
            with self.subTest(error=type(error).__name__):
                rollback = Mock()
                with patch.object(frappe, "session", SimpleNamespace(user="QA")), \
                     patch.object(actions.purchase_operation, "_existing", return_value=None), \
                     patch.object(actions.purchase_operation, "_reserve"), \
                     patch.object(actions, "_batch_context", side_effect=error), \
                     patch.object(frappe, "db", SimpleNamespace(rollback=rollback)):
                    if isinstance(error, frappe.ValidationError):
                        result = actions.record_document_batch([{"name": "PO", "modified": "stale"}], [{}],
                            "12345678-1234-1234-1234-123456789abc")
                        self.assertEqual(result, {"failed": True, "error": "Stale source"})
                    else:
                        with self.assertRaisesRegex(RuntimeError, "Unknown response"):
                            actions.record_document_batch([{"name": "PO", "modified": "stale"}], [{}],
                                "12345678-1234-1234-1234-123456789abc")
                rollback.assert_called_once_with()

    def test_no_submit_permission_returns_native_pending_projection(self):
        doc = SimpleNamespace(name="PE", modified="v1")
        with patch("frappe.model.workflow.get_workflow_name", return_value=""), patch.object(actions, "_workflow_actions", return_value=[]), patch.object(actions, "_payment", return_value={"document": {"docstatus": 0}}), patch.object(actions, "submit_document") as submit:
            self.assertEqual(actions._confirm_payment(doc)["document"]["docstatus"], 0)
        submit.assert_not_called()

    def test_explicit_approval_reuses_native_submit_endpoint_and_version(self):
        doc = SimpleNamespace(name="PE", modified="v1")
        with patch("frappe.model.workflow.get_workflow_name", return_value="Approval"), patch.object(actions, "submit_document", return_value={"document": {"docstatus": 1}}) as submit:
            self.assertEqual(actions._confirm_payment(doc, "Approve")["document"]["docstatus"], 1)
        submit.assert_called_once_with("Payment Entry", "PE", "v1", "Approve")

    def test_native_failure_acknowledges_only_after_database_rollback(self):
        from contextlib import nullcontext

        cache = SimpleNamespace(lock=lambda *args, **kwargs: nullcontext(), get_value=lambda key: None)
        rollback = Mock()
        with patch.object(frappe, "session", SimpleNamespace(user="QA")), \
             patch.object(actions.purchase_operation, "_existing", return_value=None), \
             patch.object(actions.purchase_operation, "_reserve"), \
             patch.object(frappe, "db", SimpleNamespace(rollback=rollback)):
            result = actions._payment_request("12345678-1234-1234-1234-123456789abc", [], Mock(side_effect=frappe.ValidationError("Native failure")))
        rollback.assert_called_once_with()
        self.assertEqual(result, {"failed": True, "error": "Native failure"})


if __name__ == "__main__":
    unittest.main()
