"""Permission-aware Item master data pages for the mobile inventory workspace."""

import frappe
from frappe import _
from frappe.query_builder import Case, Order
from frappe.query_builder.functions import Count
from frappe.utils import cint, strip_html


ITEM_SEARCH_FIELDS = (
    "custom_specifications",
    "custom_mnemonic_code",
    "custom_sku",
    "custom_external_code",
)
ITEM_OPTIONAL_FIELDS = (
    "custom_specifications",
    "custom_mnemonic_code",
    "custom_sku",
    "custom_external_code",
    "custom_item_classification",
    "custom_short_name",
    "custom_item_short_name",
    "custom_mes_issue_uom",
)
ITEM_EDITABLE_CUSTOM_FIELDS = ITEM_OPTIONAL_FIELDS[:-1]


def _item_meta():
    return frappe.get_meta("Item")


def _existing_fields(fieldnames):
    meta = _item_meta()
    return [fieldname for fieldname in fieldnames if meta.has_field(fieldname)]


def _item_row(row):
    result = {
        "name": row.get("name"),
        "item_name": row.get("item_name") or row.get("name"),
        "item_group": row.get("item_group"),
        "stock_uom": row.get("stock_uom"),
        "disabled": bool(row.get("disabled")),
        "is_stock_item": bool(row.get("is_stock_item")),
        "is_purchase_item": bool(row.get("is_purchase_item")),
        "is_sales_item": bool(row.get("is_sales_item")),
        "modified": str(row.get("modified") or ""),
    }
    for fieldname in _existing_fields(ITEM_OPTIONAL_FIELDS):
        result[fieldname] = row.get(fieldname) or ""
    return result


def _item_group_names(item_group):
    if not item_group:
        return []
    group = frappe.get_doc("Item Group", item_group)
    group.check_permission("read")
    if not group.is_group:
        return [group.name]
    rows = frappe.get_list(
        "Item Group",
        filters={"lft": [">=", group.lft], "rgt": ["<=", group.rgt]},
        fields=["name"],
        order_by="lft asc",
        limit=0,
    )
    return [row.name for row in rows]


@frappe.whitelist()
def get_mobile_item_list(search=None, status="enabled", stock_kind="all", item_group=None, limit=20, offset=0):
    if not frappe.has_permission("Item", "read"):
        frappe.throw(_("当前账号没有物料读取权限"), frappe.PermissionError)

    search = (search or "").strip()
    status = status if status in {"all", "enabled", "disabled"} else "enabled"
    stock_kind = stock_kind if stock_kind in {"all", "stock", "non_stock"} else "all"
    item_group = (item_group or "").strip()
    limit = max(1, min(cint(limit) or 20, 100))
    offset = max(cint(offset), 0)

    item = frappe.qb.DocType("Item")
    filters = item.name.isnotnull()
    if status == "enabled":
        filters &= item.disabled == 0
    elif status == "disabled":
        filters &= item.disabled == 1
    if stock_kind == "stock":
        filters &= item.is_stock_item == 1
    elif stock_kind == "non_stock":
        filters &= item.is_stock_item == 0
    if item_group:
        groups = _item_group_names(item_group)
        filters &= item.item_group.isin(groups or [item_group])

    rank = None
    if search:
        literal = search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        prefix = f"{literal}%"
        contains = f"%{literal}%"
        matches = item.name.like(contains) | item.item_name.like(contains) | item.description.like(contains)
        for fieldname in _existing_fields(ITEM_SEARCH_FIELDS):
            matches |= item[fieldname].like(contains)
        filters &= matches
        rank = (
            Case()
            .when(item.name == search, 0)
            .when(item.name.like(prefix), 1)
            .when(item.name.like(contains), 2)
            .when(item.item_name.like(prefix), 3)
            .when(item.item_name.like(contains), 4)
            .else_(5)
        )

    total = (
        frappe.qb.get_query(
            item,
            fields=[Count("*").as_("total")],
            filters=filters,
            ignore_permissions=False,
        )
        .run(as_dict=True)[0]
        .total
    )
    fields = [
        "name",
        "item_name",
        "item_group",
        "stock_uom",
        "disabled",
        "is_stock_item",
        "is_purchase_item",
        "is_sales_item",
        "modified",
        *_existing_fields(ITEM_OPTIONAL_FIELDS),
    ]
    query = frappe.qb.get_query(
        item,
        fields=[item[fieldname] for fieldname in fields],
        filters=filters,
        limit=limit,
        offset=offset,
        ignore_permissions=False,
    )
    if rank is not None:
        query = query.orderby(rank, order=Order.asc)
    else:
        query = query.orderby(item.modified, order=Order.desc)
    rows = query.orderby(item.name, order=Order.asc).run(as_dict=True)
    entries = [_item_row(row) for row in rows]
    return {
        "entries": entries,
        "total": cint(total),
        "has_more": offset + len(entries) < total,
        "can_create": bool(frappe.has_permission("Item", "create")),
    }


