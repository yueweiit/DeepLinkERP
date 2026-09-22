import builtins
from unittest.mock import MagicMock, call, patch

import frappe
from frappe.tests import UnitTestCase

from crm_integration.crm_integration.sales_order import (
	CRM_STATUS_CONFIRMED_DEPOSIT_PUSH_PRODUCTION,
	CRM_STATUS_IN_PRODUCTION,
	PENDING_PRODUCTION,
	build_mes_sales_order_payload,
	confirm_deposit_and_push_to_mes_job,
	confirm_deposit_and_push_to_mes,
	enqueue_confirm_deposit_and_push_to_mes,
	get_mes_integration_services,
	make_crm_trace_id,
	prevent_duplicate_crm_order_no,
	reconcile_final_payment,
	reject_sales_order,
	run_confirm_deposit_sync,
)


class TestMESSalesOrderPayload(UnitTestCase):
	def test_versions_are_preserved_per_sales_order_line(self):
		order = frappe._dict(
			name="SO-001",
			custom_crm_order_no="CRM-001",
			items=[
				frappe._dict(name="SOI-PRINT", item_code="ITEM-001", qty=100, custom_version="PC_PRINT"),
				frappe._dict(name="SOI-OTHER", item_code="ITEM-001", qty=50, custom_version="OTHER_VERSION"),
			],
		)

		payload = build_mes_sales_order_payload(order)
		self.assertEqual(
			[(row["name"], row["custom_version"]) for row in payload["data"]["items"]],
			[("SOI-PRINT", "PC_PRINT"), ("SOI-OTHER", "OTHER_VERSION")],
		)

	def test_orders_without_versions_keep_optional_field_absent(self):
		for version_fields in ({}, {"custom_version": None}, {"custom_version": ""}):
			with self.subTest(version_fields=version_fields):
				order = frappe._dict(
					name="SO-001",
					custom_crm_order_no="CRM-001",
					items=[frappe._dict(item_code="ITEM-001", qty=100, **version_fields)],
				)

				payload = build_mes_sales_order_payload(order)
				self.assertEqual(len(payload["data"]["items"]), 1)
				self.assertNotIn("custom_version", payload["data"]["items"][0])


