import json

import frappe
from frappe import _
from frappe.utils import flt, now

from erpnext.selling.doctype.sales_order.sales_order import make_delivery_note
from erpnext.stock.doctype.item.item import get_item_defaults

from crm_integration.crm_integration.sales_order import (
    DELIVERABLE,
    PENDING_FINAL_PAYMENT,
    PENDING_PRODUCTION,
    set_process_status,
)
from mes_integration.mes_integration.integration_log import create_mes_log, update_mes_log
from mes_integration.mes_integration.settings import is_mes_integration_enabled, throw_mes_integration_disabled
from mes_integration.mes_integration.stock_entry import (
    get_mes_item_largest_stock_warehouse,
    get_mes_receipt_fallback_target_warehouse,
    validate_mes_api_user,
)


@frappe.whitelist()
def create_draft_delivery_note_from_mes(data=None):
    payload = parse_json_if_needed(data)

    if not isinstance(payload, dict):
        frappe.throw(_("缺少请求数据或数据格式不正确"))

    sales_order_name = payload.get("sales_order")
    company = frappe.db.get_value("Sales Order", sales_order_name, "company") if sales_order_name else None
    if not is_mes_integration_enabled(company):
        throw_mes_integration_disabled(company)

    validate_mes_api_user()
    validate_mes_delivery_note_permissions()

    mes_log = create_mes_log(
        direction="Inbound",
        event="MES Delivery Note Draft Create",
        status="Pending",
        reference_doctype="Sales Order",
        reference_name=payload.get("sales_order"),
        source="MES",
        request_url=get_request_url(),
        request_payload=payload,
    )

    try:
        delivery_note = create_draft_delivery_note(payload)
    except Exception:
        update_mes_log(
            mes_log,
            status="Failed",
            error_message=frappe.get_traceback(),
        )
        raise

    response = {
        "status": "success",
        "message": _("销售出库草稿已创建"),
        "delivery_note": delivery_note.name,
        "sales_order": payload.get("sales_order"),
        "sales_order_status": frappe.db.get_value(
            "Sales Order", payload.get("sales_order"), "custom_process_status"
        ),
        "delivery_note_url": frappe.utils.get_url_to_form("Delivery Note", delivery_note.name),
        "timestamp": now(),
    }

    update_mes_log(
        mes_log,
        status="Success",
        reference_doctype="Delivery Note",
        reference_name=delivery_note.name,
        response_payload=response,
    )

    return response


def create_draft_delivery_note(payload):
    sales_order_name = payload.get("sales_order")
    if not sales_order_name:
        frappe.throw(_("缺少销售订单编号 sales_order"))

    if not frappe.db.exists("Sales Order", sales_order_name):
        frappe.throw(_("未找到销售订单 {0}").format(sales_order_name))

    sales_order = frappe.get_doc("Sales Order", sales_order_name)
    validate_sales_order_for_mes_delivery_note(sales_order)

    items = payload.get("items")
    if not isinstance(items, list) or not items:
        frappe.throw(_("销售出库明细不能为空"))

    allocations = allocate_delivery_note_items(sales_order, items)

    delivery_note = make_delivery_note(
        sales_order.name,
        kwargs={"skip_item_mapping": True, "for_reserved_stock": False},
    )
    delivery_note.set("items", [])

    for allocation in allocations:
        append_delivery_note_item(delivery_note, allocation)

    delivery_note.run_method("set_missing_values")
    delivery_note.run_method("set_po_nos")
    delivery_note.run_method("calculate_taxes_and_totals")
    delivery_note.run_method("set_use_serial_batch_fields")
    delivery_note.insert()

    if sales_order.get("custom_process_status") == PENDING_PRODUCTION:
        set_process_status(sales_order, PENDING_FINAL_PAYMENT)

    return delivery_note


def validate_sales_order_for_mes_delivery_note(sales_order):
    if sales_order.docstatus != 1:
        frappe.throw(_("销售订单 {0} 必须已提交").format(sales_order.name))

    process_status = sales_order.get("custom_process_status")
    if process_status not in (PENDING_PRODUCTION, PENDING_FINAL_PAYMENT):
        frappe.throw(
            _("销售订单 {0} 状态为 {1}，不允许创建出库草稿").format(
                sales_order.name, process_status or ""
            )
        )


