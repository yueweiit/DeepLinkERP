import frappe
from frappe import _
from frappe.model.mapper import get_mapped_doc
from frappe.utils import cint, flt, now


CUSTOM_ISSUE_MATERIAL_REQUEST_TYPES = (
    "Material Issue",
    "Material Transfer for Manufacture",
    "Injection Molding Issuance",
)


@frappe.whitelist()
def create_and_submit_material_request_from_mes(data=None, material_request=None):
    """Create a Material Request draft from MES and submit it immediately."""
    from mes_integration.mes_integration.stock_entry import validate_mes_api_user

    payload = get_mes_material_request_payload(data=data, material_request=material_request)

    if not isinstance(payload, dict):
        frappe.throw(_("缺少请求数据或数据格式不正确"))

    validate_mes_api_user()
    validate_mes_material_request_permissions()

    material_request_data = extract_material_request_data(payload)

    if not isinstance(material_request_data, dict):
        frappe.throw(_("缺少 Material Request 数据或数据格式不正确"))

    material_request_data = material_request_data.copy()
    material_request_data["doctype"] = "Material Request"

    material_request_doc = frappe.get_doc(material_request_data)
    validate_mes_material_request_data(material_request_doc)

    material_request_doc.insert()
    material_request_doc.submit()

    frappe.response["data"] = {
        "status": "success",
        "message": _("物料需求已创建并提交。"),
        "material_request": material_request_doc.name,
        "material_request_type": material_request_doc.material_request_type,
        "material_request_docstatus": material_request_doc.docstatus,
        "material_request_url": frappe.utils.get_url_to_form(
            "Material Request", material_request_doc.name
        ),
        "timestamp": now(),
    }


def get_mes_material_request_payload(data=None, material_request=None):
    from mes_integration.mes_integration.stock_entry import parse_json_if_needed

    payload = parse_json_if_needed(data if data is not None else material_request)
    if isinstance(payload, dict):
        return payload

    if getattr(frappe, "request", None) and frappe.request.is_json:
        request_json = frappe.request.get_json(silent=True) or {}
        if isinstance(request_json, dict):
            if request_json.get("data") is not None:
                return parse_json_if_needed(request_json.get("data"))
            return request_json

    form_dict = getattr(frappe, "form_dict", None) or {}
    for fieldname in ("data", "material_request"):
        if form_dict.get(fieldname) is not None:
            return parse_json_if_needed(form_dict.get(fieldname))

    return {
        key: value
        for key, value in dict(form_dict).items()
        if key not in ("cmd", "method") and not key.startswith("_")
    }


def extract_material_request_data(payload):
    from mes_integration.mes_integration.stock_entry import parse_json_if_needed

    if not isinstance(payload, dict):
        return payload

    if payload.get("material_request") is not None:
        return parse_json_if_needed(payload.get("material_request"))

    if payload.get("data") is not None:
        nested_payload = parse_json_if_needed(payload.get("data"))
        return extract_material_request_data(nested_payload)

    return payload


def validate_mes_material_request_permissions():
    for permission_type in ("create", "submit"):
        if not frappe.has_permission("Material Request", permission_type):
            frappe.throw(
                _("当前用户缺少 {0} 的 {1} 权限").format(
                    "Material Request", permission_type
                ),
                frappe.PermissionError,
            )


