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


def _source(name, write=False):
    doc = frappe.get_doc(DOCTYPE, name, for_update=write)
    doc.check_permission("write" if write else "read")
    required = {"target_company", "purchase_order", "approval_status", "process_instance_id", "process_code",
                "oa_code", "apply_date", "creator", "execution_region", "department", "project", "order_no",
                "currency", "payment_amount", "detail_total_amount", "items_json", "processors_json", "payee",
                "description", "delivery_date", "payments_json", "payment_terms", "payment_date", "attachments_json"}
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
    if doc.get("target_company"):
        _native("Company", doc.target_company)
    elif frappe.session.user != "Administrator" and "System Manager" not in frappe.get_roles():
        frappe.throw("来源公司待确认，请由管理员核对", frappe.PermissionError)
    return doc


def _normalize(row):
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
    return contract.normalize(row, detail_rows=details)


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
    if len(rows) != 1 or not contract.in_scope(rows[0]):
        frappe.throw("采购来源已移出范围或不存在，请核对原单")
    source = _normalize(rows[0])
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


def _bind(doc, order, source, evidence, correction_reason=""):
    _write_fields("Purchase Order",{"custom_oa_purchase_expense"})
    _write_fields(DOCTYPE,{"purchase_order","target_company"})
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
              SOURCE_FIELD:json.dumps(source,ensure_ascii=False,default=str), EVIDENCE_FIELD:json.dumps(evidence,ensure_ascii=False,default=str),
              "source_stale":0, "source_invalid":0, "source_pending":0, "sync_status":"Purchase Order Created"}
    frappe.db.set_value(DOCTYPE,doc.name,values)
    if correction_reason:
        doc.add_comment("Comment", "采购来源人工核对：" + str(correction_reason)[:2000])


@frappe.whitelist(methods=["POST"])
def create_purchase_order_from_source(name, expected_version, company, supplier, currency, schedule_date, items, correction_reason=""):
    doc = _source(name, write=True)
    if doc.get("purchase_order"):
        _native("Purchase Order",doc.purchase_order,"read")
        return {"name":doc.purchase_order,"doctype":"Purchase Order"}
    source, evidence = _fresh_source(doc)
    _assert_current(source,evidence,expected_version)
    if doc.get("target_company") and doc.target_company != company:
        frappe.throw("来源公司与采购订单公司不一致")
    if not company or not supplier or not schedule_date or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(schedule_date)):
        frappe.throw("请明确选择公司、供应商和需求日期")
    _native("Company",company); party = _native("Supplier",supplier); _native("Currency",currency)
    if party.get("disabled"):
        frappe.throw("供应商已停用")
    if not frappe.has_permission("Purchase Order","create"):
        frappe.throw("没有权限新建采购订单",frappe.PermissionError)
    try:
        selected = contract.validate_selection(source,currency,frappe.parse_json(items),correction_reason)
    except ValueError as exc:
        frappe.throw(str(exc))
    _validate_items(selected)
    _write_fields("Purchase Order", {"company","supplier","currency","schedule_date","items"})
    _write_fields("Purchase Order Item", {"item_code","qty","uom","rate","schedule_date"}, "Purchase Order")
    order = frappe.new_doc("Purchase Order")
    order.company,order.supplier,order.currency,order.schedule_date = company,supplier,currency,schedule_date
    order.transaction_date = frappe.utils.nowdate()
    order.set("items",[])
    for row in selected:
        order.append("items",{**row,"schedule_date":schedule_date})
    order.insert()  # Native validation and create permissions; never ignore_permissions.
    _bind(doc,order,source,evidence,correction_reason)
    return {"name":order.name,"doctype":"Purchase Order"}


