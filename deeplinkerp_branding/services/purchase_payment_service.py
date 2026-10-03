"""Procurement reads and native Payment Entry drafts; never submit or post GL here."""
from __future__ import annotations

import hashlib
import json
import re
from contextlib import contextmanager
from decimal import Decimal, InvalidOperation

import frappe
from frappe.model import get_permitted_fields
from frappe.utils import getdate, nowdate

SOURCES = {"Purchase Receipt", "Purchase Order"}
PI_FIELDS = {"company", "supplier", "currency", "party_account_currency", "grand_total", "base_grand_total",
             "rounded_total", "base_rounded_total", "disable_rounded_total", "outstanding_amount", "items", "is_return"}


def amount(value):
    try:
        value = Decimal(str(value or 0))
    except (InvalidOperation, ValueError):
        raise ValueError("金额必须为有效数字")
    if not value.is_finite():
        raise ValueError("金额必须为有限数字")
    return value


def _require_fields(doctype, fields, parenttype=None):
    permitted = set(get_permitted_fields(doctype, parenttype=parenttype, permission_type="read"))
    meta = frappe.get_meta(doctype)
    levels = set(meta.get_permlevel_access(permission_type="read", parenttype=parenttype))
    permitted.update(df.fieldname for df in meta.fields if df.fieldtype in ("Table", "Table MultiSelect") and df.permlevel in levels)
    if not set(fields) <= permitted:
        frappe.throw("无权查看完整关联或金额字段", frappe.PermissionError)


def _read(doctype, name, fields=()):
    doc = frappe.get_doc(doctype, name)
    doc.check_permission("read")
    _require_fields(doctype, fields)
    if doc.get("company"):
        frappe.get_doc("Company", doc.company).check_permission("read")
    return doc


LINK_WARNING = "关联缺失或无权读取，请在原生单据核对；快捷付款/确认应付已禁用"
SOURCE_FIELDS = {"company", "supplier", "currency", "grand_total", "items", "status"}


@contextmanager
def _quiet_link_errors():
    """Caught Frappe throws must not enqueue private target names in _server_messages."""
    previous = frappe.flags.mute_messages
    frappe.flags.mute_messages = True
    try:
        yield
    finally:
        frappe.flags.mute_messages = previous


def _related(doctype, name, warnings, fields=(), company=None, supplier=None):
    """Resolve optional links through normal permissions; never disclose hidden target names."""
    with _quiet_link_errors():
        try:
            doc = _read(doctype, name, fields)
            if (company and doc.company != company) or (supplier and doc.supplier != supplier):
                raise frappe.PermissionError
            return doc
        except (frappe.DoesNotExistError, frappe.PermissionError):
            if LINK_WARNING not in warnings:
                warnings.append(LINK_WARNING)
            return None


def _source_links(doc, doctype, field, warnings):
    names = sorted({item.get(field) for item in doc.items if item.get(field)})
    return [name for name in names if _related(doctype, name, warnings, SOURCE_FIELDS,
                                              doc.company, doc.supplier)]


def _source(doctype, name):
    if doctype not in SOURCES:
        frappe.throw("仅支持采购订单和采购入库")
    return _read(doctype, name, SOURCE_FIELDS)


def _invoice_names(doctype, name):
    field = "purchase_receipt" if doctype == "Purchase Receipt" else "purchase_order"
    _require_fields("Purchase Invoice", {"items"})
    _require_fields("Purchase Invoice Item", {field}, "Purchase Invoice")
    # Discover parent candidates only through the readable source link; callers must
    # resolve each parent with _read/_related before exposing names or balances.
    # Joining to the parent would silently hide orphan children and permit duplicate PI creation.
    return frappe.get_all("Purchase Invoice Item", filters={field: name},
                          distinct=True, limit_page_length=0, pluck="parent")


def invoice_balance(doc):
    """Outstanding is ERPNext's maintained party-ledger balance, not a sum of PE rows."""
    currency = doc.party_account_currency or doc.currency
    rounded = not doc.disable_rounded_total and bool(doc.rounded_total)
    total_field = "rounded_total" if rounded else "grand_total"
    if currency == doc.currency:
        total = amount(doc.get(total_field))
    elif currency == frappe.get_cached_value("Company", doc.company, "default_currency"):
        total = amount(doc.get("base_" + total_field))
    else:
        frappe.throw("应付账户币种无法安全换算，请打开原生应付单核对")
    outstanding = amount(doc.outstanding_amount)
    return {"currency": currency, "total": float(total), "settled": float(total - outstanding),
            "outstanding": float(outstanding)}


