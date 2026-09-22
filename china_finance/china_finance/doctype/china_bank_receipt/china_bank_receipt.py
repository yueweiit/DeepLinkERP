from frappe.model.document import Document

from china_finance.services.bank_receipt_import import protect_service_document


class ChinaBankReceipt(Document):
	def validate(self):
		protect_service_document()

	def on_trash(self):
		protect_service_document()
