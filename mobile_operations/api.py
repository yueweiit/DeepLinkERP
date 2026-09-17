import frappe
import frappe.defaults
from frappe import _
from frappe.query_builder import Case, Order
from frappe.query_builder.functions import Coalesce, Count
from frappe.utils import cint, flt, nowdate
from mes_integration.mes_integration.material_request import (
	is_mes_material_request,
)
from mes_integration.mes_integration.settings import is_mes_integration_enabled


ISSUE_TYPES = {
    "Material Issue",
    "Material Transfer for Manufacture",
    "Injection Molding Issuance",
}

STOCK_ENTRY_STATUS_FILTERS = {"all", "draft", "submitted"}
INVENTORY_STOCK_STATUS_FILTERS = {"all", "positive", "insufficient", "negative", "zero"}
MOBILE_INVENTORY_SUMMARY_CACHE_TTL = 15
STOCK_ENTRY_TYPE_LABELS = {
    "Material Issue": "物料发料",
    "Material Receipt": "物料收料",
    "Material Transfer": "物料调拨",
    "Material Transfer for Manufacture": "生产领料",
    "Injection Molding Issuance": "注塑发料",
    "Manufacture": "生产入库",
    "Repack": "物料重包装",
    "Send to Subcontractor": "发送给委外商",
}


@frappe.whitelist()
def get_mobile_material_request_form_options():
	"""Return the permission-aware options used by the mobile create form."""
	if not frappe.has_permission("Material Request", "create"):
		frappe.throw(_("当前用户没有创建物料需求的权限"), frappe.PermissionError)

	type_field = frappe.get_meta("Material Request").get_field("material_request_type")
	types = [
		{"value": value, "label": _(value)}
		for value in (type_field.options or "").splitlines()
		if value.strip()
	]
	companies = frappe.get_list(
		"Company",
		fields=["name"],
		order_by="name asc",
		limit_page_length=100,
	)
	warehouses = frappe.get_list(
		"Warehouse",
		filters={"is_group": 0, "disabled": 0},
		fields=["name", "warehouse_name", "parent_warehouse", "company"],
		order_by="warehouse_name asc, name asc",
		limit_page_length=500,
	)
	defaults = frappe.defaults.get_defaults()
	default_company = frappe.defaults.get_user_default("Company") or defaults.get("company")
	if not default_company and companies:
		default_company = companies[0]["name"]

	return {
		"types": types,
		"companies": companies,
		"warehouses": warehouses,
		"default_company": default_company,
		"today": nowdate(),
	}


@frappe.whitelist()
def search_mobile_material_request_items(search=None, limit=20):
	"""Search stock items for the mobile Material Request item selector."""
	if not frappe.has_permission("Material Request", "create"):
		frappe.throw(_("当前用户没有创建物料需求的权限"), frappe.PermissionError)

	search = (search or "").strip()
	if len(search) < 2:
		return []

	search_value = f"%{search}%"
	return frappe.get_list(
		"Item",
		filters={"disabled": 0},
		or_filters=[
			["Item", "name", "like", search_value],
			["Item", "item_name", "like", search_value],
			["Item", "description", "like", search_value],
		],
		fields=["name", "item_name", "stock_uom"],
		order_by="name asc",
		limit_page_length=max(1, min(cint(limit) or 20, 30)),
	)


@frappe.whitelist()
def create_mobile_material_request(data=None, submit=0):
	"""Create and optionally submit a Material Request from the mobile form."""
	if not frappe.has_permission("Material Request", "create"):
		frappe.throw(_("当前用户没有创建物料需求的权限"), frappe.PermissionError)
	should_submit = cint(submit)
	if should_submit and not frappe.has_permission("Material Request", "submit"):
		frappe.throw(_("当前用户没有提交物料需求的权限"), frappe.PermissionError)

	data = frappe.parse_json(data or {})
	if not isinstance(data, dict):
		frappe.throw(_("物料需求数据格式不正确"))

	request_type = (data.get("material_request_type") or "").strip()
	type_field = frappe.get_meta("Material Request").get_field("material_request_type")
	valid_types = {value.strip() for value in (type_field.options or "").splitlines() if value.strip()}
	if request_type not in valid_types:
		frappe.throw(_("物料需求类型不正确"))

	company = (data.get("company") or "").strip()
	if not company:
		frappe.throw(_("请选择公司"))

	items = data.get("items") or []
	if not items:
		frappe.throw(_("请至少添加一项物料"))

	doc = frappe.new_doc("Material Request")
	doc.material_request_type = request_type
	doc.company = company
	doc.transaction_date = data.get("transaction_date") or nowdate()
	doc.schedule_date = data.get("schedule_date") or nowdate()
	doc.set_warehouse = (data.get("set_warehouse") or "").strip() or None
	transfer_types = {"Material Transfer", "Material Transfer for Manufacture"}
	doc.set_from_warehouse = (
		(data.get("set_from_warehouse") or "").strip() or None
		if request_type in transfer_types
		else None
	)

	for index, item_data in enumerate(items, start=1):
		item_code = (item_data.get("item_code") or "").strip()
		qty = flt(item_data.get("qty"))
		if not item_code or qty <= 0:
			frappe.throw(_("第 {0} 行物料和数量不能为空").format(index))

		item = frappe.get_cached_doc("Item", item_code)
		if item.disabled:
			frappe.throw(_("物料 {0} 已停用").format(item_code))

		doc.append(
			"items",
			{
				"item_code": item_code,
				"item_name": item.item_name,
				"qty": qty,
				"uom": (item_data.get("uom") or item.stock_uom),
				"stock_uom": item.stock_uom,
				"conversion_factor": flt(item_data.get("conversion_factor")) or 1,
				"schedule_date": item_data.get("schedule_date") or doc.schedule_date,
				"warehouse": (item_data.get("warehouse") or doc.set_warehouse) or None,
				"from_warehouse": ((item_data.get("from_warehouse") or doc.set_from_warehouse) or None) if request_type in transfer_types else None,
			},
		)

	doc.insert()
	if should_submit:
		doc.submit()
	_clear_mobile_inventory_summary_cache()

	return {"name": doc.name, "docstatus": doc.docstatus, "status": doc.status}


