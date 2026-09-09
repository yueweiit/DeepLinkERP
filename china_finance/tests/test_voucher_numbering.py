from datetime import date, datetime

from frappe.tests import UnitTestCase

from china_finance.services.voucher import _build_formal_voucher_numbering


class TestVoucherNumbering(UnitTestCase):
	def test_formal_vouchers_are_numbered_by_posting_date(self):
		existing = [
			{
				"name": "CNV-2026-00001",
				"posting_date": date(2026, 1, 31),
				"creation": datetime(2026, 1, 1, 9, 0),
			},
			{
				"name": "CNV-2026-00002",
				"posting_date": date(2026, 1, 15),
				"creation": datetime(2026, 1, 2, 9, 0),
			},
		]
		current = {
			"name": "CNV-2026-00003",
			"posting_date": date(2026, 1, 1),
			"creation": datetime(2026, 1, 3, 9, 0),
		}

		ordered = _build_formal_voucher_numbering(existing, current)

		self.assertEqual(
			[row["name"] for row in ordered],
			["CNV-2026-00003", "CNV-2026-00002", "CNV-2026-00001"],
		)

	def test_same_posting_date_uses_creation_then_name(self):
		existing = [
			{
				"name": "CNV-2026-00002",
				"posting_date": date(2026, 1, 1),
				"creation": datetime(2026, 1, 2, 9, 0),
			},
			{
				"name": "CNV-2026-00001",
				"posting_date": date(2026, 1, 1),
				"creation": datetime(2026, 1, 1, 9, 0),
			},
		]
		current = {
			"name": "CNV-2026-00003",
			"posting_date": date(2026, 1, 1),
			"creation": datetime(2026, 1, 3, 9, 0),
		}

		ordered = _build_formal_voucher_numbering(existing, current)

		self.assertEqual(
			[row["name"] for row in ordered],
			["CNV-2026-00001", "CNV-2026-00002", "CNV-2026-00003"],
		)
