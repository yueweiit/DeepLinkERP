"""China Finance draft behavior for Journal Entry balance validation."""

from erpnext.accounts.doctype.journal_entry.journal_entry import JournalEntry


class ChinaFinanceJournalEntry(JournalEntry):
	"""Allow incremental draft entry while protecting submitted accounting."""

	def validate_total_debit_and_credit(self):
		# Users may save a draft while entering several lines. ERPNext changes
		# docstatus to 1 before validating a submit, so submitted documents still
		# go through the native balance check below.
		if self.docstatus == 0:
			return
		super().validate_total_debit_and_credit()
