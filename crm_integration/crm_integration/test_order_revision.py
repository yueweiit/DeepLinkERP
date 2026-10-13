from contextlib import nullcontext
import hashlib
import json
from unittest.mock import MagicMock, patch

import frappe
from frappe.tests import UnitTestCase

from crm_integration.crm_integration.order_revision import (
	CRMOrderConflict,
	apply_items,
	check_version,
	current_order,
	describe_order,
	execute_revoke,
	execute_resubmit,
	execute_update,
	get_operation_result,
	assert_editable,
	assert_revokeable,
	eligibility,
	linked_facts,
	lock_expected_order,
	run_operation,
	validate_financial_revision,
	validate_operation,
)
from crm_integration.crm_integration.sales_order import protect_crm_order_identity


class TestCRMOrderRevision(UnitTestCase):
	def make_revoke_payload(self):
		return {
			"operationId": "OP-001", "operationType": "ORDER_REVOKE",
			"crmOrderNo": "CRM-001", "crmOrderId": "CRM-ID", "erpOrderId": "SO-001",
			"crmApprovalRound": 1, "expectedErpVersion": "ERP-V1",
			"operator": {"id": "USER-1"}, "reason": "撤回审批",
		}

	def test_new_operation_commits_result_with_business_change(self):
		op = MagicMock()
		with (
			patch("crm_integration.crm_integration.order_revision.validate_crm_api_user"),
			patch("crm_integration.crm_integration.order_revision.crm_sales_order_creation_lock", return_value=nullcontext()),
			patch.object(frappe.db, "get_value", return_value=None),
			patch.object(frappe.db, "savepoint"),
			patch.object(frappe.db, "commit") as commit,
			patch.object(frappe, "get_doc", return_value=op),
		):
			result = run_operation(self.make_revoke_payload(), "ORDER_REVOKE",
				lambda _: {"operationStatus": "SUCCEEDED", "revokedErpOrderId": "SO-001"})
		self.assertEqual(op.status, "SUCCEEDED")
		self.assertEqual(result["operationId"], "OP-001")
		op.insert.assert_called_once()
		op.save.assert_called_once()
		commit.assert_called_once()

	def test_rejected_operation_rolls_back_business_and_persists_result(self):
		op = MagicMock()
		with (
			patch("crm_integration.crm_integration.order_revision.validate_crm_api_user"),
			patch("crm_integration.crm_integration.order_revision.crm_sales_order_creation_lock", return_value=nullcontext()),
			patch.object(frappe.db, "get_value", return_value=None),
			patch.object(frappe.db, "savepoint"),
			patch.object(frappe.db, "rollback") as rollback,
			patch.object(frappe.db, "commit") as commit,
			patch.object(frappe, "get_doc", return_value=op),
		):
			def reject(_):
				raise CRMOrderConflict("订单已出库")

			result = run_operation(self.make_revoke_payload(), "ORDER_REVOKE", reject)
		self.assertEqual(result["operationStatus"], "REJECTED")
		self.assertFalse(result["sideEffects"])
		rollback.assert_called_once_with(save_point="crm_order_business")
		commit.assert_called_once()

	def test_current_order_ignores_cancelled_history(self):
		rows = [
			frappe._dict(name="SO-OLD", docstatus=2, custom_crm_order_id="CRM-ID"),
			frappe._dict(name="SO-NEW", docstatus=1, custom_crm_order_id="CRM-ID"),
		]
		with (
			patch("crm_integration.crm_integration.order_revision.order_names", return_value=rows),
			patch.object(frappe, "get_doc", return_value=frappe._dict(name="SO-NEW")),
		):
			current, history = current_order("CRM-001", "SO-NEW", "CRM-ID")
		self.assertEqual(current.name, "SO-NEW")
		self.assertEqual(len(history), 2)

	def test_current_order_rejects_two_active_orders(self):
		rows = [frappe._dict(name=name, docstatus=1) for name in ("SO-A", "SO-B")]
		with patch("crm_integration.crm_integration.order_revision.order_names", return_value=rows):
			with self.assertRaises(CRMOrderConflict):
				current_order("CRM-001")

	def test_operation_id_cannot_be_reused_with_different_payload(self):
		payload = {
			"operationId": "OP-001", "operationType": "ORDER_REVOKE",
			"crmOrderNo": "CRM-001", "crmOrderId": "CRM-ID", "erpOrderId": "SO-001",
			"crmApprovalRound": 1, "expectedErpVersion": "2026-10-09 12:00:00",
			"operator": {"id": "USER-1"}, "reason": "撤回审批",
		}
		with (
			patch("crm_integration.crm_integration.order_revision.validate_crm_api_user"),
			patch("crm_integration.crm_integration.order_revision.crm_sales_order_creation_lock", return_value=nullcontext()),
			patch.object(frappe.db, "get_value", return_value=("another-hash", "{}", "SUCCEEDED")),
			self.assertRaises(CRMOrderConflict),
		):
			run_operation(payload, "ORDER_REVOKE", MagicMock())

	def test_stale_erp_version_is_rejected_under_row_lock(self):
		with patch.object(frappe.db, "get_value", return_value="newer-version") as get_value:
			with self.assertRaises(CRMOrderConflict):
				lock_expected_order({"erpOrderId": "SO-001", "expectedErpVersion": "older-version"})
		get_value.assert_called_once_with("Sales Order", "SO-001", "modified", for_update=True)

	def test_structural_edit_after_mes_push_is_rejected(self):
		row = frappe._dict(name="ROW-1", item_code="ITEM-1", qty=10,
			custom_crm_order_item_id="LINE-1", delivered_qty=0, work_order_qty=0,
			billed_amt=0, produced_qty=0)
		row.set = lambda field, value: row.__setitem__(field, value)
		doc = MagicMock(items=[row], custom_process_status="Pending Production")
		facts = {"workOrders": [], "productionPlans": [], "stockEntries": [], "stockReservations": []}
		with self.assertRaisesRegex(CRMOrderConflict, "STRUCTURAL_CHANGE_BLOCKED"):
				apply_items(doc, [{"action": "UPDATE", "crmOrderItemId": "LINE-1",
					"erpOrderItemId": "ROW-1", "qty": 12}], facts)

	def test_all_revisions_after_mes_push_are_rejected(self):
		doc = MagicMock(company="Company", status="Submitted", custom_process_status="Pending Production",
			items=[frappe._dict(delivered_qty=0)])
		doc.get.return_value = None
		facts = {"deliveryNotes": [], "mesPush": {"lastPushStatus": "Success"}}
		with patch("crm_integration.crm_integration.order_revision.is_crm_integration_enabled", return_value=True):
			self.assertEqual(eligibility(doc, facts)[0], "MES_PUSHED")
			with self.assertRaisesRegex(CRMOrderConflict, "MES_PUSHED"):
				assert_editable(doc, facts)

	def test_e3_acknowledgement_blocks_revision_after_status_rollback(self):
		doc = MagicMock(company="Company", status="Submitted",
			custom_process_status="Pending Deposit Confirmation",
			items=[frappe._dict(delivered_qty=0)])
		doc.get.side_effect = lambda field: 1 if field == "custom_crm_production_started" else None
		facts = {"deliveryNotes": [], "mesPush": {"lastPushStatus": None}}
		with patch("crm_integration.crm_integration.order_revision.is_crm_integration_enabled", return_value=True):
			self.assertEqual(eligibility(doc, facts)[0], "PRODUCTION_STARTED")
			with self.assertRaisesRegex(CRMOrderConflict, "PRODUCTION_STARTED"):
				assert_editable(doc, facts)

	def test_delivery_blocks_revoke_even_after_production_started(self):
		doc = MagicMock(company="Company", status="Submitted",
			custom_process_status="Pending Production",
			items=[frappe._dict(name="ROW-1", delivered_qty=0)])
		doc.get.side_effect = lambda field: 1 if field == "custom_crm_production_started" else None
		facts = {"deliveryNotes": ["DN-001"], "mesPush": {"lastPushStatus": "Success"},
			"workOrders": [], "productionPlans": [], "stockEntries": [],
			"advancePaid": 0, "paymentEntries": [], "salesInvoices": []}
		with patch("crm_integration.crm_integration.order_revision.is_crm_integration_enabled", return_value=True):
			for delivery_notes, delivered_qty in ((["DN-001"], 0), ([], 1)):
				facts["deliveryNotes"] = delivery_notes
				doc.items[0].delivered_qty = delivered_qty
				self.assertEqual(eligibility(doc, facts)[0], "DELIVERED")
				with self.assertRaisesRegex(CRMOrderConflict, "DELIVERED"):
					assert_revokeable(doc, facts)
				with patch("crm_integration.crm_integration.order_revision.linked_facts", return_value=facts):
					state = describe_order(doc, [])
				self.assertFalse(state["canRevoke"])
				self.assertEqual(state["reasonCode"], "DELIVERED")

	def test_add_item_requires_explicit_finite_nonnegative_rate(self):
		doc = MagicMock(items=[], name="SO-001", custom_process_status="Pending Deposit Confirmation")
		facts = {"workOrders": [], "productionPlans": [], "stockEntries": [], "stockReservations": []}
		change = {"action": "ADD", "crmOrderItemId": "LINE-2", "item_code": "ITEM-2", "qty": 2}
		with patch("erpnext.controllers.accounts_controller.set_order_defaults") as defaults:
			for rate in (None, "bad", "NaN", "Infinity", -1, True):
				request = {**change, **({} if rate is None else {"rate": rate})}
				with self.assertRaisesRegex(frappe.ValidationError, "rate"):
					apply_items(doc, [request], facts)
			defaults.assert_not_called()
			defaults.return_value = frappe._dict(item_code="ITEM-2")
			self.assertTrue(apply_items(doc, [{**change, "rate": 0}], facts))
		doc.append.assert_called_once()

	def test_financial_revision_requires_valid_rate_and_actual_tax(self):
		doc = MagicMock(company="Company", currency="USD", conversion_rate=1,
			items=[frappe._dict(billed_amt=0)])
		facts = {"advancePaid": 0, "paymentEntries": [], "salesInvoices": []}
		with patch.object(frappe, "get_cached_value", return_value="USD"):
			validate_financial_revision(doc, {"currency": "EUR", "conversion_rate": 1.2},
				[{"charge_type": "Actual", "account_head": "Tax - Co", "tax_amount": 10}], facts)
			with self.assertRaisesRegex(frappe.ValidationError, "conversion_rate"):
				validate_financial_revision(doc, {"currency": "EUR"}, None, facts)
			with self.assertRaisesRegex(frappe.ValidationError, "Actual"):
				validate_financial_revision(doc, {},
					[{"charge_type": "On Net Total", "account_head": "Tax - Co", "tax_amount": 10}], facts)
		facts["paymentEntries"] = ["PE-001"]
		with self.assertRaisesRegex(CRMOrderConflict, "收款或开票"):
			validate_financial_revision(doc, {}, [], facts)

	def test_financial_revision_applies_currency_and_replaces_actual_taxes(self):
		doc = MagicMock(name="SO-001", company="Company", currency="USD",
			conversion_rate=1, custom_crm_revision=1,
			custom_process_status="Pending Deposit Confirmation", flags=frappe._dict(), items=[])
		doc.get.side_effect = lambda field: getattr(doc, field, None)
		doc.grand_total = 110
		payload = {"crmOrderNo": "CRM-001", "erpOrderId": "SO-001", "crmOrderId": "CRM-ID",
			"expectedCrmRevision": 1, "targetCrmRevision": 2, "crmApprovalRound": 1,
			"header": {"currency": "EUR", "conversion_rate": 1.2},
			"taxes": [{"charge_type": "Actual", "account_head": "Tax - Co", "tax_amount": 10}]}
		facts = {"purchaseOrders": [], "workOrders": [], "productionPlans": [],
			"stockEntries": [], "stockReservations": [], "advancePaid": 0,
			"paymentEntries": [], "salesInvoices": [], "mesPush": {}}
		with (
			patch("crm_integration.crm_integration.order_revision.lock_expected_order"),
			patch("crm_integration.crm_integration.order_revision.current_order", return_value=(doc, [])),
			patch("crm_integration.crm_integration.order_revision.check_version"),
			patch("crm_integration.crm_integration.order_revision.linked_facts", return_value=facts),
			patch("crm_integration.crm_integration.order_revision.assert_editable"),
			patch("crm_integration.crm_integration.order_revision.describe_order", return_value={}),
			patch.object(frappe, "get_cached_value", return_value="USD"),
		):
			result = execute_update(payload)
		self.assertEqual(result["grandTotal"], 110)
		doc.set.assert_any_call("currency", "EUR")
		doc.set.assert_any_call("conversion_rate", 1.2)
		doc.set.assert_any_call("taxes_and_charges", None)
		doc.set.assert_any_call("taxes", payload["taxes"])
		doc.calculate_taxes_and_totals.assert_called_once()
		self.assertEqual(doc.ignore_pricing_rule, 1)

	def test_payment_template_change_rebuilds_schedule(self):
		doc = MagicMock(company="Company", currency="USD", conversion_rate=1,
			payment_terms_template="OLD", grand_total=100, base_grand_total=100,
			custom_crm_revision=1, custom_process_status="Pending Deposit Confirmation",
			flags=frappe._dict(), items=[])
		doc.get.side_effect = lambda field: getattr(doc, field, None)
		doc.set.side_effect = lambda field, value: setattr(doc, field, value)
		payload = {"crmOrderNo": "CRM-001", "erpOrderId": "SO-001", "crmOrderId": "CRM-ID",
			"expectedCrmRevision": 1, "targetCrmRevision": 2, "crmApprovalRound": 1,
			"header": {"payment_terms_template": "NEW"}}
		facts = {"purchaseOrders": [], "workOrders": [], "productionPlans": [],
			"stockEntries": [], "stockReservations": [], "advancePaid": 0,
			"paymentEntries": [], "salesInvoices": [], "mesPush": {}}
		with (
			patch("crm_integration.crm_integration.order_revision.lock_expected_order"),
			patch("crm_integration.crm_integration.order_revision.current_order", return_value=(doc, [])),
			patch("crm_integration.crm_integration.order_revision.check_version"),
			patch("crm_integration.crm_integration.order_revision.linked_facts", return_value=facts),
			patch("crm_integration.crm_integration.order_revision.assert_editable"),
			patch("crm_integration.crm_integration.order_revision.describe_order", return_value={}),
		):
			execute_update(payload)
		doc.set.assert_any_call("payment_schedule", [])
		doc.set_payment_schedule.assert_called_once()

	def test_fixed_payment_amount_rejects_total_change(self):
		doc = MagicMock(company="Company", currency="USD", conversion_rate=1,
			payment_terms_template="FIXED", payment_schedule=[frappe._dict(invoice_portion=0)],
			grand_total=100, base_grand_total=100, rounded_total=0, base_rounded_total=0,
			custom_crm_revision=1,
			custom_process_status="Pending Deposit Confirmation", flags=frappe._dict(), items=[])
		doc.get.side_effect = lambda field: getattr(doc, field, None)
		doc.calculate_taxes_and_totals.side_effect = lambda: setattr(doc, "grand_total", 120)
		payload = {"crmOrderNo": "CRM-001", "erpOrderId": "SO-001", "crmOrderId": "CRM-ID",
			"expectedCrmRevision": 1, "targetCrmRevision": 2, "crmApprovalRound": 1,
			"header": {"custom_remark": "updated"}}
		facts = {"purchaseOrders": [], "workOrders": [], "productionPlans": [],
			"stockEntries": [], "stockReservations": [], "advancePaid": 0,
			"paymentEntries": [], "salesInvoices": [], "mesPush": {}}
		with (
			patch("crm_integration.crm_integration.order_revision.lock_expected_order"),
			patch("crm_integration.crm_integration.order_revision.current_order", return_value=(doc, [])),
			patch("crm_integration.crm_integration.order_revision.check_version"),
			patch("crm_integration.crm_integration.order_revision.linked_facts", return_value=facts),
			patch("crm_integration.crm_integration.order_revision.assert_editable"),
			self.assertRaisesRegex(CRMOrderConflict, "固定金额付款计划"),
		):
			execute_update(payload)
		doc.save.assert_not_called()

	def test_revoke_after_mes_push_is_allowed_without_downstream_facts(self):
		doc = MagicMock(company="Company", status="Submitted", custom_process_status="Pending Production",
			items=[frappe._dict(delivered_qty=0)])
		facts = {
			"deliveryNotes": [], "mesPush": {"lastPushStatus": "Success"},
			"workOrders": [], "productionPlans": [], "stockEntries": [],
			"advancePaid": 0, "paymentEntries": [], "salesInvoices": [],
		}
		with patch("crm_integration.crm_integration.order_revision.is_crm_integration_enabled", return_value=True):
			assert_revokeable(doc, facts)

	def test_execute_revoke_after_mes_push_cancels_erp_order(self):
		doc = MagicMock(
			company="Company", status="Submitted",
			custom_process_status="Pending Production", docstatus=1,
			items=[frappe._dict(delivered_qty=0)],
		)
		doc.name = "SO-001"
		doc.get.side_effect = lambda field: {
			"custom_crm_order_id": "CRM-ID", "custom_crm_approval_round": 1,
		}.get(field)
		facts = {
			"deliveryNotes": [], "mesPush": {"lastPushStatus": "Success"},
			"workOrders": [], "productionPlans": [], "stockEntries": [],
			"advancePaid": 0, "paymentEntries": [], "salesInvoices": [],
		}
		with (
			patch("crm_integration.crm_integration.order_revision.lock_expected_order"),
			patch("crm_integration.crm_integration.order_revision.current_order", return_value=(doc, [])),
			patch("crm_integration.crm_integration.order_revision.check_version"),
			patch("crm_integration.crm_integration.order_revision.linked_facts", return_value=facts),
			patch("crm_integration.crm_integration.order_revision.is_crm_integration_enabled", return_value=True),
		):
			result = execute_revoke(self.make_revoke_payload())
		self.assertEqual(result["revokedErpOrderId"], "SO-001")
		doc.cancel.assert_called_once()

	def test_resubmit_accepts_new_approval_round_after_revocation(self):
		old_doc = frappe._dict(name="SO-OLD", modified="ERP-V1", company="Company",
			customer="Customer", transaction_date="2026-10-09", custom_crm_order_id="CRM-ID",
			custom_crm_approval_round=1, custom_crm_revision=2)
		new_doc = MagicMock(name="SO-NEW", modified="ERP-V2", docstatus=1,
			custom_crm_revision=3, items=[frappe._dict(name="ROW-NEW", custom_crm_order_item_id="LINE-1")])
		new_doc.name = "SO-NEW"
		payload = {**self.make_revoke_payload(), "operationType": "ORDER_RESUBMIT",
			"erpOrderId": "SO-OLD", "crmApprovalRound": 2, "targetCrmRevision": 3,
			"salesOrder": {"customer": "Customer", "company": "Company",
				"custom_crm_order_no": "CRM-001", "items": [
					{"item_code": "ITEM-1", "qty": 1, "custom_crm_order_item_id": "LINE-1"}]}}
		with (
			patch("crm_integration.crm_integration.order_revision.lock_expected_order"),
			patch("crm_integration.crm_integration.order_revision.current_order", return_value=(None,
				[frappe._dict(name="SO-OLD", docstatus=2)])),
			patch("crm_integration.crm_integration.order_revision.is_crm_integration_enabled", return_value=True),
			patch.object(frappe.db, "exists", return_value=True),
			patch.object(frappe, "get_doc", side_effect=[old_doc, new_doc]),
			patch("crm_integration.crm_integration.api.validate_sales_order_payload"),
			patch("crm_integration.crm_integration.api.create_sales_order", return_value={"name": "SO-NEW"}) as create,
		):
			result = execute_resubmit(payload)
		self.assertEqual(result["effectiveErpOrderId"], "SO-NEW")
		self.assertEqual(create.call_args.args[0]["custom_crm_approval_round"], 2)
		old_doc.modified = "ERP-V2"
		with self.assertRaisesRegex(CRMOrderConflict, "ERP 版本已改变"):
			check_version(old_doc, payload, require_same_approval_round=False)
		old_doc.modified = "ERP-V1"
		with self.assertRaisesRegex(CRMOrderConflict, "CRM 稳定订单 ID 不匹配"):
			check_version(old_doc, {**payload, "crmOrderId": "OTHER-ID"}, require_same_approval_round=False)

	def test_draft_purchase_order_is_reported_as_structural_link(self):
		doc = MagicMock(name="SO-001", items=[frappe._dict(name="ROW-1")])
		doc.name = "SO-001"
		doc.get.return_value = 0
		with (
			patch.object(frappe, "get_all", side_effect=lambda doctype, **kwargs:
				["PO-001"] if doctype == "Purchase Order Item" else []) as get_all,
			patch("crm_integration.crm_integration.order_revision.mes_push_state", return_value={}),
			patch.object(frappe.db, "has_column", return_value=False),
		):
			facts = linked_facts(doc)
		self.assertEqual(facts["purchaseOrders"], ["PO-001"])
		purchase_calls = [call for call in get_all.call_args_list if call.args[0] == "Purchase Order Item"]
		self.assertTrue(all(call.kwargs["filters"]["docstatus"] == ["!=", 2] for call in purchase_calls))

	def test_purchase_order_or_ordered_qty_blocks_structural_edit(self):
		row = frappe._dict(name="ROW-1", item_code="ITEM-1", warehouse="WH-1", ordered_qty=0)
		doc = MagicMock(items=[row], custom_crm_revision=1,
			custom_process_status="Pending Deposit Confirmation")
		doc.get.side_effect = lambda field: getattr(doc, field, None)
		payload = {"crmOrderNo": "CRM-001", "erpOrderId": "SO-001", "crmOrderId": "CRM-ID",
			"expectedCrmRevision": 1, "targetCrmRevision": 2, "crmApprovalRound": 1,
			"items": [{"action": "UPDATE", "crmOrderItemId": "LINE-1", "qty": 12}]}
		facts = {"purchaseOrders": ["PO-001"], "workOrders": [], "productionPlans": [],
			"stockEntries": [], "stockReservations": [], "advancePaid": 0,
			"paymentEntries": [], "salesInvoices": [], "mesPush": {}}
		with (
			patch("crm_integration.crm_integration.order_revision.lock_expected_order"),
			patch("crm_integration.crm_integration.order_revision.current_order", return_value=(doc, [])),
			patch("crm_integration.crm_integration.order_revision.check_version"),
			patch("crm_integration.crm_integration.order_revision.linked_facts", return_value=facts),
			patch("crm_integration.crm_integration.order_revision.assert_editable"),
			patch("crm_integration.crm_integration.order_revision.apply_items", return_value=True),
		):
			with self.assertRaisesRegex(CRMOrderConflict, "采购关联"):
				execute_update(payload)
			facts["purchaseOrders"] = []
			row.ordered_qty = 3
			with self.assertRaisesRegex(CRMOrderConflict, "采购关联"):
				execute_update(payload)
			row.ordered_qty = 0
			facts["purchaseOrders"] = ["PO-001"]
			payload.pop("items")
			payload["header"] = {"set_warehouse": "WH-2"}
			with self.assertRaisesRegex(CRMOrderConflict, "采购关联"):
				execute_update(payload)

	def test_billed_item_cannot_be_replaced(self):
		row = frappe._dict(name="ROW-1", item_code="ITEM-1", qty=10,
			custom_crm_order_item_id="LINE-1", delivered_qty=0, work_order_qty=0,
			ordered_qty=0, billed_amt=200, produced_qty=0)
		doc = MagicMock(items=[row], custom_process_status="Pending Deposit Confirmation")
		facts = {"workOrders": [], "productionPlans": [], "stockEntries": [], "stockReservations": []}
		with self.assertRaisesRegex(CRMOrderConflict, "下游数量"):
			apply_items(doc, [{"action": "UPDATE", "crmOrderItemId": "LINE-1",
				"erpOrderItemId": "ROW-1", "item_code": "ITEM-2"}], facts)

	def test_qty_only_revision_cannot_drop_below_billed_amount(self):
		row = frappe._dict(name="ROW-1", item_code="ITEM-1", qty=10, rate=100, amount=1000,
			warehouse="WH-1", custom_crm_order_item_id="LINE-1", billed_amt=800,
			ordered_qty=0, delivered_qty=0)
		row.set = lambda field, value: row.__setitem__(field, value)
		doc = MagicMock(items=[row], custom_crm_revision=1,
			custom_process_status="Pending Deposit Confirmation", flags=frappe._dict())
		doc.calculate_taxes_and_totals = lambda: row.__setitem__("amount", row.qty * row.rate)
		doc.get.side_effect = lambda field: getattr(doc, field, None)
		payload = {"crmOrderNo": "CRM-001", "erpOrderId": "SO-001", "crmOrderId": "CRM-ID",
			"expectedCrmRevision": 1, "targetCrmRevision": 2, "crmApprovalRound": 1,
			"items": [{"action": "UPDATE", "crmOrderItemId": "LINE-1", "erpOrderItemId": "ROW-1", "qty": 5}]}
		facts = {"purchaseOrders": [], "workOrders": [], "productionPlans": [],
			"stockEntries": [], "stockReservations": [], "advancePaid": 0,
			"paymentEntries": [], "salesInvoices": [], "mesPush": {}}
		with (
			patch("crm_integration.crm_integration.order_revision.lock_expected_order"),
			patch("crm_integration.crm_integration.order_revision.current_order", return_value=(doc, [])),
			patch("crm_integration.crm_integration.order_revision.check_version"),
			patch("crm_integration.crm_integration.order_revision.linked_facts", return_value=facts),
			patch("crm_integration.crm_integration.order_revision.assert_editable"),
		):
			with self.assertRaisesRegex(CRMOrderConflict, "低于已开票金额"):
				execute_update(payload)

	def test_nonstructural_revision_keeps_purchase_and_existing_billing_links(self):
		row = frappe._dict(name="ROW-1", item_code="ITEM-1", qty=5, rate=100,
			amount=500, billed_amt=800, warehouse="WH-1", ordered_qty=3,
			custom_crm_order_item_id="LINE-1")
		doc = MagicMock(items=[row], custom_crm_revision=1,
			custom_process_status="Pending Deposit Confirmation", flags=frappe._dict(), grand_total=500)
		doc.get.side_effect = lambda field: getattr(doc, field, None)
		payload = {"crmOrderNo": "CRM-001", "erpOrderId": "SO-001", "crmOrderId": "CRM-ID",
			"expectedCrmRevision": 1, "targetCrmRevision": 2, "crmApprovalRound": 1,
			"header": {"custom_remark": "仅更新备注"}}
		facts = {"purchaseOrders": ["PO-001"], "workOrders": [], "productionPlans": [],
			"stockEntries": [], "stockReservations": [], "advancePaid": 0,
			"paymentEntries": [], "salesInvoices": [], "mesPush": {}}
		with (
			patch("crm_integration.crm_integration.order_revision.lock_expected_order"),
			patch("crm_integration.crm_integration.order_revision.current_order", return_value=(doc, [])),
			patch("crm_integration.crm_integration.order_revision.check_version"),
			patch("crm_integration.crm_integration.order_revision.linked_facts", return_value=facts),
			patch("crm_integration.crm_integration.order_revision.assert_editable"),
			patch("crm_integration.crm_integration.order_revision.describe_order", return_value={}),
		):
			result = execute_update(payload)
		self.assertEqual(result["operationStatus"], "SUCCEEDED")
		doc.set.assert_called_once_with("custom_remark", "仅更新备注")

	def test_update_requires_consecutive_crm_revision(self):
		payload = {
			"operationId": "OP-001", "operationType": "ORDER_UPDATE",
			"crmOrderNo": "CRM-001", "crmOrderId": "CRM-ID", "erpOrderId": "SO-001",
			"crmApprovalRound": 1, "expectedErpVersion": "ERP-V1",
			"expectedCrmRevision": 2, "targetCrmRevision": 4,
			"operator": {"id": "USER-1"}, "reason": "修改数量", "items": [{"action": "UPDATE"}],
		}
		with self.assertRaises(frappe.ValidationError):
			validate_operation(payload, "ORDER_UPDATE")

	def test_crm_identity_cannot_be_changed_by_generic_save(self):
		before = frappe._dict(custom_crm_order_no="CRM-001", custom_crm_revision=1, items=[])
		doc = frappe._dict(custom_crm_order_no="CRM-001", custom_crm_revision=2,
			flags=frappe._dict(), items=[])
		doc.get_doc_before_save = lambda: before
		with self.assertRaisesRegex(frappe.ValidationError, "CRM 订单身份与版本"):
			protect_crm_order_identity(doc)

	def test_failed_operation_retries_same_payload_and_id(self):
		payload = {
			"operationId": "OP-RETRY", "operationType": "ORDER_REVOKE",
			"crmOrderNo": "CRM-001", "crmOrderId": "CRM-ID", "erpOrderId": "SO-001",
			"crmApprovalRound": 1, "expectedErpVersion": "ERP-V1",
			"operator": {"id": "USER-1"}, "reason": "撤回审批",
		}
		canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
		digest = hashlib.sha256(canonical.encode()).hexdigest()
		op = MagicMock(attempt_count=1)
		with (
			patch("crm_integration.crm_integration.order_revision.validate_crm_api_user"),
			patch("crm_integration.crm_integration.order_revision.crm_sales_order_creation_lock", return_value=nullcontext()),
			patch.object(frappe.db, "get_value", return_value=(digest, "{}", "FAILED")),
			patch.object(frappe.db, "savepoint"),
			patch.object(frappe.db, "commit"),
			patch.object(frappe, "get_doc", return_value=op),
		):
			result = run_operation(payload, "ORDER_REVOKE", lambda _: {"operationStatus": "SUCCEEDED"})
		self.assertEqual(result["operationStatus"], "SUCCEEDED")
		self.assertEqual(op.attempt_count, 2)

	def test_retry_trace_id_does_not_change_business_hash(self):
		payload = {
			"operationId": "OP-TRACE", "operationType": "ORDER_REVOKE",
			"crmOrderNo": "CRM-001", "crmOrderId": "CRM-ID", "erpOrderId": "SO-001",
			"crmApprovalRound": 1, "expectedErpVersion": "ERP-V1",
			"operator": {"id": "USER-1"}, "reason": "撤回审批", "traceId": "ATTEMPT-2",
		}
		business = {key: value for key, value in payload.items() if key != "traceId"}
		canonical = json.dumps(business, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
		digest = hashlib.sha256(canonical.encode()).hexdigest()
		with (
			patch("crm_integration.crm_integration.order_revision.validate_crm_api_user"),
			patch("crm_integration.crm_integration.order_revision.crm_sales_order_creation_lock", return_value=nullcontext()),
			patch.object(frappe.db, "get_value", return_value=(digest, '{"operationStatus":"SUCCEEDED"}', "SUCCEEDED")),
		):
			result = run_operation(payload, "ORDER_REVOKE", MagicMock())
		self.assertTrue(result["idempotentReplay"])

	def test_operation_result_survives_current_order_conflict(self):
		row = frappe._dict(crm_order_no="CRM-001", status="SUCCEEDED", request_hash="hash",
			result_payload='{"operationStatus":"SUCCEEDED"}', operation_type="ORDER_REVOKE")
		with (
			patch("crm_integration.crm_integration.order_revision.validate_crm_api_user"),
			patch.object(frappe.db, "get_value", return_value=row),
			patch("crm_integration.crm_integration.order_revision.current_order",
				side_effect=CRMOrderConflict("两个有效单")),
		):
			result = get_operation_result("OP-001", "CRM-001")
		self.assertEqual(result["operationStatus"], "SUCCEEDED")
		self.assertEqual(result["currentOrderError"], "两个有效单")
