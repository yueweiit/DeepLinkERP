import frappe
from frappe.tests import UnitTestCase

from china_finance.services.voucher import _build_amendment_voucher_key, _next_formal_sequence, get_posting_date


class TestVoucherNumbering(UnitTestCase):
	def test_next_sequence_uses_the_larger_high_water_mark(self):
		self.assertEqual(_next_formal_sequence(15, 15), 16)
		self.assertEqual(_next_formal_sequence(15, 17), 18)

	def test_next_sequence_does_not_reuse_a_previous_number(self):
		self.assertEqual(_next_formal_sequence(0, 3), 4)

	def test_amendment_uses_a_distinct_snapshot_key(self):
		voucher = frappe._dict(source_key="Posting|Journal Entry|ACC-JV-2026-00382-1")
		self.assertEqual(
			_build_amendment_voucher_key(voucher),
			"amendment|Posting|Journal Entry|ACC-JV-2026-00382-1",
		)

	def test_period_closing_uses_period_end_date_for_snapshot(self):
		doc = frappe._dict(
			doctype="Period Closing Voucher",
			period_end_date="2026-05-31",
			transaction_date="2026-09-17",
		)
		self.assertEqual(str(get_posting_date(doc)), "2026-05-31")
