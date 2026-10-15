from frappe.model.document import Document


class PurchaseSourceMappingRule(Document):
	def validate(self):
		from deeplinkerp_branding.services.purchase_source_rules import validate_rule_write

		validate_rule_write(self)

	def on_trash(self):
		from deeplinkerp_branding.services.purchase_source_rules import validate_rule_write

		validate_rule_write(self)

	def before_rename(self, *args, **kwargs):
		from deeplinkerp_branding.services.purchase_source_rules import validate_rule_write

		validate_rule_write(self)
