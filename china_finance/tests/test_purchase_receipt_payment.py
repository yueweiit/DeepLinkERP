from unittest import TestCase

from china_finance.china_finance.report.china_purchase_receipt_payment import china_purchase_receipt_payment


class TestPurchaseReceiptPayment(TestCase):
	def test_report_executes_and_exposes_payment_chain(self):
		columns, rows, _message, _chart, summary, skip_total_row = china_purchase_receipt_payment.execute(
			{"company": "test", "from_date": "2026-01-01", "to_date": "2026-12-31", "payment_status": "未生成应付"}
		)
		fieldnames = {column["fieldname"] for column in columns}
		self.assertTrue({"purchase_receipt", "purchase_invoices", "payment_entries", "payment_status"} <= fieldnames)
		self.assertIsInstance(rows, list)
		self.assertIsInstance(summary, list)
		self.assertEqual(skip_total_row, 1)
