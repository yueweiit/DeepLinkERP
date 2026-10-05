from frappe.model.document import Document


class OperatingExpenseSyncSettings(Document):
    def validate(self):
        from deeplinkerp_branding.services.operating_expenses import validate_managed_document
        validate_managed_document(self)

    def on_trash(self):
        from deeplinkerp_branding.services.operating_expenses import validate_managed_document
        validate_managed_document(self)