def allocate_delivery_note_items(sales_order, items):
    remaining_by_item = get_sales_order_remaining_qty_by_item(sales_order)
    allocations = []

    for index, request_row in enumerate(items, start=1):
        row = frappe._dict(request_row or {})
        item_code = row.get("item_code")
        qty = flt(row.get("qty"))

        if not item_code:
            frappe.throw(_("第 {0} 行缺少物料编码 item_code").format(index))

        if qty <= 0:
            frappe.throw(_("第 {0} 行出库数量必须大于 0").format(index))

        sales_order_rows = remaining_by_item.get(item_code)
        if not sales_order_rows:
            frappe.throw(_("物料 {0} 不在销售订单 {1} 的明细中").format(item_code, sales_order.name))

        available_qty = sum(flt(so_row.remaining_qty) for so_row in sales_order_rows)
        if qty > available_qty:
            frappe.throw(
                _("物料 {0} 出库数量 {1} 超过剩余可出库数量 {2}").format(
                    item_code, format_float(qty), format_float(available_qty)
                )
            )

        warehouse = get_mes_delivery_note_item_warehouse(
            item_code,
            sales_order.company,
            row.get("warehouse"),
        )

        qty_to_allocate = qty
        for so_row in sales_order_rows:
            if qty_to_allocate <= 0:
                break

            row_remaining_qty = flt(so_row.remaining_qty)
            if row_remaining_qty <= 0:
                continue

            allocated_qty = min(qty_to_allocate, row_remaining_qty)
            allocations.append(
                frappe._dict(
                    sales_order=sales_order,
                    sales_order_item=so_row.doc,
                    qty=allocated_qty,
                    warehouse=warehouse,
                    batch_no=row.get("batch_no"),
                )
            )

            so_row.remaining_qty = row_remaining_qty - allocated_qty
            qty_to_allocate -= allocated_qty

    return allocations


def get_sales_order_remaining_qty_by_item(sales_order):
    draft_qty_by_so_detail = get_draft_delivery_note_qty_by_so_detail(sales_order.name)
    remaining_by_item = {}

    for row in sales_order.get("items", []):
        if not row.get("item_code") or row.get("delivered_by_supplier"):
            continue

        remaining_qty = flt(row.get("qty")) - flt(row.get("delivered_qty")) - flt(
            draft_qty_by_so_detail.get(row.name)
        )
        if remaining_qty <= 0:
            continue

        remaining_by_item.setdefault(row.item_code, []).append(
            frappe._dict(doc=row, remaining_qty=remaining_qty)
        )

    return remaining_by_item


def get_draft_delivery_note_qty_by_so_detail(sales_order):
    rows = frappe.db.sql(
        """
        SELECT dni.so_detail, SUM(IFNULL(dni.qty, 0)) AS qty
        FROM `tabDelivery Note Item` dni
        INNER JOIN `tabDelivery Note` dn ON dn.name = dni.parent
        WHERE dni.against_sales_order = %s
            AND dn.docstatus = 0
            AND IFNULL(dni.so_detail, '') != ''
        GROUP BY dni.so_detail
        """,
        (sales_order,),
        as_dict=True,
    )
    return {row.so_detail: flt(row.qty) for row in rows}


def format_float(value):
    return frappe.format_value(flt(value), {"fieldtype": "Float"})


def get_mes_delivery_note_item_warehouse(item_code, company, requested_warehouse=None):
    if requested_warehouse:
        validate_warehouse_company(requested_warehouse, company)
        return requested_warehouse

    stock_warehouse = get_mes_item_largest_stock_warehouse(item_code, company)
    if stock_warehouse:
        return stock_warehouse

    default_warehouse = (get_item_defaults(item_code, company) or {}).get("default_warehouse")
    if default_warehouse:
        validate_warehouse_company(default_warehouse, company)
        return default_warehouse

    fallback_warehouse = get_mes_receipt_fallback_target_warehouse()
    validate_warehouse_company(fallback_warehouse, company)
    return fallback_warehouse


def validate_warehouse_company(warehouse, company):
    warehouse_doc = frappe.db.get_value(
        "Warehouse",
        warehouse,
        ["name", "company", "is_group", "disabled"],
        as_dict=True,
    )

    if not warehouse_doc:
        frappe.throw(_("未找到仓库 {0}").format(warehouse))

    if warehouse_doc.is_group or warehouse_doc.disabled:
        frappe.throw(_("仓库 {0} 不可用于出库").format(warehouse))

    if warehouse_doc.company and warehouse_doc.company != company:
        frappe.throw(_("仓库 {0} 不属于公司 {1}").format(warehouse, company))


