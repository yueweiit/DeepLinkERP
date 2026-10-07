"""Original procurement evidence attached to the existing OA -> native PO flow.

Source synchronization writes only the evidence cache. Order creation uses the
caller's native permissions and creates a draft, never a receipt/payment/GL.
"""
from __future__ import annotations

import copy
import json
import re
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from decimal import Decimal
from urllib.parse import urlencode

import frappe
from frappe.model import get_permitted_fields

from . import operating_oa_source as oa, purchase_source_contract as contract
from .operating_expense_contract import digest

DOCTYPE = "OA Purchase Request"
SOURCE_FIELD = "custom_purchase_source_json"
EVIDENCE_FIELD = "custom_cashier_payment_evidence"
BOUND_FIELD = "custom_purchase_bound_version"
SOURCE_ID_FIELD = "custom_purchase_source_id"
RECONCILIATION_FIELD = "custom_purchase_payment_reconciliation"
BENEFICIARY_FIELD = "custom_purchase_beneficiary_company"
PROPOSAL_FIELD = "custom_purchase_company_proposal"
PROJECT_FIELD = "custom_purchase_project"
CONFIRMED_FIELD = "custom_purchase_company_confirmed"
CONFIRMED_BY_FIELD = "custom_purchase_company_confirmed_by"
CONFIRMED_ON_FIELD = "custom_purchase_company_confirmed_on"
SOURCE_PAGE_SIZE = 100  # Keep each upstream read below its fixed 10-second deadline.
MAX_SOURCE_ROWS = 20000
_managed = ContextVar("purchase_source_managed", default=False)


@contextmanager
def managed_write():
    token = _managed.set(True)
    try:
        yield
    finally:
        _managed.reset(token)


def _json(value):
    return json.loads(value or "{}") if isinstance(value, str) else dict(value or {})


def _version(source, evidence):
    return digest([source.get("version"), evidence.get("version")])


def _native(doctype, name, permission="read"):
    doc = frappe.get_doc(doctype, name)
    doc.check_permission(permission)
    if doctype == "Company":
        from frappe.permissions import get_user_permissions
        allowed = get_user_permissions(frappe.session.user).get("Company", [])
        if allowed and name not in {p.doc for p in allowed}:
            frappe.throw("无权访问此公司", frappe.PermissionError)
    elif doc.get("company"):
        _native("Company", doc.company)
    return doc


def _write_fields(doctype, fields, parenttype=None):
    allowed = set(get_permitted_fields(doctype, parenttype=parenttype, permission_type="write"))
    meta = frappe.get_meta(doctype)
    levels = set(meta.get_permlevel_access(permission_type="write", parenttype=parenttype))
    allowed.update(f.fieldname for f in meta.fields if f.fieldtype in ("Table","Table MultiSelect") and f.permlevel in levels)
    if not set(fields) <= allowed:
        frappe.throw("没有权限填写完整采购字段", frappe.PermissionError)


def _confirmed_company(doc):
    # A legacy native PO link already identifies the legal purchasing company.
    # An old unbound target_company may only be an applicant-organization hint.
    return doc.get("target_company") if doc.get("purchase_order") or frappe.utils.cint(doc.get(CONFIRMED_FIELD)) else None


def _source(name, write=False):
    doc = frappe.get_doc(DOCTYPE, name, for_update=write)
    doc.check_permission("write" if write else "read")
    required = {"target_company", "purchase_order", "approval_status", "process_instance_id", "process_code",
                "oa_code", "apply_date", "creator", "execution_region", "department", "project", "order_no",
                "currency", "payment_amount", "detail_total_amount", "items_json", "processors_json", "payee",
                "description", "delivery_date", "payments_json", "payment_terms", "payment_date", "attachments_json",
                BENEFICIARY_FIELD, PROPOSAL_FIELD, PROJECT_FIELD, CONFIRMED_FIELD}
    if not required <= set(get_permitted_fields(DOCTYPE, permission_type="read")):
        frappe.throw("没有权限查看完整采购来源", frappe.PermissionError)
    from .purchase_payment_service import _require_fields
    _require_fields(DOCTYPE,{"items","processors","payments"})
    for child,fields in (("OA Purchase Request Item",{"item_code","item_name","specification","qty","uom","amount"}),
                         ("OA Purchase Request Processor",{"processor_name","processor_phone","odt","sales_order_no","processing_materials","qty","unit_price","amount"}),
                         ("OA Purchase Request Payment",{"payee","amount","payment_terms","currency","payment_date"})):
        _require_fields(child,fields,DOCTYPE)
    if not doc.get(SOURCE_FIELD):
        frappe.throw("此采购申请尚未接入原始来源，请先同步核对")
    company = _confirmed_company(doc)
    if company:
        _native("Company", company)
    elif frappe.session.user != "Administrator" and "System Manager" not in frappe.get_roles():
        frappe.throw("来源公司待确认，请由管理员核对", frappe.PermissionError)
    return doc


def _normalize(row, *, occurrences=None):
    # Reuse the existing DingTalk table/text extractor, not a second table parser.
    from overseas_costing.scripts.import_oa_logistics import extract_purchase_expense_rows, _iter_form_components
    from overseas_costing.utils.field_mapper import map_purchase_expense_row_to_item
    prepared = copy.deepcopy(row)
    if isinstance(prepared.get("form_component_values"), str):
        prepared["form_component_values"] = json.loads(prepared["form_component_values"])
    # DingTalk has used both rowValue objects and arrays of cells. Adapt only
    # their envelope; the existing shared extractor still parses every cell.
    for component in _iter_form_components(prepared):
        if (component.get("componentType") or component.get("component_type")) != "TableField":
            continue
        try:
            value=component.get("value")
            rows=json.loads(value) if isinstance(value,str) else value
        except (TypeError,ValueError):
            continue
        if isinstance(rows,list):
            component["value"]=[{"rowValue":r} if isinstance(r,list) else r for r in rows]
    details = [map_purchase_expense_row_to_item(r) for r in extract_purchase_expense_rows(prepared)]
    return contract.normalize(row, detail_rows=details, occurrences=occurrences)