def _invoice_row(doc, source_type, source_name):
    _require_fields("Purchase Invoice Item", {"purchase_order", "purchase_receipt"}, "Purchase Invoice")
    field = "purchase_receipt" if source_type == "Purchase Receipt" else "purchase_order"
    shared = any(row.get(field) != source_name for row in doc.items)
    balance = invoice_balance(doc) if doc.docstatus == 1 else {}
    blocked = doc.invoice_is_blocked() if doc.docstatus == 1 else False
    return {"name": doc.name, "docstatus": doc.docstatus, "is_return": bool(doc.is_return),
            "shared": shared, "scope_label": "共享应付整单余额" if shared else "关联应付余额",
            "can_pay": bool(doc.docstatus == 1 and not doc.is_return and not blocked and balance.get("outstanding", 0) > 0),
            "blocked": bool(blocked), **balance}


def summarize(invoices):
    groups = {}
    for row in invoices:
        if row["docstatus"] != 1 or row["is_return"]:
            continue
        currency = row["currency"]
        target = groups.setdefault(currency, {"currency": currency, "total": Decimal(0), "settled": Decimal(0), "outstanding": Decimal(0)})
        for key in ("total", "settled", "outstanding"):
            target[key] += amount(row[key])
    return [{key: float(value) if isinstance(value, Decimal) else value for key, value in row.items()} for row in groups.values()]


def _vouchers(payment_name):
    if not frappe.db.exists("DocType", "China Accounting Voucher") or not frappe.has_permission("China Accounting Voucher", "read"):
        return []
    _require_fields("China Accounting Voucher", {"source_doctype", "source_name", "source_event", "status", "statutory_number"})
    return frappe.get_list("China Accounting Voucher", filters={"source_doctype": "Payment Entry", "source_name": payment_name},
                           fields=["name", "statutory_number", "source_event", "status", "docstatus"], limit_page_length=0)


def _procurement_references(payment, warnings):
    _require_fields("Payment Entry Reference", {"reference_doctype", "reference_name", "allocated_amount"}, "Payment Entry")
    refs = []
    for row in payment.references:
        if row.reference_doctype == "Purchase Order":
            order = _related("Purchase Order", row.reference_name, warnings, SOURCE_FIELDS, payment.company, payment.party)
            if order:
                refs.append({"doctype": "Purchase Order", "name": order.name, "allocated": row.allocated_amount, "currency": payment.paid_to_account_currency if payment.payment_type == "Pay" else payment.paid_from_account_currency, "orders": [order.name], "receipts": []})
        elif row.reference_doctype == "Purchase Invoice":
            invoice = _related("Purchase Invoice", row.reference_name, warnings, PI_FIELDS, payment.company, payment.party)
            if not invoice:
                continue
            _require_fields("Purchase Invoice Item", {"purchase_order", "purchase_receipt"}, "Purchase Invoice")
            orders = _source_links(invoice, "Purchase Order", "purchase_order", warnings)
            receipts = _source_links(invoice, "Purchase Receipt", "purchase_receipt", warnings)
            if any(item.purchase_order or item.purchase_receipt for item in invoice.items):
                refs.append({"doctype": "Purchase Invoice", "name": invoice.name, "allocated": row.allocated_amount, "currency": payment.paid_to_account_currency if payment.payment_type == "Pay" else payment.paid_from_account_currency, "orders": orders, "receipts": receipts})
    return refs


def _payment_row(doc):
    _require_fields("Payment Entry", {"company", "party", "party_type", "payment_type", "references", "posting_date", "paid_amount", "paid_from_account_currency", "paid_from", "received_amount", "paid_to_account_currency", "paid_to", "remarks"})
    doc.check_permission("read")
    frappe.get_doc("Company", doc.company).check_permission("read")
    warnings = []
    refs = _procurement_references(doc, warnings)
    if not refs:
        return None
    try:
        vouchers = _vouchers(doc.name)
    except frappe.PermissionError:
        vouchers = []
    return {"name": doc.name, "company": doc.company, "supplier": doc.party, "posting_date": doc.posting_date,
            "docstatus": doc.docstatus, "payment_type": doc.payment_type, "amount": doc.received_amount if doc.payment_type == "Receive" else doc.paid_amount,
            "currency": doc.paid_to_account_currency if doc.payment_type == "Receive" else doc.paid_from_account_currency, "bank_account": doc.paid_to if doc.payment_type == "Receive" else doc.paid_from, "remarks": doc.remarks,
            "references": refs, "vouchers": vouchers, "warnings": warnings,
            "state": {0: "草稿 · 未计已付", 1: "已提交", 2: "已取消 · 未计已付"}[doc.docstatus]}