@frappe.whitelist()
def submit_mobile_material_request(name=None):
	"""Submit an existing draft Material Request from the mobile detail view."""
	if not name:
		frappe.throw(_("缺少物料需求编号"))

	doc = frappe.get_doc("Material Request", name)
	if not frappe.has_permission("Material Request", "submit", doc=doc):
		frappe.throw(_("当前用户没有提交物料需求的权限"), frappe.PermissionError)
	if doc.docstatus != 0:
		frappe.throw(_("只有草稿状态的物料需求可以提交"))

	doc.submit()
	_clear_mobile_inventory_summary_cache()
	return {"name": doc.name, "docstatus": doc.docstatus, "status": doc.status}


@frappe.whitelist()
def issue_and_push_mobile_material_request(material_request_name=None, items=None):
	"""Create the issue Stock Entry and push it to DLM from mobile."""
	if not material_request_name:
		frappe.throw(_("缺少物料需求编号"))

	from mes_integration.mes_integration.material_request import issue_and_push_to_dlm_from_dialog

	result = issue_and_push_to_dlm_from_dialog(material_request_name, items)
	_clear_mobile_inventory_summary_cache()
	return result


@frappe.whitelist()
def create_mobile_material_request_stock_entry(material_request_name=None, items=None):
	"""Create a draft Stock Entry for a manually created Material Request."""
	if not material_request_name:
		frappe.throw(_("缺少物料需求编号"))

	from mes_integration.mes_integration.material_request import (
		create_issue_stock_entry_from_mobile,
	)

	result = create_issue_stock_entry_from_mobile(material_request_name, items)
	_clear_mobile_inventory_summary_cache()
	return result


@frappe.whitelist()
def get_mobile_material_request_issue_options(material_request_name=None):
	"""Return remaining quantities, source warehouses and live stock for mobile issue."""
	if not material_request_name:
		frappe.throw(_("缺少物料需求编号"))

	doc = frappe.get_doc("Material Request", material_request_name)
	doc.check_permission("read")
	if doc.docstatus != 1:
		frappe.throw(_("物料需求必须已提交"))
	if doc.status in ("Stopped", "Cancelled"):
		frappe.throw(_("已停止或已取消的物料需求不能发料"))
	if doc.material_request_type not in ISSUE_TYPES:
		frappe.throw(_("当前物料需求类型不支持生成物料移动"))
	if not frappe.has_permission("Bin", "read"):
		frappe.throw(_("当前用户缺少库存读取权限"), frappe.PermissionError)

	from mes_integration.mes_integration.material_request import (
		get_material_request_item_remaining_qty,
		get_realtime_issued_stock_qty_by_mr_item,
	)

	item_docs = list(doc.get("items") or [])
	realtime_issued = get_realtime_issued_stock_qty_by_mr_item([row.name for row in item_docs])
	warehouses = frappe.get_list(
		"Warehouse",
		filters={"company": doc.company, "is_group": 0, "disabled": 0},
		fields=["name", "warehouse_name", "parent_warehouse"],
		order_by="warehouse_name asc, name asc",
		limit_page_length=0,
	)
	warehouse_names = [warehouse.name for warehouse in warehouses]
	item_codes = [row.item_code for row in item_docs if row.item_code]
	bins = []
	if warehouse_names and item_codes:
		bins = frappe.get_list(
			"Bin",
			filters={"warehouse": ["in", warehouse_names], "item_code": ["in", item_codes]},
			fields=["item_code", "warehouse", "actual_qty"],
			limit_page_length=0,
		)
	actual_qty_by_item_warehouse = {
		(item.item_code, item.warehouse): flt(item.actual_qty) for item in bins
	}
	is_transfer = doc.material_request_type == "Material Transfer for Manufacture"
	items = []
	for row in item_docs:
		remaining_qty = get_material_request_item_remaining_qty(row, realtime_issued)
		if not row.item_code or remaining_qty <= 0:
			continue
		source_warehouse = (
			row.from_warehouse or row.warehouse or doc.set_warehouse or doc.set_from_warehouse
		)
		target_warehouse = (row.warehouse or doc.set_warehouse) if is_transfer else None
		item_warehouses = []
		for warehouse in warehouses:
			actual_qty = actual_qty_by_item_warehouse.get((row.item_code, warehouse.name), 0)
			if actual_qty > 0 or warehouse.name == source_warehouse:
				item_warehouses.append({**warehouse, "actual_qty": actual_qty})
		items.append(
			{
				"material_request_item": row.name,
				"item_code": row.item_code,
				"item_name": row.item_name,
				"remaining_qty": remaining_qty,
				"uom": row.uom or row.stock_uom,
				"stock_uom": row.stock_uom or row.uom,
				"conversion_factor": flt(row.conversion_factor) or 1,
				"source_warehouse": source_warehouse,
				"target_warehouse": target_warehouse,
				"warehouses": item_warehouses,
			}
		)

	return {"material_request_type": doc.material_request_type, "is_transfer": is_transfer, "items": items}


@frappe.whitelist()
def get_mobile_material_request_dashboard(search=None, bucket="all", limit=40, offset=0):
    """Return a permission-aware, card-friendly Material Request view."""
    if not frappe.has_permission("Material Request", "read"):
        frappe.throw(_("当前用户没有物料需求读取权限"), frappe.PermissionError)

    limit = max(1, min(cint(limit) or 40, 100))
    offset = max(cint(offset), 0)
    bucket = (bucket or "all").strip()
    if bucket not in {"all", "in_progress", "to_issue", "partial", "transit", "exception"}:
        bucket = "all"
    search = (search or "").strip()
    fields = [
        "name",
        "title",
        "material_request_type",
        "docstatus",
        "status",
        "transfer_status",
        "per_ordered",
        "per_received",
        "schedule_date",
        "set_warehouse",
        "set_from_warehouse",
        "modified",
    ]
    if frappe.db.has_column("Material Request", "custom_material_request_no"):
        fields.append("custom_material_request_no")
    if frappe.db.has_column("Material Request", "custom_request_source"):
        fields.append("custom_request_source")

    material_request = frappe.qb.DocType("Material Request")
    filters, completed_or_exception = _get_material_request_dashboard_filters(
        material_request,
        bucket,
        search,
        include_custom_request_no="custom_material_request_no" in fields,
    )
    total = _get_permission_aware_count(material_request, filters)
    query = frappe.qb.get_query(
        material_request,
        fields=[material_request[field] for field in fields],
        filters=filters,
        limit=limit,
        offset=offset,
        ignore_permissions=False,
    )
    if bucket == "all":
        query = query.orderby(
            Case().when(completed_or_exception, 1).else_(0),
            order=Order.asc,
        )
    query = query.orderby(material_request.modified, order=Order.desc)
    page_rows = query.run(as_dict=True)
    requests = [_build_mobile_request_row(row) for row in page_rows]
    _add_item_summaries(requests)
    summary = _get_mobile_inventory_summary_data()["material_request"]
    return {
        "summary": summary,
        "requests": requests,
        "total": total,
        "has_more": offset + len(requests) < total,
    }


