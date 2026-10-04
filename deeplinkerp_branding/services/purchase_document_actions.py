"""Small, permission checked projections and explicit native procurement actions."""
from __future__ import annotations

import hashlib
import json
import re

import frappe
from frappe.model import get_permitted_fields
from frappe.utils import getdate

from deeplinkerp_branding.services import purchase_payment_service as service

TARGETS = {("Purchase Receipt", "Purchase Invoice"), ("Purchase Order", "Purchase Receipt")}
HEADERS = {"Purchase Invoice": {"posting_date", "bill_no", "bill_date", "remarks"},
           "Purchase Receipt": {"posting_date", "remarks"}}
ITEM_EDITS = {"Purchase Invoice": {"qty", "rate"}, "Purchase Receipt": {"qty", "warehouse"}}
ITEM_FIELDS = {"item_code", "item_name", "qty", "uom", "rate", "warehouse"}
HEADER_FIELDS = {"company", "supplier", "currency", "posting_date", "remarks", "items", "taxes", "net_total", "grand_total"}
TAX_FIELDS = {"charge_type", "account_head", "description", "rate", "tax_amount", "total"}
ADVANCED = "此单据包含共享来源或高级原生设置，请打开原生单据处理"


def _fields(doctype, fields, permission="read", parenttype=None):
    fields = {field for field in fields if frappe.get_meta(doctype).has_field(field)}
    if permission == "read":
        service._require_fields(doctype, fields, parenttype)
    else:
        permitted = set(get_permitted_fields(doctype, parenttype=parenttype, permission_type=permission))
        levels = set(frappe.get_meta(doctype).get_permlevel_access(permission_type=permission, parenttype=parenttype))
        permitted.update(df.fieldname for df in frappe.get_meta(doctype).fields
                         if df.fieldtype == "Table" and df.permlevel in levels)
        if not fields <= permitted:
            frappe.throw("没有编辑所选字段的权限", frappe.PermissionError)
    return fields


def _version(doc, expected):
    if not expected or str(doc.modified) != str(expected):
        frappe.throw("单据已改变，请刷新抽屉后重试")


def _locked(doctype, name):
    doc = frappe.get_doc(doctype, name, for_update=True)
    doc.check_permission("read")
    if doc.get("company"):
        service._read("Company", doc.company)
    return doc


def _workflow_actions(doc):
    from frappe.model.workflow import get_transitions, get_workflow, get_workflow_name, has_approval_access
    if doc.doctype == "Purchase Receipt" or doc.is_new() or doc.docstatus != 0:
        return []
    if get_workflow_name(doc.doctype):
        _fields(doc.doctype, {get_workflow(doc.doctype).workflow_state_field})
        return [row.action for row in get_transitions(doc)
                if has_approval_access(frappe.session.user, doc, row)]
    return ["Submit"] if doc.has_permission("submit") and doc.doctype in ("Purchase Invoice", "Payment Entry") else []


def _editable_fields(doc, fields, parenttype=None):
    permitted = []
    for field in sorted(fields):
        try:
            with service._quiet_link_errors():
                _fields(doc.doctype, {field}, "write", parenttype)
            permitted.append(field)
        except frappe.PermissionError:
            pass
    return permitted


def _key(row, target):
    return row.get("pr_detail" if target == "Purchase Invoice" else "purchase_order_item")


def _native(source, target):
    if (source.doctype, target) not in TARGETS:
        frappe.throw("不支持此来源和目标单据")
    if source.docstatus != 1 or source.get("is_return"):
        frappe.throw("来源必须已提交且非退货")
    _fields(source.doctype, HEADER_FIELDS)
    _fields("Purchase Taxes and Charges", TAX_FIELDS, parenttype=source.doctype)
    _fields(target, HEADER_FIELDS | HEADERS[target])
    _fields(target + " Item", ITEM_FIELDS | {"pr_detail", "purchase_order_item"}, parenttype=target)
    _fields("Purchase Taxes and Charges", TAX_FIELDS, parenttype=target)
    source_fields = {"qty", "rate", "uom", "item_code", "item_name", "warehouse"}
    source_fields |= {"received_qty", "delivered_by_supplier"} if target == "Purchase Receipt" else {"rejected_qty", "received_qty"}
    _fields(source.doctype + " Item", source_fields, parenttype=source.doctype)
    if target == "Purchase Invoice":
        from erpnext.stock.doctype.purchase_receipt.purchase_receipt import make_purchase_invoice
        return make_purchase_invoice(source.name)
    from erpnext.buying.doctype.purchase_order.purchase_order import make_purchase_receipt
    return make_purchase_receipt(source.name)


