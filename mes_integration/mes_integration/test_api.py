from unittest.mock import patch

import frappe
from frappe.tests import UnitTestCase

from mes_integration.api import get_batch_bin_rows


class TestMESAPI(UnitTestCase):
	def test_batch_bin_rows_accepts_existing_item_without_stock(self):
		bin_rows = [
			{
				"item_code": "ITEM-WITH-STOCK",
				"warehouse": "Stores - TC",
				"actual_qty": 5,
				"reserved_qty": 0,
				"projected_qty": 5,
				"stock_uom": "Nos",
			}
		]

		with (
			patch(
				"mes_integration.mes_integration.stock_entry.validate_mes_api_user"
			),
			patch.object(frappe, "has_permission", return_value=True),
			patch.object(frappe, "get_list", return_value=bin_rows),
			patch.object(
				frappe,
				"get_all",
				return_value=["ITEM-WITH-STOCK", "ITEM-WITHOUT-STOCK"],
			),
		):
			result = get_batch_bin_rows(
				["ITEM-WITH-STOCK", "ITEM-WITHOUT-STOCK", "ITEM-UNKNOWN"]
			)

		self.assertTrue(result["success"])
		self.assertEqual(result["rows"], bin_rows)
		self.assertEqual(result["no_stock_item_codes"], ["ITEM-WITHOUT-STOCK"])
		self.assertEqual(result["invalid_item_codes"], ["ITEM-UNKNOWN"])
		self.assertEqual(result["missing_item_codes"], ["ITEM-UNKNOWN"])