@frappe.whitelist()
def get_mobile_material_request_detail(name):
    """Return the compact detail needed by the mobile Material Request screen."""
    if not name:
        frappe.throw(_("缺少物料需求编号"))

    doc = frappe.get_doc("Material Request", name)
    doc.check_permission("read")
    item_rows = []
    for row in doc.get("items") or []:
        requested_qty = flt(row.get("qty"))
        issued_qty = flt(row.get("custom_transferred_qty") or row.get("ordered_qty"))
        source_warehouse = (
            row.get("from_warehouse")
            or row.get("warehouse")
            or doc.get("set_warehouse")
            or doc.get("set_from_warehouse")
        )
        target_warehouse = (
            row.get("warehouse") or doc.get("set_warehouse")
            if doc.get("material_request_type") == "Material Transfer for Manufacture"
            else None
        )
        item_rows.append(
            {
                "material_request_item": row.get("name"),
                "item_code": row.get("item_code"),
                "item_name": row.get("item_name"),
                "description": row.get("description"),
                "qty": requested_qty,
                "issued_qty": issued_qty,
                "remaining_qty": max(requested_qty - issued_qty, 0),
                "uom": row.get("uom") or row.get("stock_uom"),
                "stock_uom": row.get("stock_uom") or row.get("uom"),
                "source_warehouse": source_warehouse,
                "target_warehouse": target_warehouse,
                "warehouse": row.get("warehouse") or row.get("from_warehouse"),
                "schedule_date": row.get("schedule_date") or doc.get("schedule_date"),
            }
        )

    base = _build_mobile_request_row(doc)
    base["item_count"] = len(item_rows)
    base["item_preview"] = "、".join(
        " · ".join(value for value in [item.get("item_code"), item.get("item_name")] if value)
        for item in item_rows[:2]
    )
    issue_types = {"Material Issue", "Injection Molding Issuance"}
    transfer_types = {"Material Transfer", "Material Transfer for Manufacture"}
    if doc.get("material_request_type") in issue_types:
        warehouse_mode = "issue"
        target_warehouse = None
        source_warehouse = doc.get("set_warehouse") or next(
            (item.get("warehouse") for item in item_rows if item.get("warehouse")), None
        )
    else:
        warehouse_mode = "transfer" if doc.get("material_request_type") in transfer_types else "target"
        target_warehouse = doc.get("set_warehouse")
        source_warehouse = doc.get("set_from_warehouse") if warehouse_mode == "transfer" else None
    is_mes_request = is_mes_material_request(doc)
    can_create_movement = bool(
        doc.docstatus == 1
        and doc.status not in ("Stopped", "Cancelled")
        and doc.material_request_type in ISSUE_TYPES
        and flt(doc.per_ordered) < 100
        and frappe.has_permission("Stock Entry", "create")
    )
    material_movement_hint = _get_material_movement_hint(doc)
    return {
        **base,
        "request_source": "MES" if is_mes_request else "Manual",
        "source_label": _("MES") if is_mes_request else _("手动创建"),
        "can_submit": bool(doc.docstatus == 0 and frappe.has_permission("Material Request", "submit", doc=doc)),
        "can_push_to_dlm": bool(
            is_mes_request
            and can_create_movement
            and is_mes_integration_enabled(doc.company)
        ),
        "can_create_material_movement": bool(can_create_movement and not is_mes_request),
        "material_movement_hint": material_movement_hint,
        "warehouse_mode": warehouse_mode,
        "target_warehouse": target_warehouse,
        "source_warehouse": source_warehouse,
        "items": item_rows,
    }


@frappe.whitelist()
def get_mobile_stock_entry_dashboard(search=None, status="all", limit=40, offset=0):
    """Return a compact, permission-aware Stock Entry workbench for mobile."""
    if not frappe.has_permission("Stock Entry", "read"):
        frappe.throw(_("当前用户没有物料移动读取权限"), frappe.PermissionError)

    limit = max(1, min(cint(limit) or 40, 100))
    offset = max(cint(offset), 0)
    status = (status or "all").strip()
    if status not in STOCK_ENTRY_STATUS_FILTERS:
        status = "all"
    search = (search or "").strip()

    fields = [
        "name",
        "stock_entry_type",
        "purpose",
        "docstatus",
        "posting_date",
        "company",
        "from_warehouse",
        "to_warehouse",
        "modified",
    ]
    if frappe.db.has_column("Stock Entry", "custom_stock_entry_no"):
        fields.append("custom_stock_entry_no")
    if frappe.db.has_column("Stock Entry", "custom_mes_status"):
        fields.append("custom_mes_status")

    stock_entry = frappe.qb.DocType("Stock Entry")
    filters = None
    if status == "draft":
        filters = stock_entry.docstatus == 0
    elif status == "submitted":
        filters = stock_entry.docstatus == 1

    if search:
        search_value = f"%{search}%"
        child_parents = frappe.get_all(
            "Stock Entry Detail",
            filters={"parenttype": "Stock Entry"},
            or_filters=[
                ["Stock Entry Detail", "item_code", "like", search_value],
                ["Stock Entry Detail", "item_name", "like", search_value],
                ["Stock Entry Detail", "description", "like", search_value],
            ],
            pluck="parent",
            distinct=True,
            limit_page_length=2000,
        )
        search_filters = (
            stock_entry.name.like(search_value)
            | stock_entry.stock_entry_type.like(search_value)
            | stock_entry.purpose.like(search_value)
            | stock_entry.company.like(search_value)
            | stock_entry.from_warehouse.like(search_value)
            | stock_entry.to_warehouse.like(search_value)
        )
        if "custom_stock_entry_no" in fields:
            search_filters |= stock_entry.custom_stock_entry_no.like(search_value)
        if child_parents:
            search_filters |= stock_entry.name.isin(child_parents)
        filters = search_filters if filters is None else filters & search_filters

    total = _get_permission_aware_count(stock_entry, filters)
    rows = frappe.qb.get_query(
        stock_entry,
        fields=[stock_entry[field] for field in fields],
        filters=filters,
        limit=limit,
        offset=offset,
        ignore_permissions=False,
    ).orderby(stock_entry.modified, order=Order.desc).run(as_dict=True)
    entries = _build_mobile_stock_entry_rows(rows)
    summary = _get_mobile_inventory_summary_data()["stock_entry"]
    return {
        "summary": summary,
        "entries": entries,
        "total": total,
        "has_more": offset + len(entries) < total,
    }


