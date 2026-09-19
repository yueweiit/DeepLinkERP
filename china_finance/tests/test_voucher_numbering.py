from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase, UnitTestCase

from china_finance.services.closing import _get_period_closing_next_states
from china_finance.services.voucher import (
	_build_amendment_voucher_key, _next_formal_sequence, get_posting_date,
	assign_voucher_number, backfill_period_closing_voucher_numbers,
)
from china_finance.china_finance.report.china_voucher_ledger.china_voucher_ledger import execute as voucher_ledger


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

	def test_period_closing_shortcut_only_runs_remaining_workflow_states(self):
		self.assertEqual(
			_get_period_closing_next_states("Draft"),
			("Pending Review", "Approved", "Posted"),
		)
		self.assertEqual(_get_period_closing_next_states("Pending Review"), ("Approved", "Posted"))
		self.assertEqual(_get_period_closing_next_states("Approved"), ("Posted",))
		self.assertEqual(_get_period_closing_next_states("Posted"), ())

	def test_closing_cancellation_does_not_consume_a_number(self):
		voucher = frappe._dict(
			source_doctype="Period Closing Voucher", source_name="PCV-1",
			source_event="Cancellation", source_key="Cancellation|Period Closing Voucher|PCV-1",
		)
		assign_voucher_number(voucher)
		self.assertEqual(voucher.sequence_number, 0)
		self.assertIsNone(voucher.statutory_number)
		self.assertEqual(voucher.voucher_key, "cancellation|Cancellation|Period Closing Voucher|PCV-1")


class TestClosingVoucherNumberingIntegration(IntegrationTestCase):
	def setUp(self):
		super().setUp()
		self.company = f"_Test Closing Number {frappe.generate_hash(length=8)}"
		# Minimal database fixtures isolate numbering/reporting from GL creation,
		# which is independently owned by ERPNext's posting controllers.
		frappe.get_doc({
			"doctype": "Company", "name": self.company, "company_name": self.company,
			"abbr": frappe.generate_hash(length=5), "default_currency": "CNY",
		}).db_insert()
		settings = patch(
			"china_finance.services.voucher.get_company_settings",
			return_value=frappe._dict(company=self.company, enabled=1),
		)
		settings.start()
		self.addCleanup(settings.stop)

	def make_voucher(self, source_doctype, posting_date="2026-07-31", amended_from=None, legacy=False):
		source = frappe.get_doc({
			"doctype": source_doctype, "name": f"TEST-{frappe.generate_hash(length=10)}",
			"company": self.company, "docstatus": 1, "posting_date": posting_date,
			"transaction_date": "2026-09-19", "period_start_date": posting_date[:8] + "01",
			"period_end_date": posting_date, "amended_from": amended_from,
		})
		source.db_insert()
		voucher = frappe.get_doc({
			"doctype": "China Accounting Voucher", "company": self.company,
			"posting_date": posting_date, "voucher_word": "记", "currency": "CNY",
			"source_doctype": source.doctype, "source_name": source.name,
			"source_event": "Posting", "source_key": f"Posting|{source.doctype}|{source.name}",
			"entries": [
				{"account": "Test Expense", "debit": 100, "credit": 0},
				{"account": "Test Profit", "debit": 0, "credit": 100},
			],
		})
		if legacy:
			voucher.voucher_key = f"business|{self.company}|{source.doctype}|{source.name}|Posting"
		voucher.flags.ignore_links = True
		voucher.flags.ignore_permissions = True
		voucher.insert()
		voucher.submit()
		return source, voucher

	def report(self, **filters):
		return voucher_ledger({
			"company": self.company, "from_date": "2026-07-01", "to_date": "2026-08-31", **filters,
		})[1]

	def test_closing_is_numbered_after_monthly_sources_and_sorted_last(self):
		self.make_voucher("Journal Entry")
		self.make_voucher("Payment Entry", "2026-07-30")
		source, closing = self.make_voucher("Period Closing Voucher")
		self.assertEqual(closing.statutory_number, "记3")
		self.assertEqual(closing.accounting_period, "2026-07")
		self.assertEqual(self.report()[-2]["statutory_number"], "记3")
		self.assertEqual(self.report()[-2]["source_name"], source.name)
		self.assertEqual(len(self.report(voucher_word="记3")), 2)
		self.assertEqual(self.report(voucher_word="记3")[0]["source_name"], source.name)
		_, next_month = self.make_voucher("Journal Entry", "2026-08-01")
		self.assertEqual(next_month.statutory_number, "记1")
		self.assertEqual(self.report()[-2]["accounting_period"], "2026-08")

	def test_reclosing_takes_new_tail_number_but_journal_amendment_keeps_number(self):
		original_source, original_closing = self.make_voucher("Period Closing Voucher")
		frappe.db.set_value(original_source.doctype, original_source.name, "docstatus", 2)
		frappe.db.set_value(original_closing.doctype, original_closing.name, "status", "Reversed")
		journal, original = self.make_voucher("Journal Entry")
		_, amended = self.make_voucher("Journal Entry", amended_from=journal.name)
		self.assertEqual(amended.statutory_number, original.statutory_number)
		_, closing = self.make_voucher("Period Closing Voucher", amended_from=original_source.name)
		self.assertEqual(closing.statutory_number, "记3")
		self.assertEqual(self.report()[-2]["voucher_snapshot"], closing.name)

	def test_backfill_is_idempotent_and_only_numbers_current_posting_snapshots(self):
		_, ordinary = self.make_voucher("Journal Entry")
		source, active = self.make_voucher("Period Closing Voucher", legacy=True)
		cancelled_source, cancelled = self.make_voucher("Period Closing Voucher", legacy=True)
		frappe.db.set_value(cancelled_source.doctype, cancelled_source.name, "docstatus", 2)
		frappe.db.set_value(cancelled.doctype, cancelled.name, "status", "Reversed")
		_, superseded = self.make_voucher("Period Closing Voucher", legacy=True)
		frappe.db.set_value(superseded.doctype, superseded.name, "source_key", "legacy-reused|" + superseded.name)
		before_hash = active.source_hash
		preview = backfill_period_closing_voucher_numbers(self.company)
		self.assertEqual([row.name for row in preview], [active.name])
		active.reload()
		self.assertFalse(active.statutory_number)
		result = backfill_period_closing_voucher_numbers(self.company, apply=True)
		self.assertEqual(result[0]["statutory_number"], "记2")
		active.reload()
		self.assertEqual(active.source_hash, before_hash)
		self.assertEqual(active.total_debit, 100)
		ordinary.reload()
		self.assertEqual(ordinary.statutory_number, "记1")
		cancelled.reload()
		superseded.reload()
		self.assertFalse(cancelled.statutory_number)
		self.assertFalse(superseded.statutory_number)
		self.assertEqual(backfill_period_closing_voucher_numbers(self.company, apply=True), [])
		if frappe.db.has_column("Period Closing Voucher", "custom_china_voucher_number"):
			self.assertEqual(frappe.db.get_value(source.doctype, source.name, "custom_china_voucher_number"), "记2")