def _cashier_snapshot(until):
    from .operating_expenses import _request
    items, cursor = [], None
    for _ in range(40):
        result = _request("/api/integrations/erp/purchase-expenses", {"limit":500, "until":until, **({"cursor":cursor} if cursor else {})})
        try:
            same_instant = oa.timestamp(result.get("until")) == oa.timestamp(until)
        except (ValueError, TypeError):
            same_instant = False
        if not same_instant:
            frappe.throw("采购出纳快照时间不符")
        items.extend(result["items"])
        if result["end"]:
            if len({i["source_id"] for i in items}) != len(items):
                frappe.throw("采购出纳根标识重复，请管理员核对")
            return items
        if cursor == result["next_cursor"]:
            frappe.throw("采购出纳分页未前进")
        cursor = result["next_cursor"]
    frappe.throw("采购出纳来源超过本次读取上限")


def _fresh_source(doc):
    from .operating_expenses import _oa_connection
    old = _json(doc.get(SOURCE_FIELD))
    until = datetime.now(timezone.utc).isoformat()
    rows, _ = oa.read_page(_oa_connection()._connection, 1, until, identity=old["oa_identity"], process_codes=contract.PROCESS_CODES)
    occurrences = contract._field_occurrences(rows[0]) if len(rows) == 1 else None
    if len(rows) != 1 or not contract.in_scope(rows[0], occurrences=occurrences):
        frappe.throw("采购来源已移出中国/墨西哥2026范围或不存在，请核对原单")
    source = _normalize(rows[0], occurrences=occurrences)
    if source["oa_identity"] != old["oa_identity"]:
        frappe.throw("采购来源身份不符")
    return source, contract.payment_evidence(source, _cashier_snapshot(until))


def _assert_current(source, evidence, expected_version):
    if _version(source, evidence) != expected_version:
        frappe.throw("来源或付款证据已变化，请刷新后重新核对")
    if not source.get("eligible"):
        frappe.throw("采购来源未审批通过、已拒绝或撤销，不能办理")


def _validate_items(items):
    for row in items:
        item = _native("Item", row["item_code"])
        _native("UOM", row["uom"])
        if item.get("disabled") or not item.get("is_purchase_item"):
            frappe.throw("物料必须为启用的采购物料")
        units = {item.stock_uom} | {u.uom for u in item.get("uoms") or []}
        if row["uom"] not in units:
            frappe.throw("采购单位未在物料中维护，请先核对单位换算")


def _validate_buyer_company(doc, company, correction_reason):
    if not doc.get("target_company") or doc.target_company == company:
        return
    if doc.get("purchase_order") or frappe.utils.cint(doc.get(CONFIRMED_FIELD)) or not frappe.utils.cint(doc.get("backfill_imported")):
        frappe.throw("来源公司与采购订单公司不一致")
    if not str(correction_reason or "").strip():
        frappe.throw("原申请组织仅为采购公司建议；更正采购公司请填写核对说明")


def _project_company(project, company):
    meta = frappe.get_meta("Project")
    return bool(meta.has_field("company") and meta.has_field("is_active") and company
                and project.get("company") == company and project.get("is_active") == "Yes")


def _role_candidate(source, key, doctype, company=None):
    """Exact, permission-scoped native matches; duplicate labels stay ambiguous."""
    raw = source.get(key)
    status = source.get(key + "_status") or ("unique" if isinstance(raw, str) and raw.strip() else "missing")
    if status != "unique":
        return {"value":None, "status":status}
    display = "company_name" if doctype == "Company" else "project_name"
    filters = [[doctype,"name","=",raw]]
    if frappe.get_meta(doctype).has_field(display):
        filters.append([doctype,display,"=",raw])
    try:
        candidates = frappe.get_list(doctype, or_filters=filters, fields=["name"], limit_page_length=2)
        if len(candidates) != 1:
            return {"value":None, "status":"ambiguous" if candidates else "unresolved"}
        native = _native(doctype, candidates[0]["name"])
    except frappe.PermissionError:
        return {"value":None, "status":"unreadable"}
    if doctype == "Project" and not _project_company(native, company):
        return {"value":None, "status":"incompatible"}
    return {"value":native.name, "status":"unique"}


def _select_roles(doc, source, company, beneficiary_company=None, project=None):
    values = {}
    for key,doctype,field,explicit in (("beneficiary_company","Company",BENEFICIARY_FIELD,beneficiary_company),
                                       ("project","Project",PROJECT_FIELD,project)):
        if explicit is not None and not isinstance(explicit, str):
            frappe.throw("请明确选择已有受益公司" if key == "beneficiary_company" else "请明确选择已有项目或用空白字符串留空")
        explicit = explicit.strip() if explicit is not None else None
        # Existing verified values survive a newer raw source snapshot.
        chosen = explicit if explicit is not None else doc.get(field)
        if chosen:
            native = _native(doctype, str(chosen).strip())
            if doctype == "Project" and not _project_company(native, company):
                frappe.throw("项目必须启用且明确属于采购公司，请选择有效项目或明确留空")
            values[key] = native.name
            continue
        if explicit is not None and key == "project":
            values[key] = ""  # Explicitly leaving it empty also clears an older verified source link.
            continue
        candidate = _role_candidate(source,key,doctype,company)
        if candidate["status"] == "ambiguous" or (key == "beneficiary_company" and candidate["status"] not in ("unique","missing")):
            frappe.throw("请明确选择已有受益公司" if key == "beneficiary_company" else "项目来源不唯一，请明确选择已有项目或留空")
        values[key] = candidate["value"]
    return values["beneficiary_company"], values["project"]


