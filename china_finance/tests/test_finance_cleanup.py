"""Exercise the cleanup inventory against rolled-back, isolated database fixtures."""

import unittest
from unittest.mock import patch

import frappe

from china_finance.services.finance_cleanup import preview_finance_cleanup


class TestFinanceCleanup(unittest.TestCase):
	def setUp(self):
		self.prefix = "CF_Cleanup_" + frappe.generate_hash(length=8)
		frappe.db.savepoint(self.prefix)
		self.addCleanup(frappe.db.rollback, save_point=self.prefix)
		self.company = self.insert("Company", "Company", company_name=self.prefix, abbr=self.prefix[-5:], default_currency="CNY")
		self.other_company = self.insert("Company", "Other Company", company_name=self.prefix + " Other", abbr=self.prefix[-4:], default_currency="CNY")
		self.source = self.insert("Journal Entry", "Cancelled", company=self.company, posting_date="2026-07-01", docstatus=2)
		self.amendment = self.insert("Journal Entry", "Amendment", company=self.company, posting_date="2026-08-01", docstatus=1, amended_from=self.source)
		self.other_source = self.insert("Journal Entry", "Other Source", company=self.other_company, posting_date="2026-07-01", docstatus=1)
		self.snapshot = self.insert("China Accounting Voucher", "Snapshot", company=self.company, posting_date="2026-07-01", docstatus=2,
			source_doctype="Journal Entry", source_name=self.source, source_event="Posting", source_key=self.prefix + "|Posting")
		self.reversal = self.insert("China Accounting Voucher", "Reversal", company=self.company, posting_date="2026-07-02", docstatus=1,
			source_doctype="Journal Entry", source_name=self.source, source_event="Cancellation", reversal_of=self.snapshot, source_key=self.prefix + "|Cancellation")
		self.assignment = self.insert("China Cash Flow Assignment", "Assignment", company=self.company, posting_date="2026-07-01",
			source_doctype="Journal Entry", source_name=self.source, china_accounting_voucher=self.snapshot)
		self.ledger = self.insert("GL Entry", "Ledger", company=self.company, posting_date="2026-07-01", voucher_type="Journal Entry", voucher_no=self.source, is_cancelled=1)
		self.bank = self.insert("Bank Transaction", "Bank", company=self.company, date="2026-07-01", docstatus=1, deposit=100,
			allocated_amount=100, unallocated_amount=0, status="Reconciled")
		self.allocation = self.insert("Bank Transaction Payments", "Allocation", parent=self.bank, parenttype="Bank Transaction", parentfield="payment_entries",
			payment_document="Journal Entry", payment_entry=self.source, allocated_amount=100)

	def insert(self, doctype, label, **values):
		name = self.prefix + "-" + label
		frappe.get_doc({"doctype": doctype, "name": name, **values}).db_insert()
		return name

	def preview(self, **kwargs):
		return preview_finance_cleanup(self.company, **kwargs)

	def test_date_scope_keeps_external_amendment_as_blocker_and_does_not_write(self):
		before = frappe.get_doc("Journal Entry", self.source).as_json()
		with patch.object(frappe.db, "delete", side_effect=AssertionError("inventory attempted delete")), \
			patch.object(frappe.db, "set_value", side_effect=AssertionError("inventory attempted update")), \
			patch.object(frappe.db, "commit", side_effect=AssertionError("inventory attempted commit")):
			result = self.preview(from_date="2026-07-01", to_date="2026-07-31")
		self.assertEqual(result["mode"], "preview_only")
		self.assertEqual(result["source_counts"]["Journal Entry"]["total"], 1)
		self.assertEqual({r["name"] for r in result["sources"]["Journal Entry"]}, {self.source})
		self.assertTrue(any(b.get("reference_name") == self.amendment for b in result["blockers"]))
		self.assertEqual(result["related_counts"]["China Accounting Voucher"], 2)
		self.assertEqual(result["related_counts"]["GL Entry"], 1)
		self.assertEqual(result["related_counts"]["China Cash Flow Assignment"], 1)
		self.assertEqual(before, frappe.get_doc("Journal Entry", self.source).as_json())
		self.assertEqual(frappe.db.get_value("Bank Transaction", self.bank, "allocated_amount"), 100)
		self.assertTrue(frappe.db.exists("Bank Transaction Payments", self.allocation))
		self.assertTrue(frappe.db.exists("Journal Entry", self.other_source))

	def test_cancelled_only_still_includes_submitted_reversal_snapshot(self):
		result = self.preview(cancelled_only=True)
		self.assertEqual(result["source_counts"]["Journal Entry"]["by_docstatus"], {2: 1})
		self.assertIn(self.reversal, {r["name"] for r in result["related_records"]["China Accounting Voucher"]})
		self.assertTrue(any(b.get("reference_name") == self.amendment for b in result["blockers"]))

	def test_shared_bank_allocations_are_reported_and_preserved(self):
		other = self.insert("Bank Transaction Payments", "Other Allocation", parent=self.bank, parenttype="Bank Transaction", parentfield="payment_entries",
			payment_document="Journal Entry", payment_entry=self.amendment, allocated_amount=50)
		result = self.preview(to_date="2026-07-31")
		rows = {r["name"]: r for r in result["bank_allocations_to_review"]}
		self.assertTrue(rows[self.allocation]["references_selected_source"])
		self.assertFalse(rows[other]["references_selected_source"])
		self.assertEqual(result["bank_transactions_to_preserve"][0]["name"], self.bank)

	def test_invoice_source_and_orphan_snapshots_are_not_selected(self):
		invoice = self.insert("Sales Invoice", "Invoice", company=self.company, posting_date="2026-07-01", docstatus=1)
		snapshot = self.insert("China Accounting Voucher", "Invoice Snapshot", company=self.company, posting_date="2026-07-01", docstatus=1,
			source_doctype="Sales Invoice", source_name=invoice, source_event="Posting", source_key=self.prefix + "|Invoice")
		orphan = self.insert("China Accounting Voucher", "Orphan", company=self.company, posting_date="2026-07-01", docstatus=1,
			source_doctype="Journal Entry", source_name=self.prefix + "-Missing", source_event="Posting", source_key=self.prefix + "|Missing")
		result = self.preview()
		preserved = {r["name"]: r for r in result["other_accounting_vouchers_to_preserve"]}
		self.assertTrue(preserved[snapshot]["source_exists"])
		self.assertFalse(preserved[orphan]["source_exists"])
		self.assertEqual(result["source_counts"]["Journal Entry"]["total"], 2)

	def test_outgoing_invoice_link_and_incoming_cancelled_reference_are_blockers(self):
		invoice = self.insert("Sales Invoice", "Invoice", company=self.company, posting_date="2026-07-01", docstatus=1)
		self.insert("Journal Entry Account", "Invoice Reference", parent=self.source, parenttype="Journal Entry", parentfield="accounts",
			reference_type="Sales Invoice", reference_name=invoice)
		referrer = self.insert("Payment Entry", "Cancelled Referrer", company=self.other_company, posting_date="2026-07-01", docstatus=2)
		self.insert("Payment Entry Reference", "Cancelled Reference", parent=referrer, parenttype="Payment Entry", parentfield="references",
			reference_doctype="Journal Entry", reference_name=self.source, docstatus=2)
		result = self.preview()
		refs = {b.get("reference_name") for b in result["blockers"]}
		self.assertIn(invoice, refs)
		self.assertIn(referrer, refs)

	def test_frozen_period_and_later_closing_are_reported(self):
		frappe.db.set_value("Company", self.company, "accounts_frozen_till_date", "2026-08-31")
		closing = self.insert("Period Closing Voucher", "Closing", company=self.company, period_start_date="2026-01-01", period_end_date="2026-08-31",
			docstatus=1, gle_processing_status="Completed")
		result = self.preview(to_date="2026-07-31")
		self.assertTrue(any(b.get("frozen_until") for b in result["blockers"]))
		self.assertTrue(any(b.get("name") == closing for b in result["blockers"]))

	def test_attachments_and_cross_company_association_are_reported(self):
		attachment = self.insert("File", "Receipt", file_name="receipt.pdf", file_url="/private/files/cleanup-test.pdf",
			is_private=1, attached_to_doctype="Journal Entry", attached_to_name=self.source)
		bad_snapshot = self.insert("China Accounting Voucher", "Cross Company Snapshot", company=self.other_company,
			posting_date="2026-07-01", source_doctype="Journal Entry", source_name=self.source,
			source_event="Posting", source_key=self.prefix + "|Cross")
		result = self.preview()
		self.assertEqual(result["attachments_to_preserve"][0]["name"], attachment)
		self.assertTrue(any(b.get("name") == bad_snapshot and b.get("company") == self.other_company for b in result["blockers"]))
		self.assertEqual(frappe.db.get_value("File", attachment, "attached_to_name"), self.source)

	def test_exact_company_and_valid_dates_required(self):
		for values in ({"company": ""}, {"company": self.prefix}, {"company": self.company, "from_date": "bad"},
			{"company": self.company, "from_date": "2026-08-01", "to_date": "2026-07-31"}):
			with self.assertRaises(frappe.ValidationError):
				preview_finance_cleanup(**values)
		with patch("frappe.only_for", side_effect=frappe.PermissionError):
			with self.assertRaises(frappe.PermissionError):
				self.preview()