def _current_maximum(source, target):
    """Current-read cap under the source lock; native maker still owns mapping/taxes.

    ERPNext PR's get_pending_qty is a local closure. Its rejected/returned quantity
    adjustment is mirrored here because its helper queries are snapshot reads.
    Quantities stay in each native source row's UOM, never converted independently.
    """
    if target == "Purchase Receipt":
        return {row.name: max(service.amount(0), service.amount(row.qty) - service.amount(row.received_qty))
                for row in source.items if not row.get("delivered_by_supplier")}
    billed = {}
    service._require_fields("Purchase Invoice Item", {"pr_detail", "qty"}, "Purchase Invoice")
    service._require_fields("Purchase Receipt Item", {"purchase_receipt_item", "qty"}, "Purchase Receipt")
    for row in frappe.db.get_values("Purchase Invoice Item", {"purchase_receipt": source.name, "docstatus": 1},
                                   ["pr_detail", "qty"], as_dict=True, for_update=True):
        billed[row.pr_detail] = billed.get(row.pr_detail, service.amount(0)) + service.amount(row.qty)
    parents = frappe.db.get_values("Purchase Receipt", {"return_against": source.name, "is_return": 1, "docstatus": 1},
                                   ["name"], as_dict=True, for_update=True)
    returned = {}
    if parents:
        for row in frappe.db.get_values("Purchase Receipt Item", {"parent": ["in", [row.name for row in parents]],
                "parenttype": "Purchase Receipt", "parentfield": "items"},
                ["purchase_receipt_item", "qty"], as_dict=True, for_update=True):
            returned[row.purchase_receipt_item] = returned.get(row.purchase_receipt_item, service.amount(0)) + abs(service.amount(row.qty))
    rejected = frappe.db.get_single_value("Buying Settings", "bill_for_rejected_quantity_in_purchase_invoice")
    result = {}
    for row in source.items:
        qty = service.amount(row.received_qty if rejected else row.qty) - billed.get(row.name, service.amount(0))
        if not rejected:
            returned_qty = returned.get(row.name, service.amount(0))
            if row.rejected_qty and returned_qty:
                returned_qty -= service.amount(row.rejected_qty)
            if returned_qty:
                qty = max(service.amount(0), qty - returned_qty)
        result[row.name] = max(service.amount(0), qty)
    return result


def _current_drafts(source):
    service._require_fields("Purchase Invoice", {"items"})
    service._require_fields("Purchase Invoice Item", {"purchase_receipt"}, "Purchase Invoice")
    parents = frappe.db.get_values("Purchase Invoice Item", {"purchase_receipt": source.name, "docstatus": 0},
                                  ["parent"], as_dict=True, distinct=True, for_update=True)
    for row in parents:
        with service._quiet_link_errors():
            try:
                doc = _locked("Purchase Invoice", row.parent)
            except (frappe.DoesNotExistError, frappe.PermissionError):
                frappe.throw(service.LINK_WARNING)
        if doc.docstatus == 0:
            return True
    return False


def _source(source_doctype, source_name):
    source = service._source(source_doctype, source_name)
    chain = service.get_purchase_chain(source_doctype, source_name, include_payments=False)
    if chain["incomplete_links"]:
        frappe.throw(service.LINK_WARNING)
    return source, chain


def _advanced(doc, source):
    field = "purchase_receipt" if doc.doctype == "Purchase Invoice" else "purchase_order"
    _fields(doc.doctype + " Item", {field}, parenttype=doc.doctype)
    return bool(doc.get("is_return") or doc.get("update_stock") or doc.get("is_subcontracted")
                or any(row.get(field) != source.name for row in doc.items)
                or len({_key(row, doc.doctype) for row in doc.items}) != len(doc.items))