@frappe.whitelist()
def get_mobile_item_detail(name=None):
    if not name:
        frappe.throw(_("缺少物料编码"))
    doc = frappe.get_doc("Item", name)
    doc.check_permission("read")
    result = _item_row(doc)
    result.update(
        {
            "description": strip_html(doc.description or ""),
            "can_view_inventory": bool(frappe.has_permission("Bin", "read")),
        }
    )
    return result


def _check_create_permission():
    if not frappe.has_permission("Item", "create"):
        frappe.throw(_("当前账号没有创建物料的权限"), frappe.PermissionError)


@frappe.whitelist()
def get_mobile_item_form_options():
    _check_create_permission()
    meta = _item_meta()
    defaults = {}
    for fieldname in ("is_stock_item", "is_purchase_item", "is_sales_item"):
        field = meta.get_field(fieldname)
        defaults[fieldname] = cint(field.default) if field else 1
    return {
        "defaults": defaults,
        "custom_fields": _existing_fields(ITEM_EDITABLE_CUSTOM_FIELDS),
    }


@frappe.whitelist()
def search_mobile_item_references(kind=None, search=None, limit=20):
    _check_create_permission()
    kind = (kind or "").strip()
    search = (search or "").strip()
    limit = max(1, min(cint(limit) or 20, 50))
    if kind not in {"item_group", "uom"}:
        return []
    search_value = f"%{search}%"
    if kind == "item_group":
        rows = frappe.get_list(
            "Item Group",
            filters={"is_group": 0},
            or_filters=[
                ["Item Group", "name", "like", search_value],
                ["Item Group", "parent_item_group", "like", search_value],
            ] if search else None,
            fields=["name", "parent_item_group"],
            order_by="name asc",
            limit=limit,
        )
        return [
            {"value": row.name, "label": row.name, "description": row.parent_item_group or ""}
            for row in rows
        ]
    rows = frappe.get_list(
        "UOM",
        or_filters=[
            ["UOM", "name", "like", search_value],
            ["UOM", "uom_name", "like", search_value],
        ] if search else None,
        fields=["name", "uom_name"],
        order_by="name asc",
        limit=limit,
    )
    return [
        {"value": row.name, "label": row.name, "description": row.uom_name if row.uom_name != row.name else ""}
        for row in rows
    ]


@frappe.whitelist(methods=["POST"])
def create_mobile_item(data=None):
    _check_create_permission()
    data = frappe.parse_json(data or {})
    if not isinstance(data, dict):
        frappe.throw(_("物料数据格式不正确"))

    item_code = (data.get("item_code") or "").strip()
    item_group = (data.get("item_group") or "").strip()
    stock_uom = (data.get("stock_uom") or "").strip()
    if not item_code or not item_group or not stock_uom:
        frappe.throw(_("请填写物料编码并选择物料组和库存单位"))
    if frappe.db.exists("Item", item_code):
        frappe.throw(_("物料编码 {0} 已存在").format(item_code), frappe.DuplicateEntryError)

    group = frappe.get_doc("Item Group", item_group)
    group.check_permission("read")
    if group.is_group:
        frappe.throw(_("请选择末级物料组"))
    uom = frappe.get_doc("UOM", stock_uom)
    uom.check_permission("read")

    doc = frappe.new_doc("Item")
    doc.item_code = item_code
    doc.item_name = (data.get("item_name") or "").strip() or item_code
    doc.item_group = group.name
    doc.stock_uom = uom.name
    doc.description = (data.get("description") or "").strip()
    for fieldname in ("is_stock_item", "is_purchase_item", "is_sales_item"):
        field = doc.meta.get_field(fieldname)
        default = cint(field.default) if field else 1
        doc.set(fieldname, cint(data[fieldname]) if fieldname in data else default)
    for fieldname in _existing_fields(ITEM_EDITABLE_CUSTOM_FIELDS):
        field = doc.meta.get_field(fieldname)
        if field and not field.read_only:
            doc.set(fieldname, (data.get(fieldname) or "").strip())
    doc.insert()
    return {"name": doc.name}
