import builtins
from unittest.mock import MagicMock, patch

import frappe
from frappe.tests import UnitTestCase

from crm_integration.crm_integration.delivery_note import (
	allocate_crm_shipment_items,
	delivery_note_dimensions_match,
	enqueue_crm_delivery_note_cancellation_event,
	enqueue_mes_delivery_note_status_callback,
	get_or_create_crm_delivery_note,
	update_sales_orders_delivery_process_status,
	validate_crm_shipment_payload,
)
from crm_integration.crm_integration.sales_order import CRM_STATUS_SHIPMENT_CANCELLED


class TestCRMShipmentAllocation(UnitTestCase):
	def test_crm_shipment_requires_stable_shipment_number(self):
		with self.assertRaisesRegex(frappe.ValidationError, "custom_crm_shipment_no"):
			validate_crm_shipment_payload(
				{
					"sales_order": "SO-001",
					"items": [{"item_code": "ITEM-001", "qty": 1}],
				}
			)

	def test_crm_shipment_rejects_legacy_delivery_note_draft(self):
		with self.assertRaisesRegex(frappe.ValidationError, "delivery_note 参数已停用"):
			validate_crm_shipment_payload(
				{
					"custom_crm_shipment_no": "CRM-SHIP-001",
					"sales_order": "SO-001",
					"delivery_note": "DN-DRAFT-001",
					"items": [{"item_code": "ITEM-001", "qty": 1}],
				}
			)

	def test_submitted_delivery_note_quantity_is_credited_for_idempotent_replay(self):
		sales_order = frappe._dict(
			name="SO-001",
			docstatus=1,
			items=[
				frappe._dict(
					name="SOI-001",
					item_code="ITEM-001",
					qty=10,
					delivered_qty=10,
					custom_version="PC_PRINT",
				)
			],
		)
		delivery_note = frappe._dict(
			docstatus=1,
			items=[
				frappe._dict(
					against_sales_order="SO-001",
					so_detail="SOI-001",
					qty=4,
				)
			],
		)

		allocations = allocate_crm_shipment_items(
			sales_order,
			[
				{
					"sales_order_item": "SOI-001",
					"item_code": "ITEM-001",
					"custom_version": "PC_PRINT",
					"qty": 4,
				}
			],
			credit_delivery_note=delivery_note,
		)

		self.assertEqual(allocations[0].qty, 4)

	def test_version_selects_the_matching_sales_order_item(self):
		sales_order = frappe._dict(
			name="SO-001",
			docstatus=1,
			items=[
				frappe._dict(
					name="SOI-PRINT",
					item_code="ITEM-001",
					qty=5,
					delivered_qty=0,
					custom_version="PC_PRINT",
				),
				frappe._dict(
					name="SOI-OTHER",
					item_code="ITEM-001",
					qty=5,
					delivered_qty=0,
					custom_version="OTHER",
				),
			],
		)

		allocations = allocate_crm_shipment_items(
			sales_order,
			[{"item_code": "ITEM-001", "custom_version": "PC_PRINT", "qty": 2}],
		)
		self.assertEqual(allocations[0].sales_order_item.name, "SOI-PRINT")

		with self.assertRaisesRegex(frappe.ValidationError, "多个版本"):
			allocate_crm_shipment_items(sales_order, [{"item_code": "ITEM-001", "qty": 2}])

	def test_first_crm_shipment_creates_a_new_delivery_note(self):
		sales_order = frappe._dict(name="SO-001")
		payload = {"custom_crm_shipment_no": "CRM-SHIP-001"}
		allocations = [frappe._dict(qty=1)]
		created = frappe._dict(name="DN-001", docstatus=0)

		with (
			patch(
				"crm_integration.crm_integration.delivery_note.get_delivery_note_by_crm_shipment_no",
				return_value=None,
			),
			patch(
				"crm_integration.crm_integration.delivery_note.make_crm_delivery_note",
				return_value=created,
			) as make_delivery_note,
		):
			delivery_note, idempotent_replay = get_or_create_crm_delivery_note(
				sales_order, payload, allocations
			)

		self.assertIs(delivery_note, created)
		self.assertFalse(idempotent_replay)
		make_delivery_note.assert_called_once_with(sales_order, payload, allocations)

	def test_one_order_line_can_be_split_by_warehouse_and_batch(self):
		sales_order_item = frappe._dict(name="SOI-001")
		allocations = [
			frappe._dict(
				sales_order_item=sales_order_item,
				request_row=frappe._dict(
					warehouse="Warehouse A", batch_no="BATCH-A", serial_no="SERIAL-A"
				),
				qty=2,
			),
			frappe._dict(
				sales_order_item=sales_order_item,
				request_row=frappe._dict(warehouse="Warehouse B", batch_no="BATCH-B"),
				qty=3,
			),
		]
		delivery_note = frappe._dict(
			items=[
				frappe._dict(
					so_detail="SOI-001",
					warehouse="Warehouse A",
					batch_no="BATCH-A",
					serial_no="SERIAL-A",
					qty=2,
				),
				frappe._dict(
					so_detail="SOI-001", warehouse="Warehouse B", batch_no="BATCH-B", qty=3
				),
			]
		)

		self.assertTrue(delivery_note_dimensions_match(delivery_note, allocations))
		delivery_note["items"][1].warehouse = "Warehouse C"
		self.assertFalse(delivery_note_dimensions_match(delivery_note, allocations))