def _role_projection(doc, source):
    warnings = []
    def visible(doctype, name, label):
        if not name:
            return None
        try:
            return _native(doctype, name).name
        except (frappe.PermissionError, frappe.DoesNotExistError):
            warnings.append(label + "不可访问，请核对已有记录和公司权限")
            return None

    company = _confirmed_company(doc)
    proposal = doc.get(PROPOSAL_FIELD)
    if not proposal and not company and frappe.utils.cint(doc.get("backfill_imported")):
        proposal = doc.get("target_company")  # Preserve the old hint without relabeling it as confirmed.
    proposal = visible("Company", proposal, "建议采购公司")
    beneficiary = _role_candidate(source,"beneficiary_company","Company")
    project = _role_candidate(source,"project","Project",company or proposal)
    if not company:
        warnings.append("采购公司待确认；申请人组织仅为采购公司建议")
    for label,candidate in (("最终使用/销售公司",beneficiary),("来源项目",project)):
        status = candidate["status"]
        if status == "ambiguous":
            warnings.append(label + "来源或候选不唯一，请明确选择已有记录")
        elif status in ("unresolved","unreadable"):
            warnings.append(label + "未能匹配可访问的已有记录，请人工核对")
        elif status == "incompatible":
            warnings.append("来源项目未满足启用及采购公司归属条件；原文保留，原生采购项目留空或选择有效项目")
    return {"purchasing_company":company, "company_confirmed":bool(company), "buyer_company_proposal":proposal,
            "beneficiary_company":visible("Company",doc.get(BENEFICIARY_FIELD),"已确认最终使用/销售公司"),
            "beneficiary_company_candidate":beneficiary["value"], "beneficiary_company_status":beneficiary["status"],
            "project":visible("Project",doc.get(PROJECT_FIELD),"已确认采购项目"),
            "project_candidate":project["value"], "project_status":project["status"], "role_warnings":warnings}


def _role_projections(records, sources, permitted, purchase_orders):
    """Request-local list roles, after the native OA name/field ACL query.

    Source hints are labelled pending evidence. Exact native candidates obey
    record, Company and field permissions, but never become confirmed roles.
    Linked native PO.company is authoritative; proposals cannot assign it.
    Company/Project discovery is batched and each candidate is checked once.
    This read-only projection does not change confirmation or synchronization.
    """
    from .purchase_payment_service import _record_reader, _read, _quiet_link_errors
    from .purchase_order_progress import _ProgressReader, _FieldScope
    from .purchase_fulfilment_service import _company
    records = list(records)
    reader = _record_reader.get() or _ProgressReader(get_permitted_fields); token = _record_reader.set(reader)
    try:
        native_fields = {dt: reader.fields.permitted(dt) if isinstance(reader.fields, _FieldScope) else
            set(get_permitted_fields(dt, permission_type="read")) for dt in ("Company", "Project")}
        readable = {dt: bool(frappe.has_permission(dt, "read")) for dt in native_fields}
        metadata = {dt: frappe.get_meta(dt) for dt in native_fields}
        tokens = {"Company": set(), "Project": set()}
        direct = {"Company": set(), "Project": set()}
        forward_companies = {}
        source_names = {doc["name"] for doc in records}
        for order in purchase_orders.values():
            source_name = order.get("custom_oa_purchase_expense")
            if source_name in source_names:
                companies = forward_companies.setdefault(source_name, set())
                if order.get("company"):
                    companies.add(order["company"])
        def purchasing_company(doc):
            linked = doc.get("purchase_order")
            if linked and linked in purchase_orders:
                return purchase_orders[linked].get("company")
            if doc["name"] in forward_companies:
                companies = forward_companies[doc["name"]]
                return next(iter(companies)) if len(companies) == 1 else None
            return doc.get("target_company") if not linked and doc.get(CONFIRMED_FIELD) in (True, 1, "1") else None
        for doc in records:
            source = sources.get(doc["name"], {})
            for key, dt, field in (("beneficiary_company", "Company", BENEFICIARY_FIELD), ("project", "Project", PROJECT_FIELD)):
                raw = source.get(key)
                if field in permitted and isinstance(raw, str) and raw.strip():
                    tokens[dt].add(raw)
                if doc.get(field):
                    direct[dt].add(doc[field])
            direct["Company"].update(value for value in (doc.get("target_company"), doc.get(PROPOSAL_FIELD),
                purchasing_company(doc)) if value)
        indexes = {dt: {} for dt in tokens}
        for dt, values in tokens.items():
            allowed = native_fields[dt]
            display = "company_name" if dt == "Company" else "project_name"
            if values and "name" in allowed and readable[dt]:
                conditions = [[dt, "name", "in", list(values)]]
                fields = ["name"]
                if display in allowed and metadata[dt].has_field(display):
                    conditions.append([dt, display, "in", list(values)]); fields.append(display)
                with _quiet_link_errors():
                    try:
                        found = frappe.get_list(dt, or_filters=conditions, fields=fields, limit_page_length=0)
                    except frappe.PermissionError:
                        found = []
                for row in found:
                    direct[dt].add(row["name"])
                    for key in fields:
                        value = row.get(key)
                        if value in values:
                            indexes[dt].setdefault(value, set()).add(row["name"])
            reader.preload(dt, direct[dt])
        reader.preload("Company", {doc.company for (dt, _), doc in reader.docs.items() if dt == "Project" and doc and doc.get("company")})
        visible_cache = {}
        def visible(dt, name):
            if not name or "name" not in native_fields[dt] or not readable[dt]:
                return None
            key = (dt, name)
            if key not in visible_cache:
                with _quiet_link_errors():
                    try:
                        doc = _company(name) if dt == "Company" else _read(dt, name)
                        if dt == "Project" and doc.get("company"):
                            _company(doc.company)
                        visible_cache[key] = doc
                    except (frappe.PermissionError, frappe.DoesNotExistError):
                        visible_cache[key] = None
            return visible_cache[key]
        def candidate(source, key, dt, company):
            raw = source.get(key)
            status = source.get(key + "_status") or ("unique" if isinstance(raw, str) and raw.strip() else "missing")
            if status != "unique":
                return {"value": None, "status": status}
            matches = indexes[dt].get(raw, set())
            if len(matches) != 1:
                return {"value": None, "status": "ambiguous" if matches else "unresolved"}
            name = next(iter(matches)); doc = visible(dt, name)
            if doc is None:
                return {"value": None, "status": "unreadable"}
            if dt == "Project" and (not {"company", "is_active"} <= native_fields[dt] or
                    not metadata[dt].has_field("company") or not metadata[dt].has_field("is_active") or
                    not company or doc.get("company") != company or doc.get("is_active") != "Yes"):
                return {"value": None, "status": "incompatible"}
            return {"value": name, "status": "unique"}
        result = {}
        for doc in records:
            source = sources.get(doc["name"], {}); warnings = []
            company = purchasing_company(doc)
            company_doc = visible("Company", company)
            company = company_doc.name if company_doc else None
            proposal = doc.get(PROPOSAL_FIELD)
            if not proposal and not company and doc.get("backfill_imported"):
                proposal = doc.get("target_company")
            proposal_doc = visible("Company", proposal)
            role = {"purchasing_company": company, "company_confirmed": bool(company),
                "buyer_company_proposal": proposal_doc.name if proposal_doc else None, "source_hint_label": "来源待核对"}
            if not company:
                warnings.append("采购公司待确认；申请人组织仅为采购公司建议")
            for key, dt, field in (("beneficiary_company", "Company", BENEFICIARY_FIELD), ("project", "Project", PROJECT_FIELD)):
                permitted_source = source if field in permitted else {}
                match = candidate(permitted_source, key, dt, company)
                confirmed = visible(dt, doc.get(field)) if field in permitted else None
                if dt == "Project" and not {"company", "is_active"} <= native_fields[dt]:
                    confirmed = None
                role.update({key: confirmed.name if confirmed else None, key + "_candidate": match["value"],
                    key + "_status": match["status"], "source_" + key + "_hint": permitted_source.get(key)})
                if match["status"] in ("ambiguous", "unresolved", "unreadable", "incompatible"):
                    warnings.append(("最终归属" if dt == "Company" else "来源项目") + "待核对已有记录、权限及项目归属")
                if doc.get(field) and not confirmed:
                    warnings.append("已确认角色不可访问，请核对已有记录和公司权限")
            role["beneficiary_companies"] = [role["beneficiary_company"]] if role["beneficiary_company"] else []
            role["role_warnings"] = warnings
            result[doc["name"]] = role
        return result
    finally:
        _record_reader.reset(token)


