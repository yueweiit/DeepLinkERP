import json

from requests.exceptions import RequestException

import frappe
from frappe.utils import flt, get_request_session, getdate, now

from erpnext.stock.doctype.item.item import get_item_defaults

from mes_integration.mes_integration.settings import is_mes_integration_enabled, throw_mes_integration_disabled
from mes_integration.mes_integration.integration_log import (
    create_mes_log,
    is_mes_api_user,
    update_mes_log,
)


@frappe.whitelist()
def push_to_mes(stock_entry_name):
    """
    将已提交的 Stock Entry 发料结果回写到 MES。
    """
    stock_entry = frappe.get_doc("Stock Entry", stock_entry_name)
    if not is_mes_integration_enabled(stock_entry.get("company")):
        throw_mes_integration_disabled(stock_entry.get("company"))

    if stock_entry.docstatus != 1:
        frappe.throw(frappe._("库存移动单必须已提交才能推送到 MES"))

    if not is_dlm_issue_stock_entry(stock_entry):
        frappe.throw(frappe._("只有其他出库、工单发料、注塑发料可以推送至 DLM"))

    if stock_entry.get("custom_mes_status") == "Pushed":
        message = frappe._("此库存移动单已推送至 MES，无需重复推送")
        create_mes_log(
            direction="Outbound",
            event="Stock Entry Issue Confirm",
            status="Failed",
            reference_doctype="Stock Entry",
            reference_name=stock_entry.name,
            source="ERPNext",
            request_url=get_dlm_material_issue_callback_url(),
            error_message=message,
            batch_no=stock_entry.get("custom_stock_entry_no"),
        )
        frappe.db.commit()
        frappe.throw(message)

    payload = build_issue_confirm_payload(stock_entry)
    request_url = get_dlm_material_issue_callback_url()
    mes_log = create_mes_log(
        direction="Outbound",
        event="Stock Entry Issue Confirm",
        status="Pending",
        reference_doctype="Stock Entry",
        reference_name=stock_entry.name,
        source="ERPNext",
        request_url=request_url,
        request_payload=payload,
        batch_no=stock_entry.get("custom_stock_entry_no"),
    )

    frappe.logger().info(f"推送库存移动单 {stock_entry_name} 到 DLM: {frappe.as_json(payload)}")

    try:
        response = post_issue_confirm(payload, request_url)
        validate_issue_confirm_response(response, payload)
        stock_entry.db_set("custom_mes_status", "Pushed")

        update_mes_log(
            mes_log,
            status="Success",
            response_payload=response,
            trace_id=response.get("traceId"),
            processed=get_dlm_processed_count(response),
        )
    except Exception:
        update_mes_log(
            mes_log,
            status="Failed",
            error_message=frappe.get_traceback(),
        )
        frappe.db.commit()
        raise

    return {
        "status": "success",
        "message": f"库存移动单 {stock_entry_name} 已成功推送到 DLM",
        "mes_status": "Pushed",
        "processed": get_dlm_processed_count(response),
        "trace_id": response.get("traceId"),
        "timestamp": now(),
    }


def build_issue_confirm_payload(stock_entry):
    validate_stock_entry_for_issue_confirm(stock_entry)

    posting_date = getdate(stock_entry.posting_date).isoformat() if stock_entry.posting_date else None
    material_request = get_issue_material_request(stock_entry)
    items_by_code = {}
    missing_fields = []

    for row in stock_entry.get("items", []):
        issued_qty = flt(row.get("transfer_qty") or row.get("qty"))

        if issued_qty <= 0:
            continue

        if not row.get("item_code"):
            missing_fields.append(f"第 {row.idx} 行缺少: item_code")
            continue

        item = items_by_code.setdefault(
            row.get("item_code"),
            {
                "item_code": row.get("item_code"),
                "total_issued_qty": 0,
            },
        )
        item["total_issued_qty"] = flt(item["total_issued_qty"]) + issued_qty

    if missing_fields:
        frappe.throw("<br>".join(missing_fields), title=frappe._("DLM 发料回调字段不完整"))

    items = list(items_by_code.values())
    if not items:
        frappe.throw(frappe._("没有可推送到 DLM 的发料明细"))

    return {
        "material_request": material_request,
        "stock_entry": stock_entry.name,
        "posting_date": posting_date,
        "items": items,
    }