@frappe.whitelist(methods=["POST"])
def associate_purchase_order(name, purchase_order, expected_version, correction_reason=""):
    doc = _source(name,write=True)
    if doc.get("purchase_order") and doc.purchase_order != purchase_order:
        frappe.throw("来源已关联采购订单，请先核对现有关联")
    source,evidence = _fresh_source(doc)
    _assert_current(source,evidence,expected_version)
    order = frappe.get_doc("Purchase Order",purchase_order,for_update=True)
    order.check_permission("write"); _native("Company",order.company)
    if order.docstatus == 2 or order.status in ("Closed","Cancelled","On Hold"):
        frappe.throw("不能关联已取消、关闭或暂停的订单")
    if doc.get("target_company") and doc.target_company != order.company:
        frappe.throw("来源公司与采购订单公司不一致")
    try:
        contract.validate_selection(source,order.currency,[{k:r.get(k) for k in ("item_code","qty","uom","rate")} for r in order.items],correction_reason)
    except ValueError as exc:
        frappe.throw(str(exc))
    _bind(doc,order,source,evidence,correction_reason)
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
    return {"name":doc.name,"version":version,
            "source":source,"cashier":evidence,"purchase_order":doc.purchase_order,"target_company":doc.target_company,
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
                "payee":source.get("payee"),"target_company":company,"sync_status":"Pending Purchase Order",
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
    if len(cached)>20000:
        frappe.throw("已接入采购来源超过核对上限，请管理员核对")
    for record in cached:
        old=_json(record.get(SOURCE_FIELD))
        if not old or old["source_id"] in seen:
            continue
        rows,_=oa.read_page(connection,1,until,identity=old["oa_identity"],process_codes=contract.PROCESS_CODES)
        if len(rows)==1 and contract.in_scope(rows[0]):
            source=_normalize(rows[0])
        else:
            source=_invalidate_source(old,"关联钉钉采购原单不存在或已移出中国2026范围，请先核对",rows[0] if len(rows)==1 else None)
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
        for _ in range(40):
            rows,cursor = oa.read_page(connection,500,until,cursor=cursor,process_codes=contract.PROCESS_CODES)
            selected = [r for r in rows if contract.in_scope(r)]
            applicants = [oa.resolution_applicant(r,cashier) for r in selected]
            resolutions = _request("/api/integrations/erp/resolve-applicant-companies",data={"applicants":applicants})["items"] if applicants else []
            if len(resolutions) != len(applicants):
                frappe.throw("采购申请人归属数量不符")
            for row,applicant,resolution in zip(selected,applicants,resolutions):
                if any(resolution.get(k) != applicant[k] for k in ("user_id","employee_name")):
                    frappe.throw("采购申请人归属身份不符")
                source = _normalize(row)
                legal = oa.COMPANY_BRIDGES.get(resolution.get("assigned_department")) if resolution.get("status") == "matched" else None
                company = legal if legal and frappe.db.exists("Company",legal) else None
                _cache_source(source,contract.payment_evidence(source,cashier),company); count+=1; seen.add(source["source_id"])
            # Retain previously imported but withdrawn/out-of-scope applications as audit evidence.
            for row in rows:
                if contract.in_scope(row):
                    continue
                doc = _cached_doc({"source_id":oa.application_id(row),"oa_identity":{"corp_id":row["corp_id"],"process_instance_id":row["process_instance_id"]}})
                if doc and doc.get(SOURCE_FIELD):
                    old=_invalidate_source(_json(doc.get(SOURCE_FIELD)),"钉钉采购原单已移出中国2026范围，请先核对",row)
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
    if not doc.get(SOURCE_FIELD) and not (old and old.get(SOURCE_FIELD)):
        return
    protected=(SOURCE_FIELD,EVIDENCE_FIELD,SOURCE_ID_FIELD,BOUND_FIELD,RECONCILIATION_FIELD,"purchase_order","target_company",
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
    parts=["`tabOA Purchase Request`.target_company IN ("+",".join(frappe.db.escape(c) for c in companies)+")"] if companies else []
    if "System Manager" in frappe.get_roles(user): parts.append("COALESCE(`tabOA Purchase Request`.target_company,'')=''")
    restriction="("+" OR ".join(parts)+")" if parts else "1=0"
    return "(COALESCE(`tabOA Purchase Request`.custom_purchase_source_id,'')='' OR "+restriction+")"


def has_permission(doc,user=None,ptype=None):
    # Native role/document permissions are checked separately. A controller
    # hook's None is a denial in Frappe 16, not a neutral result.
    if not doc.get(SOURCE_ID_FIELD): return True
    from frappe.permissions import get_user_permissions
    user=user or frappe.session.user
    if ptype in ("delete","cancel","submit"): return False
    if not doc.target_company: return user == "Administrator" or "System Manager" in frappe.get_roles(user)
    permissions=get_user_permissions(user).get("Company",[])
    return bool(frappe.has_permission("Company","read",doc=doc.target_company,user=user) and (not permissions or doc.target_company in {p.doc for p in permissions}))


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
        frappe.set_user("Administrator")
        sync_purchase_sources()
    finally:
        frappe.set_user(user)
