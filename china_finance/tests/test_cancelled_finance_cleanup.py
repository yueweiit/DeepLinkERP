import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import frappe

from china_finance.services.cancelled_finance_cleanup import cleanup_cancelled_finance
from china_finance.services.finance_cleanup import preview_finance_cleanup


class TestCancelledFinanceCleanup(unittest.TestCase):
	def setUp(self):
		self.prefix = "CF_Purge_" + frappe.generate_hash(length=8)
		frappe.db.savepoint(self.prefix)
		self.addCleanup(frappe.db.rollback, save_point=self.prefix)
		self.temp = tempfile.TemporaryDirectory()
		self.addCleanup(self.temp.cleanup)
		self.company = self.insert(
			"Company", "Company", company_name=self.prefix, abbr=self.prefix[-5:], default_currency="CNY"
		)
		self.other_company = self.insert(
			"Company",
			"Other Company",
			company_name=self.prefix + " Other",
			abbr=self.prefix[-4:],
			default_currency="CNY",
		)
		self.source = self.insert(
			"Journal Entry", "Original", company=self.company, posting_date="2026-07-01", docstatus=2
		)
		self.amendment = self.insert(
			"Journal Entry",
			"Amendment",
			company=self.company,
			posting_date="2026-07-01",
			docstatus=2,
			amended_from=self.source,
		)
		self.child = self.insert(
			"Journal Entry Account",
			"Account Row",
			parent=self.source,
			parenttype="Journal Entry",
			parentfield="accounts",
		)
		self.other_source = self.insert(
			"Journal Entry",
			"Other Source",
			company=self.other_company,
			posting_date="2026-07-01",
			docstatus=2,
		)
		self.order = self.insert("Sales Order", "Order", company=self.company, docstatus=1)
		self.payment = self.insert(
			"Payment Entry", "Payment", company=self.company, posting_date="2026-07-01", docstatus=0
		)
		self.insert(
			"Payment Entry Reference",
			"Order Reference",
			parent=self.payment,
			parenttype="Payment Entry",
			parentfield="references",
			reference_doctype="Sales Order",
			reference_name=self.order,
		)
		self.snapshot = self.insert(
			"China Accounting Voucher",
			"Snapshot",
			company=self.company,
			posting_date="2026-07-01",
			docstatus=2,
			source_doctype="Journal Entry",
			source_name=self.source,
			source_event="Posting",
			source_key=self.prefix + "|Posting",
		)
		self.reversal = self.insert(
			"China Accounting Voucher",
			"Reversal",
			company=self.company,
			posting_date="2026-07-01",
			docstatus=1,
			source_doctype="Journal Entry",
			source_name=self.source,
			source_event="Cancellation",
			reversal_of=self.snapshot,
			source_key=self.prefix + "|Cancellation",
		)
		self.ledger = self.insert(
			"Payment Ledger Entry",
			"PLE",
			company=self.company,
			posting_date="2026-07-01",
			voucher_type="Journal Entry",
			voucher_no=self.source,
			delinked=1,
			amount=100,
			amount_in_account_currency=100,
		)
		self.receipt_path = Path(self.temp.name) / "receipt.pdf"
		self.receipt_path.write_bytes(b"original receipt bytes")
		self.attachment = self.insert(
			"File",
			"Receipt",
			file_name="receipt.pdf",
			file_url=str(self.receipt_path),
			is_private=1,
			attached_to_doctype="Journal Entry",
			attached_to_name=self.source,
		)
		self.comment = self.insert(
			"Comment",
			"Comment",
			reference_doctype="Journal Entry",
			reference_name=self.source,
			content="Original note",
		)
		self.series = self.insert(
			"China Voucher Sequence",
			"Sequence",
			company=self.company,
			fiscal_year="2026",
			accounting_period="2026-07",
			voucher_word="记",
			current_value=14,
			sequence_key=self.prefix,
		)
		self.path = Path(self.temp.name) / "preview.json"
		self.save_preview()

	def insert(self, dt, label, **values):
		name = self.prefix + "-" + label
		frappe.get_doc({"doctype": dt, "name": name, **values}).db_insert()
		return name

	def save_preview(self):
		self.path.write_text(frappe.as_json(preview_finance_cleanup(self.company)))

	def run_cleanup(self, apply=0, **kwargs):
		with patch("china_finance.services.cancelled_finance_cleanup._assert_maintenance_window"):
			return cleanup_cancelled_finance(self.company, str(self.path), apply=apply, **kwargs)

	def test_default_is_read_only_and_keeps_order_linked_draft(self):
		result = self.run_cleanup()
		self.assertEqual(result["status"], "ready")
		self.assertEqual(result["delete_counts"]["Journal Entry"], 2)
		self.assertEqual(result["delete_counts"]["China Accounting Voucher"], 2)
		self.assertEqual(
			result["preserved_sources"], [{"doctype": "Payment Entry", "name": self.payment, "docstatus": 0}]
		)
		self.assertTrue(frappe.db.exists("Journal Entry", self.source))

	def test_relative_preview_path_uses_bench_root_instead_of_sites_working_directory(self):
		with patch(
			"china_finance.services.cancelled_finance_cleanup.get_bench_path", return_value=self.temp.name
		):
			result = cleanup_cancelled_finance(self.company, preview_file="preview.json")
		self.assertEqual(result["status"], "ready")
		self.assertTrue(frappe.db.exists("Journal Entry", self.source))

	def test_sync_issue_referencing_snapshot_is_archived_once_with_its_source(self):
		issue = self.insert(
			"China Voucher Sync Issue",
			"Snapshot Issue",
			company=self.company,
			source_doctype="China Accounting Voucher",
			source_name=self.snapshot,
			cancellation_voucher=self.reversal,
			issue_key=self.prefix + "|Snapshot Issue",
		)
		plan = self.run_cleanup()
		self.assertEqual(plan["status"], "ready", plan["blockers"])
		self.assertEqual(plan["delete_names"]["China Voucher Sync Issue"], [issue])
		result = self.apply_with_local_export()
		self.assertEqual(result["status"], "removed", result["blockers"])
		self.assertFalse(frappe.db.exists("China Voucher Sync Issue", issue))
		archives = frappe.get_all(
			"Deleted Document", filters={"deleted_doctype": "China Voucher Sync Issue", "deleted_name": issue}
		)
		self.assertEqual(len(archives), 1)

	def test_snapshot_sync_issue_cross_company_and_outside_snapshot_links_still_block(self):
		issue = self.insert(
			"China Voucher Sync Issue",
			"Snapshot Issue",
			company=self.other_company,
			source_doctype="China Accounting Voucher",
			source_name=self.snapshot,
			issue_key=self.prefix + "|Snapshot Issue",
		)
		result = self.apply_with_local_export()
		self.assertEqual(result["status"], "blocked")
		self.assertTrue(any(b.get("name") == issue and "其他公司" in b["reason"] for b in result["blockers"]))
		frappe.db.set_value(
			"China Voucher Sync Issue",
			issue,
			{"company": self.company, "cancellation_voucher": self.prefix + "-Outside Snapshot"},
		)
		result = self.apply_with_local_export()
		self.assertEqual(result["status"], "blocked")
		self.assertTrue(
			any(
				b.get("name") == issue and b.get("reference_name") == self.prefix + "-Outside Snapshot"
				for b in result["blockers"]
			)
		)
		self.assertTrue(frappe.db.exists("China Voucher Sync Issue", issue))
		self.assertTrue(frappe.db.exists("Journal Entry", self.source))

	def test_apply_archives_and_cleans_cancelled_chain_without_touching_business_or_sequences(self):
		result = self.apply_with_local_export()
		self.assertEqual(result["status"], "removed")
		for dt, name in (
			("Journal Entry", self.source),
			("Journal Entry", self.amendment),
			("Journal Entry Account", self.child),
			("China Accounting Voucher", self.snapshot),
			("China Accounting Voucher", self.reversal),
			("Payment Ledger Entry", self.ledger),
		):
			self.assertFalse(frappe.db.exists(dt, name), (dt, name))
		for dt, name in (
			("Sales Order", self.order),
			("Payment Entry", self.payment),
			("Journal Entry", self.other_source),
		):
			self.assertTrue(frappe.db.exists(dt, name))
		self.assertEqual(frappe.db.get_value("China Voucher Sequence", self.series, "current_value"), 14)
		self.assertEqual(self.receipt_path.read_bytes(), b"original receipt bytes")
		file = frappe.get_doc("File", self.attachment)
		self.assertEqual(file.attached_to_doctype, "Deleted Document")
		archive = frappe.get_doc("Deleted Document", file.attached_to_name)
		self.assertEqual(archive.deleted_name, self.source)
		self.assertEqual(frappe.db.get_value("Comment", self.comment, "reference_name"), archive.name)
		data = json.loads(Path(result["record_backup"]).read_text())
		self.assertTrue(
			any(
				d["name"] == self.source and d["accounts"][0]["name"] == self.child for d in data["documents"]
			)
		)
		self.assertEqual(Path(result["record_backup"]).stat().st_mode & 0o777, 0o600)
		self.assertEqual(self.run_cleanup()["delete_counts"], {})
		self.assertEqual(self.apply_with_local_export()["status"], "nothing_to_remove")

	def apply_with_local_export(self, **kwargs):
		original = tempfile.mkstemp
		with (
			patch("china_finance.services.cancelled_finance_cleanup._assert_maintenance_window"),
			patch(
				"china_finance.services.cancelled_finance_cleanup.tempfile.mkstemp",
				side_effect=lambda **kw: original(dir=self.temp.name),
			),
		):
			return cleanup_cancelled_finance(self.company, str(self.path), apply=1, **kwargs)

	def test_later_failure_rolls_back_deleted_documents_and_attachment_links(self):
		from china_finance.services.cancelled_finance_cleanup import _purge_document

		calls = []

		def fail_after_first(doc):
			calls.append(doc.name)
			if len(calls) == 2:
				raise RuntimeError("injected failure")
			_purge_document(doc)

		with patch(
			"china_finance.services.cancelled_finance_cleanup._purge_document", side_effect=fail_after_first
		):
			with self.assertRaises(RuntimeError):
				self.apply_with_local_export()
		self.assertEqual(len(calls), 2)
		self.assertTrue(frappe.db.exists("Journal Entry", self.source))
		self.assertTrue(frappe.db.exists("Journal Entry Account", self.child))
		self.assertEqual(frappe.db.get_value("File", self.attachment, "attached_to_name"), self.source)
		self.assertFalse(frappe.db.exists("Deleted Document", {"deleted_name": self.source}))

	def test_active_ledger_and_unbalanced_payment_ledger_block_whole_batch(self):
		self.insert(
			"GL Entry",
			"Live GL",
			company=self.company,
			posting_date="2026-07-01",
			voucher_type="Journal Entry",
			voucher_no=self.source,
			is_cancelled=0,
			debit=100,
		)
		frappe.db.set_value("Payment Ledger Entry", self.ledger, "delinked", 0)
		result = self.apply_with_local_export()
		self.assertEqual(result["status"], "blocked")
		self.assertTrue(any("有效总账" in b["reason"] for b in result["blockers"]))
		self.assertTrue(any("有效余额" in b["reason"] for b in result["blockers"]))
		self.assertTrue(frappe.db.exists("Journal Entry", self.source))

	def test_immutable_payment_pairs_must_net_to_zero_per_date_and_party(self):
		frappe.db.set_value("Payment Ledger Entry", self.ledger, "delinked", 0)
		reverse = self.insert(
			"Payment Ledger Entry",
			"PLE Reverse",
			company=self.company,
			posting_date="2026-07-01",
			voucher_type="Journal Entry",
			voucher_no=self.source,
			delinked=0,
			amount=-100,
			amount_in_account_currency=-100,
		)
		self.assertEqual(self.run_cleanup()["status"], "ready")
		frappe.db.set_value("Payment Ledger Entry", reverse, "posting_date", "2026-07-02")
		result = self.run_cleanup()
		self.assertEqual(result["status"], "blocked")
		groups = [b["group"] for b in result["blockers"] if "group" in b]
		self.assertEqual({g["posting_date"] for g in groups}, {"2026-07-01", "2026-07-02"})
		self.assertTrue(all(g["voucher_no"] == self.source for g in groups))

	def make_mixed_delinked_pair(self):
		values = {
			"against_voucher_type": "Journal Entry",
			"against_voucher_no": self.source,
			"voucher_detail_no": self.child,
			"account_type": "Payable",
			"due_date": "2026-07-01",
			"amount": 830.86,
			"amount_in_account_currency": 830.86,
		}
		frappe.db.set_value("Payment Ledger Entry", self.ledger, values)
		return self.insert(
			"Payment Ledger Entry",
			"Mixed Reverse",
			company=self.company,
			posting_date="2026-07-01",
			voucher_type="Journal Entry",
			voucher_no=self.source,
			delinked=0,
			**{**values, "amount": -830.86, "amount_in_account_currency": -830.86},
		)

	def test_mixed_delinked_cancellation_residue_requires_explicit_option(self):
		reverse = self.make_mixed_delinked_pair()
		result = self.run_cleanup()
		self.assertEqual(result["status"], "blocked")
		residue = result["cancelled_ledger_residue"]
		self.assertEqual(len(residue), 1)
		self.assertFalse(residue[0]["included"])
		self.assertEqual(residue[0]["names"], [reverse])
		self.assertEqual(residue[0]["delinked_names"], [self.ledger])
		self.assertEqual(residue[0]["amount"], "-830.86")
		result = self.apply_with_local_export(include_cancelled_ledger_residue=1)
		self.assertEqual(result["status"], "removed", result["blockers"])
		self.assertTrue(result["cancelled_ledger_residue"][0]["included"])
		for name in (reverse, self.ledger):
			self.assertFalse(frappe.db.exists("Payment Ledger Entry", name))
		self.assertTrue(frappe.db.exists("Payment Entry", self.payment))
		self.assertTrue(frappe.db.exists("Sales Order", self.order))

	def test_residue_option_does_not_allow_unmatched_pairs_parties_other_vouchers_or_gl(self):
		reverse = self.make_mixed_delinked_pair()
		original = frappe.get_doc("Payment Ledger Entry", reverse).as_dict()
		for values in (
			{"amount": -830.85},
			{"amount_in_account_currency": -830.85},
			{"posting_date": "2026-07-02"},
			{"party_type": "Customer", "party": "A"},
			{"against_voucher_no": self.amendment},
			{"voucher_detail_no": "different-row"},
			{"account_type": "Receivable"},
			{"due_date": "2026-07-02"},
		):
			with self.subTest(values=values):
				frappe.db.set_value("Payment Ledger Entry", reverse, values)
				self.assertEqual(self.run_cleanup(include_cancelled_ledger_residue=1)["status"], "blocked")
				frappe.db.set_value("Payment Ledger Entry", reverse, {key: original[key] for key in values})
		for name in (reverse, self.ledger):
			frappe.db.set_value("Payment Ledger Entry", name, {"party_type": "Customer", "party": "A"})
		self.assertEqual(self.run_cleanup(include_cancelled_ledger_residue=1)["status"], "blocked")
		for name in (reverse, self.ledger):
			frappe.db.set_value("Payment Ledger Entry", name, {"party_type": None, "party": None})
		self.insert(
			"GL Entry",
			"Cancelled GL",
			company=self.company,
			posting_date="2026-07-01",
			voucher_type="Journal Entry",
			voucher_no=self.source,
			is_cancelled=1,
		)
		self.assertEqual(self.run_cleanup(include_cancelled_ledger_residue=1)["status"], "blocked")

	def test_residue_requires_exact_pairs_not_just_zero_total_and_external_references_still_block(self):
		reverse = self.make_mixed_delinked_pair()
		frappe.db.set_value(
			"Payment Ledger Entry", self.ledger, {"amount": 800, "amount_in_account_currency": 800}
		)
		extra = self.insert(
			"Payment Ledger Entry",
			"Unmatched Split",
			company=self.company,
			posting_date="2026-07-01",
			voucher_type="Journal Entry",
			voucher_no=self.source,
			delinked=1,
			amount=30.86,
			amount_in_account_currency=30.86,
			against_voucher_type="Journal Entry",
			against_voucher_no=self.source,
			voucher_detail_no=self.child,
			account_type="Payable",
			due_date="2026-07-01",
		)
		self.assertEqual(self.run_cleanup(include_cancelled_ledger_residue=1)["status"], "blocked")
		frappe.db.delete("Payment Ledger Entry", {"name": extra})
		frappe.db.set_value(
			"Payment Ledger Entry", self.ledger, {"amount": 830.86, "amount_in_account_currency": 830.86}
		)
		self.insert(
			"Payment Entry Reference",
			"Outside Reference",
			parent=self.payment,
			parenttype="Payment Entry",
			parentfield="references",
			reference_doctype="Journal Entry",
			reference_name=self.source,
		)
		result = self.apply_with_local_export(include_cancelled_ledger_residue=1)
		self.assertEqual(result["status"], "blocked")
		self.assertTrue(any(b.get("reference_name") == self.payment for b in result["blockers"]))
		self.assertTrue(frappe.db.exists("Payment Ledger Entry", reverse))
		self.assertTrue(frappe.db.exists("Journal Entry", self.source))

	def test_changed_source_and_bank_allocation_block_cleanup(self):
		frappe.db.set_value("Journal Entry", self.source, "docstatus", 1)
		self.assertEqual(self.run_cleanup()["status"], "blocked")
		frappe.db.set_value("Journal Entry", self.source, "docstatus", 2)
		self.save_preview()
		bank = self.insert("Bank Transaction", "Bank", company=self.company, date="2026-07-01", docstatus=1)
		self.insert(
			"Bank Transaction Payments",
			"Allocation",
			parent=bank,
			parenttype="Bank Transaction",
			parentfield="payment_entries",
			payment_document="Journal Entry",
			payment_entry=self.source,
			allocated_amount=10,
		)
		result = self.run_cleanup()
		self.assertTrue(any(b.get("reference_name") == bank for b in result["blockers"]))

	def test_orphan_snapshot_requires_explicit_option_and_no_source_ledger(self):
		orphan = self.insert(
			"China Accounting Voucher",
			"Orphan",
			company=self.company,
			posting_date="2026-07-01",
			docstatus=1,
			source_doctype="Journal Entry",
			source_name=self.prefix + "-Missing",
			source_event="Posting",
			source_key=self.prefix + "|Orphan",
		)
		self.save_preview()
		self.assertNotIn(orphan, self.run_cleanup()["delete_names"]["China Accounting Voucher"])
		self.assertIn(
			orphan, self.run_cleanup(include_orphan_snapshots=1)["delete_names"]["China Accounting Voucher"]
		)
		self.insert(
			"GL Entry",
			"Orphan GL",
			company=self.company,
			posting_date="2026-07-01",
			voucher_type="Journal Entry",
			voucher_no=self.prefix + "-Missing",
			is_cancelled=1,
		)
		self.assertEqual(self.run_cleanup(include_orphan_snapshots=1)["status"], "blocked")

	def test_orphan_apply_cleans_associations_and_preserves_live_source_snapshots(self):
		missing = self.prefix + "-Missing"
		orphan = self.insert(
			"China Accounting Voucher",
			"Orphan",
			company=self.company,
			posting_date="2026-07-01",
			docstatus=1,
			source_doctype="Journal Entry",
			source_name=missing,
			source_event="Posting",
			source_key=self.prefix + "|Orphan",
		)
		child = self.insert(
			"China Accounting Voucher Entry",
			"Orphan Row",
			parent=orphan,
			parenttype="China Accounting Voucher",
			parentfield="entries",
		)
		issue = self.insert(
			"China Voucher Sync Issue",
			"Orphan Issue",
			company=self.company,
			source_doctype="Journal Entry",
			source_name=missing,
			issue_key=self.prefix,
		)
		snapshot_issue = self.insert(
			"China Voucher Sync Issue",
			"Orphan Snapshot Issue",
			company=self.company,
			source_doctype="China Accounting Voucher",
			source_name=orphan,
			issue_key=self.prefix + "|Orphan Snapshot",
		)
		assignment = self.insert(
			"China Cash Flow Assignment",
			"Orphan Assignment",
			company=self.company,
			source_doctype="Journal Entry",
			source_name=missing,
			china_accounting_voucher=orphan,
		)
		invoice = self.insert(
			"Sales Invoice", "Invoice", company=self.company, posting_date="2026-07-01", docstatus=1
		)
		preserved = self.insert(
			"China Accounting Voucher",
			"Invoice Snapshot",
			company=self.company,
			posting_date="2026-07-01",
			docstatus=1,
			source_doctype="Sales Invoice",
			source_name=invoice,
			source_event="Posting",
			source_key=self.prefix + "|Invoice",
		)
		preserved_issue = self.insert(
			"China Voucher Sync Issue",
			"Preserved Snapshot Issue",
			company=self.company,
			source_doctype="China Accounting Voucher",
			source_name=preserved,
			issue_key=self.prefix + "|Preserved Snapshot",
		)
		self.save_preview()
		# A voucher created after inventory must never be silently absorbed.
		new_source = self.insert(
			"Journal Entry", "Later Cancelled", company=self.company, posting_date="2026-07-01", docstatus=2
		)
		result = self.apply_with_local_export(include_orphan_snapshots=1)
		self.assertEqual(result["status"], "removed", result["blockers"])
		for dt, name in (
			("China Accounting Voucher", orphan),
			("China Accounting Voucher Entry", child),
			("China Voucher Sync Issue", issue),
			("China Voucher Sync Issue", snapshot_issue),
			("China Cash Flow Assignment", assignment),
		):
			self.assertFalse(frappe.db.exists(dt, name), (dt, name))
		for dt, name in (
			("Sales Invoice", invoice),
			("China Accounting Voucher", preserved),
			("China Voucher Sync Issue", preserved_issue),
			("Journal Entry", new_source),
		):
			self.assertTrue(frappe.db.exists(dt, name), (dt, name))

	def test_orphan_source_with_retained_business_reference_blocks_cleanup(self):
		missing = self.prefix + "-Missing"
		self.insert(
			"China Accounting Voucher",
			"Orphan",
			company=self.company,
			posting_date="2026-07-01",
			docstatus=1,
			source_doctype="Journal Entry",
			source_name=missing,
			source_event="Posting",
			source_key=self.prefix + "|Orphan",
		)
		self.insert(
			"Payment Entry Reference",
			"Missing Reference",
			parent=self.payment,
			parenttype="Payment Entry",
			parentfield="references",
			reference_doctype="Journal Entry",
			reference_name=missing,
		)
		self.save_preview()
		result = self.apply_with_local_export(include_orphan_snapshots=1)
		self.assertEqual(result["status"], "blocked")
		self.assertTrue(any(b.get("reference_name") == self.payment for b in result["blockers"]))
		self.assertTrue(frappe.db.exists("Journal Entry", self.source))

	def test_source_removed_since_preview_blocks_when_associations_remain(self):
		frappe.db.delete("Journal Entry", {"name": self.source})
		result = self.run_cleanup()
		self.assertEqual(result["status"], "blocked")
		self.assertTrue(any("来源凭证已删除" in b["reason"] for b in result["blockers"]))

	def test_frozen_period_and_later_closing_block_cleanup(self):
		frappe.db.set_value("Company", self.company, "accounts_frozen_till_date", "2026-08-31")
		closing = self.insert(
			"Period Closing Voucher",
			"Closing",
			company=self.company,
			period_start_date="2026-01-01",
			period_end_date="2026-08-31",
			docstatus=1,
		)
		result = self.run_cleanup()
		self.assertEqual(result["status"], "blocked")
		self.assertTrue(any(b.get("frozen_until") for b in result["blockers"]))
		self.assertTrue(any(b.get("name") == closing for b in result["blockers"]))

	def test_site_mismatch_and_maintenance_guard_prevent_mutations(self):
		data = json.loads(self.path.read_text())
		data["site"] = "other-site"
		self.path.write_text(json.dumps(data))
		with self.assertRaises(frappe.ValidationError):
			self.run_cleanup()
		self.save_preview()
		with patch.dict(frappe.conf, {"maintenance_mode": 0}):
			with self.assertRaises(frappe.ValidationError):
				cleanup_cancelled_finance(self.company, str(self.path), apply=1)
		with (
			patch.dict(frappe.conf, {"maintenance_mode": 1}),
			patch("frappe.utils.background_jobs.get_jobs", return_value={frappe.local.site: ["running_job"]}),
		):
			with self.assertRaises(frappe.ValidationError):
				cleanup_cancelled_finance(self.company, str(self.path), apply=1)
		self.assertTrue(frappe.db.exists("Journal Entry", self.source))
