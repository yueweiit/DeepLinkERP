from unittest.mock import MagicMock, patch

import frappe
from frappe.tests import UnitTestCase

from crm_integration.crm_integration.sales_order import (
	confirm_deposit_and_push_to_mes,
	reconcile_final_payment,
	reject_sales_order,
)


class TestSalesOrderPermissions(UnitTestCase):
	def test_reject_checks_cancel_permission_before_crm_push(self):
		doc = self.make_sales_order()
		doc.check_permission.side_effect = frappe.PermissionError

		with (
			patch.object(frappe, "get_doc", return_value=doc),
			patch(
				"crm_integration.crm_integration.sales_order.is_crm_integration_enabled",
				return_value=True,
			),
			patch(
				"crm_integration.crm_integration.sales_order.push_sales_order_status_to_crm"
			) as push_status,
			self.assertRaises(frappe.PermissionError),
		):
			reject_sales_order("SO-001")

		doc.check_permission.assert_called_once_with("cancel")
		push_status.assert_not_called()

	def test_confirm_deposit_checks_write_permission_before_push(self):
		doc = self.make_sales_order()
		doc.check_permission.side_effect = frappe.PermissionError

		with (
			patch.object(frappe, "get_doc", return_value=doc),
			patch(
				"crm_integration.crm_integration.sales_order.is_crm_integration_enabled",
				return_value=True,
			),
			patch(
				"crm_integration.crm_integration.sales_order.push_sales_order_status_to_crm"
			) as push_status,
			self.assertRaises(frappe.PermissionError),
		):
			confirm_deposit_and_push_to_mes("SO-001")

		doc.check_permission.assert_called_once_with("write")
		push_status.assert_not_called()

	def test_reconcile_final_payment_checks_write_permission_before_status_change(self):
		doc = self.make_sales_order()
		doc.check_permission.side_effect = frappe.PermissionError

		with (
			patch.object(frappe, "get_doc", return_value=doc),
			patch(
				"crm_integration.crm_integration.sales_order.is_crm_integration_enabled",
				return_value=True,
			),
			patch("crm_integration.crm_integration.sales_order.set_process_status") as set_status,
			self.assertRaises(frappe.PermissionError),
		):
			reconcile_final_payment("SO-001")

		doc.check_permission.assert_called_once_with("write")
		set_status.assert_not_called()

	def make_sales_order(self):
		doc = MagicMock()
		doc.name = "SO-001"
		doc.docstatus = 1
		doc.get.side_effect = lambda field: {
			"company": "Test Company",
			"custom_process_status": "Pending Deposit Confirmation",
			"status": "To Deliver and Bill",
		}.get(field)
		return doc
