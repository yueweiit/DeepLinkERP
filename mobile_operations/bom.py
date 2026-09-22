"""Permission-aware BOM views for the mobile production workspace."""

from math import isfinite

import frappe
import frappe.defaults
from frappe import _
from frappe.query_builder import Case, Order
from frappe.query_builder.functions import Count
from frappe.utils import cint, flt, get_datetime, strip_html


def _status(row):
    if cint(row.get("docstatus")) == 2:
        return "cancelled"
    if cint(row.get("docstatus")) == 0:
        return "draft"
    return "active" if row.get("is_active") else "inactive"


def _bom_row(row):
    return {
        "name": row.get("name"),
        "item": row.get("item"),
        "item_name": row.get("item_name"),
        "specification": row.get("custom_bom_specification") or "",
        "quantity": flt(row.get("quantity")),
        "uom": row.get("uom"),
        "company": row.get("company"),
        "status": _status(row),
        "is_default": bool(row.get("is_default")),
        "modified": str(row.get("modified") or "")[:10],
    }


@frappe.whitelist()
def get_mobile_bom_list(search=None, status="active", company=None, limit=20, offset=0):
    if not frappe.has_permission("BOM", "read"):
        frappe.throw(_("当前账号没有 BOM 读取权限"), frappe.PermissionError)

    search = (search or "").strip()
    company = (company or "").strip()
    limit = max(1, min(cint(limit) or 20, 100))
    offset = max(cint(offset), 0)
    bom = frappe.qb.DocType("BOM")
    states = {
        "all": bom.docstatus >= 0,
        "active": (bom.docstatus == 1) & (bom.is_active == 1),
        "default": (bom.docstatus == 1) & (bom.is_active == 1) & (bom.is_default == 1),
        "draft": bom.docstatus == 0,
        "inactive": (bom.docstatus == 1) & (bom.is_active == 0),
        "cancelled": bom.docstatus == 2,
    }
    filters = states.get(status, states["active"])
    if company:
        filters &= bom.company == company
    fields = [
        "name",
        "item",
        "item_name",
        "quantity",
        "uom",
        "company",
        "docstatus",
        "is_active",
        "is_default",
        "modified",
    ]
    if frappe.get_meta("BOM").has_field("custom_bom_specification"):
        fields.append("custom_bom_specification")
    if search:
        literal = search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        contains = f"%{literal}%"
        matches = bom.name.like(contains) | bom.item.like(contains) | bom.item_name.like(contains)
        if "custom_bom_specification" in fields:
            matches |= bom.custom_bom_specification.like(contains)
        filters &= matches

    total = (
        frappe.qb.get_query(bom, fields=[Count("*").as_("total")], filters=filters, ignore_permissions=False)
        .run(as_dict=True)[0]
        .total
    )
    query = frappe.qb.get_query(
        bom,
        fields=[bom[field] for field in fields],
        filters=filters,
        limit=limit,
        offset=offset,
        ignore_permissions=False,
    )
    if search:
        query = query.orderby(
            Case()
            .when((bom.item == search) | (bom.name == search), 0)
            .when(bom.item.like(f"{literal}%"), 1)
            .else_(2),
            order=Order.asc,
        )
    rows = (
        query.orderby(bom.is_default, order=Order.desc)
        .orderby(bom.modified, order=Order.desc)
        .orderby(bom.name, order=Order.asc)
        .run(as_dict=True)
    )
    entries = [_bom_row(row) for row in rows]
    # Child rows are restricted to the already permission-filtered BOM page.
    counts = (
        frappe.get_all(
            "BOM Item",
            filters={"parenttype": "BOM", "parent": ["in", [r.name for r in rows]]},
            fields=["parent", {"COUNT": "name", "as": "item_count"}],
            group_by="parent",
            limit_page_length=0,
        )
        if rows
        else []
    )
    counts = {row.parent: row.item_count for row in counts}
    for row in entries:
        row["item_count"] = counts.get(row["name"], 0)

    companies = frappe.get_list(
        "BOM", fields=["company"], distinct=True, order_by="company asc", limit_page_length=0
    )
    return {
        "entries": entries,
        "total": cint(total),
        "has_more": offset + len(entries) < total,
        "companies": [r.company for r in companies if r.company],
        "can_create": bool(frappe.has_permission("BOM", "create")),
    }