def _projection(doc, maximum=None, source=None):
    fields = _fields(doc.doctype, HEADER_FIELDS | HEADERS[doc.doctype])
    item_fields = _fields(doc.doctype + " Item", ITEM_FIELDS | {"pr_detail", "purchase_order_item"}, parenttype=doc.doctype)
    tax_fields = _fields("Purchase Taxes and Charges", TAX_FIELDS, parenttype=doc.doctype)
    out = {field: doc.get(field) for field in fields - {"items", "taxes"}}
    out.update(doctype=doc.doctype, name=None if doc.is_new() else doc.name,
               modified=doc.get("modified"), docstatus=doc.docstatus,
               items=[{**{field: row.get(field) for field in item_fields - {"pr_detail", "purchase_order_item"}},
                       "key": _key(row, doc.doctype), "max_qty": (maximum or {}).get(_key(row, doc.doctype), row.qty)} for row in doc.items],
               taxes=[{field: row.get(field) for field in tax_fields} for row in doc.get("taxes", [])],
               allowed_actions=_workflow_actions(doc))
    advanced = bool(source and _advanced(doc, source))
    if advanced:
        out["allowed_actions"] = []
    can_edit = bool(not advanced and doc.docstatus == 0 and doc.has_permission("create" if doc.is_new() else "write"))
    return {"document": out, "editable_fields": _editable_fields(doc, HEADERS[doc.doctype]) if can_edit else [],
            "editable_item_fields": _editable_fields(doc.items[0], ITEM_EDITS[doc.doctype], doc.doctype) if can_edit and doc.items else [],
            "allowed_actions": out["allowed_actions"], "advanced_reason": ADVANCED if advanced else ""}


@frappe.whitelist()
def preview_document(source_doctype, source_name, target_doctype, target_name=None):
    source, chain = _source(source_doctype, source_name)
    if (source_doctype, target_doctype) not in TARGETS:
        frappe.throw("不支持此来源和目标单据")
    if target_name:
        doc = service._read(target_doctype, target_name, HEADER_FIELDS)
        if doc.company != source.company or doc.supplier != source.supplier:
            frappe.throw("来源公司或供应商不一致")
        linkfield = "purchase_receipt" if target_doctype == "Purchase Invoice" else "purchase_order"
        _fields(target_doctype + " Item", {linkfield}, parenttype=target_doctype)
        if not any(row.get(linkfield) == source_name for row in doc.items):
            frappe.throw("目标单据与来源无关联")
        if doc.docstatus != 0 or _advanced(doc, source):
            return _projection(doc, source=source)
    else:
        if target_doctype == "Purchase Invoice" and chain["draft_invoices"]:
            frappe.throw("已有应付草稿，请选择继续编辑")
        doc = None
    native = _native(source, target_doctype)
    maximum = {_key(row, target_doctype): row.qty for row in native.items}
    return _projection(doc or native, maximum, source)


def _changes(value):
    value = frappe.parse_json(value) if isinstance(value, str) else value
    if not isinstance(value, dict):
        frappe.throw("修改内容必须为对象")
    return value


def _edit_document(doc, changes, maximum):
    allowed = HEADERS[doc.doctype] | {"items"}
    if set(changes) - allowed:
        frappe.throw("包含不支持的字段，请在原生单据处理")
    _fields(doc.doctype, set(changes), "write")
    for field in HEADERS[doc.doctype] & changes.keys():
        value = changes[field]
        doc.set(field, getdate(value) if field.endswith("date") and value else value)
    edits = changes.get("items", [])
    if not isinstance(edits, list):
        frappe.throw("明细修改必须为列表")
    by_key = {_key(row, doc.doctype): row for row in doc.items}
    seen = set()
    for edit in edits:
        if not isinstance(edit, dict) or set(edit) - (ITEM_EDITS[doc.doctype] | {"key"}):
            frappe.throw("包含不支持的明细字段")
        key = edit.get("key")
        if key not in by_key or key in seen:
            frappe.throw("来源明细无效或重复")
        seen.add(key)
        _fields(doc.doctype + " Item", set(edit) - {"key"}, "write", doc.doctype)
        row = by_key[key]
        for field in ITEM_EDITS[doc.doctype] & edit.keys():
            row.set(field, float(service.amount(edit[field])) if field in ("qty", "rate") else edit[field])
    for row in doc.items:
        if service.amount(row.qty) <= 0 or service.amount(row.qty) > service.amount(maximum.get(_key(row, doc.doctype), 0)):
            frappe.throw("数量超过最新剩余数量或不是正数，请刷新")
        if service.amount(row.rate) < 0:
            frappe.throw("单价不能为负数")
        if row.get("warehouse"):
            warehouse = service._read("Warehouse", row.warehouse, {"company", "is_group"})
            if warehouse.company != doc.company or warehouse.is_group:
                frappe.throw("仓库必须为同公司明细仓库")
    doc.run_method("calculate_taxes_and_totals")
    if doc.doctype == "Purchase Invoice":
        doc.set_payment_schedule()