def _bind(doc, order, source, evidence, correction_reason="", *, beneficiary_company=None, project=None):
    _write_fields("Purchase Order",{"custom_oa_purchase_expense"})
    role_values = {key:value for key,value in ((BENEFICIARY_FIELD,beneficiary_company),(PROJECT_FIELD,project)) if value is not None}
    _write_fields(DOCTYPE,{"purchase_order","target_company", *role_values})
    if order.get("custom_oa_purchase_expense") not in (None,"",doc.name):
        frappe.throw("采购订单已关联另一条钉钉申请")
    if not order.meta.has_field("custom_oa_purchase_expense"):
        frappe.throw("采购关联字段未安装，请联系管理员")
    # Rechecking the same link updates source evidence only, not the native PO.
    if order.get("custom_oa_purchase_expense") != doc.name:
        if order.docstatus == 1 and not order.meta.get_field("custom_oa_purchase_expense").allow_on_submit:
            frappe.throw("该已提交订单不允许更新采购关联，请先核对元数据策略")
        order.custom_oa_purchase_expense=doc.name
        with managed_write():
            order.save()  # Native permissions/update-after-submit still apply.
    values = {"purchase_order":order.name, "target_company":order.company, BOUND_FIELD:source["version"],
              CONFIRMED_FIELD:1, CONFIRMED_BY_FIELD:frappe.session.user, CONFIRMED_ON_FIELD:frappe.utils.now_datetime(), **role_values,
              SOURCE_FIELD:json.dumps(source,ensure_ascii=False,default=str), EVIDENCE_FIELD:json.dumps(evidence,ensure_ascii=False,default=str),
              "source_stale":0, "source_invalid":0, "source_pending":0, "sync_status":"Purchase Order Created"}
    frappe.db.set_value(DOCTYPE,doc.name,values)
    if correction_reason:
        doc.add_comment("Comment", "采购来源人工核对：" + str(correction_reason)[:2000])


@frappe.whitelist(methods=["POST"])
def create_purchase_order_from_source(name, expected_version, company, supplier, currency, schedule_date, items, correction_reason="", beneficiary_company=None, project=None):
    doc = _source(name, write=True)
    if doc.get("purchase_order"):
        _native("Purchase Order",doc.purchase_order,"read")
        return {"name":doc.purchase_order,"doctype":"Purchase Order"}
    source, evidence = _fresh_source(doc)
    _assert_current(source,evidence,expected_version)
    _validate_buyer_company(doc,company,correction_reason)
    if not company or not supplier or not schedule_date or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(schedule_date)):
        frappe.throw("请明确选择公司、供应商和需求日期")
    _native("Company",company); party = _native("Supplier",supplier); _native("Currency",currency)
    if party.get("disabled"):
        frappe.throw("供应商已停用")
    if not frappe.has_permission("Purchase Order","create"):
        frappe.throw("没有权限新建采购订单",frappe.PermissionError)
    selected_beneficiary,selected_project = _select_roles(doc,source,company,beneficiary_company,project)
    try:
        selected = contract.validate_selection(source,currency,frappe.parse_json(items),correction_reason)
    except ValueError as exc:
        frappe.throw(str(exc))
    _validate_items(selected)
    fields = {"company","supplier","currency","schedule_date","items"}
    if selected_project:
        if not frappe.get_meta("Purchase Order").has_field("project"):
            frappe.throw("采购订单项目字段未安装，请联系管理员")
        fields.add("project")
    _write_fields("Purchase Order", fields)
    _write_fields("Purchase Order Item", {"item_code","qty","uom","rate","schedule_date"}, "Purchase Order")
    order = frappe.new_doc("Purchase Order")
    order.company,order.supplier,order.currency,order.schedule_date = company,supplier,currency,schedule_date
    if selected_project:
        order.project = selected_project
    order.transaction_date = frappe.utils.nowdate()
    order.set("items",[])
    for row in selected:
        order.append("items",{**row,"schedule_date":schedule_date})
    order.insert()  # Native validation and create permissions; never ignore_permissions.
    _bind(doc,order,source,evidence,correction_reason,beneficiary_company=selected_beneficiary,project=selected_project)
    return {"name":order.name,"doctype":"Purchase Order"}