@frappe.whitelist()
def get_mobile_stock_entry_detail(name=None):
    """Return the mobile detail view for a Stock Entry."""
    if not name:
        frappe.throw(_("缺少物料移动编号"))
    doc = frappe.get_doc("Stock Entry", name)
    doc.check_permission("read")
    return _build_mobile_stock_entry_detail(doc)


@frappe.whitelist()
def get_mobile_inventory_summary():
    """Return the lightweight counts shared by the mobile home and inventory pages."""
    return _get_mobile_inventory_summary_data()


@frappe.whitelist()
def get_mobile_inventory_options():
    """Return company options for the mobile inventory query."""
    if not frappe.has_permission("Bin", "read"):
        frappe.throw(_("当前用户没有库存读取权限"), frappe.PermissionError)

    companies = frappe.get_list(
        "Company",
        fields=["name"],
        order_by="name asc",
        limit_page_length=100,
    )
    defaults = frappe.defaults.get_defaults()
    default_company = frappe.defaults.get_user_default("Company") or defaults.get("company")
    return {"companies": companies, "default_company": default_company}


@frappe.whitelist()
def get_mobile_inventory_suggestions(kind=None, search_text=None, company=None, limit=20):
    """Return fuzzy suggestions for the mobile inventory query fields."""
    if not frappe.has_permission("Bin", "read"):
        frappe.throw(_("当前用户没有库存读取权限"), frappe.PermissionError)

    kind = (kind or "").strip()
    search_text = (search_text or "").strip()
    company = (company or "").strip()
    limit = max(1, min(cint(limit) or 20, 30))
    if kind not in {"item", "warehouse", "location"} or not search_text:
        return {"suggestions": []}

    search_value = f"%{search_text}%"
    if kind == "item":
        rows = frappe.get_list(
            "Item",
            filters={"disabled": 0},
            or_filters=[
                ["Item", "name", "like", search_value],
                ["Item", "item_name", "like", search_value],
                ["Item", "description", "like", search_value],
            ],
            fields=["name", "item_name", "description"],
            limit_page_length=limit,
            order_by="name asc",
        )
        return {
            "suggestions": [
                {
                    "value": row.get("name"),
                    "label": row.get("name"),
                    "sublabel": row.get("item_name") or row.get("description"),
                }
                for row in rows
                if row.get("name")
            ]
        }

    warehouse_filters = {"is_group": 0, "disabled": 0}
    if company:
        warehouse_filters["company"] = company
    rows = frappe.get_list(
        "Warehouse",
        filters=warehouse_filters,
        or_filters=[
            ["Warehouse", "name", "like", search_value],
            ["Warehouse", "warehouse_name", "like", search_value],
            ["Warehouse", "parent_warehouse", "like", search_value],
        ],
        fields=["name", "warehouse_name", "parent_warehouse", "company"],
        limit_page_length=limit * 4,
        order_by="name asc",
    )
    suggestions = []
    seen = set()
    for row in rows:
        display = _get_mobile_inventory_warehouse_display(row)
        if kind == "warehouse":
            candidates = [
                display["warehouse_name"],
                display["parent_warehouse"],
                display["display_name"],
            ]
            if not any(search_text.casefold() in str(value or "").casefold() for value in candidates):
                continue
            value = display["warehouse_name"] or display["parent_warehouse"]
            label = value
            sublabel = row.get("company") or ""
        else:
            if search_text.casefold() not in display["location_code"].casefold():
                continue
            value = display["location_code"]
            label = value
            sublabel = " · ".join(
                value for value in [display["warehouse_name"], row.get("company")] if value
            )
        if not value or value in seen:
            continue
        seen.add(value)
        suggestions.append({"value": value, "label": label, "sublabel": sublabel})
        if len(suggestions) >= limit:
            break
    return {"suggestions": suggestions}


