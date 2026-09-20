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