def validate_mes_material_request_data(material_request):
    if material_request.doctype != "Material Request":
        frappe.throw(_("只能通过此接口创建 Material Request"))

    if material_request.docstatus != 0:
        frappe.throw(_("MES 传入的物料需求必须是草稿状态"))

    if not material_request.get("material_request_type"):
        frappe.throw(_("缺少物料需求类型 material_request_type"))

    if not material_request.get("company"):
        frappe.throw(_("缺少物料需求公司"))

    if not material_request.get("items"):
        frappe.throw(_("物料需求至少需要一行明细"))

    for row in material_request.get("items"):
        if not row.get("item_code"):
            frappe.throw(_("第 {0} 行缺少物料号").format(row.idx))

        if flt(row.get("qty")) <= 0:
            frappe.throw(_("第 {0} 行数量必须大于 0").format(row.idx))


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
@frappe.validate_and_sanitize_search_inputs
def issue_warehouse_query(doctype, txt, searchfield, start, page_len, filters):
    filters = filters or {}
    item_code = filters.get("item_code")
    company = filters.get("company")

    if not item_code:
        return []

    from frappe.desk.reportview import get_match_cond

    return frappe.db.sql(
        """
        SELECT
            warehouse.name,
            CONCAT_WS(' : ', 'Actual Qty', IFNULL(ROUND(bin.actual_qty, 2), 0)) AS actual_qty
        FROM `tabWarehouse` warehouse
        LEFT JOIN `tabBin` bin
            ON bin.warehouse = warehouse.name
            AND bin.item_code = %(item_code)s
        WHERE warehouse.is_group = 0
            AND IFNULL(warehouse.disabled, 0) = 0
            AND (%(company)s IS NULL OR %(company)s = '' OR IFNULL(warehouse.company, '') IN ('', %(company)s))
            AND warehouse.name LIKE %(txt)s
            {mcond}
        ORDER BY IFNULL(bin.actual_qty, 0) DESC, warehouse.name ASC
        LIMIT %(page_len)s OFFSET %(start)s
        """.format(mcond=get_match_cond("Warehouse")),
        {
            "item_code": item_code,
            "company": company,
            "txt": f"%{txt}%",
            "page_len": page_len,
            "start": start,
        },
    )


@frappe.whitelist()
def get_item_warehouse_actual_qty(item_code, warehouse):
    if not item_code or not warehouse:
        return 0

    return flt(
        frappe.db.get_value(
            "Bin",
            {"item_code": item_code, "warehouse": warehouse},
            "actual_qty",
        )
    )


@frappe.whitelist()
def issue_and_push_to_dlm_from_dialog(material_request_name, items=None):
    """Create, submit and push a Stock Entry from editable Material Request issue rows."""
    from mes_integration.mes_integration.stock_entry import push_to_mes

    mr = frappe.get_doc("Material Request", material_request_name)
    validate_material_request_can_issue_to_dlm(mr)

    issue_rows = get_issue_dialog_rows(items)
    stock_entry = build_stock_entry_from_material_request_issue_rows(mr, issue_rows)
    stock_entry.insert()
    stock_entry.submit()

    try:
        push_result = push_to_mes(stock_entry.name)
    except Exception:
        frappe.log_error(title="DLM 推送失败（弹窗发料并推送）", message=frappe.get_traceback())
        return {
            "status": "partial",
            "message": _("物料移动 {0} 已创建并提交，但推送至 DLM 失败，请手动推送。").format(
                stock_entry.name
            ),
            "material_request": mr.name,
            "stock_entry": stock_entry.name,
        }

    return {
        "status": "success",
        "message": _("物料移动 {0} 已创建、提交并推送至 DLM。").format(stock_entry.name),
        "material_request": mr.name,
        "stock_entry": stock_entry.name,
        "push_result": push_result,
    }


def validate_material_request_can_issue_to_dlm(mr):
    if mr.docstatus != 1:
        frappe.throw(_("物料需求必须已提交"))

    if mr.status in ("Stopped", "Cancelled"):
        frappe.throw(_("已停止或已取消的物料需求不能发料"))

    if mr.material_request_type not in CUSTOM_ISSUE_MATERIAL_REQUEST_TYPES:
        frappe.throw(_("只有物料发料、工单发料、注塑发料可以发料并推送至 DLM"))


def get_issue_dialog_rows(items):
    from mes_integration.mes_integration.stock_entry import parse_json_if_needed

    rows = parse_json_if_needed(items)
    if not isinstance(rows, list):
        frappe.throw(_("缺少发料明细或发料明细格式不正确"))

    return [row for row in rows if isinstance(row, dict) and flt(row.get("qty")) > 0]