def get_issue_material_request(stock_entry):
    material_requests = {
        row.get("material_request")
        for row in stock_entry.get("items", [])
        if row.get("material_request") and flt(row.get("transfer_qty") or row.get("qty")) > 0
    }

    if len(material_requests) > 1:
        frappe.throw(
            frappe._("一张物料移动只能回调一个 Material Request，当前包含：{0}").format(
                ", ".join(sorted(material_requests))
            )
        )

    return next(iter(material_requests), None)


def validate_stock_entry_for_issue_confirm(stock_entry):
    if not get_issue_material_request(stock_entry):
        frappe.throw(frappe._("请先关联原生 Material Request，再推送至 DLM"))


def post_issue_confirm(payload, url=None):
    url = url or get_dlm_material_issue_callback_url()
    timeout = flt(frappe.conf.get("mes_request_timeout") or 15)

    try:
        response = get_request_session().post(
            url,
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=timeout,
        )
        response.raise_for_status()
        return response.json()
    except RequestException as exc:
        response = getattr(exc, "response", None)
        log_mes_push_error("DLM 发料回调接口 HTTP 调用失败", payload, response)
        frappe.throw(
            get_mes_http_error_message(response)
            or frappe._("DLM 发料回调接口调用失败：{0}").format(url)
        )
    except ValueError:
        log_mes_push_error("DLM 发料回调接口响应不是 JSON", payload)
        frappe.throw(frappe._("DLM 发料回调接口响应不是 JSON，请查看 Error Log"))


def validate_issue_confirm_response(response, payload):
    if not isinstance(response, dict):
        log_mes_push_error("DLM 发料回调接口响应格式异常", payload, response)
        frappe.throw(frappe._("DLM 发料回调接口响应格式异常"))

    if not is_successful_dlm_response(response):
        log_mes_push_error("DLM 发料回调接口返回失败", payload, response)
        frappe.throw(get_mes_error_message(response) or frappe._("DLM 发料回调失败"))

    data = response.get("data") or {}
    status = data.get("status")
    valid_statuses = {"processed", "already_issued", "partial"}

    if status and status not in valid_statuses:
        log_mes_push_error("DLM 发料回调业务状态异常", payload, response)
        frappe.throw(
            get_mes_error_message(response)
            or frappe._("DLM 发料回调业务状态异常：{0}").format(status)
        )


def is_successful_dlm_response(response):
    if response.get("code") is not None:
        return str(response.get("code")) == "0"

    return bool(response.get("success"))


def get_dlm_processed_count(response):
    data = response.get("data") or {}
    if "lines_updated" in data:
        return data.get("lines_updated")

    return data.get("processed")


def get_dlm_material_issue_callback_url():
    url = frappe.conf.get("dlm_material_issue_callback_url")
    if not url:
        frappe.throw(frappe._("缺少 DLM 接口配置：dlm_material_issue_callback_url"))
    return url


def get_mes_error_message(response):
    messages = []

    if response.get("message"):
        messages.append(response.get("message"))

    for error in response.get("errors") or []:
        if isinstance(error, dict):
            messages.append(error.get("message") or error.get("error") or frappe.as_json(error))
        else:
            messages.append(str(error))

    for error in (response.get("data") or {}).get("errors") or []:
        if isinstance(error, dict):
            messages.append(error.get("error") or error.get("message") or frappe.as_json(error))
        else:
            messages.append(str(error))

    return "<br>".join(filter(None, messages))


def log_mes_push_error(title, payload, response=None):
    message = {
        "payload": payload,
        "response": get_response_for_log(response),
        "traceback": frappe.get_traceback(),
    }
    frappe.log_error(title=title, message=frappe.as_json(message))


