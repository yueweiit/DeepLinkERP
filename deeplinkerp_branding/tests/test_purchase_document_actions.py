"""Current native quantity caps and protected mapping fields."""
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import frappe

from deeplinkerp_branding.services import purchase_document_actions as actions


class QuantityCapTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(callable(getattr(actions, "_current_maximum", None)), "Current locking quantity guard is missing")

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


class WorkflowActionTests(unittest.TestCase):
    def test_purchase_receipt_never_offers_submission_even_with_active_workflow(self):
        doc = SimpleNamespace(doctype="Purchase Receipt", docstatus=0, is_new=lambda: False)
        with patch("frappe.model.workflow.get_workflow_name", return_value="Active"), patch("frappe.model.workflow.get_workflow", return_value=SimpleNamespace(workflow_state_field="workflow_state")), patch.object(actions, "_fields"), patch("frappe.model.workflow.get_transitions") as transitions:
            self.assertEqual(actions._workflow_actions(doc), [])
        transitions.assert_not_called()

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


if __name__ == "__main__":
    unittest.main()