@frappe.whitelist(methods=["POST"])
def associate_purchase_order(name, purchase_order, expected_version, correction_reason="", beneficiary_company=None, project=None):
    doc = _source(name,write=True)
    if doc.get("purchase_order") and doc.purchase_order != purchase_order:
        frappe.throw("来源已关联采购订单，请先核对现有关联")
    source,evidence = _fresh_source(doc)
    _assert_current(source,evidence,expected_version)
    order = frappe.get_doc("Purchase Order",purchase_order,for_update=True)
    order.check_permission("write"); _native("Company",order.company)
    if order.docstatus == 2 or order.status in ("Closed","Cancelled","On Hold"):
        frappe.throw("不能关联已取消、关闭或暂停的订单")
    _validate_buyer_company(doc,order.company,correction_reason)
    native_project = order.get("project") or ""
    if project is not None and str(project).strip() != native_project:
        frappe.throw("请先在已有采购订单核对项目；关联入口不会改写订单项目")
    selected_beneficiary,selected_project = _select_roles(doc,source,order.company,beneficiary_company,native_project)
    try:
        contract.validate_selection(source,order.currency,[{k:r.get(k) for k in ("item_code","qty","uom","rate")} for r in order.items],correction_reason)
    except ValueError as exc:
        frappe.throw(str(exc))
    _bind(doc,order,source,evidence,correction_reason,beneficiary_company=selected_beneficiary,project=selected_project)
    return {"name":order.name,"doctype":"Purchase Order"}


@frappe.whitelist()
def get_purchase_source_detail(name, fresh=0):
    doc = _source(name)
    source = _json(doc.get(SOURCE_FIELD)); evidence = _json(doc.get(EVIDENCE_FIELD))
    if frappe.utils.cint(fresh):
        # Explicit re-read only: no synchronization or native-document writes.
        source,evidence=_fresh_source(doc)
    version=_version(source,evidence)
    source["source_url"] = "https://aflow.dingtalk.com/dingtalk/mobile/homepage.htm?" + urlencode({"procInstId":source["oa_identity"]["process_instance_id"]})
    from .unified_purchase_service import cashier_evidence_readable
    readable = cashier_evidence_readable()
    finance = frappe.session.user == "Administrator" or bool({"Accounts User","Accounts Manager"} & set(frappe.get_roles()))
    if not readable:
        evidence = {"payment_evidence_status":"hidden", "paid_amount":None,"issues":["没有权限查看出纳付款证据"]}
    else:
        evidence = {**evidence,"attachments":[{**a,"attachment_id":a.get("source_id"),"downloadable":bool(finance and re.fullmatch(r"/api/integrations/erp/purchase-expenses/(attachments|payment-vouchers)/[1-9][0-9]{0,18}",a.get("url") or ""))} for a in evidence.get("attachments",[])]}
    reconciliation=_json(doc.get(RECONCILIATION_FIELD))
    reconciled=bool(readable and reconciliation.get("verified") and reconciliation.get("evidence_version")==evidence.get("version"))
    notice="已核对对应 ERP 付款记录；再次付款仍会复查有效状态" if reconciled else "历史付款尚未核对为 ERP 入账；不会自动补记付款"
    roles = _role_projection(doc,source)
    return {"name":doc.name,"version":version,
            "source":source,"cashier":evidence,"purchase_order":doc.purchase_order,
            "target_company":roles["purchasing_company"] or roles["buyer_company_proposal"], **roles,
            "can_write":doc.has_permission("write"),"can_create":frappe.has_permission("Purchase Order","create"),
            "reconciliation_notice":notice if readable else None,
            "can_reconcile":bool(doc.purchase_order and doc.has_permission("write") and readable and finance)}


@frappe.whitelist()
def download_source_attachment(name, attachment_id, version):
    from .operating_expenses import _finance,_request
    _finance(); doc = _source(name)
    from .unified_purchase_service import cashier_evidence_readable
    if not cashier_evidence_readable():
        frappe.throw("没有权限查看出纳付款证据",frappe.PermissionError)
    source,evidence = _fresh_source(doc)
    candidates = [a for a in evidence.get("attachments",[]) if a.get("source_id") == attachment_id and a.get("version") == version]
    if len(candidates) != 1:
        frappe.throw("附件不存在或已变化，请刷新核对")
    file = candidates[0]; path = file.get("url") or ""
    if not re.fullmatch(r"/api/integrations/erp/purchase-expenses/(attachments|payment-vouchers)/[1-9][0-9]{0,18}",path):
        frappe.throw("附件路径无效，请在钉钉原单核对")
    frappe.response.update(type="download",filename=frappe.utils.strip_html(file.get("filename") or "附件"),filecontent=_request(path,download=True))