@frappe.whitelist()
def get_mobile_inventory_dashboard(
    item_search=None,
    warehouse_name=None,
    location_code=None,
    company=None,
    stock_status="all",
    limit=40,
    offset=0,
):
    """Return filtered Bin rows in a card-friendly format for mobile."""
    if not frappe.has_permission("Bin", "read"):
        frappe.throw(_("当前用户没有库存读取权限"), frappe.PermissionError)

    item_search = (item_search or "").strip()
    warehouse_name = (warehouse_name or "").strip()
    location_code = (location_code or "").strip()
    company = (company or "").strip()
    stock_status = (stock_status or "all").strip()
    if stock_status not in INVENTORY_STOCK_STATUS_FILTERS:
        stock_status = "all"
    limit = max(1, min(cint(limit) or 40, 100))
    offset = max(cint(offset), 0)

    if not any((item_search, warehouse_name, location_code)):
        return {
            "items": [],
            "total": 0,
            "has_more": False,
            "requires_query": True,
            "message": _("请输入物料、仓库名称或库位号后查询"),
            "summary": {"total": 0, "positive": 0, "insufficient": 0, "negative": 0, "zero": 0},
        }

    item_codes = None
    if item_search:
        search_value = f"%{item_search}%"
        item_rows = frappe.get_list(
            "Item",
            filters={"disabled": 0},
            or_filters=[
                ["Item", "name", "like", search_value],
                ["Item", "item_name", "like", search_value],
                ["Item", "description", "like", search_value],
            ],
            fields=["name"],
            limit_page_length=2000,
        )
        item_codes = [row.get("name") for row in item_rows if row.get("name")]
        if not item_codes:
            return _empty_mobile_inventory_result()

    warehouse_names = None
    if warehouse_name or location_code:
        warehouse_filters = {"is_group": 0, "disabled": 0}
        if company:
            warehouse_filters["company"] = company
        warehouse_rows = frappe.get_list(
            "Warehouse",
            filters=warehouse_filters,
            fields=["name", "warehouse_name", "parent_warehouse", "company"],
            limit_page_length=0,
        )
        warehouse_rows = [
            row
            for row in warehouse_rows
            if _matches_mobile_inventory_warehouse(row, warehouse_name, location_code)
        ]
        warehouse_names = [row.get("name") for row in warehouse_rows if row.get("name")]
        if not warehouse_names:
            return _empty_mobile_inventory_result()

    base_filters = {}
    if item_codes is not None:
        base_filters["item_code"] = ["in", item_codes]
    if warehouse_names is not None:
        base_filters["warehouse"] = ["in", warehouse_names]
    if company:
        base_filters["company"] = company

    bin_filters = dict(base_filters)
    _apply_mobile_inventory_status_filter(bin_filters, stock_status)
    total = _count_mobile_inventory_bins(bin_filters)
    summary = {
        "total": total,
        "positive": _count_mobile_inventory_bins_with_status(base_filters, "positive"),
        "insufficient": _count_mobile_inventory_bins_with_status(base_filters, "insufficient"),
        "negative": _count_mobile_inventory_bins_with_status(base_filters, "negative"),
        "zero": _count_mobile_inventory_bins_with_status(base_filters, "zero"),
    }
    rows = frappe.get_list(
        "Bin",
        filters=bin_filters,
        fields=[
            "item_code",
            "warehouse",
            "actual_qty",
            "reserved_qty",
            "reserved_qty_for_production",
            "reserved_qty_for_sub_contract",
            "reserved_qty_for_production_plan",
            "projected_qty",
            "stock_uom",
        ],
        order_by="item_code asc, warehouse asc",
        limit_start=offset,
        limit_page_length=limit,
    )
    items_by_code = _get_mobile_inventory_items({row.get("item_code") for row in rows if row.get("item_code")})
    warehouses_by_name = _get_mobile_inventory_warehouses({row.get("warehouse") for row in rows if row.get("warehouse")})
    items = [
        _build_mobile_inventory_row(row, items_by_code, warehouses_by_name)
        for row in rows
    ]
    return {
        "items": items,
        "total": total,
        "has_more": offset + len(items) < total,
        "requires_query": False,
        "summary": summary,
    }


def _empty_mobile_inventory_result():
    return {
        "items": [],
        "total": 0,
        "has_more": False,
        "requires_query": False,
        "summary": {"total": 0, "positive": 0, "insufficient": 0, "negative": 0, "zero": 0},
    }


def _matches_mobile_inventory_warehouse(row, warehouse_name, location_code):
    display = _get_mobile_inventory_warehouse_display(row)
    query_name = warehouse_name.casefold()
    query_location = location_code.casefold()
    if query_name:
        candidates = [
            display["warehouse_name"],
            display["parent_warehouse"],
            display["display_name"],
        ]
        if not any(query_name in str(value or "").casefold() for value in candidates):
            return False
    if query_location:
        candidates = [row.get("name"), display["location_code"], display["display_name"]]
        if not any(query_location in str(value or "").casefold() for value in candidates):
            return False
    return True


def _count_mobile_inventory_bins(filters):
    return len(
        frappe.get_list(
            "Bin",
            filters=filters,
            fields=["name"],
            limit_page_length=0,
        )
    )


def _count_mobile_inventory_bins_with_status(filters, status):
    status_filters = dict(filters)
    _apply_mobile_inventory_status_filter(status_filters, status)
    return _count_mobile_inventory_bins(status_filters)


def _apply_mobile_inventory_status_filter(filters, status):
    if status == "positive":
        filters["actual_qty"] = [">", 0]
    elif status == "insufficient":
        filters["projected_qty"] = ["<", 0]
    elif status == "negative":
        filters["actual_qty"] = ["<", 0]
    elif status == "zero":
        filters["actual_qty"] = ["=", 0]


def _get_mobile_inventory_items(item_codes):
    if not item_codes:
        return {}
    rows = frappe.get_list(
        "Item",
        filters={"name": ["in", list(item_codes)]},
        fields=["name", "item_name", "description", "stock_uom"],
        limit_page_length=0,
    )
    return {row.get("name"): row for row in rows}


def _get_mobile_inventory_warehouses(warehouse_names):
    if not warehouse_names:
        return {}
    rows = frappe.get_list(
        "Warehouse",
        filters={"name": ["in", list(warehouse_names)]},
        fields=["name", "warehouse_name", "parent_warehouse", "company"],
        limit_page_length=0,
    )
    return {row.get("name"): _get_mobile_inventory_warehouse_display(row) for row in rows}


def _get_mobile_inventory_warehouse_display(row):
    raw_name = str(row.get("warehouse_name") or row.get("name") or "").strip()
    parent_name = str(row.get("parent_warehouse") or "").strip()
    company_suffix = _get_mobile_inventory_company_suffix(parent_name)
    display_name = raw_name[:-len(company_suffix)].strip() if company_suffix and raw_name.endswith(company_suffix) else raw_name
    parent_display = parent_name[:-len(company_suffix)].strip() if company_suffix and parent_name.endswith(company_suffix) else parent_name
    location_code = display_name.split(None, 1)[0] if display_name else ""
    warehouse_label = display_name[len(location_code):].strip() if location_code else display_name
    return {
        "display_name": display_name,
        "location_code": location_code,
        "warehouse_name": warehouse_label or parent_display,
        "parent_warehouse": parent_display,
        "company": row.get("company"),
    }


def _get_mobile_inventory_company_suffix(parent_name):
    separator_index = parent_name.rfind(" - ")
    return parent_name[separator_index:] if separator_index >= 0 else ""