class TestDeliveryNoteCRMEvents(UnitTestCase):
	def test_missing_optional_mes_app_does_not_break_delivery_note(self):
		original_import = builtins.__import__

		def import_without_mes(name, *args, **kwargs):
			if name.startswith("mes_integration"):
				error = ModuleNotFoundError("No module named 'mes_integration'")
				error.name = "mes_integration"
				raise error
			return original_import(name, *args, **kwargs)

		with (
			patch("builtins.__import__", side_effect=import_without_mes),
			patch.object(frappe, "log_error") as log_error,
		):
			enqueue_mes_delivery_note_status_callback("DN-001")

		log_error.assert_not_called()

	def test_cancelled_delivery_note_enqueues_crm_reversal(self):
		doc = frappe._dict(
			name="DN-001",
			items=[
				frappe._dict(
					against_sales_order="SO-001",
					item_code="ITEM-001",
					stock_qty=2,
				)
			],
		)

		with patch(
			"crm_integration.crm_integration.delivery_note.enqueue_sales_order_status_to_crm"
		) as enqueue_status:
			enqueue_crm_delivery_note_cancellation_event(doc, "SO-001", "Deliverable")

		enqueue_status.assert_called_once_with(
			sales_order_name="SO-001",
			external_status=CRM_STATUS_SHIPMENT_CANCELLED,
			triggered_status="Deliverable",
			trigger_event="delivery_note_cancelled",
			delivery_note_name="DN-001",
			items=[{"externalItemId": "ITEM-001", "quantity": 2.0}],
			remark="销售出库 DN-001 已取消，ERP流程状态：Deliverable",
		)

	def test_cancel_path_enqueues_cancellation_instead_of_shipment(self):
		doc = frappe._dict(name="DN-001", company="Test Company", docstatus=2)
		sales_order = MagicMock(name="sales_order")

		with (
			patch(
				"crm_integration.crm_integration.delivery_note.is_crm_integration_enabled",
				return_value=True,
			),
			patch(
				"crm_integration.crm_integration.delivery_note.get_linked_sales_orders",
				return_value=["SO-001"],
			),
			patch.object(frappe, "get_doc", return_value=sales_order),
			patch(
				"crm_integration.crm_integration.delivery_note.get_sales_order_delivery_process_status",
				return_value="Deliverable",
			),
			patch("crm_integration.crm_integration.delivery_note.set_process_status"),
			patch(
				"crm_integration.crm_integration.delivery_note.enqueue_crm_delivery_note_shipment_event"
			) as enqueue_shipment,
			patch(
				"crm_integration.crm_integration.delivery_note.enqueue_crm_delivery_note_cancellation_event"
			) as enqueue_cancellation,
			patch("crm_integration.crm_integration.delivery_note.enqueue_mes_delivery_note_status_callback"),
		):
			update_sales_orders_delivery_process_status(doc)

		enqueue_shipment.assert_not_called()
		enqueue_cancellation.assert_called_once_with(doc, "SO-001", "Deliverable")

	def test_crm_originated_submit_does_not_echo_shipment_to_crm(self):
		doc = frappe._dict(
			name="DN-001",
			company="Test Company",
			docstatus=1,
			custom_crm_shipment_no="CRM-SHIP-001",
		)
		sales_order = MagicMock(name="sales_order")

		with (
			patch(
				"crm_integration.crm_integration.delivery_note.is_crm_integration_enabled",
				return_value=True,
			),
			patch(
				"crm_integration.crm_integration.delivery_note.get_linked_sales_orders",
				return_value=["SO-001"],
			),
			patch.object(frappe, "get_doc", return_value=sales_order),
			patch(
				"crm_integration.crm_integration.delivery_note.get_sales_order_delivery_process_status",
				return_value="Partially Delivered",
			),
			patch("crm_integration.crm_integration.delivery_note.set_process_status"),
			patch(
				"crm_integration.crm_integration.delivery_note.enqueue_crm_delivery_note_shipment_event"
			) as enqueue_shipment,
			patch(
				"crm_integration.crm_integration.delivery_note.enqueue_mes_delivery_note_status_callback"
			) as enqueue_mes,
		):
			update_sales_orders_delivery_process_status(doc)

		enqueue_shipment.assert_not_called()
		enqueue_mes.assert_called_once_with("DN-001")