def get_response_for_log(response):
    if response is None:
        return None

    if isinstance(response, dict):
        return response

    response_data = {
        "status_code": response.status_code,
        "text": response.text,
    }

    try:
        response_data["json"] = response.json()
    except ValueError:
        pass

    return response_data


def get_mes_http_error_message(response):
    if response is None:
        return None

    try:
        data = response.json()
    except ValueError:
        data = {}

    message = data.get("message") or response.text
    error_code = data.get("errorCode")
    trace_id = data.get("traceId")

    parts = [frappe._("MES HTTP 状态码: {0}").format(response.status_code)]

    if error_code:
        parts.append(frappe._("错误码: {0}").format(error_code))

    if message:
        parts.append(frappe._("错误信息: {0}").format(message))

    if trace_id:
        parts.append(frappe._("Trace ID: {0}").format(trace_id))

    return "<br>".join(parts)


def is_dlm_issue_stock_entry(stock_entry):
    return stock_entry.get("stock_entry_type") in DLM_ISSUE_STOCK_ENTRY_TYPES


@frappe.whitelist()
def reset_mes_status(stock_entry_name):
    """
    重置库存转移单的 MES Status 为 Unpushed（当已推送的订单被修改时）
    """
    stock_entry = frappe.get_doc("Stock Entry", stock_entry_name)
    if not is_mes_integration_enabled(stock_entry.get("company")):
        throw_mes_integration_disabled(stock_entry.get("company"))

    if stock_entry.get("custom_mes_status") == "Pushed":
        stock_entry.db_set("custom_mes_status", "Unpushed")
        frappe.logger().info(f"库存转移单 {stock_entry_name} 已修改，MES 状态重置为 Unpushed")

        return {
            "status": "success",
            "message": f"库存转移单 {stock_entry_name} 的 MES 状态已重置为未推送",
            "mes_status": "Unpushed"
        }

    return {
        "status": "skipped",
        "message": "无需重置"
    }

SEMI_FINISHED_GOODS_RECEIPT = "Semi Finished Goods Receipt"
FINISHED_GOODS_RECEIPT = "Finished Goods Receipt"
MES_RECEIPT_STOCK_ENTRY_TYPES = {
    SEMI_FINISHED_GOODS_RECEIPT,
    FINISHED_GOODS_RECEIPT,
}
MES_RECEIPT_FALLBACK_TARGET_WAREHOUSE = "半成品 - YC"
DLM_ISSUE_STOCK_ENTRY_TYPES = {
    "Material Issue",
    "Material Transfer for Manufacture",
    "Injection Molding Issuance",
}


@frappe.whitelist()
def create_draft_stock_entry_from_mes(data=None, stock_entry=None):
    """
    Create a draft Stock Entry from MES.

    Accepted payloads:
    1. data={"sales_order": "SAL-ORD-...", "stock_entry": {...}}
    2. data={...} with sales_order inside the Stock Entry payload
    """
    payload = parse_json_if_needed(data if data is not None else stock_entry)

    if not isinstance(payload, dict):
        frappe.throw(frappe._("缺少请求数据或数据格式不正确"))

    validate_mes_api_user()
    validate_mes_stock_entry_permissions()

    if payload.get("stock_entry"):
        stock_entry_data = parse_json_if_needed(payload.get("stock_entry"))
    else:
        stock_entry_data = payload

    if not isinstance(stock_entry_data, dict):
        frappe.throw(frappe._("缺少 Stock Entry 数据或数据格式不正确"))

    stock_entry_data = stock_entry_data.copy()
    sales_order_doc = get_sales_order_by_name(payload, stock_entry_data, required=False)

    stock_entry_type = stock_entry_data.get("stock_entry_type")
    validate_mes_receipt_stock_entry_type(stock_entry_type)

    stock_entry_data.pop("sales_order", None)
    stock_entry_data.pop("sales_order_name", None)
    if not stock_entry_data.get("company") and sales_order_doc:
        stock_entry_data["company"] = sales_order_doc.company
    if not is_mes_integration_enabled(stock_entry_data.get("company")):
        throw_mes_integration_disabled(stock_entry_data.get("company"))

    stock_entry_data["doctype"] = "Stock Entry"
    stock_entry_data["stock_entry_type"] = stock_entry_type
    stock_entry_data["purpose"] = "Material Receipt"
    set_mes_stock_entry_default_target_warehouses(stock_entry_data)

    stock_entry_doc = frappe.get_doc(stock_entry_data)
    set_mes_stock_entry_item_defaults(stock_entry_doc)
    validate_mes_stock_entry_data(stock_entry_doc, sales_order_doc)
    prepare_mes_stock_entry_for_submit(stock_entry_doc)
    set_allow_zero_valuation_rate_for_mes_items_without_cost(stock_entry_doc)
    stock_entry_doc.insert()
    stock_entry_doc.db_set("stock_entry_type", stock_entry_type, update_modified=False)
    stock_entry_doc.reload()

    return {
        "status": "success",
        "message": frappe._("物料移动草稿已创建，可在 ERP 审核后直接提交。"),
        "stock_entry": stock_entry_doc.name,
        "stock_entry_type": stock_entry_doc.stock_entry_type,
        "stock_entry_docstatus": stock_entry_doc.docstatus,
        "sales_order": sales_order_doc.name if sales_order_doc else None,
        "stock_entry_url": frappe.utils.get_url_to_form("Stock Entry", stock_entry_doc.name),
        "timestamp": now(),
    }