@frappe.whitelist(methods=["POST"])
def save_document_draft(source_doctype, source_name, target_doctype, changes, request_id, target_name=None, expected_modified=None):
    changes = _changes(changes)
    if not re.fullmatch(r"[a-zA-Z0-9-]{16,80}", str(request_id or "")):
        frappe.throw("缺少有效请求标识")
    if (source_doctype, target_doctype) not in TARGETS:
        frappe.throw("不支持此来源和目标单据")
    payload = [source_doctype, source_name, target_doctype, target_name, expected_modified, changes]
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()
    key = "dlp-document-draft:" + hashlib.sha256((frappe.session.user + ":" + request_id).encode()).hexdigest()
    cache = frappe.cache()
    with cache.lock(key + ":lock", timeout=60, blocking_timeout=5):
        previous = cache.get_value(key)
        if previous:
            if previous["digest"] != digest:
                frappe.throw("同一请求内容已改变，请刷新")
            if not frappe.db.exists(target_doctype, previous["name"]):
                frappe.throw("上次请求尚未完成，请稍后重试")
            source, _ = _source(source_doctype, source_name)
            saved = service._read(target_doctype, previous["name"], HEADER_FIELDS)
            if saved.company != source.company or saved.supplier != source.supplier or _advanced(saved, source):
                frappe.throw(ADVANCED)
            result = _projection(saved, source=source)
            result["reused"] = True
            return result
        source = _locked(source_doctype, source_name)
        _source(source_doctype, source_name)
        if target_doctype == "Purchase Invoice" and not target_name and _current_drafts(source):
            frappe.throw("已有应付草稿，请选择继续编辑")
        native = _native(source, target_doctype)
        maximum = _current_maximum(source, target_doctype)
        doc = _locked(target_doctype, target_name) if target_name else native
        if target_name:
            _version(doc, expected_modified)
            doc.check_permission("write")
            if doc.company != source.company or doc.supplier != source.supplier or _advanced(doc, source):
                frappe.throw(ADVANCED)
        else:
            doc.check_permission("create")
        if doc.docstatus != 0:
            frappe.throw("只能保存草稿")
        _edit_document(doc, changes, maximum)
        doc.save() if target_name else doc.insert()
        if doc.docstatus != 0:
            frappe.throw("保存必须保持草稿状态")
        cache.set_value(key, {"digest": digest, "name": doc.name}, expires_in_sec=86400)
        result = _projection(doc, maximum, source)
        result["reused"] = False
        return result


def _payment(doc):
    fields = {"company", "posting_date", "party", "party_type", "payment_type", "paid_from", "paid_to",
              "paid_from_account_currency", "paid_to_account_currency", "paid_amount", "received_amount", "references",
              "reference_no", "reference_date", "remarks", "deductions", "unallocated_amount"}
    service._require_fields("Payment Entry", fields)
    service._require_fields("Payment Entry Reference", {"reference_doctype", "reference_name", "allocated_amount", "outstanding_amount", "payment_term"}, "Payment Entry")
    warnings = []
    references = service._procurement_references(doc, warnings)
    advanced = bool(warnings or doc.payment_type != "Pay" or doc.party_type != "Supplier" or doc.get("deductions")
                    or doc.paid_from_account_currency != doc.paid_to_account_currency or doc.unallocated_amount
                    or not doc.references or any(row.reference_doctype != "Purchase Invoice" for row in doc.references))
    receive = doc.payment_type == "Receive"
    service._bank_account(doc.paid_to if receive else doc.paid_from, doc.company,
                          doc.paid_to_account_currency if receive else doc.paid_from_account_currency)
    out = {"doctype": doc.doctype, "name": doc.name, "docstatus": doc.docstatus, "modified": doc.modified,
           "company": doc.company, "supplier": doc.party, "posting_date": doc.posting_date,
           "reference_no": doc.reference_no, "remarks": doc.remarks, "payment_type": doc.payment_type,
           "amount": doc.received_amount if receive else doc.paid_amount,
           "bank_account": doc.paid_to if receive else doc.paid_from,
           "currency": doc.paid_to_account_currency if receive else doc.paid_from_account_currency,
           "references": references, "allowed_actions": [] if advanced else _workflow_actions(doc)}
    return {"document": out, "allowed_actions": out["allowed_actions"],
            "editable_fields": _payment_editable(doc) if not advanced and doc.docstatus == 0 else [],
            "advanced_reason": ADVANCED if advanced else ""}


