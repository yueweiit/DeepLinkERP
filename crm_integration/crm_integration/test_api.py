from unittest.mock import MagicMock, patch

import frappe
from frappe.tests import UnitTestCase

from crm_integration.crm_integration.api import (
	update_sales_order_by_crm_order_no,
	validate_sales_order_update_payload,
)


class TestCRMAPI(UnitTestCase):
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