@frappe.whitelist()
def create_and_submit_stock_entry_from_mes(data=None, stock_entry=None):
    return create_draft_stock_entry_from_mes(data=data, stock_entry=stock_entry)


def get_sales_order_by_name(payload, stock_entry_data, required=True):
    sales_order = (
        payload.get("sales_order")
        or payload.get("sales_order_name")
        or stock_entry_data.get("sales_order")
        or stock_entry_data.get("sales_order_name")
    )

    if not sales_order:
        if required:
            frappe.throw(frappe._("缺少销售订单编号 sales_order"))
        return None

    if not frappe.db.exists("Sales Order", sales_order):
        frappe.throw(frappe._("未找到销售订单 {0}").format(sales_order))

    return frappe.get_doc("Sales Order", sales_order)


def parse_json_if_needed(value):
    if isinstance(value, str):
        try:
            return json.loads(value)
        except ValueError:
            return value
    return value


def validate_mes_api_user():
    if not is_mes_api_user():
        frappe.throw(frappe._("当前用户没有 MES 接口调用权限"), frappe.PermissionError)


def validate_mes_stock_entry_permissions():
    if not frappe.has_permission("Stock Entry", "create"):
        frappe.throw(
            frappe._("当前用户缺少 {0} 的 {1} 权限").format("Stock Entry", "create"),
            frappe.PermissionError,
        )


def validate_mes_receipt_stock_entry_type(stock_entry_type):
    if not stock_entry_type:
        frappe.throw(frappe._("缺少物料移动类型 stock_entry_type"))

    if stock_entry_type not in MES_RECEIPT_STOCK_ENTRY_TYPES:
        frappe.throw(
            frappe._("MES 入库接口仅支持移动类型：{0}").format(
                ", ".join(sorted(MES_RECEIPT_STOCK_ENTRY_TYPES))
            )
        )


def set_mes_stock_entry_default_target_warehouses(stock_entry_data):
    company = stock_entry_data.get("company")
    if not company:
        frappe.throw(frappe._("缺少物料移动公司，无法查询物料默认仓库"))

    missing_items = []

    for index, row in enumerate(stock_entry_data.get("items") or [], start=1):
        if row.get("t_warehouse"):
            continue

        item_code = row.get("item_code")
        if not item_code:
            continue

        if not frappe.db.exists("Item", item_code):
            missing_items.append(frappe._("第 {0} 行物料 {1} 不存在").format(index, item_code))
            continue

        stock_warehouse = get_mes_item_largest_stock_warehouse(item_code, company)
        default_warehouse = (get_item_defaults(item_code, company) or {}).get("default_warehouse")
        row["t_warehouse"] = stock_warehouse or default_warehouse or get_mes_receipt_fallback_target_warehouse()

    if missing_items:
        frappe.throw("<br>".join(missing_items), title=frappe._("物料不存在"))