def _payment_editable(doc):
    if not doc.has_permission("write"):
        return []
    permitted = _editable_fields(doc, {"posting_date", "reference_no", "remarks", "paid_amount", "received_amount", "references", "paid_from"})
    fields = [field for field in ("posting_date", "reference_no", "remarks") if field in permitted]
    if {"paid_amount", "received_amount", "references"} <= set(permitted) and "allocated_amount" in _editable_fields(doc.references[0], {"allocated_amount"}, doc.doctype):
        fields.append("amount")
    if "paid_from" in permitted:
        fields.append("bank_account")
    return fields


@frappe.whitelist()
def preview_payment(name):
    return _payment(service._read("Payment Entry", name))


def _payment_balance(doc, validate_allocations=True):
    balances = {}
    for row in doc.references:
        if row.reference_doctype != "Purchase Invoice":
            frappe.throw(ADVANCED)
        invoice = _locked("Purchase Invoice", row.reference_name)
        service._require_fields("Purchase Invoice", service.PI_FIELDS)
        if invoice.company != doc.company or invoice.supplier != doc.party or invoice.docstatus != 1 or invoice.is_return or invoice.invoice_is_blocked():
            frappe.throw("应付来源状态、公司或供应商已改变")
        for source_type, linkfield in (("Purchase Order", "purchase_order"), ("Purchase Receipt", "purchase_receipt")):
            service._require_fields("Purchase Invoice Item", {linkfield}, "Purchase Invoice")
            warnings = []
            service._source_links(invoice, source_type, linkfield, warnings)
            if warnings:
                frappe.throw(service.LINK_WARNING)
        balance = service.invoice_balance(invoice)
        if balance["currency"] != doc.paid_from_account_currency:
            frappe.throw("跨币种付款请在原生单据处理")
        balances[invoice.name] = balance
    allocated = {}
    for row in doc.references:
        allocated[row.reference_name] = allocated.get(row.reference_name, service.amount(0)) + service.amount(row.allocated_amount)
    if validate_allocations and any(value < 0 or value > service.amount(balances[name]["outstanding"]) for name, value in allocated.items()):
        frappe.throw("核销超过最新原生余额，请刷新")
    return balances


@frappe.whitelist(methods=["POST"])
def update_payment_draft(name, changes, expected_modified):
    changes = _changes(changes)
    allowed = {"posting_date", "reference_no", "remarks", "amount", "bank_account"}
    if set(changes) - allowed:
        frappe.throw("包含不支持的付款字段")
    doc = _locked("Payment Entry", name)
    _version(doc, expected_modified)
    doc.check_permission("write")
    if doc.docstatus != 0 or _payment(doc)["advanced_reason"]:
        frappe.throw(ADVANCED)
    _fields("Payment Entry", (set(changes) - {"amount", "bank_account"}) |
            ({"paid_amount", "received_amount", "references"} if "amount" in changes else set()) |
            ({"paid_from"} if "bank_account" in changes else set()), "write")
    balances = _payment_balance(doc, validate_allocations="amount" not in changes)
    account = service._bank_account(changes.get("bank_account") or doc.paid_from, doc.company, doc.paid_to_account_currency, for_update=True)
    if "amount" in changes:
        value = service.amount(changes["amount"])
        if value <= 0 or value > sum((service.amount(row["outstanding"]) for row in balances.values()), service.amount(0)):
            frappe.throw("付款金额超过最新原生余额或不是正数")
        # Reuse native term schedules; do not invent or remove reference rows.
        from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry
        plans = {}
        for invoice in balances:
            native = get_payment_entry("Purchase Invoice", invoice, bank_account=account.name)
            for row in native.references:
                plans[(row.reference_name, row.payment_term or "")] = service.amount(row.outstanding_amount)
        remaining = value
        service._require_fields("Payment Entry Reference", {"payment_term", "outstanding_amount"}, "Payment Entry")
        _fields("Payment Entry Reference", {"allocated_amount"}, "write", "Payment Entry")
        for row in doc.references:
            maximum = plans.get((row.reference_name, row.payment_term or ""), service.amount(0))
            allocated = min(remaining, max(service.amount(0), maximum))
            row.allocated_amount = float(allocated)
            remaining -= allocated
        if remaining:
            frappe.throw("现有原生付款计划无法完整分配，请打开原生单据")
        doc.paid_amount = doc.received_amount = float(value)
    doc.paid_from = account.name
    for field in ("posting_date", "reference_no", "remarks"):
        if field in changes:
            doc.set(field, getdate(changes[field]) if field == "posting_date" else changes[field])
    if "remarks" in changes:
        doc.custom_remarks = 1
    _payment_balance(doc)
    doc.save()
    return _payment(doc)


