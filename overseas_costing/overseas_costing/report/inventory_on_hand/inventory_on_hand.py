"""实际库存与来源追溯报表。"""

from __future__ import annotations

from typing import Any

try:
    import frappe
    from frappe import _
except Exception:  # pragma: no cover - 本地单测环境不安装 Frappe
    frappe = None
    _ = lambda value: value


COUNT_UOM_TOKENS = (
    "个",
    "件",
    "套",
    "卷",
    "包",
    "张",
    "片",
    "支",
    "条",
    "台",
    "pieza",
    "conjunto",
    "rollo",
    "paquete",
    "hoja",
    "ramo",
    "barra",
    "unidad",
)


def execute(filters=None):
    filters = frappe._dict(filters or {})
    rows = get_data(filters)
    return get_columns(), rows


def get_columns() -> list[dict[str, Any]]:
    return [
        {
            "label": _("正式物料编码"),
            "fieldname": "item_code",
            "fieldtype": "Link",
            "options": "Item",
            "width": 145,
        },
        {"label": _("物料名称（双语）"), "fieldname": "item_name", "width": 240},
        {
            "label": _("仓库"),
            "fieldname": "warehouse",
            "fieldtype": "Link",
            "options": "Warehouse",
            "width": 180,
        },
        {"label": _("原始库位"), "fieldname": "original_location", "width": 125},
        {
            "label": _("物料组"),
            "fieldname": "item_group",
            "fieldtype": "Link",
            "options": "Item Group",
            "width": 210,
        },
        {
            "label": _("汇总数量"),
            "fieldname": "actual_qty",
            "fieldtype": "Float",
            "width": 120,
        },
        {
            "label": _("库存单位"),
            "fieldname": "stock_uom",
            "fieldtype": "Link",
            "options": "UOM",
            "width": 110,
        },
        {"label": "DPCI", "fieldname": "dpci", "width": 130},
        {"label": _("外部编码"), "fieldname": "external_code", "width": 155},
        {
            "label": _("原始标识/别名"),
            "fieldname": "original_identifier_alias",
            "width": 220,
        },
    ]


def get_quantity_display(actual_qty: Any, stock_uom: str | None) -> tuple[int, str]:
    value = float(actual_qty or 0)
    normalized_uom = str(stock_uom or "").strip().lower()
    is_count_uom = any(token in normalized_uom for token in COUNT_UOM_TOKENS)
    if not is_count_uom:
        return 2, ""
    if abs(value - round(value)) <= 1e-9:
        return 0, ""
    return 2, "计数单位存在小数库存"


def get_data(filters) -> list[dict[str, Any]]:
    conditions = ["bin.actual_qty != 0"]
    params: dict[str, Any] = {}

    filter_specs = (
        ("company", "warehouse.company = %(company)s", False),
        ("warehouse", "bin.warehouse = %(warehouse)s", False),
        ("original_location", "bin.custom_original_location LIKE %(original_location)s", True),
        ("item_code", "bin.item_code = %(item_code)s", False),
        ("item_group", "item.item_group = %(item_group)s", False),
    )
    for fieldname, condition, use_like in filter_specs:
        value = filters.get(fieldname) if filters else None
        if not value:
            continue
        conditions.append(condition)
        params[fieldname] = f"%{value}%" if use_like else value

    rows = frappe.db.sql(
        f"""
        SELECT
            bin.item_code AS item_code,
            item.item_name AS item_name,
            bin.warehouse AS warehouse,
            COALESCE(bin.custom_original_location, '') AS original_location,
            item.item_group AS item_group,
            bin.actual_qty AS actual_qty,
            item.stock_uom AS stock_uom,
            COALESCE(item.custom_dpci, '') AS dpci,
            COALESCE(item.custom_external_code, '') AS external_code,
            COALESCE(item.custom_original_identifier_alias, '') AS original_identifier_alias
        FROM `tabBin` bin
        INNER JOIN `tabItem` item ON item.name = bin.item_code
        INNER JOIN `tabWarehouse` warehouse ON warehouse.name = bin.warehouse
        WHERE {" AND ".join(conditions)}
        ORDER BY
            bin.warehouse,
            COALESCE(bin.custom_original_location, ''),
            bin.item_code
        """,
        params,
        as_dict=True,
    )
    _decorate_quantity_display(rows)
    return rows


def _decorate_quantity_display(rows: list[dict[str, Any]]) -> None:
    for row in rows:
        precision, warning = get_quantity_display(
            row.get("actual_qty"), row.get("stock_uom")
        )
        row["quantity_precision"] = precision
        row["quantity_warning"] = warning
