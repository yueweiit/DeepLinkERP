from unittest.mock import patch

import frappe
from frappe.tests import UnitTestCase

from mes_integration.mes_integration.sales_order import (
	enqueue_sales_order_status_callback,
	get_sales_order_status_job_id,
	push_sales_order_status_to_mes_job,
)


class TestMESSalesOrder(UnitTestCase):
	def test_sales_order_status_job_id_is_stable_and_event_scoped(self):
		first = get_sales_order_status_job_id(
			"SAL-ORD-2026-00001",
			"待发货",
			"final_payment_reconciled",
		)
		second = get_sales_order_status_job_id(
			"SAL-ORD-2026-00001",
			"待发货",
			"final_payment_reconciled",
		)
		different = get_sales_order_status_job_id(
			"SAL-ORD-2026-00001",
			"已完成",
			"delivery_completed",
		)

		self.assertEqual(first, second)
		self.assertNotEqual(first, different)

	def test_sales_order_status_enqueue_uses_retry_job(self):
		job_id = get_sales_order_status_job_id(
			"SAL-ORD-2026-00001",
			"待发货",
			"final_payment_reconciled",
		)
		with patch(
			"mes_integration.mes_integration.sales_order.frappe.enqueue"
		) as enqueue:
			enqueue_sales_order_status_callback(
				"SAL-ORD-2026-00001",
				triggered_status="待发货",
				trigger_event="final_payment_reconciled",
			)

		enqueue.assert_called_once_with(
			"mes_integration.mes_integration.sales_order.push_sales_order_status_to_mes_job",
			queue="short",
			timeout=300,
			enqueue_after_commit=True,
			job_id=job_id,
			deduplicate=True,
			sales_order_name="SAL-ORD-2026-00001",
			triggered_status="待发货",
			trigger_event="final_payment_reconciled",
		)

	def test_sales_order_status_job_retries_callback_failure(self):
		with (
			patch(
				"mes_integration.mes_integration.sales_order.push_sales_order_status_to_mes",
				side_effect=RuntimeError("MES unavailable"),
			),
			patch.object(frappe.db, "commit") as commit,
			self.assertRaises(frappe.RetryBackgroundJobError),
		):
			push_sales_order_status_to_mes_job("SAL-ORD-2026-00001")

		commit.assert_called_once_with()
