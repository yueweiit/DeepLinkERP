import frappe


BASE_PURPOSE = "Material Receipt"
RECEIPT_STOCK_ENTRY_TYPES = (
    "Semi Finished Goods Receipt",
    "Finished Goods Receipt",
)
LEGACY_STOCK_ENTRY_TYPE_RENAMES = {
    "半成品入库": "Semi Finished Goods Receipt",
}


def execute():
    rename_legacy_stock_entry_types()

    for stock_entry_type in RECEIPT_STOCK_ENTRY_TYPES:
        ensure_receipt_stock_entry_type(stock_entry_type)

    frappe.clear_cache(doctype="Stock Entry Type")
    frappe.clear_cache(doctype="Stock Entry")


def rename_legacy_stock_entry_types():
    for old_name, new_name in LEGACY_STOCK_ENTRY_TYPE_RENAMES.items():
        if not frappe.db.exists("Stock Entry Type", old_name):
            continue

        frappe.rename_doc(
            "Stock Entry Type",
            old_name,
            new_name,
            force=True,
            merge=bool(frappe.db.exists("Stock Entry Type", new_name)),
            ignore_permissions=True,
            show_alert=False,
            rebuild_search=False,
        )


def ensure_receipt_stock_entry_type(name):
    if frappe.db.exists("Stock Entry Type", name):
        stock_entry_type = frappe.get_doc("Stock Entry Type", name)
        if stock_entry_type.purpose != BASE_PURPOSE:
            stock_entry_type.purpose = BASE_PURPOSE
            stock_entry_type.save(ignore_permissions=True)
        return

    frappe.get_doc(
        {
            "doctype": "Stock Entry Type",
            "name": name,
            "purpose": BASE_PURPOSE,
        }
    ).insert(ignore_permissions=True)