class TestSalesOrderPermissions(UnitTestCase):
	def test_duplicate_crm_order_no_is_rejected_before_insert(self):
		doc = frappe._dict(custom_crm_order_no="CRM-001")

		with (
			patch(
				"crm_integration.crm_integration.sales_order.get_sales_order_names_by_crm_order_no",
				return_value=["SO-EXISTING"],
			),
			self.assertRaises(frappe.ValidationError),
		):
			prevent_duplicate_crm_order_no(doc)

	def test_reject_checks_cancel_permission_before_crm_push(self):
		doc = self.make_sales_order()
		doc.check_permission.side_effect = frappe.PermissionError

		with (
			patch.object(frappe, "get_doc", return_value=doc),
			patch(
				"crm_integration.crm_integration.sales_order.is_crm_integration_enabled",
				return_value=True,
			),
			patch(
				"crm_integration.crm_integration.sales_order.push_sales_order_status_to_crm"
			) as push_status,
			self.assertRaises(frappe.PermissionError),
		):
			reject_sales_order("SO-001")

		doc.check_permission.assert_called_once_with("cancel")
		push_status.assert_not_called()

	def test_confirm_deposit_checks_write_permission_before_push(self):
		doc = self.make_sales_order()
		doc.check_permission.side_effect = frappe.PermissionError

		with (
			patch.object(frappe, "get_doc", return_value=doc),
			patch(
				"crm_integration.crm_integration.sales_order.is_crm_integration_enabled",
				return_value=True,
			),
			patch(
				"crm_integration.crm_integration.sales_order.push_sales_order_status_to_crm"
			) as push_status,
			self.assertRaises(frappe.PermissionError),
		):
			confirm_deposit_and_push_to_mes("SO-001")

		doc.check_permission.assert_called_once_with("write")
		push_status.assert_not_called()

	def test_confirm_deposit_queues_external_sync_after_commit(self):
		doc = self.make_sales_order()

		with (
			patch.object(frappe, "get_doc", return_value=doc),
			patch(
				"crm_integration.crm_integration.sales_order.is_crm_integration_enabled",
				return_value=True,
			),
			patch(
				"crm_integration.crm_integration.sales_order.enqueue_confirm_deposit_and_push_to_mes"
			) as enqueue_sync,
			patch("crm_integration.crm_integration.sales_order.validate_mes_sync_available"),
			patch(
				"crm_integration.crm_integration.sales_order.push_sales_order_status_to_crm"
			) as push_status,
			patch("crm_integration.crm_integration.sales_order.push_sales_order_to_mes") as push_mes,
		):
			result = confirm_deposit_and_push_to_mes("SO-001")

		enqueue_sync.assert_called_once_with("SO-001")
		push_status.assert_not_called()
		push_mes.assert_not_called()
		self.assertTrue(result["queued"])

	def test_missing_mes_app_returns_clear_validation_error(self):
		original_import = builtins.__import__

		def import_without_mes(name, *args, **kwargs):
			if name.startswith("mes_integration"):
				error = ModuleNotFoundError("No module named 'mes_integration'")
				error.name = "mes_integration"
				raise error
			return original_import(name, *args, **kwargs)

		with (
			patch("builtins.__import__", side_effect=import_without_mes),
			self.assertRaisesRegex(frappe.ValidationError, "mes_integration"),
		):
			get_mes_integration_services()

	def test_confirm_deposit_job_is_deduplicated(self):
		with patch.object(frappe, "enqueue") as enqueue:
			enqueue_confirm_deposit_and_push_to_mes("SO-001")

		enqueue.assert_called_once_with(
			"crm_integration.crm_integration.sales_order.confirm_deposit_and_push_to_mes_job",
			queue="short",
			enqueue_after_commit=True,
			job_id="crm-confirm-deposit-SO-001",
			deduplicate=True,
			sales_order_name="SO-001",
		)

	def test_confirm_deposit_job_advances_status_only_after_external_sync(self):
		doc = self.make_sales_order()
		operations = MagicMock()

		with (
			patch(
				"crm_integration.crm_integration.sales_order.push_sales_order_status_to_crm"
			) as push_status,
			patch("crm_integration.crm_integration.sales_order.push_sales_order_to_mes") as push_mes,
			patch("crm_integration.crm_integration.sales_order.set_process_status") as set_status,
		):
			operations.attach_mock(push_status, "push_status")
			operations.attach_mock(push_mes, "push_mes")
			operations.attach_mock(set_status, "set_status")
			run_confirm_deposit_sync(doc)

		self.assertEqual(
			operations.mock_calls,
			[
				call.push_status(doc, CRM_STATUS_CONFIRMED_DEPOSIT_PUSH_PRODUCTION),
				call.push_status(doc, CRM_STATUS_IN_PRODUCTION),
				call.push_mes(doc),
				call.set_status(doc, PENDING_PRODUCTION),
			],
		)

	def test_failed_confirm_deposit_job_persists_failure_log(self):
		doc = self.make_sales_order()

		with (
			patch.object(frappe, "get_doc", return_value=doc),
			patch(
				"crm_integration.crm_integration.sales_order.is_crm_integration_enabled",
				return_value=True,
			),
			patch(
				"crm_integration.crm_integration.sales_order.run_confirm_deposit_sync",
				side_effect=RuntimeError("MES unavailable"),
			),
			patch.object(frappe.db, "rollback") as rollback,
			patch.object(frappe.db, "commit") as commit,
			patch("crm_integration.crm_integration.sales_order.create_crm_log") as create_log,
			self.assertRaisesRegex(RuntimeError, "MES unavailable"),
		):
			confirm_deposit_and_push_to_mes_job("SO-001")

		rollback.assert_called_once_with()
		create_log.assert_called_once()
		commit.assert_called_once_with()

	def test_crm_status_trace_id_is_stable_for_retries(self):
		first = make_crm_trace_id("SO-001", CRM_STATUS_IN_PRODUCTION)
		second = make_crm_trace_id("SO-001", CRM_STATUS_IN_PRODUCTION)

		self.assertEqual(first, second)

	def test_reconcile_final_payment_checks_write_permission_before_status_change(self):
		doc = self.make_sales_order()
		doc.check_permission.side_effect = frappe.PermissionError

		with (
			patch.object(frappe, "get_doc", return_value=doc),
			patch(
				"crm_integration.crm_integration.sales_order.is_crm_integration_enabled",
				return_value=True,
			),
			patch("crm_integration.crm_integration.sales_order.set_process_status") as set_status,
			self.assertRaises(frappe.PermissionError),
		):
			reconcile_final_payment("SO-001")

		doc.check_permission.assert_called_once_with("write")
		set_status.assert_not_called()

	def make_sales_order(self):
		doc = MagicMock()
		doc.name = "SO-001"
		doc.docstatus = 1
		doc.get.side_effect = lambda field: {
			"company": "Test Company",
			"custom_process_status": "Pending Deposit Confirmation",
			"status": "To Deliver and Bill",
		}.get(field)
		return doc
