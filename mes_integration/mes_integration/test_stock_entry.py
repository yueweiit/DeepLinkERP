from unittest.mock import patch

import frappe
from frappe.tests import UnitTestCase

from mes_integration.mes_integration.stock_entry import (
	build_stock_entry_status_payload,
	build_mes_stock_entry_response,
	create_and_submit_stock_entry_from_mes,
	enqueue_mes_stock_entry_status_callback,
	get_existing_mes_receipt_stock_entry,
	get_mes_receipt_item_identity,
	get_sales_order_by_reference,
	is_mes_receipt_stock_entry,
	notify_mes_stock_entry_status,
	set_mes_stock_entry_sales_order,
	validate_mes_receipt_identity,
	validate_mes_receipt_stock_entry_type,
)


class TestMESStockEntry(UnitTestCase):
	def test_receipt_type_accepts_standard_material_receipt(self):
		validate_mes_receipt_stock_entry_type("Material Receipt")

	def test_standard_material_receipt_requires_mes_request_context(self):
		stock_entry = frappe._dict(stock_entry_type="Material Receipt")
		stock_entry.flags = frappe._dict()

		with patch(
			"mes_integration.mes_integration.stock_entry.is_mes_api_user",
			return_value=False,
		):
			self.assertFalse(is_mes_receipt_stock_entry(stock_entry))

		stock_entry.flags.mes_receipt_request = True
		self.assertTrue(is_mes_receipt_stock_entry(stock_entry))

	def test_manual_standard_material_receipt_does_not_trigger_mes_callback(self):
		stock_entry = frappe._dict(stock_entry_type="Material Receipt")
		stock_entry.flags = frappe._dict()

		with patch(
			"mes_integration.mes_integration.stock_entry.is_mes_api_user",
			return_value=False,
		), patch(
			"mes_integration.mes_integration.stock_entry.frappe.local.request",
			frappe._dict(path="/api/method/frappe.desk.form.save.savedocs"),
			create=True,
		):
			self.assertFalse(is_mes_receipt_stock_entry(stock_entry))

	def test_persisted_mes_receipt_marker_triggers_callback(self):
		stock_entry = frappe._dict(
			stock_entry_type="Material Receipt",
			custom_mes_receipt=1,
		)
		stock_entry.flags = frappe._dict()

		with patch(
			"mes_integration.mes_integration.stock_entry.is_mes_api_user",
			return_value=False,
		):
			self.assertTrue(is_mes_receipt_stock_entry(stock_entry))

	def test_mes_receipt_marker_is_added_when_field_exists(self):
		stock_entry_data = {}

		with patch(
			"mes_integration.mes_integration.stock_entry.frappe.db.has_column",
			return_value=True,
		):
			from mes_integration.mes_integration.stock_entry import mark_mes_receipt_stock_entry

			mark_mes_receipt_stock_entry(stock_entry_data)

		self.assertEqual(stock_entry_data["custom_mes_receipt"], 1)

	def test_create_and_submit_alias_submits(self):
		with patch(
			"mes_integration.mes_integration.stock_entry.create_draft_stock_entry_from_mes",
			return_value={"status": "success"},
		) as create_stock_entry:
			result = create_and_submit_stock_entry_from_mes(
				data={"stock_entry_type": "Material Receipt"}
			)

		create_stock_entry.assert_called_once_with(
			data={"stock_entry_type": "Material Receipt"},
			stock_entry=None,
			submit=True,
		)
		self.assertEqual(result["status"], "success")

	def test_sales_order_reference_resolves_crm_order_number(self):
		sales_order = frappe._dict(
			name="SAL-ORD-2026-00218",
			custom_crm_order_no="SHOP20260831001",
			company="YUEWEI CN悦为中国",
		)

		with patch(
			"mes_integration.mes_integration.stock_entry.frappe.db.exists",
			return_value=False,
		), patch(
			"mes_integration.mes_integration.stock_entry.frappe.db.has_column",
			return_value=True,
		), patch(
			"mes_integration.mes_integration.stock_entry.frappe.get_list",
			return_value=[sales_order.name],
		), patch(
			"mes_integration.mes_integration.stock_entry.frappe.get_doc",
			return_value=sales_order,
		) as get_doc:
			result = get_sales_order_by_reference(
				{"sales_order": "SHOP20260831001"}, {}, required=True
			)

		self.assertEqual(result.name, "SAL-ORD-2026-00218")
		get_doc.assert_called_once_with("Sales Order", "SAL-ORD-2026-00218")

	def test_resolved_sales_order_is_written_to_stock_entry_payload(self):
		stock_entry_data = {}
		sales_order = frappe._dict(name="SAL-ORD-2026-00218")

		with patch(
			"mes_integration.mes_integration.stock_entry.frappe.db.has_column",
			return_value=True,
		):
			set_mes_stock_entry_sales_order(stock_entry_data, sales_order)

		self.assertEqual(stock_entry_data["custom_sales_order"], sales_order.name)

	def test_receipt_status_is_enqueued_after_commit(self):
		stock_entry = frappe._dict(
			name="MAT-STE-2026-00001",
			company="Test Company",
			docstatus=1,
		)

		with (
			patch(
				"mes_integration.mes_integration.stock_entry.is_mes_integration_enabled",
				return_value=True,
			),
			patch(
				"mes_integration.mes_integration.stock_entry.is_mes_receipt_stock_entry",
				return_value=True,
			),
			patch.object(type(frappe.db.after_commit), "add") as add_callback,
			patch(
				"mes_integration.mes_integration.stock_entry.enqueue_mes_stock_entry_status_callback"
			) as enqueue_callback,
		):
			notify_mes_stock_entry_status(stock_entry, "on_submit")
			add_callback.assert_called_once()
			add_callback.call_args.args[0]()

		enqueue_callback.assert_called_once_with(stock_entry.name, 1)

	def test_receipt_status_payload_uses_event_docstatus(self):
		stock_entry = frappe._dict(
			name="MAT-STE-2026-00001",
			docstatus=2,
			custom_stock_entry_no="MES-RECEIPT-001",
		)

		payload = build_stock_entry_status_payload(stock_entry, docstatus=1)

		self.assertEqual(payload["docstatus"], 1)
		self.assertEqual(payload["erpStatus"], "submitted")

	def test_mes_receipt_item_identity_is_order_independent(self):
		first = get_mes_receipt_item_identity(
			[
				{"item_code": "ITEM-B", "qty": 2},
				{"item_code": "ITEM-A", "qty": 1},
			]
		)
		second = get_mes_receipt_item_identity(
			[
				{"item_code": "ITEM-A", "qty": 1},
				{"item_code": "ITEM-B", "qty": 2},
			]
		)

		self.assertEqual(first, second)

	def test_mes_receipt_identity_rejects_changed_request(self):
		existing = frappe._dict(
			name="MAT-STE-2026-00001",
			company="Test Company",
			stock_entry_type="Finished Goods Receipt",
			custom_stock_entry_no="MES-RECEIPT-001",
			custom_sales_order="SAL-ORD-2026-00001",
			items=[{"item_code": "ITEM-A", "qty": 1}],
		)
		request_data = {
			"company": "Test Company",
			"stock_entry_type": "Finished Goods Receipt",
			"custom_stock_entry_no": "MES-RECEIPT-001",
			"items": [{"item_code": "ITEM-B", "qty": 1}],
		}

		with self.assertRaises(frappe.ValidationError):
			validate_mes_receipt_identity(existing, request_data, None)

		self.assertEqual(
			frappe.response.get("error_code"),
			"ERP_STOCK_ENTRY_IDENTITY_CONFLICT",
		)

	def test_mes_receipt_identity_rejects_changed_batch(self):
		existing = frappe._dict(
			name="MAT-STE-2026-00001",
			company="Test Company",
			stock_entry_type="Finished Goods Receipt",
			custom_stock_entry_no="MES-RECEIPT-001",
			custom_sales_order="SAL-ORD-2026-00001",
			posting_date="2026-09-19",
			items=[
				{
					"item_code": "ITEM-A",
					"qty": 1,
					"batch_no": "BATCH-001",
				}
			],
		)
		request_data = {
			"company": "Test Company",
			"stock_entry_type": "Finished Goods Receipt",
			"custom_stock_entry_no": "MES-RECEIPT-001",
			"posting_date": "2026-09-19",
			"items": [
				{
					"item_code": "ITEM-A",
					"qty": 1,
					"batch_no": "BATCH-002",
				}
			],
		}

		with self.assertRaises(frappe.ValidationError):
			validate_mes_receipt_identity(
				existing,
				request_data,
				frappe._dict(name="SAL-ORD-2026-00001"),
			)

	def test_mes_receipt_identity_rejects_changed_posting_date(self):
		existing = frappe._dict(
			name="MAT-STE-2026-00001",
			company="Test Company",
			stock_entry_type="Finished Goods Receipt",
			custom_stock_entry_no="MES-RECEIPT-001",
			custom_sales_order="SAL-ORD-2026-00001",
			posting_date="2026-09-18",
			items=[{"item_code": "ITEM-A", "qty": 1}],
		)
		request_data = {
			"company": "Test Company",
			"stock_entry_type": "Finished Goods Receipt",
			"custom_stock_entry_no": "MES-RECEIPT-001",
			"posting_date": "2026-09-19",
			"items": [{"item_code": "ITEM-A", "qty": 1}],
		}

		with self.assertRaises(frappe.ValidationError):
			validate_mes_receipt_identity(
				existing,
				request_data,
				frappe._dict(name="SAL-ORD-2026-00001"),
			)

	def test_duplicate_mes_receipt_numbers_are_not_auto_selected(self):
		with (
			patch(
				"mes_integration.mes_integration.stock_entry.frappe.db.has_column",
				return_value=True,
			),
			patch(
				"mes_integration.mes_integration.stock_entry.frappe.get_all",
				return_value=["MAT-STE-2026-00001", "MAT-STE-2026-00002"],
			),
		):
			with self.assertRaises(frappe.ValidationError):
				get_existing_mes_receipt_stock_entry("Test Company", "MES-RECEIPT-001")

	def test_mes_receipt_lookup_excludes_material_issue_scope(self):
		with (
			patch(
				"mes_integration.mes_integration.stock_entry.frappe.db.has_column",
				return_value=True,
			),
			patch(
				"mes_integration.mes_integration.stock_entry.frappe.get_all",
				return_value=[],
			) as get_all,
		):
			result = get_existing_mes_receipt_stock_entry(
				"Test Company", "MES-RECEIPT-001"
			)

		self.assertIsNone(result)
		self.assertEqual(
			get_all.call_args.kwargs["filters"],
			{
				"company": "Test Company",
				"custom_stock_entry_no": "MES-RECEIPT-001",
				"stock_entry_type": [
					"in",
					[
						"Finished Goods Receipt",
						"Material Receipt",
						"Semi Finished Goods Receipt",
					],
				],
				"custom_mes_receipt": 1,
			},
		)

	def test_distinct_payload_with_shared_receipt_number_is_rejected(self):
		existing = frappe._dict(
			name="MAT-STE-2026-00001",
			company="Test Company",
			stock_entry_type="Semi Finished Goods Receipt",
			custom_stock_entry_no="MES-RECEIPT-001",
			custom_sales_order="SAL-ORD-2026-00001",
			items=[{"item_code": "ITEM-A", "qty": 50}],
		)
		request_data = {
			"company": "Test Company",
			"stock_entry_type": "Semi Finished Goods Receipt",
			"custom_stock_entry_no": "MES-RECEIPT-001",
			"items": [{"item_code": "ITEM-A", "qty": 4}],
		}
		sales_order = frappe._dict(name="SAL-ORD-2026-00001")

		with (
			patch(
				"mes_integration.mes_integration.stock_entry.frappe.db.has_column",
				return_value=True,
			),
			patch(
				"mes_integration.mes_integration.stock_entry.frappe.get_all",
				return_value=[existing.name],
			),
			patch(
				"mes_integration.mes_integration.stock_entry.frappe.get_doc",
				return_value=existing,
			),
		):
			with self.assertRaises(frappe.ValidationError):
				get_existing_mes_receipt_stock_entry(
					"Test Company",
					"MES-RECEIPT-001",
					request_data=request_data,
					sales_order_doc=sales_order,
				)

		self.assertEqual(
			frappe.response.get("error_code"),
			"ERP_STOCK_ENTRY_IDENTITY_CONFLICT",
		)

	def test_exact_retry_with_shared_receipt_number_reuses_existing_entry(self):
		existing = frappe._dict(
			name="MAT-STE-2026-00001",
			company="Test Company",
			stock_entry_type="Semi Finished Goods Receipt",
			custom_stock_entry_no="MES-RECEIPT-001",
			custom_sales_order="SAL-ORD-2026-00001",
			items=[{"item_code": "ITEM-A", "qty": 50}],
		)
		request_data = {
			"company": "Test Company",
			"stock_entry_type": "Semi Finished Goods Receipt",
			"custom_stock_entry_no": "MES-RECEIPT-001",
			"items": [{"item_code": "ITEM-A", "qty": 50}],
		}
		sales_order = frappe._dict(name="SAL-ORD-2026-00001")

		with (
			patch(
				"mes_integration.mes_integration.stock_entry.frappe.db.has_column",
				return_value=True,
			),
			patch(
				"mes_integration.mes_integration.stock_entry.frappe.get_all",
				return_value=[existing.name],
			),
			patch(
				"mes_integration.mes_integration.stock_entry.frappe.get_doc",
				return_value=existing,
			),
		):
			result = get_existing_mes_receipt_stock_entry(
				"Test Company",
				"MES-RECEIPT-001",
				request_data=request_data,
				sales_order_doc=sales_order,
			)

		self.assertIs(result, existing)

	def test_mes_receipt_identity_conflict_uses_http_409(self):
		from mes_integration.mes_integration.stock_entry import (
			MESStockEntryIdentityConflict,
			throw_mes_receipt_identity_conflict,
		)

		with self.assertRaises(MESStockEntryIdentityConflict) as raised:
			throw_mes_receipt_identity_conflict("duplicate receipt")

		self.assertEqual(raised.exception.http_status_code, 409)
		self.assertEqual(
			frappe.response.get("error_code"),
			"ERP_STOCK_ENTRY_IDENTITY_CONFLICT",
		)

	def test_reused_mes_receipt_response_marks_idempotent_reuse(self):
		stock_entry = frappe._dict(
			name="MAT-STE-2026-00001",
			stock_entry_type="Finished Goods Receipt",
			docstatus=1,
		)

		response = build_mes_stock_entry_response(stock_entry, None, reused=True)

		self.assertTrue(response["idempotent_reuse"])
		self.assertEqual(response["stock_entry"], stock_entry.name)
		self.assertTrue(response["submitted"])

	def test_receipt_status_enqueue_has_stable_deduplication_key(self):
		with patch("mes_integration.mes_integration.stock_entry.frappe.enqueue") as enqueue:
			enqueue_mes_stock_entry_status_callback("MAT-STE-2026-00001", 2)

		enqueue.assert_called_once_with(
			"mes_integration.mes_integration.stock_entry.push_stock_entry_status_to_mes_job",
			queue="short",
			timeout=300,
			job_id="mes-stock-entry-status:MAT-STE-2026-00001:2",
			deduplicate=True,
			stock_entry_name="MAT-STE-2026-00001",
			docstatus=2,
		)