@frappe.whitelist(methods=["POST"])
def submit_document(doctype, name, expected_modified, workflow_action=None):
    if doctype not in ("Purchase Invoice", "Payment Entry"):
        frappe.throw("此抽屉仅支持应付和付款明确提交；入库请在原生单据处理")
    doc = _locked(doctype, name)
    _version(doc, expected_modified)
    if doc.docstatus != 0:
        frappe.throw("只能提交草稿")
    if doctype == "Payment Entry":
        service._bank_account(doc.paid_from, doc.company, doc.paid_from_account_currency, for_update=True)
        if _payment(doc)["advanced_reason"]:
            frappe.throw(ADVANCED)
        _payment_balance(doc)
        if service.amount(doc.paid_amount) <= 0 or service.amount(doc.paid_amount) != sum((service.amount(row.allocated_amount) for row in doc.references), service.amount(0)):
            frappe.throw("付款金额必须完整分配到原生引用")
    else:
        service._require_fields("Purchase Invoice", HEADER_FIELDS)
        service._require_fields("Purchase Invoice Item", {"purchase_receipt", "pr_detail", "qty"}, "Purchase Invoice")
        names = {row.purchase_receipt for row in doc.items if row.purchase_receipt}
        if len(names) != 1:
            frappe.throw(ADVANCED)
        source_name = next(iter(names))
        source = _locked("Purchase Receipt", source_name)
        _source("Purchase Receipt", source_name)
        if source.company != doc.company or source.supplier != doc.supplier or _advanced(doc, source):
            frappe.throw(ADVANCED)
        _native(source, "Purchase Invoice")
        maximum = _current_maximum(source, "Purchase Invoice")
        totals = {}
        for row in doc.items:
            totals[row.pr_detail] = totals.get(row.pr_detail, service.amount(0)) + service.amount(row.qty)
        if any(qty <= 0 or qty > maximum.get(key, service.amount(0)) for key, qty in totals.items()):
            frappe.throw("应付数量超过最新剩余数量，请刷新")
    from frappe.model.workflow import apply_workflow, get_workflow_name
    actions = _workflow_actions(doc)
    action = workflow_action or "Submit"
    if action not in actions:
        frappe.throw("没有当前提交或工作流操作权限", frappe.PermissionError)
    if get_workflow_name(doctype):
        doc = apply_workflow(doc.as_dict(), action)
    else:
        doc.check_permission("submit")
        doc.submit()
    return _payment(doc) if doctype == "Payment Entry" else _projection(doc)


@frappe.whitelist()
def get_voucher_detail(name):
    fields = {"company", "posting_date", "status", "source_doctype", "source_name", "source_event", "statutory_number",
              "reversal_of", "reversed_by", "remarks", "currency", "total_debit", "total_credit", "entries"}
    doc = service._read("China Accounting Voucher", name, fields)
    row_fields = {"account", "account_name", "debit", "credit", "remarks"}
    row_fields = _fields("China Accounting Voucher Entry", row_fields, parenttype=doc.doctype)
    out = {field: doc.get(field) for field in fields - {"entries", "source_name", "reversal_of", "reversed_by"}}
    out.update(name=doc.name, docstatus=doc.docstatus, entries=[{field: row.get(field) for field in row_fields} for row in doc.entries])
    warnings = []
    for field in ("reversal_of", "reversed_by"):
        target = doc.get(field)
        if target and service._related(doc.doctype, target, warnings, {"company"}, doc.company):
            out[field] = target
    if doc.source_name and service._related(doc.source_doctype, doc.source_name, warnings, {"company"}, doc.company):
        out["source_name"] = doc.source_name
    out["warnings"] = warnings
    return out