@frappe.whitelist()
def get_payment_records(company=None, supplier=None, purchase_order=None, purchase_receipt=None, search=None, start=0, page_length=50):
    if purchase_order:
        _source("Purchase Order", purchase_order)
    receipt_orders = set()
    if purchase_receipt:
        receipt = _source("Purchase Receipt", purchase_receipt)
        _require_fields("Purchase Receipt Item", {"purchase_order"}, "Purchase Receipt")
        receipt_orders = set(_source_links(receipt, "Purchase Order", "purchase_order", []))
    start, page_length = int(start), int(page_length)
    if start < 0 or not 1 <= page_length <= 100:
        frappe.throw("分页参数无效")
    _require_fields("Payment Entry", {"party_type", "references"})
    filters = {"party_type": "Supplier", "payment_type": ["in", ["Pay", "Receive"]]}
    for field, value in (("company", company), ("party", supplier)):
        if value:
            filters[field] = value
    names = frappe.get_list("Payment Entry", filters=filters, fields=["name"], order_by="posting_date desc, creation desc", limit_page_length=0, pluck="name")
    rows = []
    for name in names:
        try:
            with _quiet_link_errors():
                row = _payment_row(frappe.get_doc("Payment Entry", name))
        except (frappe.DoesNotExistError, frappe.PermissionError):
            continue
        if not row:
            continue
        refs = row["references"]
        if purchase_order and not any(purchase_order in ref["orders"] for ref in refs):
            continue
        if purchase_receipt and not any(purchase_receipt in ref["receipts"] or (ref["doctype"] == "Purchase Order" and receipt_orders.intersection(ref["orders"])) for ref in refs):
            continue
        if search and str(search).casefold() not in (row["name"] + " " + row["supplier"]).casefold():
            continue
        rows.append(row)
    # No monetary total: refunds and mixed-purpose/multi-currency payments must not be silently summed.
    return {"rows": rows[start:start + page_length], "total_count": len(rows),
            "notice": "关联缺失或无权读取的单据不会作为可用链接；请在原生单据核对。仅显示有权查看的订单预付款或关联采购应付付款；草稿、取消不计已付。金额为整张付款单银行币种金额，核销见引用。关联订单预付款尚未核销时不计本入库已付。"}


def _order_progress(names, warnings):
    rows=[]
    for name in names:
        try:
            order=_related("Purchase Order", name, warnings, SOURCE_FIELDS)
            if not order:
                continue
            with _quiet_link_errors():
                _require_fields("Purchase Order Item", {"qty","received_qty","uom","rate"}, "Purchase Order")
            units={}
            pending=Decimal(0)
            for item in order.items:
                qty=max(Decimal(0),amount(item.qty)); received=max(Decimal(0),amount(item.received_qty))
                left=max(Decimal(0),qty-received);pending+=left*amount(item.rate)
                unit=units.setdefault(item.uom,{"uom":item.uom,"ordered":Decimal(0),"received":Decimal(0),"pending":Decimal(0)})
                unit["ordered"]+=qty;unit["received"]+=received;unit["pending"]+=left
            rows.append({"name":name,"currency":order.currency,"grand_total":order.grand_total,
                         "pending_net_amount":float(pending),"units":[{k:float(v) if isinstance(v,Decimal) else v for k,v in u.items()} for u in units.values()]})
        except frappe.PermissionError:
            if LINK_WARNING not in warnings:
                warnings.append(LINK_WARNING)
    return rows


