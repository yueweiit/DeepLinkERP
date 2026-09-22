from frappe.model.document import Document

from china_finance.services.bank_receipt_import import protect_service_document, validate_import_document


class ChinaBankReceiptImport(Document):
	def validate(self):
		validate_import_document(self)

	def on_trash(self):
		protect_service_document()