def _cached_doc(source):
    name = frappe.db.get_value(DOCTYPE,{SOURCE_ID_FIELD:source["source_id"]},"name")
    if name:
        return frappe.get_doc(DOCTYPE,name,for_update=True)
    candidates=frappe.get_all(DOCTYPE,filters={"process_instance_id":source["oa_identity"]["process_instance_id"]},fields=["name"],limit_page_length=2)
    if len(candidates)>1:
        frappe.throw("本地采购来源实例重复，不能自动选取关联；请管理员核对")
    name=candidates[0].name if candidates else None
    if name:
        if source.get("instance_count",1) != 1:
            frappe.throw("旧采购来源企业身份不唯一，不能自动绑定")
        doc = frappe.get_doc(DOCTYPE,name,for_update=True)
        old = _json(doc.get(SOURCE_FIELD))
        if old.get("oa_identity") and old["oa_identity"] != source["oa_identity"]:
            frappe.throw("旧采购来源身份冲突")
        return doc
    return None


def _cache_source(source,evidence,company=None):
    doc = _cached_doc(source)
    values = {SOURCE_ID_FIELD:source["source_id"],SOURCE_FIELD:json.dumps(source,ensure_ascii=False,default=str),
              EVIDENCE_FIELD:json.dumps(evidence,ensure_ascii=False,default=str),"approval_status":source.get("status"),
              "source_invalid":int(not source.get("eligible")),"source_pending":int(source.get("status") != "COMPLETED")}
    if doc:
        values["source_stale"] = int(bool(doc.get(BOUND_FIELD) and doc.get(BOUND_FIELD) != source["version"]))
        frappe.db.set_value(DOCTYPE,doc.name,values,update_modified=False)
        return doc.name
    doc = frappe.new_doc(DOCTYPE)
    doc.update({**values,"process_instance_id":source["process_instance_id"],"process_code":source["process_code"],
                # Frappe field:oa_code keeps this equal to the internal document name.
                # The immutable original approval number remains in SOURCE_FIELD.
                "oa_code":"DT-PUR-"+digest(source["source_id"]),"apply_date":source["apply_date"],"creator":source.get("originator_user_name"),
                "execution_region":source.get("region"),"currency":source.get("currency"),"description":source.get("description"),
                "payee":source.get("payee"),"target_company":None,PROPOSAL_FIELD:company,CONFIRMED_FIELD:0,"sync_status":"Pending Purchase Order",
                "backfill_imported":1,"items_json":json.dumps(source["items"],ensure_ascii=False),"detail_total_amount":source.get("detail_total_amount"),
                "payment_amount":source.get("requested_amount")})
    with managed_write():
        doc.insert(ignore_permissions=True,set_name="DT-PUR-"+digest(source["source_id"]))  # Source cache only, exact identity name.
    return doc.name


def _invalidate_source(source,reason,row=None):
    source=copy.deepcopy(source)
    source.update(eligible=False,issues=list(dict.fromkeys([*(source.get("issues") or []),reason])))
    if row:
        source.update(status=row.get("status"),result=row.get("result"),updated_at=str(row.get("updated_at") or ""))
    source.pop("version",None)
    source["version"]=digest(source)
    return source


def _reconcile_cached_sources(connection,until,seen,cashier):
    # A source moved outside the year/template, or physically removed upstream,
    # must not remain actionable merely because it disappeared from the scan.
    # Preserve originals and all manual native fields; only invalidate the cache.
    cached=frappe.get_all(DOCTYPE,filters={SOURCE_ID_FIELD:["!=",""]},fields=["name",SOURCE_FIELD],limit_page_length=0)
    if len(cached)>MAX_SOURCE_ROWS:
        frappe.throw("已接入采购来源超过核对上限，请管理员核对")
    for record in cached:
        old=_json(record.get(SOURCE_FIELD))
        if not old or old["source_id"] in seen:
            continue
        rows,_=oa.read_page(connection,1,until,identity=old["oa_identity"],process_codes=contract.PROCESS_CODES)
        occurrences = contract._field_occurrences(rows[0]) if len(rows) == 1 else None
        if len(rows)==1 and contract.in_scope(rows[0],occurrences=occurrences):
            source=_normalize(rows[0],occurrences=occurrences)
        else:
            source=_invalidate_source(old,"关联钉钉采购原单不存在或已移出中国/墨西哥2026范围，请先核对",rows[0] if len(rows)==1 else None)
        _cache_source(source,contract.payment_evidence(source,cashier))


