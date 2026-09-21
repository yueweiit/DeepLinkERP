import json
from unittest.mock import patch

from frappe.tests import UnitTestCase

from china_finance.services import voucher_batch


class TestVoucherBatch(UnitTestCase):
	def test_submission_order_ignores_reverse_list_order(self):
		with patch.object(voucher_batch.frappe, "get_all", return_value=["early", "late"]) as query:
			self.assertEqual(voucher_batch.sort_voucher_names("Journal Entry", ["late", "missing", "early"]),
				["early", "late", "missing"])
			self.assertEqual(query.call_args.kwargs["order_by"], "posting_date asc, creation asc, name asc")

	def test_native_bulk_submit_receives_sorted_names_and_original_parameters(self):
		with patch.object(voucher_batch, "sort_voucher_names", return_value=["early", "late"]), patch(
			"frappe.desk.doctype.bulk_update.bulk_update.submit_cancel_or_update_docs", return_value=["failed"]
		) as native:
			result = voucher_batch.submit_cancel_or_update_docs("Journal Entry", '["late", "early"]', task_id="task")
			self.assertEqual(result, ["failed"])
			native.assert_called_once_with("Journal Entry", ["early", "late"], action="submit", data=None, task_id="task")

	def test_cancellation_keeps_native_order(self):
		with patch.object(voucher_batch, "sort_voucher_names") as sort, patch(
			"frappe.desk.doctype.bulk_update.bulk_update.submit_cancel_or_update_docs"
		) as native:
			voucher_batch.submit_cancel_or_update_docs("Journal Entry", ["late", "early"], action="cancel")
			sort.assert_not_called()
			self.assertEqual(native.call_args.args[1], ["late", "early"])

	def test_workflow_sorts_before_native_background_dispatch(self):
		with patch.object(voucher_batch, "sort_voucher_names", return_value=["early", "late"]), patch(
			"frappe.model.workflow.bulk_workflow_approval", return_value="native-result"
		) as native:
			self.assertEqual(voucher_batch.bulk_workflow_approval('["late", "early"]', "Journal Entry", "Post"), "native-result")
			self.assertEqual(json.loads(native.call_args.args[0]), ["early", "late"])
			self.assertEqual(native.call_args.args[1:], ("Journal Entry", "Post"))

	def test_unrelated_documents_do_not_query_accounting_dates(self):
		with patch.object(voucher_batch.frappe, "get_all") as query:
			self.assertEqual(voucher_batch.sort_voucher_names("ToDo", ["b", "a"]), ["b", "a"])
			query.assert_not_called()