@frappe.whitelist()
def get_purchase_chain(source_doctype, source_name, include_payments=True):
    doc = _source(source_doctype, source_name)
    _require_fields(source_doctype + " Item", {"purchase_order"} if source_doctype == "Purchase Receipt" else {"qty", "received_qty", "amount"}, source_doctype)
    invoices = []
    warnings = []
    if frappe.has_permission("Purchase Invoice", "read"):
        for name in _invoice_names(source_doctype, source_name):
            invoice = _related("Purchase Invoice", name, warnings, PI_FIELDS, doc.company, doc.supplier)
            if not invoice:
                continue
            _require_fields("Purchase Invoice Item", {"purchase_order", "purchase_receipt"}, "Purchase Invoice")
            _source_links(invoice, "Purchase Order", "purchase_order", warnings)
            _source_links(invoice, "Purchase Receipt", "purchase_receipt", warnings)
            if invoice.company == doc.company and invoice.supplier == doc.supplier:
                invoices.append(_invoice_row(invoice, source_doctype, source_name))
    else:
        warnings.append("无采购应付读取权限，余额不可见")
    if any(row["shared"] for row in invoices):
        warnings.append("关联应付包含其他订单/入库；金额为共享应付整单余额，不分摊冒充本入库已付")
    payments = []
    if include_payments in (True, 1, "1", "true") and frappe.has_permission("Payment Entry", "read"):
        payments = get_payment_records(**{"purchase_receipt" if source_doctype == "Purchase Receipt" else "purchase_order": doc.name}, page_length=100)["rows"]
    can_create = bool(doc.docstatus == 1 and not doc.get("is_return") and frappe.has_permission("Payment Entry", "create"))
    reason = "" if can_create else "来源未提交、已退货，或没有创建付款权限"
    eligible = [row for row in invoices if row["can_pay"]]
    if not eligible:
        reason = reason or ("有关联应付草稿，请核对并提交；草稿不计应付" if any(i["docstatus"] == 0 for i in invoices) else "关联应付已结清、暂停或取消，请打开关联单据核对" if invoices else "尚无可付款的已提交应付单，请先确认应付")
    orders = []
    if source_doctype == "Purchase Receipt":
        orders = _source_links(doc, "Purchase Order", "purchase_order", warnings)
    else:
        orders = [doc.name]
    progress = _order_progress(orders, warnings)
    incomplete = LINK_WARNING in warnings
    if incomplete:
        reason = LINK_WARNING
        for row in invoices:
            row["can_pay"] = False
    return {"source_doctype": source_doctype, "name": doc.name, "company": doc.company, "supplier": doc.supplier,
            "currency": doc.currency, "grand_total": doc.grand_total, "status": doc.status,
            "docstatus": doc.docstatus, "orders": orders, "order_progress": progress, "invoices": invoices, "balances": [] if incomplete else summarize(invoices), "incomplete_links": incomplete,
            "can_create_invoice": bool(not incomplete and source_doctype == "Purchase Receipt" and doc.docstatus == 1 and not doc.get("is_return") and frappe.has_permission("Purchase Invoice", "read") and frappe.has_permission("Purchase Invoice", "create") and not any(i["docstatus"] in (0, 1) for i in invoices)),
            "payments": payments, "warnings": warnings, "can_create": can_create and bool(eligible) and not incomplete, "reason": reason,
            "settlement_label": "已付/核销（含预付款抵扣、贷项等）"}


@frappe.whitelist()
def get_receipt_list(filters=None, start=0, page_length=100, **unused):
    filters = json.loads(filters) if isinstance(filters, str) else filters or {}
    if not isinstance(filters, dict):
        frappe.throw("筛选条件必须为对象")
    query = {}
    for field in ("company", "supplier", "status"):
        if filters.get(field):
            query[field] = filters[field]
    if filters.get("search"):
        query["name"] = ["like", "%" + str(filters["search"]) + "%"]
    if filters.get("from_date") or filters.get("to_date"):
        query["posting_date"] = ["between", [filters.get("from_date") or "1900-01-01", filters.get("to_date") or "2999-12-31"]]
    fields = ["name", "supplier_name", "supplier", "posting_date", "status", "company", "currency", "grand_total", "docstatus", "is_return"]
    _require_fields("Purchase Receipt", fields)
    start, page_length = int(start), min(100, max(1, int(page_length)))
    rows = frappe.get_list("Purchase Receipt", filters=query, fields=fields, order_by="posting_date desc, creation desc", start=start, limit_page_length=page_length)
    for row in rows:
        try:
            with _quiet_link_errors():
                chain = get_purchase_chain("Purchase Receipt", row.name, include_payments=False)
            row.update({key: chain[key] for key in ("orders", "balances", "can_create", "reason", "warnings", "incomplete_links")})
            row["payment_state"] = ("关联缺失或无权读取" if chain["incomplete_links"] else "共享应付" if any(i["shared"] for i in chain["invoices"]) else "余额不可见" if chain["warnings"] else "未形成应付")
            if chain["balances"] and not chain["warnings"]:
                balances = chain["balances"]
                row["payment_state"] = "已付清" if all(b["outstanding"] <= 0 for b in balances) else "部分付款/核销" if any(b["settled"] > 0 for b in balances) else "未付款"
        except (frappe.PermissionError, frappe.DoesNotExistError):
            row.update(balances=[], orders=[], can_create=False, reason=LINK_WARNING, payment_state="关联缺失或无权读取", warnings=[LINK_WARNING], incomplete_links=True)
    total = len(frappe.get_list("Purchase Receipt", filters=query, fields=["name"], limit_page_length=0))
    return {"rows": rows, "total_count": total}


