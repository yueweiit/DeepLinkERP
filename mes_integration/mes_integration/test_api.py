from unittest.mock import patch

import frappe
from frappe.tests import UnitTestCase

from mes_integration import api
from mes_integration.mes_integration.delivery_note import (
	create_draft_delivery_note_from_mes,
	retry_push_delivery_note_status_to_mes,
)
from mes_integration.mes_integration.material_request import (
	batch_issue_and_push_to_dlm,
	create_and_submit_material_request_from_mes,
	create_issue_stock_entry_from_mobile,
	get_material_request_task_status,
	issue_and_push_to_dlm_from_dialog,
)
from mes_integration.mes_integration.sales_order import (
	retry_push_sales_order_status_to_mes,
)
from mes_integration.mes_integration.stock_entry import (
	create_and_submit_stock_entry_from_mes,
	create_draft_stock_entry_from_mes,
	retry_push_stock_entry_status_to_mes,
)


class TestMESAPIHTTPMethods(UnitTestCase):
	@patch(
		"mes_integration.mes_integration.stock_entry.create_draft_stock_entry_from_mes"
	)
	def test_create_stock_entry_submits_by_default(self, create_stock_entry):
		api.create_stock_entry(data={"stock_entry_type": "Finished Goods Receipt"})

		create_stock_entry.assert_called_once_with(
			data={"stock_entry_type": "Finished Goods Receipt"},
			stock_entry=None,
			submit=True,
		)

	@patch(
		"mes_integration.mes_integration.stock_entry.create_draft_stock_entry_from_mes"
	)
	def test_create_stock_entry_allows_explicit_draft(self, create_stock_entry):
		api.create_stock_entry(
			stock_entry={"stock_entry_type": "Semi Finished Goods Receipt"},
			submit=0,
		)

		create_stock_entry.assert_called_once_with(
			data=None,
			stock_entry={"stock_entry_type": "Semi Finished Goods Receipt"},
			submit=0,
		)

	def test_inventory_distinguishes_zero_disabled_nonstock_and_missing_items(self):
		bin_rows = [
			frappe._dict(
				item_code="ITEM-WITH-STOCK",
				warehouse="Stores - TC",
				actual_qty=5,
				reserved_qty=0,
				projected_qty=5,
				stock_uom="Nos",
			),
			frappe._dict(
				item_code="ITEM-DISABLED",
				warehouse="Stores - TC",
				actual_qty=3,
			),
		]
		item_rows = [
			frappe._dict(name="ITEM-ZERO", stock_uom="Nos", is_stock_item=1, disabled=0),
			frappe._dict(
				name="ITEM-WITH-STOCK", stock_uom="Nos", is_stock_item=1, disabled=0
			),
			frappe._dict(
				name="ITEM-DISABLED", stock_uom="Nos", is_stock_item=1, disabled=1
			),
			frappe._dict(
				name="ITEM-NONSTOCK", stock_uom="Nos", is_stock_item=0, disabled=0
			),
		]

		with (
			patch(
				"mes_integration.mes_integration.stock_entry.validate_mes_api_user"
			),
			patch.object(frappe, "has_permission", return_value=True),
			patch.object(frappe, "get_list", side_effect=[bin_rows, item_rows]),
		):
			result = api.get_batch_bin_rows(
				[
					"ITEM-ZERO",
					"ITEM-WITH-STOCK",
					"ITEM-DISABLED",
					"ITEM-NONSTOCK",
					"ITEM-MISSING",
				]
			)

		self.assertEqual(result["no_stock_item_codes"], ["ITEM-ZERO"])
		self.assertEqual(result["disabled_item_codes"], ["ITEM-DISABLED"])
		self.assertEqual(result["non_stock_item_codes"], ["ITEM-NONSTOCK"])
		self.assertEqual(result["invalid_item_codes"], ["ITEM-MISSING"])
		self.assertEqual(
			[row["item_code"] for row in result["rows"]],
			["ITEM-WITH-STOCK", "ITEM-ZERO"],
		)
		self.assertEqual(result["rows"][1]["actual_qty"], 0)

	def test_write_endpoints_only_allow_post(self):
		write_endpoints = (
			api.create_stock_entry,
			api.create_and_submit_stock_entry,
			api.create_material_request,
			create_draft_stock_entry_from_mes,
			create_and_submit_stock_entry_from_mes,
			create_and_submit_material_request_from_mes,
			create_draft_delivery_note_from_mes,
			issue_and_push_to_dlm_from_dialog,
			create_issue_stock_entry_from_mobile,
			batch_issue_and_push_to_dlm,
			retry_push_stock_entry_status_to_mes,
			retry_push_delivery_note_status_to_mes,
			retry_push_sales_order_status_to_mes,
		)

		for endpoint in write_endpoints:
			with self.subTest(endpoint=endpoint.__name__):
				self.assertEqual(
					frappe.allowed_http_methods_for_whitelisted_func[endpoint],
					["POST"],
				)

	def test_read_endpoints_keep_get_and_post_compatibility(self):
		read_endpoints = (
			api.get_material_request_task_status,
			api.get_batch_bin_rows,
			get_material_request_task_status,
		)

		for endpoint in read_endpoints:
			with self.subTest(endpoint=endpoint.__name__):
				self.assertEqual(
					frappe.allowed_http_methods_for_whitelisted_func[endpoint],
					["GET", "POST"],
				)