def _build_mobile_inventory_row(row, items_by_code, warehouses_by_name):
    actual_qty = flt(row.get("actual_qty"))
    reserved_qty = (
        flt(row.get("reserved_qty"))
        + flt(row.get("reserved_qty_for_production"))
        + flt(row.get("reserved_qty_for_sub_contract"))
        + flt(row.get("reserved_qty_for_production_plan"))
    )
    projected_qty = flt(row.get("projected_qty"))
    available_qty = actual_qty - reserved_qty
    status = "negative" if actual_qty < 0 else "insufficient" if projected_qty < 0 else "positive" if actual_qty > 0 else "zero"
    status_labels = {
        "positive": _("有库存"),
        "insufficient": _("库存不足"),
        "negative": _("负库存"),
        "zero": _("库存为零"),
    }
    item = items_by_code.get(row.get("item_code"), {})
    warehouse = warehouses_by_name.get(row.get("warehouse"), {})
    return {
        "item_code": row.get("item_code"),
        "item_name": item.get("item_name") or item.get("description"),
        "description": item.get("description"),
        "stock_uom": row.get("stock_uom") or item.get("stock_uom"),
        "warehouse": row.get("warehouse"),
        "warehouse_display": warehouse.get("display_name") or row.get("warehouse"),
        "warehouse_name": warehouse.get("warehouse_name"),
        "location_code": warehouse.get("location_code"),
        "parent_warehouse": warehouse.get("parent_warehouse"),
        "company": warehouse.get("company"),
        "actual_qty": actual_qty,
        "reserved_qty": reserved_qty,
        "available_qty": available_qty,
        "projected_qty": projected_qty,
        "status": status,
        "status_label": status_labels[status],
    }


def _get_permission_aware_count(doctype, filters=None):
    rows = frappe.qb.get_query(
        doctype,
        fields=[Count("*").as_("total")],
        filters=filters if filters is not None else {},
        ignore_permissions=False,
    ).run(as_dict=True)
    return cint(rows[0].get("total")) if rows else 0


def _get_material_request_dashboard_filters(
    material_request,
    bucket,
    search=None,
    include_custom_request_no=False,
):
    status = Coalesce(material_request.status, "")
    transfer_status = Coalesce(material_request.transfer_status, "")
    progress = Coalesce(material_request.per_ordered, 0)
    exception = (material_request.docstatus == 2) | status.isin(("Stopped", "Cancelled"))
    not_exception = (material_request.docstatus != 2) & ~status.isin(("Stopped", "Cancelled"))
    not_in_transit = transfer_status != "In Transit"
    completed = (
        not_exception
        & not_in_transit
        & (material_request.docstatus == 1)
        & (progress >= 100)
    )
    bucket_filters = {
        "in_progress": not_exception & ~completed,
        "to_issue": (
            not_exception
            & not_in_transit
            & (material_request.docstatus == 1)
            & (progress <= 0)
            & material_request.material_request_type.isin(tuple(ISSUE_TYPES))
        ),
        "partial": (
            not_exception
            & not_in_transit
            & (material_request.docstatus == 1)
            & (progress > 0)
            & (progress < 100)
        ),
        "transit": not_exception & (transfer_status == "In Transit"),
        "exception": exception,
    }
    filters = bucket_filters.get(bucket)
    if search:
        search_value = f"%{search}%"
        search_filters = material_request.name.like(search_value) | material_request.title.like(search_value)
        if include_custom_request_no:
            search_filters |= material_request.custom_material_request_no.like(search_value)
        filters = search_filters if filters is None else filters & search_filters
    return filters, completed | exception


def _get_mobile_inventory_summary_cache_key():
    language = getattr(frappe.local, "lang", None) or ""
    return f"mobile_operations:inventory_summary:{frappe.session.user}:{language}"


def _clear_mobile_inventory_summary_cache():
    frappe.cache.delete_value(_get_mobile_inventory_summary_cache_key())


def _get_mobile_inventory_summary_data():
    cache_key = _get_mobile_inventory_summary_cache_key()
    cached = frappe.cache.get_value(cache_key)
    if cached is not None:
        return cached

    material_request_summary = []
    if frappe.has_permission("Material Request", "read"):
        material_request_rows = frappe.get_list(
            "Material Request",
            fields=[
                "docstatus",
                "status",
                "transfer_status",
                "per_ordered",
                "material_request_type",
            ],
            limit_page_length=0,
        )
        material_request_summary = _build_summary(material_request_rows)

    stock_entry_summary = []
    if frappe.has_permission("Stock Entry", "read"):
        stock_entry_fields = ["name", "docstatus"]
        if frappe.db.has_column("Stock Entry", "custom_mes_status"):
            stock_entry_fields.append("custom_mes_status")
        stock_entry_rows = frappe.get_list(
            "Stock Entry",
            fields=stock_entry_fields,
            limit_page_length=0,
        )
        stock_entry_summary = _build_stock_entry_summary(stock_entry_rows)

    result = {
        "material_request": material_request_summary,
        "stock_entry": stock_entry_summary,
    }
    frappe.cache.set_value(
        cache_key,
        result,
        expires_in_sec=MOBILE_INVENTORY_SUMMARY_CACHE_TTL,
    )
    return result


@frappe.whitelist()
def submit_mobile_stock_entry(name=None):
    """Submit a draft Stock Entry from the mobile detail view."""
    if not name:
        frappe.throw(_("缺少物料移动编号"))
    doc = frappe.get_doc("Stock Entry", name)
    doc.check_permission("read")
    if not frappe.has_permission("Stock Entry", "submit", doc=doc):
        frappe.throw(_("当前用户没有提交物料移动的权限"), frappe.PermissionError)
    if doc.docstatus != 0:
        frappe.throw(_("只有草稿状态的物料移动可以提交"))
    doc.submit()
    _clear_mobile_inventory_summary_cache()
    return {
        "name": doc.name,
        "docstatus": doc.docstatus,
        "status": _get_stock_entry_status_label(doc),
    }


@frappe.whitelist()
def push_mobile_stock_entry_to_dlm(name=None):
    """Push an eligible MES Stock Entry to DLM from mobile."""
    if not name:
        frappe.throw(_("缺少物料移动编号"))
    from mes_integration.mes_integration.stock_entry import push_to_mes

    result = push_to_mes(name)
    _clear_mobile_inventory_summary_cache()
    return result