def append_delivery_note_item(delivery_note, allocation):
    sales_order_item = allocation.sales_order_item
    qty = flt(allocation.qty)
    conversion_factor = flt(sales_order_item.get("conversion_factor")) or 1
    rate = flt(sales_order_item.get("rate"))
    base_rate = flt(sales_order_item.get("base_rate"))

    if not allocation.warehouse:
        frappe.throw(_("物料 {0} 缺少出库仓库").format(sales_order_item.item_code))

    row = delivery_note.append(
        "items",
        {
            "item_code": sales_order_item.item_code,
            "item_name": sales_order_item.item_name,
            "description": sales_order_item.description,
            "qty": qty,
            "stock_qty": qty * conversion_factor,
            "uom": sales_order_item.uom,
            "stock_uom": sales_order_item.stock_uom,
            "conversion_factor": conversion_factor,
            "warehouse": allocation.warehouse,
            "rate": rate,
            "base_rate": base_rate,
            "amount": qty * rate,
            "base_amount": qty * base_rate,
            "against_sales_order": allocation.sales_order.name,
            "so_detail": sales_order_item.name,
            "delivery_date": sales_order_item.get("delivery_date") or allocation.sales_order.get("delivery_date"),
        },
    )

    if allocation.batch_no and frappe.db.get_value("Item", sales_order_item.item_code, "has_batch_no"):
        row.batch_no = allocation.batch_no




PENDING_RELEASE = "Pending Release"
READY_TO_DELIVER = "Ready to Deliver"
DELIVERED = "Delivered"


def set_delivery_readiness_status(doc, method=None):
    if not is_mes_integration_enabled(doc.get("company")):
        return

    doc.custom_delivery_readiness_status = get_delivery_readiness_status(doc)


def validate_delivery_note_ready_to_deliver(doc, method=None):
    if not is_mes_integration_enabled(doc.get("company")):
        return

    set_delivery_readiness_status(doc, method)
    if (
        doc.custom_delivery_readiness_status
        and doc.custom_delivery_readiness_status != READY_TO_DELIVER
    ):
        frappe.throw(_("销售出库关联的销售订单尚未全部放行发货，不能提交。"))


def set_delivered_readiness_status(doc, method=None):
    if not is_mes_integration_enabled(doc.get("company")):
        return

    status = get_delivery_readiness_status(doc)
    if frappe.db.has_column("Delivery Note", "custom_delivery_readiness_status"):
        doc.db_set("custom_delivery_readiness_status", status, update_modified=False)


def clear_delivery_readiness_status(doc, method=None):
    if not is_mes_integration_enabled(doc.get("company")):
        return

    if frappe.db.has_column("Delivery Note", "custom_delivery_readiness_status"):
        doc.db_set("custom_delivery_readiness_status", None, update_modified=False)


def get_delivery_readiness_status(doc):
    statuses = get_linked_sales_order_process_statuses(doc)
    if not statuses:
        return None

    if doc.docstatus == 1:
        return DELIVERED

    if doc.docstatus != 0:
        return None

    if all(status == DELIVERABLE for status in statuses):
        return READY_TO_DELIVER

    return PENDING_RELEASE


def get_linked_sales_order_process_statuses(doc):
    sales_orders = sorted(
        {
            row.get("against_sales_order")
            for row in doc.get("items", [])
            if row.get("against_sales_order")
        }
    )
    if not sales_orders:
        return []

    rows = frappe.get_all(
        "Sales Order",
        filters={"name": ["in", sales_orders]},
        pluck="custom_process_status",
    )
    return [status for status in rows if status]


def update_delivery_readiness_status_for_sales_orders(sales_orders):
    if isinstance(sales_orders, str):
        sales_orders = [sales_orders]

    sales_orders = [name for name in sales_orders if name]
    if not sales_orders or not frappe.db.has_column("Delivery Note", "custom_delivery_readiness_status"):
        return

    delivery_notes = get_draft_delivery_notes_for_sales_orders(sales_orders)
    for delivery_note_name in delivery_notes:
        delivery_note = frappe.get_doc("Delivery Note", delivery_note_name)
        if not is_mes_integration_enabled(delivery_note.get("company")):
            continue

        status = get_delivery_readiness_status(delivery_note)
        if delivery_note.get("custom_delivery_readiness_status") != status:
            delivery_note.db_set("custom_delivery_readiness_status", status, update_modified=False)


def get_draft_delivery_notes_for_sales_orders(sales_orders):
    placeholders = ", ".join(["%s"] * len(sales_orders))
    rows = frappe.db.sql(
        f"""
        SELECT DISTINCT dn.name
        FROM `tabDelivery Note` dn
        INNER JOIN `tabDelivery Note Item` dni ON dni.parent = dn.name
        WHERE dn.docstatus = 0
            AND dni.against_sales_order IN ({placeholders})
        """,
        tuple(sales_orders),
        as_dict=True,
    )
    return [row.name for row in rows]

def validate_mes_delivery_note_permissions():
    if not frappe.has_permission("Delivery Note", "create"):
        frappe.throw(
            _("当前用户缺少 {0} 的 {1} 权限").format("Delivery Note", "create"),
            frappe.PermissionError,
        )


def parse_json_if_needed(value):
    if isinstance(value, str):
        try:
            return json.loads(value)
        except ValueError:
            return value
    return value


def get_request_url():
    if not getattr(frappe.local, "request", None):
        return None

    return getattr(frappe.request, "url", None)
