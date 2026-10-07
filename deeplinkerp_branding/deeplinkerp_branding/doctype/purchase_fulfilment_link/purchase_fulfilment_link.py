from frappe.model.document import Document


class PurchaseFulfilmentLink(Document):
    def validate(self):
        from deeplinkerp_branding.services.purchase_fulfilment_service import validate_managed_link
        validate_managed_link(self)

    def validate_higher_perm_levels(self):
        from deeplinkerp_branding.services.purchase_fulfilment_service import _managed
        # Native role/document checks still run. Only the server's guarded API
        # can populate the private evidence fields; REST has no level-9 access.
        if not _managed.get():
            super().validate_higher_perm_levels()

    def on_trash(self):
        from deeplinkerp_branding.services.purchase_fulfilment_service import protect_link_identity
        protect_link_identity(self)

    def before_rename(self, *args, **kwargs):
        from deeplinkerp_branding.services.purchase_fulfilment_service import protect_link_identity
        protect_link_identity(self)
