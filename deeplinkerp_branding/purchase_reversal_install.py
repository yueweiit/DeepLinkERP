"""Narrow additive metadata for a future reversal boundary; no business writes."""

TARGETS = ("Bin", "Purchase Order", "Purchase Receipt", "Purchase Invoice", "Payment Entry", "Repost Item Valuation")
FIELDNAME = "custom_purchase_reversal_operation"
DEFINITION = {"fieldname": FIELDNAME, "label": "采购冲销操作", "fieldtype": "Link",
    "options": "Integration Request", "hidden": 1, "read_only": 1, "no_copy": 1}
_REQUIRED = {"Bin": {"item_code", "warehouse"}, "Purchase Order": {"company", "items"},
    "Purchase Receipt": {"company", "items"}, "Purchase Invoice": {"company", "items"},
    "Payment Entry": {"company", "references"}, "Repost Item Valuation": {"company", "status", "based_on"}}


def after_migrate():
    import frappe
    from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

    # Preflight every target before the first metadata write. Existing native or
    # custom definitions are never overwritten or treated as a different feature.
    for doctype in (*TARGETS, "Integration Request"):
        if not frappe.db.exists("DocType", doctype) or not frappe.db.has_column(doctype, "name"):
            frappe.throw("采购冲销元数据所需原生单据类型缺失", frappe.ValidationError)
    missing = {}
    for doctype in TARGETS:
        meta = frappe.get_meta(doctype)
        if not all(meta.has_field(field) for field in _REQUIRED[doctype]):
            frappe.throw("采购冲销所需原生元数据版本不完整", frappe.ValidationError)
        # Table fields have child tables, not parent SQL columns. All stored
        # native prerequisites and compatible pointers must physically exist.
        if not all(frappe.db.has_column(doctype, field) for field in _REQUIRED[doctype] - {"items", "references"}):
            frappe.throw("采购冲销所需原生数据库列缺失", frappe.ValidationError)
        existing = meta.get_field(FIELDNAME)
        if existing:
            if existing.get("is_virtual") or not frappe.db.has_column(doctype, FIELDNAME) or any(existing.get(key) != DEFINITION[key] for key in
                    ("fieldtype", "options", "hidden", "read_only", "no_copy")):
                frappe.throw("采购冲销操作字段定义冲突，未修改现有定义", frappe.ValidationError)
        else:
            missing[doctype] = [dict(DEFINITION)]
    if missing:
        create_custom_fields(missing)
    for doctype in TARGETS:
        # Frappe's add_index checks the existing index before adding it.
        frappe.db.add_index(doctype, [FIELDNAME], "purchase_reversal_operation")