def _build_mobile_stock_entry_rows(rows):
    if not rows:
        return []
    names = [row.get("name") for row in rows if row.get("name")]
    item_rows = frappe.get_all(
        "Stock Entry Detail",
        filters={"parenttype": "Stock Entry", "parent": ["in", names]},
        fields=["parent", "item_code", "item_name", "qty", "uom", "s_warehouse", "t_warehouse", "material_request"],
        order_by="parent asc, idx asc",
        limit_page_length=0,
    )
    items_by_parent = {}
    material_requests = set()
    for item in item_rows:
        items_by_parent.setdefault(item.parent, []).append(item)
        if item.get("material_request"):
            material_requests.add(item.material_request)
    source_by_request = _get_material_request_sources(material_requests)
    result = []
    for row in rows:
        items = items_by_parent.get(row.get("name"), [])
        source = _get_stock_entry_source(items, source_by_request)
        result.append(_build_mobile_stock_entry_row(row, items, source))
    return result


def _build_mobile_stock_entry_row(row, items=None, source=None):
    items = items or []
    source = source or "Manual"
    item_preview = "、".join(
        " · ".join(value for value in [item.get("item_code"), item.get("item_name")] if value)
        for item in items[:2]
    )
    if len(items) > 2:
        item_preview += "、" + _("等 {0} 项").format(len(items))
    status = _get_stock_entry_status(row)
    return {
        "name": row.get("name"),
        "entry_no": row.get("custom_stock_entry_no") or row.get("name"),
        "stock_entry_type": row.get("stock_entry_type"),
        "type_label": _get_stock_entry_type_label(row.get("stock_entry_type")),
        "purpose": row.get("purpose"),
        "docstatus": cint(row.get("docstatus")),
        "status": status,
        "status_label": _get_stock_entry_status_label(row, source),
        "posting_date": row.get("posting_date"),
        "modified": str(row.get("modified") or "")[:10],
        "company": row.get("company"),
        "from_warehouse": row.get("from_warehouse"),
        "to_warehouse": row.get("to_warehouse"),
        "warehouse": row.get("from_warehouse") or row.get("to_warehouse"),
        "mes_status": row.get("custom_mes_status"),
        "request_source": source,
        "source_label": _get_stock_entry_source_label(source),
        "item_count": len(items),
        "item_preview": item_preview,
    }


def _build_mobile_stock_entry_detail(doc):
    item_rows = []
    material_requests = set()
    for row in doc.get("items") or []:
        if row.get("material_request"):
            material_requests.add(row.material_request)
        item_rows.append(
            {
                "item_code": row.get("item_code"),
                "item_name": row.get("item_name") or row.get("description"),
                "description": row.get("description"),
                "qty": flt(row.get("qty")),
                "transfer_qty": flt(row.get("transfer_qty") or row.get("qty")),
                "uom": row.get("uom") or row.get("stock_uom"),
                "stock_uom": row.get("stock_uom") or row.get("uom"),
                "source_warehouse": row.get("s_warehouse"),
                "target_warehouse": row.get("t_warehouse"),
                "material_request": row.get("material_request"),
                "material_request_item": row.get("material_request_item"),
            }
        )
    source_by_request = _get_material_request_sources(material_requests)
    source = _get_stock_entry_source(doc.get("items") or [], source_by_request)
    is_mes = source == "MES"
    can_submit = bool(doc.docstatus == 0 and frappe.has_permission("Stock Entry", "submit", doc=doc))
    can_push = bool(
        doc.docstatus == 1
        and is_mes
        and doc.stock_entry_type in ISSUE_TYPES
        and doc.get("custom_mes_status") != "Pushed"
        and is_mes_integration_enabled(doc.company)
    )
    return {
        "name": doc.name,
        "entry_no": doc.get("custom_stock_entry_no") or doc.name,
        "stock_entry_type": doc.get("stock_entry_type"),
        "type_label": _get_stock_entry_type_label(doc.get("stock_entry_type")),
        "purpose": doc.get("purpose"),
        "docstatus": cint(doc.docstatus),
        "status": _get_stock_entry_status(doc),
        "status_label": _get_stock_entry_status_label(doc, source),
        "posting_date": doc.get("posting_date"),
        "posting_time": doc.get("posting_time"),
        "company": doc.get("company"),
        "from_warehouse": doc.get("from_warehouse"),
        "to_warehouse": doc.get("to_warehouse"),
        "mes_status": doc.get("custom_mes_status"),
        "request_source": source,
        "source_label": _get_stock_entry_source_label(source),
        "material_requests": sorted(material_requests),
        "can_submit": can_submit,
        "can_push_to_dlm": can_push,
        "items": item_rows,
    }


def _get_material_request_sources(names):
    names = {name for name in names if name}
    if not names:
        return {}
    fields = ["name"]
    has_source_field = frappe.db.has_column("Material Request", "custom_request_source")
    if has_source_field:
        fields.append("custom_request_source")
    rows = frappe.get_all(
        "Material Request",
        filters={"name": ["in", list(names)]},
        fields=fields,
        limit_page_length=0,
    )
    sources = {name: "Manual" for name in names}
    for row in rows:
        is_mes = (
            has_source_field
            and (row.get("custom_request_source") or "").strip() == "MES"
        ) or str(row.get("name") or "").startswith("MAT-MR-MES-")
        sources[row.get("name")] = "MES" if is_mes else "Manual"
    return sources


def _get_stock_entry_source(items, source_by_request):
    if any(source_by_request.get(item.get("material_request")) == "MES" for item in items):
        return "MES"
    return "Manual"


def _build_stock_entry_summary(rows):
    draft = sum(cint(row.get("docstatus")) == 0 for row in rows)
    submitted = sum(cint(row.get("docstatus")) == 1 for row in rows)
    names = [row.get("name") for row in rows if row.get("name")]
    linked_rows = frappe.get_all(
        "Stock Entry Detail",
        filters={
            "parenttype": "Stock Entry",
            "parent": ["in", names],
            "material_request": ["is", "set"],
        },
        fields=["parent", "material_request"],
        distinct=True,
        limit_page_length=0,
    ) if names else []
    source_by_request = _get_material_request_sources(
        {row.get("material_request") for row in linked_rows if row.get("material_request")}
    )
    mes_parents = {
        row.get("parent")
        for row in linked_rows
        if source_by_request.get(row.get("material_request")) == "MES"
    }
    mes_pending = sum(
        row.get("name") in mes_parents
        and cint(row.get("docstatus")) == 1
        and row.get("custom_mes_status") != "Pushed"
        for row in rows
        if "custom_mes_status" in row
    )
    return [
        {"key": "all", "label": _("全部"), "count": len(rows)},
        {"key": "draft", "label": _("草稿"), "count": draft, "tone": "warning"},
        {"key": "submitted", "label": _("已提交"), "count": submitted},
        {"key": "mes_pending", "label": _("待推送"), "count": mes_pending, "tone": "warning"},
    ]


