"""Two-session regression; committed fixtures are restricted to the isolated QA site."""
import json
import select
import subprocess
import sys
import unittest
from unittest.mock import patch

import frappe

from china_finance.tests import test_cancellation_sync as fixtures
from china_finance.services.voucher import process_cancellation_snapshot


class TestCancellationSyncConcurrency(unittest.TestCase):
	insert = fixtures.TestCancellationSync.insert
	assignment = fixtures.TestCancellationSync.assignment
	snapshot_entries = fixtures.TestCancellationSync.snapshot_entries

	def setUp(self):
		if frappe.local.site != "po-grid-qa.localhost":
			self.skipTest("Committed concurrent fixtures are allowed only on po-grid-qa.localhost")
		fixtures.TestCancellationSync.setUp(self)
		# Unlike the ordinary tests, independent sessions must see committed
		# fixtures. Cleanup below removes only this randomly named fixture chain.
		self._cleanups.clear()
		self.addCleanup(self.cleanup_fixtures)

	def cleanup_fixtures(self):
		frappe.db.rollback()
		pattern = self.prefix + "%"
		for doctype in ("China Cash Flow Assignment Item", "China Accounting Voucher Entry"):
			frappe.db.delete(doctype, {"parent": ["like", pattern]})
		frappe.db.delete("Version", {"docname": ["like", pattern]})
		frappe.db.delete("Comment", {"reference_name": ["like", pattern]})
		for doctype in ("China Voucher Sync Issue", "China Cash Flow Assignment", "China Accounting Voucher", "GL Entry", "Payment Entry", "Account", "Company"):
			frappe.db.delete(doctype, {"name": ["like", pattern]})
		frappe.db.commit()

	def test_stale_waiting_attempt_resolves_after_transaction_owner_retries(self):
		self.snapshot_entries()
		self.assignment()
		gl_names = [self.insert("GL Entry", company=self.company, voucher_type="Payment Entry", voucher_no=self.source, account=self.account, account_currency="CNY", is_cancelled=1, debit=debit, credit=credit) for debit, credit in ((0, 100), (100, 0))]
		before_gl = [frappe.get_doc("GL Entry", name).as_dict() for name in gl_names]
		frappe.db.commit()
		# The first transaction owns the source lock and creates its snapshot,
		# while the second starts an older consistent read before waiting on it.
		frappe.get_doc("Payment Entry", self.source, for_update=True)
		with patch("china_finance.services.voucher.get_company_settings", return_value=frappe._dict(activation_date="2026-01-01")), patch("china_finance.china_finance.doctype.china_accounting_voucher.china_accounting_voucher.ChinaAccountingVoucher.autoname", lambda doc: setattr(doc, "name", self.prefix + "-Cancellation"), create=True):
			first = process_cancellation_snapshot("Payment Entry", self.source, self.issue)
		self.assertEqual(first["status"], "resolved", first)
		worker_code = '''
import json, sys
from unittest.mock import patch
sys.path.insert(0, sys.argv[1])
import frappe
from china_finance.services.voucher import process_cancellation_snapshot
frappe.init(site="po-grid-qa.localhost", sites_path="/home/frappe/frappe-bench/sites")
frappe.connect()
frappe.set_user("Administrator")
try:
    old = frappe.db.get_value("China Voucher Sync Issue", sys.argv[3], ["status", "retry_count"])
    print(json.dumps({"old": old, "isolation": frappe.db.sql("SELECT @@tx_isolation")[0][0]}), flush=True)
    with patch("china_finance.services.voucher.get_company_settings", return_value=frappe._dict(activation_date="2026-01-01")), patch("china_finance.china_finance.doctype.china_accounting_voucher.china_accounting_voucher.ChinaAccountingVoucher.autoname", lambda doc: setattr(doc, "name", sys.argv[4]), create=True):
        try:
            process_cancellation_snapshot("Payment Entry", sys.argv[2], sys.argv[3])
        except (frappe.QueryDeadlockError, frappe.QueryTimeoutError) as exc:
            retryable = type(exc).__name__
            frappe.db.rollback()
        else:
            raise AssertionError("Old snapshot must signal a retryable concurrency failure")
        result = process_cancellation_snapshot("Payment Entry", sys.argv[2], sys.argv[3])
        result["retryable_first_attempt"] = retryable
    frappe.db.commit()
    print(json.dumps(result), flush=True)
finally:
    frappe.db.rollback()
    frappe.destroy()
'''
		worker = subprocess.Popen([sys.executable, "-c", worker_code, sys.path[0], self.source, self.issue, self.prefix + "-Cancellation"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
		try:
			ready = json.loads(worker.stdout.readline())
			self.assertEqual(ready["old"], ["Pending", 0])
			self.assertEqual(ready["isolation"], "REPEATABLE-READ")
			self.assertFalse(select.select([worker.stdout], [], [], 0.2)[0], "Second session must wait for the source lock")
			frappe.db.commit()
			output, errors = worker.communicate(timeout=20)
			self.assertEqual(worker.returncode, 0, errors)
			second = json.loads(output.strip().splitlines()[-1])
			self.assertEqual(second["status"], "resolved", second)
			self.assertEqual(second["retryable_first_attempt"], "QueryDeadlockError")
			self.assertEqual(second["voucher"], first["voucher"])
			self.assertEqual(frappe.db.get_value("China Voucher Sync Issue", self.issue, ["status", "retry_count"]), ("Resolved", 1))
			self.assertEqual(frappe.db.count("China Accounting Voucher", {"source_key": f"Cancellation|Payment Entry|{self.source}"}), 1)
			self.assertEqual([frappe.get_doc("GL Entry", name).as_dict() for name in gl_names], before_gl)
			self.assertEqual(frappe.db.count("GL Entry", {"voucher_type": "Payment Entry", "voucher_no": self.source}), len(gl_names))
		finally:
			frappe.db.rollback()
			if worker.poll() is None:
				worker.terminate()
				worker.wait(timeout=5)
