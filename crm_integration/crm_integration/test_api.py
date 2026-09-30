from contextlib import nullcontext
from unittest.mock import MagicMock, patch

import frappe
from frappe.tests import UnitTestCase

from crm_integration.crm_integration.api import (
	create_and_submit_sales_order,
	get_existing_sales_order_response,
	update_sales_order_by_crm_order_no,
	update_sales_order_items,
	validate_sales_order_payload,
	validate_sales_order_update_payload,
)


class TestCRMAPI(UnitTestCase):
	def test_sales_order_create_requires_crm_order_no(self):
		with self.assertRaises(frappe.ValidationError):
			validate_sales_order_payload(
				{
					"customer": "CUSTOMER-001",
					"items": [{"item_code": "ITEM-001", "qty": 1}],
				}
			)

	def test_sales_order_create_returns_existing_submitted_order(self):
		doc = MagicMock(name="existing_sales_order")
		doc.name = "SO-001"
		doc.docstatus = 1
		doc.get.side_effect = lambda field: {
			"company": "Test Company",
			"custom_process_status": "Pending Deposit Confirmation",
		}.get(field)

		with (
			patch(
				"crm_integration.crm_integration.api.get_sales_order_names_by_crm_order_no",
				return_value=["SO-001"],
			),
			patch.object(frappe, "get_doc", return_value=doc),
		):
			result = get_existing_sales_order_response(
				{"custom_crm_order_no": "CRM-001", "company": "Test Company"}
			)

		self.assertTrue(result["idempotent_replay"])
		self.assertEqual(result["name"], "SO-001")

	def test_idempotent_replay_does_not_create_another_sales_order(self):
		payload = {
			"doctype": "Sales Order",
			"company": "Test Company",
			"customer": "CUSTOMER-001",
			"custom_crm_order_no": "CRM-001",
			"items": [{"item_code": "ITEM-001", "qty": 1}],
		}
		existing_response = {
			"status": "success",
			"name": "SO-001",
			"docstatus": 1,
			"idempotent_replay": True,
		}

		with (
			patch("crm_integration.crm_integration.api.validate_crm_api_user"),
			patch(
				"crm_integration.crm_integration.api.is_crm_integration_enabled",
				return_value=True,
			),
			patch(
				"crm_integration.crm_integration.api.crm_sales_order_creation_lock",
				return_value=nullcontext(),
			),
			patch(
				"crm_integration.crm_integration.api.get_existing_sales_order_response",
				return_value=existing_response,
			),
			patch("crm_integration.crm_integration.api.log_existing_sales_order_request"),
			patch("crm_integration.crm_integration.api.create_sales_order") as create_sales_order,
		):
			result = create_and_submit_sales_order(payload)

		self.assertEqual(result, existing_response)
		create_sales_order.assert_not_called()

	def test_sales_order_update_rejects_unsupported_header_fields(self):
		with self.assertRaises(frappe.ValidationError):
			validate_sales_order_update_payload(
				{
					"custom_crm_order_no": "CRM-001",
					"custom_process_status": "Completed",
				}
			)

	def test_sales_order_update_accepts_explicitly_allowed_fields(self):
		validate_sales_order_update_payload(
			{
				"custom_crm_order_no": "CRM-001",
				"custom_odt": "ODT-001",
				"custom_remark": "updated",
				"items": [{"item_code": "ITEM-001", "qty": 2}],
			}
		)

	def test_sales_order_update_requires_enabled_company(self):
		doc = MagicMock()
		doc.get.return_value = "Disabled Company"

		with (
			patch("crm_integration.crm_integration.api.validate_crm_api_user"),
			patch(
				"crm_integration.crm_integration.api.get_request_payload",
				return_value={"custom_crm_order_no": "CRM-001"},
			),
			patch.object(frappe, "get_all", return_value=["SO-001"]),
			patch.object(frappe, "get_doc", return_value=doc),
			patch(
				"crm_integration.crm_integration.api.is_crm_integration_enabled",
				return_value=False,
			),
			self.assertRaises(frappe.ValidationError),
		):
			update_sales_order_by_crm_order_no()

		doc.save.assert_not_called()

	def test_sales_order_item_correction_requires_row_name(self):
		row = frappe._dict(name="SOI-001", item_code="ITEM-OLD")
		doc = MagicMock()
		doc.name = "SO-001"
		doc.items = [row]
		doc.get.side_effect = lambda fieldname: {
			"custom_process_status": "Pending Deposit Confirmation"
		}.get(fieldname)

		with self.assertRaisesRegex(frappe.ValidationError, "必须传明细 name"):
			update_sales_order_items(
				doc,
				[{"item_code": "ITEM-OLD", "new_item_code": "ITEM-NEW"}],
			)

	def test_sales_order_item_correction_is_rejected_after_mes_push(self):
		row = frappe._dict(name="SOI-001", item_code="ITEM-OLD")
		doc = MagicMock()
		doc.name = "SO-001"
		doc.items = [row]
		doc.get.side_effect = lambda fieldname: {
			"custom_process_status": "Pending Production"
		}.get(fieldname)

		with self.assertRaisesRegex(frappe.ValidationError, "只能在推送 MES 前更正"):
			update_sales_order_items(
				doc,
				[{"name": row.name, "new_item_code": "ITEM-NEW"}],
			)

	def test_sales_order_item_correction_is_rejected_with_downstream_qty(self):
		row = frappe._dict(name="SOI-001", item_code="ITEM-OLD", delivered_qty=1)
		doc = MagicMock()
		doc.name = "SO-001"
		doc.items = [row]
		doc.get.side_effect = lambda fieldname: {
			"custom_process_status": "Pending Deposit Confirmation"
		}.get(fieldname)

		with self.assertRaisesRegex(frappe.ValidationError, "已产生下游数量"):
			update_sales_order_items(
				doc,
				[{"name": row.name, "new_item_code": "ITEM-NEW"}],
			)

	@patch("crm_integration.crm_integration.api.replace_sales_order_item")
	def test_sales_order_item_correction_replaces_item_and_version(self, replace_item):
		row = frappe._dict(name="SOI-001", item_code="ITEM-OLD", custom_version="OLD")
		row.set = lambda fieldname, value: row.__setitem__(fieldname, value)
		doc = MagicMock()
		doc.name = "SO-001"
		doc.items = [row]
		doc.get.side_effect = lambda fieldname: {
			"custom_process_status": "Pending Deposit Confirmation"
		}.get(fieldname)

		update_sales_order_items(
			doc,
			[
				{
					"name": row.name,
					"item_code": "ITEM-OLD",
					"new_item_code": "ITEM-NEW",
					"custom_version": "PC_PRINT",
					"qty": 8,
					"rate": 0,
				},
			],
		)

		replace_item.assert_called_once_with(doc, row, "ITEM-NEW")
		self.assertEqual(row.custom_version, "PC_PRINT")
		self.assertEqual(row.qty, 8)
		self.assertEqual(row.rate, 0)
		self.assertEqual(row.price_list_rate, 0)

	def test_sales_order_item_name_and_item_code_must_match(self):
		row = frappe._dict(name="SOI-001", item_code="ITEM-OLD")
		doc = MagicMock()
		doc.name = "SO-001"
		doc.items = [row]
		doc.get.side_effect = lambda fieldname: {
			"custom_process_status": "Pending Deposit Confirmation"
		}.get(fieldname)

		with self.assertRaisesRegex(frappe.ValidationError, "与请求中的 item_code"):
			update_sales_order_items(
				doc,
				[{"name": row.name, "item_code": "ITEM-WRONG", "qty": 2}],
			)