def _get_stock_entry_status(row):
    docstatus = cint(row.get("docstatus"))
    if docstatus == 0:
        return "draft"
    if docstatus == 1:
        return "submitted"
    return "cancelled"


def _get_stock_entry_status_label(row, source="Manual"):
    status = _get_stock_entry_status(row)
    if status == "draft":
        return _("草稿")
    if status == "submitted":
        if source == "MES" and row.get("custom_mes_status") == "Pushed":
            return _("已推送")
        return _("已提交")
    return _("已取消")


def _get_stock_entry_type_label(value):
    return _(STOCK_ENTRY_TYPE_LABELS.get(value, value or "物料移动"))


def _get_stock_entry_source_label(source):
    return _("MES") if source == "MES" else _("手动创建")


def _get_material_movement_hint(doc):
    """Return a user-facing reason when this request cannot create a Stock Entry."""
    if doc.docstatus == 0:
        return _("请先提交物料需求后再生成物料移动")

    if doc.status in ("Stopped", "Cancelled"):
        return _("当前物料需求已停止或取消，无法生成物料移动")

    if doc.material_request_type == "Purchase":
        return _("采购需求不能生成物料移动，请在采购模块处理")

    if doc.material_request_type not in ISSUE_TYPES:
        return _("当前需求类型不支持手机端生成物料移动")

    if not frappe.has_permission("Stock Entry", "create"):
        return _("当前账号没有创建物料移动的权限")

    if flt(doc.per_ordered) >= 100:
        return _("该物料需求已全部处理，无法生成新的物料移动")

    return _("当前物料需求暂时不能生成物料移动")


def _build_mobile_request_row(row):
	bucket = _get_primary_bucket(row)
	request_no = row.get("custom_material_request_no") or row.get("name")
	request_source = _get_request_source(row)
	return {
        "name": row.get("name"),
        "request_no": request_no,
        "docstatus": cint(row.get("docstatus")),
        "title": row.get("title"),
        "material_request_type": row.get("material_request_type"),
        "type_label": _get_type_label(row.get("material_request_type")),
        "status": row.get("status"),
        "status_label": _get_status_label(row, bucket),
        "primary_bucket": bucket,
        "is_active": bucket not in {"completed", "exception"},
        "progress": _get_progress(row),
        "schedule_date": row.get("schedule_date"),
        "modified": str(row.get("modified") or "")[:10],
		"warehouse": row.get("set_warehouse") or row.get("set_from_warehouse"),
		"request_source": request_source,
		"source_label": _("MES") if request_source == "MES" else _("手动创建"),
        "item_count": 0,
        "item_preview": "",
	}


def _get_request_source(row):
	if (row.get("custom_request_source") or "").strip() == "MES":
		return "MES"
	if str(row.get("name") or "").startswith("MAT-MR-MES-"):
		return "MES"
	return "Manual"


def _add_item_summaries(requests):
    names = [request.get("name") for request in requests if request.get("name")]
    if not names:
        return
    item_rows = frappe.get_all(
        "Material Request Item",
        filters={"parenttype": "Material Request", "parent": ["in", names]},
        fields=["parent", "item_code", "item_name", "idx"],
        order_by="parent asc, idx asc",
        limit_page_length=0,
    )
    items_by_parent = {}
    for row in item_rows:
        if row.get("item_code"):
            items_by_parent.setdefault(row.get("parent"), []).append(row)

    for request in requests:
        items = items_by_parent.get(request.get("name"), [])
        preview = [
            " · ".join(value for value in [row.get("item_code"), row.get("item_name")] if value)
            for row in items[:2]
        ]
        if len(items) > 2:
            preview.append(_("等 {0} 项").format(len(items)))
        request["item_count"] = len(items)
        request["item_preview"] = "、".join(preview)


def _build_summary(rows):
    active = to_issue = partial = transit = exception = 0
    for row in rows:
        bucket = _get_primary_bucket(row)
        if bucket == "exception":
            exception += 1
        elif bucket != "completed":
            active += 1
        if bucket == "to_issue":
            to_issue += 1
        elif bucket == "partial":
            partial += 1
        if row.get("transfer_status") == "In Transit":
            transit += 1

    return [
        {"key": "in_progress", "label": _("进行中"), "count": active},
        {"key": "to_issue", "label": _("待发料"), "count": to_issue, "tone": "warning"},
        {"key": "partial", "label": _("部分完成"), "count": partial},
        {"key": "transit", "label": _("调拨在途"), "count": transit, "tone": "warning"},
        {"key": "exception", "label": _("异常/停止"), "count": exception, "tone": "danger"},
    ]


def _get_primary_bucket(row):
    status = row.get("status")
    docstatus = cint(row.get("docstatus"))
    progress = flt(row.get("per_ordered"))
    if docstatus == 2 or status in {"Stopped", "Cancelled"}:
        return "exception"
    if row.get("transfer_status") == "In Transit":
        return "transit"
    if docstatus == 1 and progress >= 100:
        return "completed"
    if row.get("material_request_type") in ISSUE_TYPES and docstatus == 1 and progress <= 0:
        return "to_issue"
    if docstatus == 1 and 0 < progress < 100:
        return "partial"
    return "in_progress"


def _get_progress(row):
    return max(0, min(100, flt(row.get("per_ordered"))))


def _get_status_label(row, bucket):
    labels = {
        "exception": _("已停止/已取消"),
        "transit": _("调拨在途"),
        "completed": _("已完成"),
        "to_issue": _("待发料"),
        "partial": _("部分完成"),
    }
    if bucket in labels:
        return labels[bucket]
    return _("草稿") if cint(row.get("docstatus")) == 0 else _("处理中")


def _get_type_label(request_type):
    return {
        "Material Issue": _("物料发料"),
        "Material Transfer for Manufacture": _("生产领料"),
        "Injection Molding Issuance": _("注塑发料"),
        "Material Transfer": _("物料调拨"),
        "Purchase": _("采购需求"),
        "Manufacture": _("生产需求"),
        "Subcontracting": _("委外需求"),
        "Customer Provided": _("客户提供"),
    }.get(request_type, request_type or _("物料需求"))
