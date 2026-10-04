from unittest.mock import MagicMock, patch

import frappe
from frappe.tests import UnitTestCase

from crm_integration.crm_integration import finance_release as release
from crm_integration.crm_integration import sales_order as flow


class TestFinanceRelease(UnitTestCase):
	def setUp(self):
		super().setUp()
		self.doc = frappe._dict(doctype="Sales Order", name="SO-1", company="MX", customer="C-1", docstatus=1,
			status="To Deliver and Bill", custom_process_status=release.PENDING)
		self.enterContext(patch.object(release, "readable_fields", return_value={"company", "customer", "custom_process_status", "references", "party_type", "party", "payment_type", "posting_date", "paid_from_account_currency", "paid_to_account_currency", "reference_doctype", "reference_name", "allocated_amount"}))
		self.enterContext(patch.object(release, "has_release_permission", return_value=True))
		self.enterContext(patch.object(release, "is_crm_integration_enabled", return_value=True))
		self.enterContext(patch.object(frappe.db, "exists", return_value=False))
		self.enterContext(patch.object(frappe, "get_all", return_value=[]))

	def test_manual_authorization_does_not_require_a_recorded_deposit(self):
		review = release.review_order(self.doc)
		self.assertTrue(review["can_release"])
		self.assertEqual(review["receipts"], [])
		self.assertNotIn("required_deposit", review)

	def test_sales_order_edit_permission_does_not_grant_release(self):
		with patch.object(release, "has_release_permission", return_value=False):
			self.assertFalse(release.review_order(self.doc)["can_release"])

	def test_current_state_is_checked_independently_of_finance_authorization(self):
		for values in ({"docstatus": 0}, {"docstatus": 2}, {"status": "Closed"}, {"status": "On Hold"}, {"custom_process_status": release.PROCESSING}, {"custom_process_status": "Pending Production"}):
			with self.subTest(values=values):
				self.assertFalse(release.review_order(frappe._dict({**self.doc, **values}))["can_release"])

	def test_disabled_crm_company_cannot_release(self):
		with patch.object(release, "is_crm_integration_enabled", return_value=False):
			self.assertFalse(release.review_order(self.doc)["can_release"])

	def payment(self, **values):
		return frappe._dict(name="PE-1", company="MX", party_type="Customer", party="C-1", docstatus=1, payment_type="Receive", posting_date="2026-10-04", paid_from_account_currency="MXN",
			references=[frappe._dict(reference_doctype="Sales Order", reference_name="SO-1", allocated_amount=123)], **values)

	def test_receipts_show_allocation_not_payment_total_and_keep_currency(self):
		payment = self.payment()
		payment.references.append(frappe._dict(reference_doctype="Sales Order", reference_name="SO-OTHER", allocated_amount=900))
		with patch.object(frappe, "get_all", return_value=["PE-1"]), patch.object(frappe, "get_doc", return_value=payment), patch.object(frappe, "has_permission", return_value=True):
			row = release.recorded_receipts(self.doc)["receipts"][0]
			self.assertEqual(row["allocated_amount"], 123)
			self.assertEqual(row["currency"], "MXN")

	def test_hidden_receipt_is_omitted_without_treating_it_as_nonpayment(self):
		with patch.object(frappe, "get_all", return_value=["SECRET"]), patch.object(frappe, "get_doc", return_value=self.payment()), patch.object(frappe, "has_permission", return_value=False):
			review = release.review_order(self.doc)
			self.assertTrue(review["can_release"])
			self.assertFalse(review["receipts_complete"])
			self.assertNotIn("SECRET", str(review))

	def test_wrong_company_or_customer_association_blocks_confirmation(self):
		for field in ("company", "party"):
			payment = self.payment(); payment[field] = "OTHER"
			with self.subTest(field=field), patch.object(frappe, "get_all", return_value=["PE-1"]), patch.object(frappe, "get_doc", return_value=payment), patch.object(frappe, "has_permission", return_value=True):
				self.assertFalse(release.review_order(self.doc)["can_release"])

	def test_failed_batch_item_does_not_undo_committed_orders(self):
		with patch.object(flow, "confirm_deposit_and_push_to_mes", side_effect=[{"queued": True}, RuntimeError(), {"queued": True}]) as confirm, patch.object(frappe.db, "commit") as commit, patch.object(frappe.db, "rollback") as rollback:
			rows = release.confirm_production_release_batch(["SO-1", "SO-2", "SO-3"])["orders"]
		self.assertEqual([row["state"] for row in rows], ["processing", "failed", "processing"])
		self.assertEqual(commit.call_count, 2); rollback.assert_called_once()
		self.assertEqual(confirm.call_count, 3)

	def test_unscoped_order_review_returns_no_details(self):
		with patch.object(release, "read_order", side_effect=frappe.PermissionError):
			row = release.get_finance_release_review(["SO-HIDDEN"])["orders"][0]
		self.assertEqual(set(row), {"name", "can_release", "reason"})

	def test_confirmation_aborts_when_audit_cannot_be_saved(self):
		doc = MagicMock(); doc.name = "SO-1"; doc.company = "MX"; doc.docstatus = 1
		doc.get.side_effect = self.doc.get
		with patch.object(release, "read_order", return_value=doc), patch.object(release, "review_order", return_value={"can_release": True, "receipts": [], "receipts_complete": True}), patch.object(frappe.db, "get_value"), patch.object(flow, "is_crm_integration_enabled", return_value=True), patch.object(flow, "validate_mes_sync_available"), patch.object(flow, "create_crm_log", return_value=None), patch.object(flow, "set_process_status") as status, patch.object(flow, "enqueue_confirm_deposit_and_push_to_mes") as enqueue:
			with self.assertRaises(frappe.ValidationError): flow.confirm_deposit_and_push_to_mes("SO-1")
		status.assert_not_called(); enqueue.assert_not_called()

	def test_processing_confirmation_does_not_allow_production(self):
		with patch.object(release, "read_order", return_value=frappe._dict({**self.doc, "custom_process_status": release.PROCESSING})):
			with self.assertRaises(frappe.ValidationError): release.assert_production_released("SO-1")

	def test_production_cannot_link_an_order_from_another_company(self):
		with patch.object(release, "read_order", return_value=frappe._dict({**self.doc, "custom_process_status": "Pending Production"})):
			with self.assertRaises(frappe.ValidationError): release.assert_production_released("SO-1", "OTHER")

	def test_combined_production_plan_references_all_pass_the_same_gate(self):
		plan = frappe._dict(doctype="Production Plan", company="MX", po_items=[frappe._dict(sales_order="SO-1")], prod_plan_references=[frappe._dict(sales_order="SO-2"), frappe._dict(sales_order="SO-1")])
		with patch.object(release, "assert_production_released") as gate:
			release.validate_production_sources(plan)
		self.assertEqual(gate.call_count, 2)
		gate.assert_any_call("SO-1", "MX"); gate.assert_any_call("SO-2", "MX")

	def test_existing_released_orders_continue_without_backfilling_audit(self):
		with patch.object(release, "read_order", return_value=frappe._dict({**self.doc, "custom_process_status": "Pending Production"})):
			release.assert_production_released("SO-1", "MX")

	def test_input_is_bounded_and_deduplicated(self):
		self.assertEqual(release.order_names(["SO-1", "SO-1"]), ["SO-1"])
		for invalid in ([], "{}", [1], ["SO"] * 101):
			with self.subTest(invalid=invalid), self.assertRaises(frappe.ValidationError): release.order_names(invalid)
