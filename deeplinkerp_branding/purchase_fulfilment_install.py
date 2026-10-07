"""Additive, idempotent lookup indexes; no business documents or master data."""
def after_migrate():
    import frappe
    if frappe.db.exists("DocType", "Purchase Fulfilment Link"):
        frappe.db.add_index("Purchase Fulfilment Link", ["external_order", "active"], "fulfilment_external_active")
        frappe.db.add_index("Purchase Fulfilment Link", ["internal_order", "active"], "fulfilment_internal_active")
