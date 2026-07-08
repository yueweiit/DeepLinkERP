import frappe
from frappe import _
from frappe.utils import now

from mes_integration.mes_integration.integration_log import create_mes_log, update_mes_log
from mes_integration.mes_integration.settings import (
    is_mes_integration_enabled,
    throw_mes_integration_disabled,
)
from mes_integration.mes_integration.stock_entry import (
    get_mes_status_callback_url,
    post_stock_entry_status_to_mes,
    validate_stock_entry_status_response,
)


SALES_ORDER_STATUS_EVENT = "Sales Order Status Callback"
SALES_ORDER_STATUS_DOCUMENT_TYPE = "sales_order"


def enqueue_sales_order_status_callback(
    sales_order_name, triggered_status=None, trigger_event=None
):
    frappe.enqueue(
        "mes_integration.mes_integration.sales_order.push_sales_order_status_to_mes",
        queue="short",
        enqueue_after_commit=True,
        sales_order_name=sales_order_name,
        triggered_status=triggered_status,
        trigger_event=trigger_event,
    )


def push_sales_order_status_to_mes(
    sales_order_name, triggered_status=None, trigger_event=None
):
    sales_order = frappe.get_doc("Sales Order", sales_order_name)
    if not is_mes_integration_enabled(sales_order.get("company")):
        return None

    return push_sales_order_status_doc_to_mes(
        sales_order, triggered_status=triggered_status, trigger_event=trigger_event
    )


def push_sales_order_status_doc_to_mes(
    sales_order, triggered_status=None, trigger_event=None
):
    payload = build_sales_order_status_payload(
        sales_order, triggered_status=triggered_status, trigger_event=trigger_event
    )
    mes_log = create_mes_log(
        direction="Outbound",
        event=SALES_ORDER_STATUS_EVENT,
        status="Pending",
        reference_doctype="Sales Order",
        reference_name=sales_order.name,
        source="DeeplinkERP",
        request_payload=payload,
    )

    try:
        request_url = get_mes_status_callback_url()
        update_mes_log(mes_log, request_url=request_url)

        frappe.logger().info(
            f"回写销售订单 {sales_order.name} 状态到 MES: {frappe.as_json(payload)}"
        )

        response = post_stock_entry_status_to_mes(payload, request_url)
        validate_stock_entry_status_response(response, payload)
    except Exception:
        update_mes_log(
            mes_log,
            status="Failed",
            error_message=frappe.get_traceback(),
        )
        raise

    update_mes_log(
        mes_log,
        status="Success",
        response_payload=response,
        trace_id=response.get("traceId"),
        http_status_code=200,
    )

    return {
        "status": "success",
        "sales_order": sales_order.name,
        "trace_id": response.get("traceId"),
        "timestamp": now(),
    }


@frappe.whitelist()
def retry_push_sales_order_status_to_mes(sales_order_name):
    if not frappe.has_permission("Sales Order", "read"):
        frappe.throw(_("缺少 Sales Order 读取权限"), frappe.PermissionError)

    sales_order = frappe.get_doc("Sales Order", sales_order_name)
    if not is_mes_integration_enabled(sales_order.get("company")):
        throw_mes_integration_disabled(sales_order.get("company"))

    return push_sales_order_status_doc_to_mes(sales_order)


def build_sales_order_status_payload(
    sales_order, triggered_status=None, trigger_event=None
):
    sales_order_status = triggered_status or sales_order.get("custom_process_status")

    payload = {
        "documentType": SALES_ORDER_STATUS_DOCUMENT_TYPE,
        "erpSalesOrderNo": sales_order.name,
        "sales_order": sales_order.name,
        "documentNo": sales_order.name,
        "referenceNo": sales_order.name,
        "docstatus": sales_order.docstatus,
        "salesOrderStatus": sales_order_status,
        "erpSalesOrderStatus": sales_order_status,
        "message": (
            f"ERP Sales Order {sales_order.name} 状态：{sales_order_status or ''}"
        ),
    }

    if trigger_event:
        payload["triggerEvent"] = trigger_event
        payload["trigger_event"] = trigger_event

    return payload