@frappe.whitelist()
def get_mobile_bom_detail(name=None):
    if not name:
        frappe.throw(_("缺少 BOM 编号"))
    doc = frappe.get_doc("BOM", name)
    doc.check_permission("read")
    result = _bom_row(doc)
    result.update(
        {
            "modified": str(doc.modified),
            "can_edit": doc.docstatus == 0 and frappe.has_permission("BOM", "write", doc=doc),
            "can_submit": doc.docstatus == 0 and frappe.has_permission("BOM", "submit", doc=doc),
        }
    )
    result["description"] = strip_html(doc.description or "")
    result["items"] = [_component(row) for row in doc.get("items", [])]
    result["exploded_items"] = [_component(row, exploded=True) for row in doc.get("exploded_items", [])]
    result["operations"] = [
        {
            "operation": row.operation,
            "workstation": row.workstation or row.get("workstation_type"),
            "time_in_mins": flt(row.time_in_mins),
            "description": strip_html(row.description or ""),
        }
        for row in doc.get("operations", [])
    ]
    result["secondary_items"] = [
        {
            "item_code": row.item_code,
            "item_name": row.item_name,
            "qty": flt(row.qty),
            "uom": row.uom or row.stock_uom,
        }
        for row in doc.get("secondary_items", [])
    ]
    return result


def _component(row, exploded=False):
    return {
        "name": row.name,
        "item_code": row.item_code,
        "item_name": row.item_name,
        "description": strip_html(row.description or ""),
        "qty": flt(row.stock_qty if exploded else row.qty),
        "uom": row.stock_uom if exploded else (row.uom or row.stock_uom),
        "stock_qty": flt(row.stock_qty),
        "stock_uom": row.stock_uom,
        "bom_no": row.get("bom_no"),
        "source_warehouse": row.get("source_warehouse"),
        "operation": row.get("operation"),
        "scrap_rate": row.get("custom_scrap_rate") if not exploded else None,
        "do_not_explode": bool(row.get("do_not_explode")),
    }


def _editable_bom(name=None):
    if name:
        doc = frappe.get_doc("BOM", name)
        doc.check_permission("read")
        doc.check_permission("write")
        if doc.docstatus != 0:
            frappe.throw(_("只有草稿 BOM 可以编辑"))
        return doc
    if not frappe.has_permission("BOM", "create"):
        frappe.throw(_("当前账号没有创建 BOM 的权限"), frappe.PermissionError)
    return frappe.new_doc("BOM")


@frappe.whitelist()
def get_mobile_bom_form_options(name=None):
    doc = _editable_bom(name)
    specification = frappe.get_meta("BOM").get_field("custom_bom_specification")
    companies = frappe.get_list("Company", fields=["name"], order_by="name asc", limit_page_length=0)
    default_company = frappe.defaults.get_user_default("Company")
    return {
        "companies": companies,
        "default_company": default_company
        if default_company in [r.name for r in companies]
        else (companies[0].name if companies else ""),
        "has_specification": frappe.get_meta("BOM").has_field("custom_bom_specification"),
        "specification_read_only": bool(
            specification
            and (specification.read_only or (specification.fetch_from and not specification.fetch_if_empty))
        ),
        "has_scrap_rate": frappe.get_meta("BOM Item").has_field("custom_scrap_rate"),
        "can_submit": bool(frappe.has_permission("BOM", "submit", doc=doc)),
        "detail": get_mobile_bom_detail(name) if name else None,
    }


@frappe.whitelist()
def search_mobile_bom_items(search=None, name=None, limit=15):
    from mobile_operations.api import _search_mobile_items

    _editable_bom(name)
    items = _search_mobile_items(search, limit)
    specification = frappe.get_meta("BOM").get_field("custom_bom_specification")
    if items and specification and (specification.fetch_from or "").startswith("item."):
        field = specification.fetch_from.split(".", 1)[1]
        values = frappe.get_list(
            "Item",
            filters={"name": ["in", [row.name for row in items]]},
            fields=["name", field],
            limit_page_length=0,
        )
        values = {row.name: row.get(field) for row in values}
        for row in items:
            row["specification"] = values.get(row.name) or ""
    return items


