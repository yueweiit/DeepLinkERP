from unittest.mock import patch

import frappe
from frappe.tests import UnitTestCase

from mes_integration.mes_integration.stock_entry import (
	create_and_submit_stock_entry_from_mes,
	get_sales_order_by_reference,
	is_mes_receipt_stock_entry,
	set_mes_stock_entry_sales_order,
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
			"mes_integration.mes_integration.stock_entry.frappe.get_all",
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
