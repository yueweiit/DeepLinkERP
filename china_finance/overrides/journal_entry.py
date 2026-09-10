"""China Finance balance validation for Journal Entry saves."""

from erpnext.accounts.doctype.journal_entry.journal_entry import JournalEntry


class ChinaFinanceJournalEntry(JournalEntry):
	"""Require balanced debit and credit totals before saving any voucher."""

	def validate(self):
		super().validate()
		# ERPNext normally calls this only from before_submit. Run it here too so
		# a draft cannot be saved with an unbalanced accounting entry.
		self.validate_total_debit_and_credit()