def _positive_quantity(value):
    quantity = flt(value)
    if not isfinite(quantity) or quantity <= 0:
        frappe.throw(_("成品数量和组件用量必须大于零"))
    return quantity


@frappe.whitelist(methods=["POST"])
def save_mobile_bom(data=None, submit=0):
    data = frappe.parse_json(data or {})
    if not isinstance(data, dict):
        frappe.throw(_("BOM 数据格式不正确"))
    doc = _editable_bom(data.get("name"))
    if cint(submit):
        doc.check_permission("submit")
    if not doc.is_new() and (
        not data.get("modified") or get_datetime(data["modified"]) != get_datetime(doc.modified)
    ):
        frappe.throw(_("BOM 已被修改，请刷新后重新编辑"), frappe.TimestampMismatchError)

    company = (data.get("company") or "").strip()
    item_code = (data.get("item") or "").strip()
    if not company or not item_code:
        frappe.throw(_("请选择公司和成品物料"))
    company_doc = frappe.get_doc("Company", company)
    company_doc.check_permission("read")
    item = frappe.get_doc("Item", item_code)
    item.check_permission("read")
    if item.disabled:
        frappe.throw(_("物料 {0} 已停用").format(item_code))
    if doc.is_new() or doc.company != company:
        doc.currency = company_doc.default_currency
        doc.conversion_rate = 1
    doc.company = company
    doc.item = item_code
    doc.quantity = _positive_quantity(data.get("quantity"))
    if doc.is_new():
        doc.is_active = 1
        doc.is_default = 0
    if doc.meta.has_field("custom_bom_specification"):
        doc.custom_bom_specification = (data.get("specification") or "").strip()

    items = data.get("items")
    if not isinstance(items, list) or not items:
        frappe.throw(_("请至少添加一项组件"))
    existing = {row.name: row for row in doc.items}
    updated = []
    seen = set()
    for row_data in items:
        if not isinstance(row_data, dict) or not row_data.get("item_code"):
            frappe.throw(_("请选择有效的组件物料"))
        row_name = row_data.get("name")
        if row_name:
            if row_name not in existing or row_name in seen:
                frappe.throw(_("BOM 组件行无效，请刷新后重试"))
            seen.add(row_name)
            row = existing[row_name]
            if row.item_code != row_data["item_code"]:
                frappe.throw(_("BOM 组件行无效，请刷新后重试"))
        else:
            component = frappe.get_doc("Item", row_data["item_code"])
            component.check_permission("read")
            if component.disabled:
                frappe.throw(_("物料 {0} 已停用").format(component.name))
            row = doc.append(
                "items",
                {
                    "item_code": component.name,
                    "uom": component.stock_uom,
                    "stock_uom": component.stock_uom,
                    "conversion_factor": 1,
                },
            )
        row.qty = _positive_quantity(row_data.get("qty"))
        # Keep existing units, conversion factors, sub-BOMs and operation assignments.
        row.stock_qty = row.qty * (flt(row.conversion_factor) or 1)
        if row.meta.has_field("custom_scrap_rate"):
            scrap = flt(row_data.get("scrap_rate"))
            if not isfinite(scrap) or scrap < 0 or scrap > 100:
                frappe.throw(_("损耗率必须在 0 到 100 之间"))
            row.custom_scrap_rate = scrap
        updated.append(row)
    doc.set("items", updated)
    doc.save()
    if cint(submit):
        doc.submit()
    return {"name": doc.name, "docstatus": doc.docstatus}


@frappe.whitelist(methods=["POST"])
def submit_mobile_bom(name=None, modified=None):
    if not name:
        frappe.throw(_("缺少 BOM 编号"))
    doc = frappe.get_doc("BOM", name)
    doc.check_permission("read")
    doc.check_permission("submit")
    if doc.docstatus != 0:
        frappe.throw(_("只有草稿 BOM 可以提交"))
    if not modified or get_datetime(modified) != get_datetime(doc.modified):
        frappe.throw(_("BOM 已被修改，请刷新后重新编辑"), frappe.TimestampMismatchError)
    doc.submit()
    return {"name": doc.name, "docstatus": doc.docstatus}
