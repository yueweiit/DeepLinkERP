from unittest.mock import patch

import frappe
from frappe.tests import UnitTestCase

from mes_integration.mes_integration.delivery_note import (
	enqueue_delivery_note_status_callback,
	get_existing_mes_delivery_note,
	get_mes_delivery_note_identity_mismatches,
	get_mes_delivery_request_key,
	push_delivery_note_status_to_mes_job,
)


class TestMESDeliveryNote(UnitTestCase):
	def test_delivery_status_enqueue_uses_stable_deduplication_key(self):
		with (
			patch(
				"mes_integration.mes_integration.delivery_note.frappe.db.get_value",
				return_value=1,
			),
			patch(
				"mes_integration.mes_integration.delivery_note.frappe.enqueue"
			) as enqueue,
		):
			enqueue_delivery_note_status_callback("MAT-DN-2026-00001")

		enqueue.assert_called_once_with(
			"mes_integration.mes_integration.delivery_note.push_delivery_note_status_to_mes_job",
			queue="short",
			timeout=300,
			enqueue_after_commit=True,
			job_id="mes-delivery-note-status:MAT-DN-2026-00001:1",
			deduplicate=True,
			delivery_note_name="MAT-DN-2026-00001",
		)

	def test_delivery_status_job_retries_failed_callback(self):
		with (
			patch(
				"mes_integration.mes_integration.delivery_note.push_delivery_note_status_to_mes",
				return_value=[{"sales_order": "SAL-ORD-1", "status": "failed"}],
			),
			patch.object(frappe.db, "commit") as commit,
			self.assertRaises(frappe.RetryBackgroundJobError),
		):
			push_delivery_note_status_to_mes_job("MAT-DN-2026-00001")

		commit.assert_called_once_with()

	def test_delivery_request_key_uses_explicit_request_id(self):
		self.assertEqual(
			get_mes_delivery_request_key(
				{
					"request_id": "DELIVERY-REQUEST-001",
					"production_batch_no": "BATCH-001",
				}
			),
			"DELIVERY-REQUEST-001",
		)

	def test_delivery_request_key_requires_stable_identity(self):
		with self.assertRaises(frappe.ValidationError):
			get_mes_delivery_request_key({"sales_order": "SAL-ORD-2026-00001"})

	def test_delivery_note_identity_rejects_changed_quantity(self):
		delivery_note = frappe._dict(
			name="MAT-DN-2026-00001",
			items=[
				frappe._dict(
					item_code="ITEM-A",
					qty=10,
					against_sales_order="SAL-ORD-2026-00001",
					warehouse="Finished Goods - TC",
				)
			],
		)
		payload = {
			"sales_order": "SAL-ORD-2026-00001",
			"items": [
				{
					"item_code": "ITEM-A",
					"qty": 11,
					"warehouse": "Finished Goods - TC",
				}
			],
		}

		self.assertIn(
			"items.qty",
			get_mes_delivery_note_identity_mismatches(delivery_note, payload),
		)

	def test_exact_delivery_retry_reuses_existing_document(self):
		delivery_note = frappe._dict(
			name="MAT-DN-2026-00001",
			docstatus=0,
			items=[
				frappe._dict(
					item_code="ITEM-A",
					qty=10,
					against_sales_order="SAL-ORD-2026-00001",
					warehouse="Finished Goods - TC",
				)
			],
		)
		payload = {
			"sales_order": "SAL-ORD-2026-00001",
			"items": [
				{
					"item_code": "ITEM-A",
					"qty": 10,
					"warehouse": "Finished Goods - TC",
				}
			],
		}

		with (
			patch(
				"mes_integration.mes_integration.delivery_note.frappe.db.has_column",
				return_value=True,
			),
			patch(
				"mes_integration.mes_integration.delivery_note.frappe.get_all",
				return_value=[delivery_note.name],
			),
			patch(
				"mes_integration.mes_integration.delivery_note.frappe.get_doc",
				return_value=delivery_note,
			),
		):
			result = get_existing_mes_delivery_note(
				"Test Company",
				"DELIVERY-REQUEST-001",
				payload,
			)

		self.assertIs(result, delivery_note)
