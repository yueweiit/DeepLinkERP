import frappe
from frappe import _
from frappe.model.mapper import get_mapped_doc
from frappe.utils import cint, flt


CUSTOM_ISSUE_MATERIAL_REQUEST_TYPES = (
    "Material Issue",
    "Material Transfer for Manufacture",
    "Injection Molding Issuance",
)


@frappe.whitelist()
def make_stock_entry_from_material_request(source_name, target_doc=None):
    material_request_type = frappe.db.get_value("Material Request", source_name, "material_request_type")

    if material_request_type in CUSTOM_ISSUE_MATERIAL_REQUEST_TYPES:
        return make_issue_stock_entry(source_name, target_doc)

    from erpnext.stock.doctype.material_request.material_request import make_stock_entry

    return make_stock_entry(source_name, target_doc)


@frappe.whitelist()
def make_issue_stock_entry(source_name, target_doc=None):
    def update_item(source, target, source_parent):
        qty = (
            flt(flt(source.stock_qty) - flt(source.ordered_qty)) / target.conversion_factor
            if flt(source.stock_qty) > flt(source.ordered_qty)
            else 0
        )
        stock_entry_purpose = get_stock_entry_purpose(source_parent)
        target.qty = qty
        target.transfer_qty = qty * source.conversion_factor
        target.conversion_factor = source.conversion_factor

        if stock_entry_purpose == "Material Issue":
            target.s_warehouse = source.get("warehouse") or source_parent.get("set_warehouse")
        else:
            target.s_warehouse = source.get("from_warehouse") or source_parent.get("set_from_warehouse")
            target.t_warehouse = source_parent.get("set_warehouse") or source.get("warehouse")

    def set_missing_values(source, target):
        stock_entry_purpose = get_stock_entry_purpose(source)
        target.purpose = stock_entry_purpose
        target.stock_entry_type = get_stock_entry_type(source)
        if stock_entry_purpose == "Material Issue":
            target.from_warehouse = (
                source.get("set_warehouse")
                or get_single_material_request_item_source_warehouse(source)
            )
        else:
            target.from_warehouse = source.get("set_from_warehouse")
            target.to_warehouse = source.get("set_warehouse")
        target.set_transfer_qty()
        target.set_actual_qty()
        target.calculate_rate_and_amount(raise_error_if_no_rate=False)
        target.set_job_card_data()

    return get_mapped_doc(
        "Material Request",
        source_name,
        {
            "Material Request": {
                "doctype": "Stock Entry",
                "validation": {
                    "docstatus": ["=", 1],
                    "material_request_type": ["in", CUSTOM_ISSUE_MATERIAL_REQUEST_TYPES],
                },
            },
            "Material Request Item": {
                "doctype": "Stock Entry Detail",
                "field_map": {
                    "name": "material_request_item",
                    "parent": "material_request",
                    "uom": "stock_uom",
                    "job_card_item": "job_card_item",
                },
                "field_no_map": ["expense_account"],
                "postprocess": update_item,
                "condition": lambda doc: (
                    flt(doc.ordered_qty, doc.precision("ordered_qty"))
                    < flt(doc.stock_qty, doc.precision("ordered_qty"))
                ),
            },
        },
        target_doc,
        set_missing_values,
    )


def get_stock_entry_purpose(material_request):
    if material_request.material_request_type in ("Material Issue", "Injection Molding Issuance"):
        return "Material Issue"

    return "Material Transfer for Manufacture"


def get_stock_entry_type(material_request):
    if material_request.material_request_type == "Injection Molding Issuance":
        return "Injection Molding Issuance"

    return get_stock_entry_purpose(material_request)


def get_single_material_request_item_source_warehouse(material_request):
    warehouses = {
        row.get("from_warehouse") or row.get("warehouse")
        for row in material_request.get("items", [])
        if row.get("from_warehouse") or row.get("warehouse")
    }

    return warehouses.pop() if len(warehouses) == 1 else None


@frappe.whitelist()
def submit_issue_and_push_to_dlm(material_request_name):
    """
    一键操作：提交物料需求 → 发料出库 → 提交出库单 → 推送至 DLM。

    步骤 1-3 在同一事务中，任一失败则全部回滚。
    步骤 4 (push_to_mes) 内部会独立 commit，推送失败时 Stock Entry 仍已提交，
    返回 partial 状态提示用户手动推送。
    """
    mr = frappe.get_doc("Material Request", material_request_name)

    if mr.docstatus != 0:
        frappe.throw(_("物料需求必须是草稿状态"))

    # Step 1: 提交物料需求
    mr.submit()

    # Step 2: 创建发料出库单（基于已提交的物料需求映射）
    stock_entry = make_issue_stock_entry(mr.name)
    stock_entry.insert()

    # Step 3: 提交出库单
    stock_entry.submit()

    # Step 4: 推送至 DLM
    # push_to_mes 内部在 HTTP 失败时会 frappe.db.commit() 再 raise，
    # 因此捕获异常，将推送失败视为非致命错误（出库单已提交但未推送）。
    from mes_integration.mes_integration.stock_entry import push_to_mes

    try:
        push_result = push_to_mes(stock_entry.name)
    except Exception:
        frappe.log_error(title="DLM 推送失败（发料并推送）", message=frappe.get_traceback())
        return {
            "status": "partial",
            "message": _("物料需求已提交，出库单 {0} 已创建并提交，但推送至 DLM 失败，请手动推送。").format(
                stock_entry.name
            ),
            "material_request": mr.name,
            "stock_entry": stock_entry.name,
        }

    return {
        "status": "success",
        "message": _("物料需求已提交，出库单 {0} 已创建、提交并推送至 DLM。").format(stock_entry.name),
        "material_request": mr.name,
        "stock_entry": stock_entry.name,
        "push_result": push_result,
    }


def validate_item_details(doc, method=None):
    details = doc.get("custom_item_details") or []
    if not details:
        return

    item_rows_by_idx = {cint(row.idx): row for row in doc.get("items") if row.idx}
    item_codes = {row.item_code for row in doc.get("items") if row.item_code}

    for detail in details:
        if flt(detail.order_qty) < 0:
            frappe.throw(_("Row {0}: Order Qty cannot be negative").format(detail.idx))

        if flt(detail.issue_qty) < 0:
            frappe.throw(_("Row {0}: Issue Qty cannot be negative").format(detail.idx))

        if detail.material_request_item_idx:
            item_row = item_rows_by_idx.get(cint(detail.material_request_item_idx))

            if not item_row:
                frappe.throw(
                    _("Row {0}: Material Request Item Row {1} does not exist").format(
                        detail.idx, detail.material_request_item_idx
                    )
                )

            if detail.item_code and detail.item_code != item_row.item_code:
                frappe.throw(
                    _("Row {0}: Item Code must match Material Request Item Row {1}").format(
                        detail.idx, detail.material_request_item_idx
                    )
                )

            detail.item_code = item_row.item_code
            detail.item_name = item_row.item_name
            detail.uom = detail.get("uom") or item_row.get("uom") or item_row.get("stock_uom")
            detail.material_request_item = item_row.name
        elif detail.item_code not in item_codes:
            frappe.throw(
                _("Row {0}: Item Code {1} is not in this Material Request").format(
                    detail.idx, detail.item_code
                )
            )
        elif not detail.get("uom") and detail.item_code:
            detail.uom = frappe.db.get_value("Item", detail.item_code, "stock_uom")

