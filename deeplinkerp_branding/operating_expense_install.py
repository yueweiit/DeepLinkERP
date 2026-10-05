"""Idempotent app metadata; no financial master data or transactions."""
def after_migrate():
    from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
    create_custom_fields({"Journal Entry": [
        {"fieldname": "custom_operating_event_key", "label": "Operating expense event", "fieldtype": "Data", "unique": 1, "read_only": 1, "no_copy": 1},
        {"fieldname": "custom_operating_source", "label": "Operating expense source", "fieldtype": "Link", "options": "Operating Expense Source", "read_only": 1, "no_copy": 1},
        {"fieldname": "custom_operating_recognition", "label": "Expense recognition", "fieldtype": "Link", "options": "Journal Entry", "read_only": 1, "no_copy": 1},
        {"fieldname": "custom_operating_fingerprint", "label": "Financial fingerprint", "fieldtype": "Data", "read_only": 1, "no_copy": 1},
    ]})
