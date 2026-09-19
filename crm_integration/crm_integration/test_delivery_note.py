import builtins
from unittest.mock import MagicMock, patch

import frappe
from frappe.tests import UnitTestCase

from crm_integration.crm_integration.delivery_note import (
	enqueue_crm_delivery_note_cancellation_event,
	enqueue_mes_delivery_note_status_callback,
	update_sales_orders_delivery_process_status,
)
from crm_integration.crm_integration.sales_order import CRM_STATUS_SHIPMENT_CANCELLED


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