@frappe.whitelist(methods=["POST"])
def create_payment_draft(source_doctype, source_name, purchase_invoice, amount_to_pay, bank_account, posting_date=None, remarks=None, request_id=None, reference_no=None):
    """Save exactly a native draft. Never bypass create/read/write or approval permissions."""
    source = _source(source_doctype, source_name)
    if get_purchase_chain(source_doctype, source_name, include_payments=False)["incomplete_links"]:
        frappe.throw(LINK_WARNING)
    if source.docstatus != 1 or source.get("is_return"):
        frappe.throw("来源必须为已提交且非退货的采购单据")
    if not frappe.has_permission("Payment Entry", "create"):
        frappe.throw("没有创建付款单权限", frappe.PermissionError)
    if not re.fullmatch(r"[a-zA-Z0-9-]{16,80}", str(request_id or "")):
        frappe.throw("缺少有效请求标识，请刷新付款抽屉")
    try:
        value = amount(amount_to_pay)
    except ValueError as exc:
        frappe.throw(str(exc))
    if value <= 0:
        frappe.throw("本次金额必须大于0")
    payload = [source_doctype, source_name, purchase_invoice, str(value), bank_account, str(posting_date or nowdate()), remarks or "", reference_no or ""]
    digest = hashlib.sha256(json.dumps(payload, ensure_ascii=False).encode()).hexdigest()
    key = "dlp-purchase-draft:" + hashlib.sha256((frappe.session.user + ":" + request_id).encode()).hexdigest()
    cache = frappe.cache()
    with cache.lock(key + ":lock", timeout=60, blocking_timeout=5):
        previous = cache.get_value(key)
        if previous:
            if previous["digest"] != digest:
                frappe.throw("同一请求内容已改变，请重新打开付款抽屉")
            if not frappe.db.exists("Payment Entry", previous["name"]):
                frappe.throw("上次请求正在提交或失败，请稍后重试；不要重复创建")
            entry = _read("Payment Entry", previous["name"])
            return {"name": entry.name, "docstatus": entry.docstatus, "reused": True}
        invoice = _read("Purchase Invoice", purchase_invoice, PI_FIELDS)
        if purchase_invoice not in _invoice_names(source_doctype, source_name):
            frappe.throw("应付单与当前采购单据没有明确关联")
        if invoice.company != source.company or invoice.supplier != source.supplier:
            frappe.throw("付款公司和供应商必须与来源一致")
        if invoice.docstatus != 1 or invoice.is_return or invoice.invoice_is_blocked():
            frappe.throw("应付单未提交、为退货或已暂停付款")
        balance = invoice_balance(invoice)
        if value > amount(balance["outstanding"]):
            frappe.throw("本次金额超过最新未付余额，请刷新")
        account = _read("Account", bank_account, {"company", "account_type", "is_group", "account_currency"})
        if account.company != source.company or account.is_group or account.account_type not in ("Bank", "Cash"):
            frappe.throw("请选择同公司银行或现金记账账户")
        if account.account_currency != balance["currency"]:
            frappe.throw("跨币种付款请在原生付款单处理汇率；当前抽屉只支持同币种")
        from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry
        entry = get_payment_entry("Purchase Invoice", invoice.name, bank_account=bank_account, bank_amount=float(value))
        entry.check_permission("create")
        entry.posting_date = getdate(posting_date or nowdate())
        entry.reference_date = entry.posting_date
        entry.reference_no = str(reference_no or "")[:140] or None
        entry.paid_amount = entry.received_amount = float(value)
        entry.custom_remarks = bool(remarks)
        entry.remarks = str(remarks or "")[:1000] or f"采购付款：{source.name} / {invoice.name}"
        # Native payment-term references may be multiple. Use their order and balances without inventing terms.
        remaining = value
        for ref in entry.references:
            allocated = min(remaining, max(Decimal(0), amount(ref.outstanding_amount)))
            ref.allocated_amount = float(allocated)
            remaining -= allocated
        if remaining:
            frappe.throw("应付付款计划无法完整分配本次金额，请在原生付款单处理")
        entry.insert()  # normal Frappe validation, workflow, field and document permissions
        if entry.docstatus != 0:
            frappe.throw("付款草稿状态异常")
        # A concurrent retry sees the same name, or 'pending', never creates another draft.
        cache.set_value(key, {"digest": digest, "name": entry.name}, expires_in_sec=86400)
        return {"name": entry.name, "docstatus": 0, "reused": False}