def build_stock_entry_from_material_request_issue_rows(mr, issue_rows):
    if not issue_rows:
        frappe.throw(_("没有可发料的明细"))

    mr_items = {row.name: row for row in mr.get("items", [])}
    stock_entry = frappe.new_doc("Stock Entry")
    stock_entry.company = mr.company
    stock_entry.stock_entry_type = get_stock_entry_type(mr)
    stock_entry.purpose = get_stock_entry_purpose(mr)
    stock_entry.custom_stock_entry_no = mr.get("custom_stock_entry_no")
    stock_entry.from_warehouse = get_stock_entry_source_warehouse(mr, issue_rows, mr_items)
    if stock_entry.purpose != "Material Issue":
        stock_entry.to_warehouse = get_stock_entry_target_warehouse(mr, issue_rows, mr_items)

    for index, issue_row in enumerate(issue_rows, start=1):
        mr_item = validate_issue_dialog_row(mr, mr_items, issue_row, index)
        qty = flt(issue_row.get("qty"))
        conversion_factor = flt(mr_item.get("conversion_factor")) or 1
        stock_entry.append(
            "items",
            {
                "item_code": mr_item.item_code,
                "item_name": mr_item.get("item_name"),
                "description": mr_item.get("description"),
                "qty": qty,
                "transfer_qty": qty * conversion_factor,
                "uom": mr_item.get("uom") or mr_item.get("stock_uom"),
                "stock_uom": mr_item.get("stock_uom"),
                "conversion_factor": conversion_factor,
                "s_warehouse": issue_row.get("s_warehouse"),
                "t_warehouse": issue_row.get("t_warehouse") if stock_entry.purpose != "Material Issue" else None,
                "material_request": mr.name,
                "material_request_item": mr_item.name,
                "allow_zero_valuation_rate": 1,
            },
        )

    stock_entry.set_transfer_qty()
    stock_entry.set_actual_qty()
    stock_entry.calculate_rate_and_amount(raise_error_if_no_rate=False)
    stock_entry.set_job_card_data()
    return stock_entry


def validate_issue_dialog_row(mr, mr_items, issue_row, index):
    mr_item_name = issue_row.get("material_request_item")
    if not mr_item_name or mr_item_name not in mr_items:
        frappe.throw(_("第 {0} 行物料需求明细不存在或不属于当前物料需求").format(index))

    mr_item = mr_items[mr_item_name]
    if issue_row.get("item_code") and issue_row.get("item_code") != mr_item.item_code:
        frappe.throw(_("第 {0} 行物料编码与物料需求明细不一致").format(index))

    qty = flt(issue_row.get("qty"))
    if qty <= 0:
        frappe.throw(_("第 {0} 行本次发料数量必须大于 0").format(index))

    remaining_qty = get_material_request_item_remaining_qty(mr_item)
    if qty > remaining_qty:
        frappe.throw(
            _("第 {0} 行本次发料数量 {1} 超过剩余数量 {2}").format(
                index,
                qty,
                remaining_qty,
            )
        )

    if not issue_row.get("s_warehouse"):
        frappe.throw(_("第 {0} 行缺少发料仓").format(index))

    if get_stock_entry_purpose(mr) != "Material Issue" and not issue_row.get("t_warehouse"):
        frappe.throw(_("第 {0} 行缺少目标仓库").format(index))

    return mr_item


def get_material_request_item_remaining_qty(mr_item):
    conversion_factor = flt(mr_item.get("conversion_factor")) or 1
    requested_stock_qty = flt(mr_item.get("stock_qty")) or flt(mr_item.get("qty")) * conversion_factor
    issued_stock_qty = flt(mr_item.get("custom_transferred_qty") or mr_item.get("ordered_qty"))
    remaining_stock_qty = max(requested_stock_qty - issued_stock_qty, 0)
    return flt(remaining_stock_qty / conversion_factor)


def get_stock_entry_source_warehouse(mr, issue_rows, mr_items):
    warehouses = {
        row.get("s_warehouse")
        for row in issue_rows
        if row.get("s_warehouse") and row.get("material_request_item") in mr_items
    }
    return next(iter(warehouses)) if len(warehouses) == 1 else None


def get_stock_entry_target_warehouse(mr, issue_rows, mr_items):
    warehouses = {
        row.get("t_warehouse")
        for row in issue_rows
        if row.get("t_warehouse") and row.get("material_request_item") in mr_items
    }
    if len(warehouses) == 1:
        return next(iter(warehouses))

    return mr.get("set_warehouse")


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