@frappe.whitelist(methods=["POST"])
def sync_purchase_sources():
    from .operating_expenses import _manager,_oa_connection,_request
    _manager()
    if not frappe.db.exists("DocType",DOCTYPE) or not frappe.get_meta(DOCTYPE).has_field(SOURCE_FIELD):
        frappe.throw("采购来源元数据未安装")
    until = datetime.now(timezone.utc).isoformat(); count=0; cursor=None; seen=set()
    with frappe.cache.lock("purchase-source-sync:"+frappe.local.site,timeout=300):
        cashier = _cashier_snapshot(until)
        connection=_oa_connection()._connection
        bridge_companies = set(frappe.get_all("Company", filters={"name":["in",sorted(set(oa.COMPANY_BRIDGES.values()))]}, pluck="name"))
        for _ in range(MAX_SOURCE_ROWS // SOURCE_PAGE_SIZE):
            rows,cursor = oa.read_page(connection,SOURCE_PAGE_SIZE,until,cursor=cursor,process_codes=contract.PROCESS_CODES)
            prepared = [(row,contract._field_occurrences(row)) for row in rows]
            scoped = [(row,occurrences,contract.in_scope(row,occurrences=occurrences)) for row,occurrences in prepared]
            selected = [(row,occurrences) for row,occurrences,in_scope in scoped if in_scope]
            applicants = [oa.resolution_applicant(row,cashier) for row,_ in selected]
            resolutions = _request("/api/integrations/erp/resolve-applicant-companies",data={"applicants":applicants})["items"] if applicants else []
            if len(resolutions) != len(applicants):
                frappe.throw("采购申请人归属数量不符")
            for (row,occurrences),applicant,resolution in zip(selected,applicants,resolutions):
                if any(resolution.get(k) != applicant[k] for k in ("user_id","employee_name")):
                    frappe.throw("采购申请人归属身份不符")
                source = _normalize(row,occurrences=occurrences)
                legal = oa.COMPANY_BRIDGES.get(resolution.get("assigned_department")) if resolution.get("status") == "matched" else None
                company = legal if legal in bridge_companies else None
                _cache_source(source,contract.payment_evidence(source,cashier),company); count+=1; seen.add(source["source_id"])
            # Retain previously imported but withdrawn/out-of-scope applications as audit evidence.
            for row,_,in_scope in scoped:
                if in_scope:
                    continue
                doc = _cached_doc({"source_id":oa.application_id(row),"oa_identity":{"corp_id":row["corp_id"],"process_instance_id":row["process_instance_id"]}})
                if doc and doc.get(SOURCE_FIELD):
                    old=_invalidate_source(_json(doc.get(SOURCE_FIELD)),"钉钉采购原单已移出中国/墨西哥2026范围，请先核对",row)
                    _cache_source(old,contract.payment_evidence(old,cashier))
                    seen.add(old["source_id"])
            if cursor is None:
                _reconcile_cached_sources(connection,until,seen,cashier)
                return {"count":count,"until":until}
        frappe.throw("采购來源超过本次同步上限")


def cashier_payment_reason(evidence,reconciliation=None):
    if reconciliation and reconciliation.get("verified"):
        return ""
    paid=contract.oa.exact_amount(evidence.get("paid_amount"))
    if evidence.get("payment_evidence_status") != "recorded" or paid is None:
        return "出纳付款证据待核对，快捷付款已禁用；请先核对历史付款"
    if Decimal(paid)>0:
        return "存在出纳历史付款，请先核对并关联 ERP 付款记录，避免重复付款"
    return ""


def _verify_reconciliation(doc,evidence,names):
    from .purchase_payment_service import _read,_invoice_names,_invoice_row,PI_FIELDS
    if not isinstance(names,list) or not names or len(names)>100 or len(set(names))!=len(names) or any(not isinstance(n,str) for n in names):
        frappe.throw("请明确选择不重复的原生付款单")
    if evidence.get("payment_evidence_status") != "recorded" or contract.oa.exact_amount(evidence.get("paid_amount")) is None:
        frappe.throw("出纳付款证据未确认，不能核对为已入账")
    order=_native("Purchase Order",doc.purchase_order)
    invoices=set(_invoice_names("Purchase Order",order.name)); allocated=Decimal(0)
    for name in names:
        pe=_read("Payment Entry",name,{"company","party","party_type","payment_type","references","paid_from_account_currency","paid_to_account_currency","docstatus"})
        from .purchase_payment_service import _require_fields
        _require_fields("Payment Entry Reference",{"reference_doctype","reference_name","allocated_amount"},"Payment Entry")
        if (pe.docstatus!=1 or pe.payment_type!="Pay" or pe.party_type!="Supplier" or pe.party!=order.supplier
            or pe.company!=order.company or pe.paid_from_account_currency!=evidence.get("currency") or pe.paid_to_account_currency!=evidence.get("currency")):
            frappe.throw("付款单必须为本公司、本供应商、同币种的已提交付款")
        matched=Decimal(0)
        for ref in pe.references:
            if ref.reference_doctype=="Purchase Order" and ref.reference_name==order.name:
                matched+=Decimal(str(ref.allocated_amount))
            elif ref.reference_doctype=="Purchase Invoice" and ref.reference_name in invoices:
                invoice=_read("Purchase Invoice",ref.reference_name,PI_FIELDS)
                if invoice.docstatus!=1 or invoice.is_return or _invoice_row(invoice,"Purchase Order",order.name)["shared"]:
                    frappe.throw("共享、退货或未提交应付不能核对为本订单历史付款")
                matched+=Decimal(str(ref.allocated_amount))
        if matched<=0:
            frappe.throw("付款单没有明确核销当前采购订单或对应应付")
        allocated+=matched
    if allocated!=Decimal(evidence["paid_amount"]):
        frappe.throw("所选付款核销金额与出纳实付不一致，请先核对，不自动补记或分摊")
    return {"verified":True,"payment_entries":names,"evidence_version":evidence["version"],"amount":str(allocated),"currency":evidence["currency"]}


@frappe.whitelist(methods=["POST"])
def confirm_historical_payments(name,expected_version,payment_entries):
    from .operating_expenses import _finance
    _finance(); doc=_source(name,write=True)
    if not doc.purchase_order:
        frappe.throw("请先明确关联采购订单")
    source,evidence=_fresh_source(doc)
    _assert_current(source,evidence,expected_version)
    reconciliation=_verify_reconciliation(doc,evidence,frappe.parse_json(payment_entries))
    reconciliation.update(confirmed_by=frappe.session.user,confirmed_at=frappe.utils.now())
    frappe.db.set_value(DOCTYPE,doc.name,RECONCILIATION_FIELD,json.dumps(reconciliation,ensure_ascii=False))
    doc.add_comment("Comment","出纳历史付款已核对原生付款记录；本操作未生成、提交或修改付款单")
    return reconciliation


def payment_guard(order):
    name=order.get("custom_oa_purchase_expense")
    if not name or not frappe.get_meta(DOCTYPE).has_field(SOURCE_FIELD):
        return
    cached=frappe.db.get_value(DOCTYPE,name,SOURCE_FIELD)
    if not cached:
        return
    doc=_source(name); source,evidence=_fresh_source(doc)
    if not source.get("eligible") or doc.get(BOUND_FIELD) != source["version"]:
        frappe.throw("采购来源已变化或未通过，请先复核关联")
    reconciliation=_json(doc.get(RECONCILIATION_FIELD))
    if reconciliation.get("evidence_version")==evidence.get("version") and reconciliation.get("payment_entries"):
        reconciliation=_verify_reconciliation(doc,evidence,reconciliation["payment_entries"])
    else:
        reconciliation=None
    reason=cashier_payment_reason(evidence,reconciliation)
    if reason:
        frappe.throw(reason)


def validate_managed_source(doc,method=None):
    if _managed.get():
        return
    old=doc.get_doc_before_save()
    # This flag grants the narrow imported-company correction exception, even
    # if the raw source is attached later. Native defaults None/0 are equivalent.
    flag_values = (None,"",0,1,"0","1")
    if doc.get("backfill_imported") not in flag_values or frappe.utils.cint(doc.get("backfill_imported")) != frappe.utils.cint(old.get("backfill_imported") if old else 0):
        frappe.throw("采购来源导入标记仅允许系统设置",frappe.PermissionError)
    confirmation_changed = doc.get(CONFIRMED_FIELD) not in flag_values or frappe.utils.cint(doc.get(CONFIRMED_FIELD)) != frappe.utils.cint(old.get(CONFIRMED_FIELD) if old else 0)
    confirmation_changed = confirmation_changed or any(
        str(doc.get(field) or "") != str((old.get(field) if old else None) or "")
        for field in (CONFIRMED_BY_FIELD,CONFIRMED_ON_FIELD))
    if confirmation_changed:
        frappe.throw("采购公司确认信息仅允许办理入口设置",frappe.PermissionError)
    if not doc.get(SOURCE_FIELD) and not (old and old.get(SOURCE_FIELD)):
        return
    protected=(SOURCE_FIELD,EVIDENCE_FIELD,SOURCE_ID_FIELD,BOUND_FIELD,RECONCILIATION_FIELD,"purchase_order","target_company",
               BENEFICIARY_FIELD, PROPOSAL_FIELD, PROJECT_FIELD,
               "approval_status","source_invalid","source_pending","source_stale","process_instance_id","process_code")
    if not old or any(old.get(k) != doc.get(k) for k in protected):
        frappe.throw("来源及采购关联请使用采购订单列表的核对入口",frappe.PermissionError)


def protect_managed_source_identity(doc,method=None,*args,**kwargs):
    if doc.get(SOURCE_ID_FIELD) or doc.get(SOURCE_FIELD):
        frappe.throw("已接入的采购来源需保留审计身份，不能重命名或删除",frappe.PermissionError)


def permission_query_conditions(user=None):
    from .operating_expenses import _companies
    user=user or frappe.session.user
    if user == "Administrator": return ""
    companies=_companies(user)
    assigned="(COALESCE(`tabOA Purchase Request`.purchase_order,'')<>'' OR COALESCE(`tabOA Purchase Request`."+CONFIRMED_FIELD+",0)=1)"
    parts=["("+assigned+" AND `tabOA Purchase Request`.target_company IN ("+",".join(frappe.db.escape(c) for c in companies)+"))"] if companies else []
    if "System Manager" in frappe.get_roles(user): parts.append("(NOT "+assigned+" OR COALESCE(`tabOA Purchase Request`.target_company,'')='')")
    restriction="("+" OR ".join(parts)+")" if parts else "1=0"
    return "(COALESCE(`tabOA Purchase Request`.custom_purchase_source_id,'')='' OR "+restriction+")"


def has_permission(doc,user=None,ptype=None):
    # Native role/document permissions are checked separately. A controller
    # hook's None is a denial in Frappe 16, not a neutral result.
    if not doc.get(SOURCE_ID_FIELD): return True
    from frappe.permissions import get_user_permissions
    user=user or frappe.session.user
    if ptype in ("delete","cancel","submit"): return False
    company=_confirmed_company(doc)
    if not company: return user == "Administrator" or "System Manager" in frappe.get_roles(user)
    permissions=get_user_permissions(user).get("Company",[])
    return bool(frappe.has_permission("Company","read",doc=company,user=user) and (not permissions or company in {p.doc for p in permissions}))


@frappe.whitelist(methods=["POST"])
def legacy_create_purchase_order(docname,supplier_name=None,**kwargs):
    # Preserve old public URL but close its unsafe guessed-company/qty1 bypass.
    frappe.throw("请在采购订单列表点击“完善/关联”，明确公司、物料、单位和数量后生成草稿")


def validate_managed_order(order,method=None):
    """Read-only UI metadata cannot protect provenance from native REST saves."""
    if _managed.get():
        return
    old=order.get_doc_before_save()
    before=old.get("custom_oa_purchase_expense") if old else None
    after=order.get("custom_oa_purchase_expense")
    if not (before or after) or not frappe.db.exists("DocType",DOCTYPE) or not frappe.get_meta(DOCTYPE).has_field(SOURCE_ID_FIELD):
        return
    managed=any(frappe.db.get_value(DOCTYPE,name,SOURCE_ID_FIELD) for name in {before,after} if name)
    if managed and (before != after or (old and old.company != order.company)):
        frappe.throw("采购来源关联及公司请使用采购订单列表的核对入口",frappe.PermissionError)


def validate_source_before_submit(order,method=None):
    name=order.get("custom_oa_purchase_expense")
    if not name or not frappe.get_meta(DOCTYPE).has_field(SOURCE_FIELD) or not frappe.db.get_value(DOCTYPE,name,SOURCE_FIELD):
        return
    doc=_source(name); source,_=_fresh_source(doc)
    if not source.get("eligible") or doc.get(BOUND_FIELD)!=source["version"]:
        frappe.throw("采购来源已变化或未审批通过，请先复核关联后再提交")
    if doc.target_company != order.company:
        frappe.throw("采购订单公司与已核对来源不符")


def scheduled_sync():
    if not frappe.conf.get("purchase_source_sync_enabled"):
        return
    user=frappe.session.user
    try:
        import time
        deadline = time.monotonic() + 300  # Share the existing dedicated runner's time budget.
        frappe.set_user("Administrator")
        sync_purchase_sources()
        from .purchase_fulfilment_logistics import refresh_cached_logistics
        refresh_cached_logistics(deadline=deadline)
    finally:
        frappe.set_user(user)
