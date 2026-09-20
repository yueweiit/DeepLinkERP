from unittest.mock import patch

from frappe.tests import UnitTestCase

from mes_integration.patches.v1_0.normalize_receipt_stock_entry_types import (
	rename_legacy_stock_entry_types,
)


class TestMESMigrationPatches(UnitTestCase):
	def test_legacy_stock_entry_type_is_merged_when_target_exists(self):
		with (
			patch(
				"mes_integration.patches.v1_0.normalize_receipt_stock_entry_types.frappe.db.exists",
				side_effect=[True, True],
			),
			patch(
				"mes_integration.patches.v1_0.normalize_receipt_stock_entry_types.frappe.rename_doc"
			) as rename_doc,
			patch(
				"mes_integration.patches.v1_0.normalize_receipt_stock_entry_types.frappe.delete_doc"
			) as delete_doc,
		):
			rename_legacy_stock_entry_types()

		rename_doc.assert_called_once_with(
			"Stock Entry Type",
			"半成品入库",
			"Semi Finished Goods Receipt",
			force=True,
			merge=True,
			ignore_permissions=True,
			show_alert=False,
			rebuild_search=False,
		)
		delete_doc.assert_not_called()

	def test_legacy_stock_entry_type_is_renamed_when_target_is_missing(self):
		with (
			patch(
				"mes_integration.patches.v1_0.normalize_receipt_stock_entry_types.frappe.db.exists",
				side_effect=[True, False],
			),
			patch(
				"mes_integration.patches.v1_0.normalize_receipt_stock_entry_types.frappe.rename_doc"
			) as rename_doc,
		):
			rename_legacy_stock_entry_types()

		self.assertFalse(rename_doc.call_args.kwargs["merge"])
