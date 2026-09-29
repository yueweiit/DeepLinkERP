from unittest.mock import MagicMock, call, patch

import frappe
from frappe.tests import UnitTestCase

from mes_integration.mes_integration.sales_order_field_change import (
	apply_field_change,
	build_result,
	get_batch_payload,
	get_sales_order_field_change_result,
	hash_operation,
	process_field_change,
	replay_existing_batch,
	update_sales_order_fields_batch,
	validate_batch_idempotency_header,
	validate_batch_payload,
	validate_sales_order_for_change,
)


class TestMESSalesOrderFieldChange(UnitTestCase):
	def setUp(self):
		self.item = {
			"externalOrderId": "SAL-ORD-2026-00001",
			"orderNo": "SAL-ORD-2026-00001",
			"sourceVersion": 4,
			"changes": {},
		}
		self.change = {
			"operationId": "MES-SO-00001-V4-ODT",
			"expectedValue": "TN0001",
			"value": "TN0005",
		}

	def make_sales_order(self, process_status="Pending Production"):
		return frappe._dict(
			name="SAL-ORD-2026-00001",
			docstatus=1,
			status="To Deliver and Bill",
			company="Test Company",
			custom_crm_order_no="CRM-00001",
			custom_process_status=process_status,
			custom_odt="TN0001",
			delivery_date="2026-10-01",
			transaction_date="2026-09-01",
			items=[frappe._dict(name="SO-ITEM-1"), frappe._dict(name="SO-ITEM-2")],
		)

	def test_processing_and_pending_production_are_allowed(self):
		with (
			patch(
				"mes_integration.mes_integration.sales_order_field_change.is_mes_integration_enabled",
				return_value=True,
			),
			patch.object(frappe, "has_permission", return_value=True),
			patch.object(frappe.db, "has_column", return_value=True),
		):
			for process_status in (
				"Deposit Confirmation Processing",
				"Pending Production",
			):
				with self.subTest(process_status=process_status):
					result = validate_sales_order_for_change(
						self.make_sales_order(process_status),
						self.item,
						"odtNo",
						self.change,
					)
					self.assertIsNone(result)

	def test_later_process_status_is_rejected_without_changing_it(self):
		sales_order = self.make_sales_order("Pending Final Payment")
		with (
			patch(
				"mes_integration.mes_integration.sales_order_field_change.is_mes_integration_enabled",
				return_value=True,
			),
			patch.object(frappe, "has_permission", return_value=True),
			patch.object(frappe.db, "has_column", return_value=True),
		):
			result = validate_sales_order_for_change(
				sales_order,
				self.item,
				"odtNo",
				self.change,
			)

		self.assertEqual(result["status"], "conflict")
		self.assertEqual(result["errorCode"], "ORDER_STATE_NOT_ALLOWED")
		self.assertEqual(sales_order.custom_process_status, "Pending Final Payment")

	def test_exact_operation_replay_returns_first_result(self):
		record = frappe._dict(
			operation_id=self.change["operationId"],
			request_hash=hash_operation(self.item, "odtNo", self.change),
			status="success",
			applied_value="TN0005",
			current_value=None,
			error_code=None,
			message="success",
			retryable=0,
		)
		with (
			patch(
				"mes_integration.mes_integration.sales_order_field_change.get_operation_record",
				return_value=record,
			),
			patch(
				"mes_integration.mes_integration.sales_order_field_change.get_locked_sales_order"
			) as get_sales_order,
		):
			result = process_field_change("BATCH-1", self.item, "odtNo", self.change)

		self.assertEqual(result["status"], "success")
		self.assertEqual(result["appliedValue"], "TN0005")
		get_sales_order.assert_not_called()

	def test_operation_id_with_changed_content_is_rejected(self):
		record = frappe._dict(
			operation_id=self.change["operationId"],
			request_hash="different-hash",
		)
		with patch(
			"mes_integration.mes_integration.sales_order_field_change.get_operation_record",
			return_value=record,
		):
			result = process_field_change("BATCH-1", self.item, "odtNo", self.change)

		self.assertEqual(result["status"], "conflict")
		self.assertEqual(result["errorCode"], "IDEMPOTENCY_CONTENT_MISMATCH")

	def test_stale_source_version_is_rejected(self):
		sales_order = self.make_sales_order()
		persisted = []
		with (
			patch(
				"mes_integration.mes_integration.sales_order_field_change.get_operation_record",
				return_value=None,
			),
			patch(
				"mes_integration.mes_integration.sales_order_field_change.get_locked_sales_order",
				return_value=sales_order,
			),
			patch(
				"mes_integration.mes_integration.sales_order_field_change.validate_sales_order_for_change",
				return_value=None,
			),
			patch(
				"mes_integration.mes_integration.sales_order_field_change.get_latest_source_version",
				return_value=5,
			),
			patch(
				"mes_integration.mes_integration.sales_order_field_change.persist_result",
				side_effect=lambda *args: persisted.append(args[4]) or args[4],
			),
			patch(
				"mes_integration.mes_integration.sales_order_field_change.apply_field_change"
			) as apply_change,
		):
			result = process_field_change("BATCH-1", self.item, "odtNo", self.change)

		self.assertEqual(result["errorCode"], "STALE_SOURCE_VERSION")
		self.assertEqual(persisted[0]["currentValue"], "TN0001")
		apply_change.assert_not_called()

	def test_expected_value_mismatch_is_rejected(self):
		sales_order = self.make_sales_order()
		change = {**self.change, "expectedValue": "TN0000"}
		with (
			patch(
				"mes_integration.mes_integration.sales_order_field_change.get_operation_record",
				return_value=None,
			),
			patch(
				"mes_integration.mes_integration.sales_order_field_change.get_locked_sales_order",
				return_value=sales_order,
			),
			patch(
				"mes_integration.mes_integration.sales_order_field_change.validate_sales_order_for_change",
				return_value=None,
			),
			patch(
				"mes_integration.mes_integration.sales_order_field_change.get_latest_source_version",
				return_value=4,
			),
			patch(
				"mes_integration.mes_integration.sales_order_field_change.persist_result",
				side_effect=lambda *args: args[4],
			),
			patch(
				"mes_integration.mes_integration.sales_order_field_change.apply_field_change"
			) as apply_change,
		):
			result = process_field_change("BATCH-1", self.item, "odtNo", change)

		self.assertEqual(result["errorCode"], "EXPECTED_VALUE_MISMATCH")
		self.assertEqual(result["currentValue"], "TN0001")
		apply_change.assert_not_called()

	def test_delivery_date_updates_header_and_all_existing_items(self):
		sales_order = self.make_sales_order()
		sales_order.notify_update = MagicMock()

		with patch.object(frappe.db, "set_value") as set_value:
			apply_field_change(sales_order, "deliveryDate", "2026-10-15")

		self.assertEqual(
			set_value.call_args_list,
			[
				call(
					"Sales Order Item",
					"SO-ITEM-1",
					"delivery_date",
					"2026-10-15",
					update_modified=False,
				),
				call(
					"Sales Order Item",
					"SO-ITEM-2",
					"delivery_date",
					"2026-10-15",
					update_modified=False,
				),
				call(
					"Sales Order",
					"SAL-ORD-2026-00001",
					"delivery_date",
					"2026-10-15",
					update_modified=True,
				),
			],
		)
		self.assertEqual(sales_order.delivery_date, "2026-10-15")
		self.assertEqual(sales_order.custom_process_status, "Pending Production")

	def test_batch_rejects_duplicate_operation_ids(self):
		payload = {
			"schemaVersion": "1.0",
			"sourceSystem": "MES",
			"requestId": "BATCH-1",
			"items": [
				{
					"externalOrderId": "SO-1",
					"orderNo": "SO-1",
					"sourceVersion": 1,
					"changes": {
						"odtNo": {
							"operationId": "OP-1",
							"expectedValue": None,
							"value": "ODT-1",
						},
						"deliveryDate": {
							"operationId": "OP-1",
							"expectedValue": "2026-10-01",
							"value": "2026-10-15",
						},
					},
				}
			],
		}

		with self.assertRaises(frappe.ValidationError):
			validate_batch_payload(payload)

	def test_http_idempotency_header_must_match_request_id(self):
		with (
			patch.object(frappe.local, "request", MagicMock(), create=True),
			patch.object(frappe, "get_request_header", return_value="ANOTHER-BATCH"),
			self.assertRaises(frappe.ValidationError),
		):
			validate_batch_idempotency_header("BATCH-1")

	def test_changed_content_for_existing_batch_returns_http_409_result(self):
		batch = frappe._dict(request_id="BATCH-1", request_hash="original-hash")

		response = replay_existing_batch(batch, "changed-hash")

		self.assertEqual(response["code"], 409)
		self.assertEqual(response["errorCode"], "IDEMPOTENCY_CONTENT_MISMATCH")

	def test_root_json_array_is_reported_as_invalid_payload(self):
		request = MagicMock(is_json=True)
		request.get_json.return_value = []

		with patch.object(frappe.local, "request", request, create=True):
			payload = get_batch_payload()

		self.assertEqual(payload, [])
		with self.assertRaises(frappe.ValidationError):
			validate_batch_payload(payload)

	def test_success_result_does_not_contain_state_change(self):
		result = build_result(
			"OP-1",
			status="success",
			applied_value="ODT-2",
			message="success",
		)

		self.assertNotIn("processStatus", result)
		self.assertEqual(result["appliedValue"], "ODT-2")

	def test_batch_and_operation_results_are_persisted_and_replayed(self):
		suffix = frappe.generate_hash(length=12)
		request_id = f"TEST-BATCH-{suffix}"
		operation_id = f"TEST-OP-{suffix}"
		payload = {
			"schemaVersion": "1.0",
			"sourceSystem": "MES",
			"requestId": request_id,
			"items": [
				{
					"externalOrderId": f"MISSING-SO-{suffix}",
					"orderNo": f"MISSING-SO-{suffix}",
					"sourceVersion": 1,
					"changes": {
						"odtNo": {
							"operationId": operation_id,
							"expectedValue": None,
							"value": "ODT-TEST",
						}
					},
				}
			],
		}

		try:
			with patch(
				"mes_integration.mes_integration.sales_order_field_change.validate_mes_api_user"
			):
				response = update_sales_order_fields_batch(payload)
				replayed = update_sales_order_fields_batch(payload)
				queried = get_sales_order_field_change_result(operation_id)

			self.assertEqual(response, replayed)
			self.assertEqual(
				response["data"]["items"][0]["results"]["odtNo"]["errorCode"],
				"SALES_ORDER_NOT_FOUND",
			)
			self.assertEqual(queried["data"]["result"], response["data"]["items"][0]["results"]["odtNo"])
			self.assertTrue(
				frappe.db.exists("MES Sales Order Field Change Batch", {"request_id": request_id})
			)
			self.assertTrue(
				frappe.db.exists(
					"MES Sales Order Field Change Operation",
					{"operation_id": operation_id},
				)
			)
		finally:
			frappe.db.rollback()
