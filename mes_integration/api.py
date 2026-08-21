import json

import frappe


BATCH_BIN_FIELDS = [
    "item_code",
    "warehouse",
    "actual_qty",
    "reserved_qty",
    "projected_qty",
    "stock_uom",
]


@frappe.whitelist()
def create_stock_entry(data=None, stock_entry=None):
    """Short public alias for MES to create a draft Stock Entry."""
    from mes_integration.mes_integration.stock_entry import (
        create_draft_stock_entry_from_mes,
    )

    return create_draft_stock_entry_from_mes(data=data, stock_entry=stock_entry)


@frappe.whitelist()
def create_material_request(data=None, material_request=None):
    """Short public alias for MES to create and submit a Material Request."""
    from mes_integration.mes_integration.material_request import (
        create_and_submit_material_request_from_mes,
    )

    return create_and_submit_material_request_from_mes(
        data=data, material_request=material_request
    )


@frappe.whitelist()
def get_batch_bin_rows(item_codes=None):
    """Return Bin rows for multiple item codes using the current user's permissions.

    ``item_codes`` may be a JSON array (POST) or a comma-separated string (GET).
    The response deliberately uses a fixed field set so callers do not need to
    send a long ``fields`` query parameter.
    """
    from mes_integration.mes_integration.stock_entry import validate_mes_api_user

    validate_mes_api_user()

    requested_item_codes = _normalize_item_codes(item_codes)
    if not requested_item_codes:
        frappe.throw(frappe._("缺少有效的 item_codes 参数"))

    if not frappe.has_permission("Bin", "read"):
        frappe.throw(frappe._("当前用户缺少 Bin 的读取权限"), frappe.PermissionError)

    rows = frappe.get_list(
        "Bin",
        filters={"item_code": ["in", requested_item_codes]},
        fields=BATCH_BIN_FIELDS,
        order_by="item_code asc, warehouse asc",
        limit_page_length=0,
    )
    returned_item_codes = {row.get("item_code") for row in rows}

    return {
        "success": True,
        "rows": rows,
        "missing_item_codes": [
            item_code
            for item_code in requested_item_codes
            if item_code not in returned_item_codes
        ],
    }


def _normalize_item_codes(item_codes):
    """Normalize POST arrays and GET comma-separated item code values."""
    if item_codes is None and getattr(frappe.local, "request", None):
        request_json = frappe.request.get_json(silent=True)
        if isinstance(request_json, dict):
            item_codes = request_json.get("item_codes")

    if isinstance(item_codes, str):
        value = item_codes.strip()
        if not value:
            return []

        try:
            parsed_value = json.loads(value)
        except ValueError:
            parsed_value = None

        if isinstance(parsed_value, list):
            item_codes = parsed_value
        else:
            item_codes = value.split(",")

    if not isinstance(item_codes, (list, tuple)):
        return []

    normalized_item_codes = []
    seen_item_codes = set()
    for item_code in item_codes:
        if not isinstance(item_code, str):
            continue

        item_code = item_code.strip()
        if item_code and item_code not in seen_item_codes:
            normalized_item_codes.append(item_code)
            seen_item_codes.add(item_code)

    return normalized_item_codes