def get_mes_item_largest_stock_warehouse(item_code, company):
    warehouses = frappe.db.sql(
        """
        SELECT bin.warehouse
        FROM `tabBin` bin
        INNER JOIN `tabWarehouse` warehouse ON warehouse.name = bin.warehouse
        WHERE bin.item_code = %s
            AND IFNULL(bin.actual_qty, 0) > 0
            AND IFNULL(warehouse.is_group, 0) = 0
            AND IFNULL(warehouse.disabled, 0) = 0
            AND (IFNULL(warehouse.company, '') = '' OR warehouse.company = %s)
        ORDER BY bin.actual_qty DESC, bin.warehouse ASC
        LIMIT 1
        """,
        (item_code, company),
        as_dict=True,
    )

    return warehouses[0].warehouse if warehouses else None


def get_mes_receipt_fallback_target_warehouse():
    if not frappe.db.exists("Warehouse", MES_RECEIPT_FALLBACK_TARGET_WAREHOUSE):
        frappe.throw(
            frappe._("缺少半成品入库兜底仓库：{0}").format(MES_RECEIPT_FALLBACK_TARGET_WAREHOUSE),
            title=frappe._("仓库配置错误"),
        )

    return MES_RECEIPT_FALLBACK_TARGET_WAREHOUSE


def set_mes_stock_entry_item_defaults(stock_entry):
    for row in stock_entry.get("items", []):
        if not row.get("item_code"):
            continue

        item = frappe.db.get_value(
            "Item",
            row.get("item_code"),
            ["stock_uom", "item_name", "description"],
            as_dict=True,
        )
        if not item:
            continue

        row.stock_uom = row.get("stock_uom") or item.stock_uom
        row.uom = row.get("uom") or row.stock_uom
        row.item_name = row.get("item_name") or item.item_name
        row.description = row.get("description") or item.description

        if not flt(row.get("conversion_factor")):
            row.conversion_factor = get_mes_item_conversion_factor(
                row.get("item_code"),
                row.get("uom"),
                row.get("stock_uom"),
                row.idx,
            )


def get_mes_item_conversion_factor(item_code, uom, stock_uom, row_idx):
    if not uom or not stock_uom or uom == stock_uom:
        return 1

    conversion_factor = frappe.db.get_value(
        "UOM Conversion Detail",
        {"parent": item_code, "uom": uom},
        "conversion_factor",
    )

    if not conversion_factor:
        frappe.throw(
            frappe._("第 {0} 行缺少单位换算系数，且物料 {1} 没有单位 {2} 的换算设置").format(
                row_idx,
                item_code,
                uom,
            )
        )

    return flt(conversion_factor)


def prepare_mes_stock_entry_for_submit(stock_entry):
    stock_entry.set_transfer_qty()
    stock_entry.set_actual_qty()
    stock_entry.calculate_rate_and_amount(raise_error_if_no_rate=False)


def set_allow_zero_valuation_rate_for_mes_items_without_cost(stock_entry):
    for row in stock_entry.get("items", []):
        if has_mes_stock_entry_item_valuation_cost(row):
            continue

        row.allow_zero_valuation_rate = 1


def has_mes_stock_entry_item_valuation_cost(row):
    return any(
        flt(row.get(fieldname)) > 0
        for fieldname in ("valuation_rate", "basic_rate", "incoming_rate")
    )


