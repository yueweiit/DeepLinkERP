"""Scoped idempotent metadata only; no source import or business migration."""
def after_migrate():
    import frappe
    if not frappe.db.exists("DocType","OA Purchase Request"):
        return
    from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
    definitions={"Purchase Order":[
        {"fieldname":"custom_oa_purchase_expense","label":"钉钉采购申请","fieldtype":"Link","options":"OA Purchase Request","read_only":1,"no_copy":1,"allow_on_submit":1},
    ],"OA Purchase Request":[
        {"fieldname":"custom_purchase_source_id","label":"采购来源身份","fieldtype":"Data","unique":1,"hidden":1,"read_only":1,"no_copy":1},
        {"fieldname":"custom_purchase_source_json","label":"采购原始来源证据","fieldtype":"Long Text","hidden":1,"read_only":1,"no_copy":1,"permlevel":9},
        {"fieldname":"custom_cashier_payment_evidence","label":"出纳历史付款证据","fieldtype":"Long Text","hidden":1,"read_only":1,"no_copy":1,"permlevel":9},
        {"fieldname":"custom_purchase_bound_version","label":"已核对采购来源版本","fieldtype":"Data","hidden":1,"read_only":1,"no_copy":1},
        {"fieldname":"custom_purchase_payment_reconciliation","label":"已核对历史付款","fieldtype":"Long Text","hidden":1,"read_only":1,"no_copy":1,"permlevel":9},
        {"fieldname":"custom_purchase_beneficiary_company","label":"最终使用/销售公司","fieldtype":"Link","options":"Company","read_only":1,"no_copy":1},
        {"fieldname":"custom_purchase_company_proposal","label":"建议采购公司","fieldtype":"Link","options":"Company","read_only":1,"no_copy":1},
        {"fieldname":"custom_purchase_project","label":"已确认采购项目","fieldtype":"Link","options":"Project","read_only":1,"no_copy":1},
        {"fieldname":"custom_purchase_company_confirmed","label":"采购公司已确认","fieldtype":"Check","hidden":1,"read_only":1,"no_copy":1},
        {"fieldname":"custom_purchase_company_confirmed_by","label":"采购公司确认人","fieldtype":"Link","options":"User","hidden":1,"read_only":1,"no_copy":1},
        {"fieldname":"custom_purchase_company_confirmed_on","label":"采购公司确认时间","fieldtype":"Datetime","hidden":1,"read_only":1,"no_copy":1},
        {"fieldname":"custom_purchase_pending_reason","label":"钉钉待完善原因","fieldtype":"Small Text","read_only":1,"no_copy":1},
    ]}
    # The installed OA integration already uses a Data field on Purchase Order.
    # Preserve that field, its values and effective native behavior verbatim.
    for doctype, fields in definitions.items():
        meta=frappe.get_meta(doctype)
        missing=[field for field in fields if not meta.has_field(field["fieldname"])]
        if missing: create_custom_fields({doctype:missing})
    # Older installed OA app versions lack these fields. Do not overwrite existing
    # native DocFields or broaden any role/field permission configuration.
    meta=frappe.get_meta("OA Purchase Request")
    required=[
        {"fieldname":"target_company","label":"目标公司","fieldtype":"Link","options":"Company"},
        {"fieldname":"source_pending","label":"来源审批中","fieldtype":"Check","read_only":1},
        {"fieldname":"source_invalid","label":"来源失效","fieldtype":"Check","read_only":1},
        {"fieldname":"source_stale","label":"来源已变化","fieldtype":"Check","read_only":1},
        {"fieldname":"backfill_imported","label":"来源缓存","fieldtype":"Check","hidden":1,"read_only":1},
    ]
    missing=[f for f in required if not meta.has_field(f["fieldname"])]
    if missing: create_custom_fields({"OA Purchase Request":missing})