def validate_mes_stock_entry_data(stock_entry, sales_order=None):
    if stock_entry.doctype != "Stock Entry":
        frappe.throw(frappe._("只能通过此接口创建 Stock Entry"))

    if stock_entry.docstatus != 0:
        frappe.throw(frappe._("MES 传入的物料移动必须是草稿状态"))

    if not stock_entry.get("purpose"):
        frappe.throw(frappe._("缺少物料移动 Purpose"))

    if not stock_entry.get("company") and sales_order:
        stock_entry.company = sales_order.company

    if not stock_entry.get("company"):
        frappe.throw(frappe._("缺少物料移动公司"))

    if sales_order and stock_entry.company != sales_order.company:
        frappe.throw(frappe._("物料移动公司必须与销售订单公司一致"))

    if not stock_entry.get("items"):
        frappe.throw(frappe._("物料移动至少需要一行明细"))

    for row in stock_entry.get("items"):
        if not row.get("item_code"):
            frappe.throw(frappe._("第 {0} 行缺少物料号").format(row.idx))

        if flt(row.get("qty")) <= 0:
            frappe.throw(frappe._("第 {0} 行数量必须大于 0").format(row.idx))

        if stock_entry.purpose == "Material Receipt" and not row.get("t_warehouse"):
            frappe.throw(frappe._("第 {0} 行缺少目标仓库").format(row.idx))

        if not row.get("s_warehouse") and not row.get("t_warehouse"):
            frappe.throw(frappe._("第 {0} 行至少需要来源仓库或目标仓库").format(row.idx))

def update_material_request_transferred_qty(stock_entry, method=None):
    if not is_mes_integration_enabled(stock_entry.get("company")):
        return

    mr_item_names = {
        row.material_request_item
        for row in stock_entry.get("items", [])
        if is_material_request_issue_row(row)
    }
    if not mr_item_names:
        return

    transferred_qty_by_item = get_submitted_transferred_qty_by_material_request_item(mr_item_names)
    mr_names = set()

    for mr_item_name in mr_item_names:
        transferred_qty = transferred_qty_by_item.get(mr_item_name, 0)
        mr_name = frappe.db.get_value("Material Request Item", mr_item_name, "parent")

        frappe.db.set_value(
            "Material Request Item",
            mr_item_name,
            {
                "custom_transferred_qty": transferred_qty,
                "ordered_qty": transferred_qty,
            },
            update_modified=False,
        )

        if mr_name:
            mr_names.add(mr_name)

    for mr_name in mr_names:
        update_material_request_issue_status(mr_name)


def get_submitted_transferred_qty_by_material_request_item(mr_item_names):
    placeholders = ", ".join(["%s"] * len(mr_item_names))
    rows = frappe.db.sql(
        f"""
        SELECT
            sed.material_request_item,
            SUM(
                CASE
                    WHEN IFNULL(se.is_return, 0) = 1 THEN -IFNULL(sed.transfer_qty, 0)
                    ELSE IFNULL(sed.transfer_qty, 0)
                END
            ) AS transferred_qty
        FROM `tabStock Entry Detail` sed
        INNER JOIN `tabStock Entry` se ON se.name = sed.parent
        WHERE sed.material_request_item IN ({placeholders})
            AND sed.docstatus = 1
            AND se.docstatus = 1
            AND IFNULL(sed.s_warehouse, '') != ''
        GROUP BY sed.material_request_item
        """,
        tuple(mr_item_names),
        as_dict=True,
    )

    return {row.material_request_item: flt(row.transferred_qty) for row in rows}


def is_material_request_issue_row(row):
    return bool(
        row.get("material_request")
        and row.get("material_request_item")
        and row.get("s_warehouse")
    )


def update_material_request_issue_status(mr_name):
    mr = frappe.get_doc("Material Request", mr_name)
    if mr.docstatus != 1 or mr.status in ("Stopped", "Cancelled"):
        return None

    total_qty = 0
    issued_qty = 0

    for row in mr.get("items", []):
        total_qty += flt(row.stock_qty or row.qty)
        issued_qty += flt(row.get("custom_transferred_qty"))

    per_ordered = (issued_qty / total_qty) * 100 if total_qty else 0

    if per_ordered >= 100:
        per_ordered = 100
        status = "Issued"
    elif per_ordered > 0:
        status = "Partially Ordered"
    else:
        status = "Pending"

    frappe.db.set_value(
        "Material Request",
        mr_name,
        {
            "per_ordered": per_ordered,
            "status": status,
        },
        update_modified=False,
    )

    return {
        "issued_qty": flt(issued_qty),
        "total_qty": flt(total_qty),
        "per_ordered": flt(per_ordered),
        "status": status,
    }

