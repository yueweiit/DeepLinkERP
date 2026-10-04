"""Procurement reads and native Payment Entry drafts; never submit or post GL here."""
from __future__ import annotations

import hashlib
import json
import re
from contextlib import contextmanager
from contextvars import ContextVar
from decimal import Decimal, InvalidOperation

import frappe
from frappe.model import get_permitted_fields
from frappe.utils import getdate, nowdate

from deeplinkerp_branding.services.unified_purchase_service import _require_export_permission

SOURCES = {"Purchase Receipt", "Purchase Order"}
PI_FIELDS = {"company", "supplier", "currency", "party_account_currency", "grand_total", "base_grand_total",
             "rounded_total", "base_rounded_total", "disable_rounded_total", "outstanding_amount", "items", "is_return"}

_record_reader = ContextVar("purchase_payment_record_reader", default=None)


class _RecordReader:
    """Request-local bulk hydration; every exposed document still passes normal permissions."""

    def __init__(self):
        self.docs = {}
        self.fields = set()
        self.checked = set()

    def preload(self, doctype, names):
        names = sorted(set(names) - {name for dt, name in self.docs if dt == doctype})
        for offset in range(0, len(names), 500):
            chunk = names[offset:offset + 500]
            # Same internal raw values as get_doc/load_from_db, never returned directly.
            parents = frappe.db.get_values(doctype, {"name": ["in", chunk]}, "*", as_dict=True)
            by_name = {row.name: row for row in parents}
            # Hydrate all child tables, including fields inspected by controller/user permissions.
            for field in frappe.get_meta(doctype).get_table_fields():
                for row in by_name.values():
                    row[field.fieldname] = []
                if by_name:
                    children = frappe.db.get_values(field.options, {"parent": ["in", list(by_name)],
                        "parenttype": doctype, "parentfield": field.fieldname}, "*", as_dict=True, order_by="idx asc")
                    for child in children:
                        by_name[child.parent][field.fieldname].append(child)
            for name in chunk:
                row = by_name.get(name)
                doc = frappe.get_doc({"doctype": doctype, **row}) if row else None
                if doc:
                    if hasattr(doc, "__setup__"):
                        doc.__setup__()
                    doc.mask_fields()
                self.docs[doctype, name] = doc

    def doc(self, doctype, name):
        key = (doctype, name)
        if key not in self.docs:
            self.docs[key] = frappe.get_doc(doctype, name)
        doc = self.docs[key]
        if doc is None:
            raise frappe.DoesNotExistError
        return doc

    def check(self, doc):
        key = (doc.doctype, doc.name)
        if key not in self.checked:
            doc.check_permission("read")
            self.checked.add(key)


def _read_doc(doctype, name):
    reader = _record_reader.get()
    return reader.doc(doctype, name) if reader else frappe.get_doc(doctype, name)


def _check_read(doc):
    reader = _record_reader.get()
    if reader:
        reader.check(doc)
    else:
        doc.check_permission("read")


def amount(value):
    try:
        value = Decimal(str(value or 0))
    except (InvalidOperation, ValueError):
        raise ValueError("金额必须为有效数字")
    if not value.is_finite():
        raise ValueError("金额必须为有限数字")
    return value


def _require_fields(doctype, fields, parenttype=None):
    reader = _record_reader.get()
    key = (doctype, frozenset(fields), parenttype)
    if reader and key in reader.fields:
        return
    permitted = set(get_permitted_fields(doctype, parenttype=parenttype, permission_type="read"))
    meta = frappe.get_meta(doctype)
    levels = set(meta.get_permlevel_access(permission_type="read", parenttype=parenttype))
    permitted.update(df.fieldname for df in meta.fields if df.fieldtype in ("Table", "Table MultiSelect") and df.permlevel in levels)
    if not set(fields) <= permitted:
        frappe.throw("无权查看完整关联或金额字段", frappe.PermissionError)
    if reader:
        reader.fields.add(key)


def _read(doctype, name, fields=()):
    doc = _read_doc(doctype, name)
    _check_read(doc)
    _require_fields(doctype, fields)
    if doc.get("company"):
        _check_read(_read_doc("Company", doc.company))
    return doc


LINK_WARNING = "关联缺失或无权读取，请在原生单据核对；快捷付款/确认应付已禁用"
SOURCE_FIELDS = {"company", "supplier", "currency", "grand_total", "items", "status"}
RECEIPT_FIELDS = ["name", "supplier_name", "supplier", "posting_date", "status", "company", "currency", "grand_total", "docstatus", "is_return"]
RECEIPT_COLUMNS = {"name": "采购入库单号", "supplier_name": "供应商名称", "supplier": "供应商编码",
                   "posting_date": "入库日期", "status": "入库状态", "company": "公司", "currency": "入库币种",
                   "grand_total": "入库金额", "docstatus": "单据状态", "is_return": "是否退货",
                   "orders": "采购订单", "payment_state": "付款状态",
                   "shared_payable": "共享应付整单范围", "settlement_state": "已付/核销状态",
                   "settled": "已付/核销（各币种及整单范围）", "outstanding": "未付（各币种及整单范围）"}
PAYMENT_COLUMNS = {"name": "付款单", "posting_date": "付款日期", "supplier": "供应商", "company": "公司",
                   "payment_type": "付款类型", "amount": "金额", "currency": "付款币种", "bank_account": "记账账户",
                   "state": "付款状态", "remarks": "摘要", "references": "核销引用", "allocation_currency": "核销币种",
                   "vouchers": "会计凭证", "sync_issues": "凭证同步状态"}
BANK_WARNING = "银行或现金账户不可用或无权读取，请在原生单据核对"


def _query_fields(doctype):
    """Native stored parent fields; permission checks still apply to each requested field."""
    meta = frappe.get_meta(doctype)
    excluded = {"Table", "Table MultiSelect", "HTML", "Section Break", "Column Break", "Tab Break", "Button", "Heading", "Image", "Fold"}
    fields = set(meta.default_fields)
    fields.update(df.fieldname for df in meta.fields if df.fieldtype not in excluded and not df.get("is_virtual"))
    return fields & set(meta.get_valid_columns())


def _bank_account(name, company, currency, for_update=False):
    """One bank guard for reads and drawer writes; framework account names stay private."""
    fields = {"company", "account_currency", "is_group", "account_type", "disabled"}
    denied = False
    with _quiet_link_errors():
        try:
            if for_update:
                doc = frappe.get_doc("Account", name, for_update=True)
                _check_read(doc)
                _require_fields("Account", fields)
                _read("Company", doc.company)
            else:
                doc = _read("Account", name, fields)
        except (frappe.DoesNotExistError, frappe.PermissionError):
            denied = True
    if denied:
        frappe.throw(BANK_WARNING, frappe.PermissionError)
    if doc.company != company or doc.is_group or doc.disabled or doc.account_type not in ("Bank", "Cash") or doc.account_currency != currency:
        frappe.throw(BANK_WARNING)
    return doc


def _normalize_filter(doctype, field, operator, value):
    from frappe.utils.data import get_filter
    normalized = get_filter(doctype, [doctype, field, operator, value])
    if normalized.doctype != doctype or normalized.fieldname != field:
        frappe.throw("跨单据或明细筛选请在原生高级列表处理")
    return [doctype, field, normalized.operator.lower(), normalized.value]


def _native_filters(doctype, value, allowed):
    value = json.loads(value) if isinstance(value, str) else value or []
    if isinstance(value, dict):
        value = [[field, *(condition if isinstance(condition, (list, tuple)) else ["=", condition])]
                 for field, condition in value.items()]
    if not isinstance(value, list):
        frappe.throw("原生筛选条件必须为列表或对象")
    result = []
    for entry in value:
        if not isinstance(entry, (list, tuple)) or len(entry) not in (3, 4):
            frappe.throw("原生筛选条件格式无效")
        if len(entry) == 4 and entry[0] != doctype:
            frappe.throw("不支持跨单据筛选")
        field, operator, operand = entry[-3:]
        if field not in allowed:
            frappe.throw("不支持此父单据字段；明细筛选请在原生高级列表处理")
        _require_fields(doctype, {field})
        result.append(_normalize_filter(doctype, field, str(operator).lower(), operand))
    return result


def _order_by(doctype, value, allowed):
    clauses = []
    for part in str(value or "posting_date desc, creation desc").split(","):
        match = re.fullmatch(r"\s*(?:(?:`([^`]+)`|([a-z_][a-z0-9_ ]*))\s*\.\s*)?(?:`([a-z_][a-z0-9_]*)`|([a-z_][a-z0-9_]*))\s*(asc|desc)?\s*", part, re.I)
        if not match:
            frappe.throw("排序字段无效")
        table, field = match[1] or match[2], match[3] or match[4]
        if (table and table != "tab" + doctype) or field not in allowed:
            frappe.throw("排序字段无效")
        _require_fields(doctype, {field})
        clauses.append(field + " " + (match[5] or "asc").lower())
    if not any(clause.startswith("name ") for clause in clauses):
        clauses.append("name asc")
    return ", ".join(clauses)


def _pagination(start, page_length):
    try:
        start, page_length = int(start), int(page_length)
    except (TypeError, ValueError):
        frappe.throw("分页参数无效")
    if start < 0 or not 1 <= page_length <= 2500:
        frappe.throw("分页参数无效")
    return start, page_length


def _export(doctype, rows, columns, allowed):
    _require_export_permission(doctype, ({"name": row["name"], "owner": _read_doc(doctype, row["name"]).get("owner")}
                                        for row in rows))
    columns = json.loads(columns) if isinstance(columns, str) else columns or list(allowed)
    if not isinstance(columns, list) or not columns or len(set(columns)) != len(columns) or any(column not in allowed for column in columns):
        frappe.throw("导出列无效")
    columns = list(columns)
    if {"grand_total", "amount"}.intersection(columns) and "currency" not in columns:
        columns.append("currency")
    if doctype == "Payment Entry" and "allocation_currency" not in columns:
        columns.append("allocation_currency")
    for row in rows:
        _check_read(_read_doc(doctype, row["name"]))
    # Prevent spreadsheet formula interpretation of source text.
    def value(row, column):
        cell = row.get(column)
        if column == "posting_date":
            cell = getdate(cell) if cell else None
        elif column == "allocation_currency":
            cell = ", ".join(sorted({ref["currency"] for ref in row["references"] if ref.get("currency")}))
        elif column in ("settled", "outstanding"):
            cell = [{"currency": balance["currency"], column: balance[column],
                     "scope_label": "共享应付整单余额" if row.get("shared_payable") else "关联应付余额"}
                    for balance in row.get("balances", [])]
        if isinstance(cell, (list, dict)):
            cell = json.dumps(cell, ensure_ascii=False, default=str)
        if isinstance(cell, str):
            from frappe.utils.xlsxutils import handle_html
            cell = handle_html(cell)
            if cell.startswith(("=", "+", "-", "@")):
                cell = "'" + cell
        return cell
    from frappe.utils.xlsxutils import make_xlsx
    column_styles = {index: (1,) if column == "posting_date" else (0,)
                     for index, column in enumerate(columns) if column in {"posting_date", "grand_total", "amount"}}
    styles = {"styles": [{"num_format": "#,##0.00"}, {"num_format": "yyyy-mm-dd"}],
              "column_styles": column_styles} if column_styles else {}
    workbook = make_xlsx([[allowed[column] for column in columns]] + [[value(row, column) for column in columns] for row in rows], "采购记录", styles=styles)
    frappe.response["filename"] = doctype.replace(" ", "_") + ".xlsx"
    frappe.response["filecontent"] = workbook.getvalue()
    frappe.response["type"] = "binary"
    return None


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


def _vouchers(payment_names):
    if not frappe.db.exists("DocType", "China Accounting Voucher") or not frappe.has_permission("China Accounting Voucher", "read"):
        return []
    fields = {"source_doctype", "source_name", "source_event", "status", "statutory_number", "company"}
    _require_fields("China Accounting Voucher", fields)
    result = []
    for row in frappe.get_list("China Accounting Voucher", filters={"source_doctype": "Payment Entry", "source_name": ["in", payment_names]},
            fields=["name", "source_name", "statutory_number", "source_event", "status", "docstatus", "company"], limit_page_length=0):
        if _related("China Accounting Voucher", row.name, [], fields):
            result.append(row)
    return result


def _decorate_payments(rows):
    from deeplinkerp_branding.services.purchase_document_actions import _payment_editable, _workflow_actions
    by_name = {row["name"]: row for row in rows}
    for row in rows:
        doc = _read_doc("Payment Entry", row["name"])
        row["sync_issues"] = []
        row["can_edit"] = False
        row["allowed_actions"] = []
        try:
            with _quiet_link_errors():
                _require_fields("Payment Entry", {"deductions", "unallocated_amount"})
                simple = (not row["warnings"] and doc.payment_type == "Pay" and doc.party_type == "Supplier"
                          and not doc.get("deductions") and not doc.unallocated_amount
                          and doc.paid_from_account_currency == doc.paid_to_account_currency
                          and all(ref.reference_doctype == "Purchase Invoice" for ref in doc.references))
                row["can_edit"] = bool(simple and doc.docstatus == 0 and _payment_editable(doc))
                row["allowed_actions"] = _workflow_actions(doc) if simple else []
        except frappe.PermissionError:
            pass
    doctype = "China Voucher Sync Issue"
    if not frappe.db.exists("DocType", doctype) or not frappe.has_permission(doctype, "read"):
        return
    fields = {"company", "source_doctype", "source_name", "status", "posting_date"}
    try:
        with _quiet_link_errors():
            _require_fields(doctype, fields)
            issues = frappe.get_list(doctype, filters={"source_doctype": "Payment Entry", "source_name": ["in", list(by_name)], "status": "Pending"},
                                     fields=["name", *sorted(fields)], limit_page_length=0)
            for issue in issues:
                payment = by_name[issue.source_name]
                if issue.company != payment["company"] or not _related(doctype, issue.name, [], fields, payment["company"]):
                    continue
                # Status only: do not leak last_error or unavailable cancellation-voucher names.
                payment["sync_issues"].append({"name": issue.name, "status": issue.status, "posting_date": issue.posting_date})
    except frappe.PermissionError:
        pass


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
    _check_read(doc)
    _check_read(_read_doc("Company", doc.company))
    warnings = []
    refs = _procurement_references(doc, warnings)
    if not refs:
        return None
    bank_account = doc.paid_to if doc.payment_type == "Receive" else doc.paid_from
    currency = doc.paid_to_account_currency if doc.payment_type == "Receive" else doc.paid_from_account_currency
    try:
        with _quiet_link_errors():
            _bank_account(bank_account, doc.company, currency)
    except (frappe.PermissionError, frappe.ValidationError):
        bank_account = None
        warnings.append(BANK_WARNING)
    return {"name": doc.name, "company": doc.company, "supplier": doc.party, "posting_date": doc.posting_date,
            "docstatus": doc.docstatus, "payment_type": doc.payment_type, "amount": doc.received_amount if doc.payment_type == "Receive" else doc.paid_amount,
            "currency": currency, "bank_account": bank_account, "remarks": doc.remarks,
            "references": refs, "vouchers": [], "warnings": warnings,
            "state": {0: "草稿 · 未计已付", 1: "已提交", 2: "已取消 · 未计已付"}[doc.docstatus]}


@frappe.whitelist()
def get_payment_records(company=None, supplier=None, purchase_order=None, purchase_receipt=None, search=None, start=0, page_length=100,
                        from_date=None, to_date=None, status=None, native_filters=None, or_filters=None, order_by=None, export_format=None, columns=None):
    token = _record_reader.set(_RecordReader())
    try:
        return _payment_records(company, supplier, purchase_order, purchase_receipt, search, start, page_length,
                                from_date=from_date, to_date=to_date, status=status, native_filters=native_filters,
                                or_filters=or_filters, order_by=order_by, export_format=export_format, columns=columns)
    finally:
        _record_reader.reset(token)


def _payment_records(company, supplier, purchase_order, purchase_receipt, search, start, page_length,
                     from_date=None, to_date=None, status=None, native_filters=None, or_filters=None, order_by=None, export_format=None, columns=None):
    if purchase_order:
        _source("Purchase Order", purchase_order)
    receipt_orders = set()
    if purchase_receipt:
        receipt = _source("Purchase Receipt", purchase_receipt)
        _require_fields("Purchase Receipt Item", {"purchase_order"}, "Purchase Receipt")
        receipt_orders = set(_source_links(receipt, "Purchase Order", "purchase_order", []))
    start, page_length = _pagination(start, page_length)
    _require_fields("Payment Entry", {"party_type", "references"})
    filters = {"party_type": "Supplier", "payment_type": ["in", ["Pay", "Receive"]]}
    for field, value in (("company", company), ("party", supplier)):
        if value:
            filters[field] = value
    if from_date or to_date:
        filters["posting_date"] = ["between", [from_date or "1900-01-01", to_date or "2999-12-31"]]
    if status is not None and status != "":
        state = {"Draft": 0, "Submitted": 1, "Cancelled": 2}.get(str(status), status)
        try:
            state = int(state)
        except (TypeError, ValueError):
            frappe.throw("付款状态无效")
        if state not in (0, 1, 2):
            frappe.throw("付款状态无效")
        filters["docstatus"] = state
    allowed = _query_fields("Payment Entry")
    query = _native_filters("Payment Entry", filters, allowed | {"party_type"}) + _native_filters("Payment Entry", native_filters, allowed)
    ors = _native_filters("Payment Entry", or_filters, allowed)
    sorting = _order_by("Payment Entry", order_by, allowed)
    try:
        with _quiet_link_errors():
            _require_fields("Payment Entry", {"party"})
    except frappe.PermissionError:
        candidates = []
    else:
        candidates = frappe.get_list("Payment Entry", filters=query, or_filters=ors, fields=["name", "party"], order_by=sorting, limit_page_length=0)
    # Preserve Python casefold and literal substring semantics (SQL LIKE/collations differ).
    names = [row.name for row in candidates if not search or str(search).casefold() in (row.name + " " + (row.party or "")).casefold()]
    reader = _record_reader.get()
    reader.preload("Payment Entry", names)
    payments = [reader.doc("Payment Entry", name) for name in names if reader.docs["Payment Entry", name]]
    reader.preload("Company", {doc.company for doc in payments})
    for doctype in ("Purchase Order", "Purchase Invoice"):
        reader.preload(doctype, {ref.reference_name for doc in payments for ref in doc.references if ref.reference_doctype == doctype and ref.reference_name})
    invoices = [doc for (dt, name), doc in reader.docs.items() if dt == "Purchase Invoice" and doc]
    for doctype, field in (("Purchase Order", "purchase_order"), ("Purchase Receipt", "purchase_receipt")):
        reader.preload(doctype, {item.get(field) for doc in invoices for item in doc.items if item.get(field)})
    rows = []
    for name in names:
        try:
            with _quiet_link_errors():
                row = _payment_row(reader.doc("Payment Entry", name))
        except (frappe.DoesNotExistError, frappe.PermissionError):
            continue
        if not row:
            continue
        refs = row["references"]
        if purchase_order and not any(purchase_order in ref["orders"] for ref in refs):
            continue
        if purchase_receipt and not any(purchase_receipt in ref["receipts"] or (ref["doctype"] == "Purchase Order" and receipt_orders.intersection(ref["orders"])) for ref in refs):
            continue
        rows.append(row)
    page = rows if export_format else rows[start:start + page_length]
    if page:
        try:
            with _quiet_link_errors():
                vouchers = _vouchers([row["name"] for row in page])
            by_name = {row["name"]: row for row in page}
            for voucher in vouchers:
                parent = voucher.pop("source_name")
                if voucher.pop("company") == by_name[parent]["company"]:
                    by_name[parent]["vouchers"].append(voucher)
        except frappe.PermissionError:
            pass
        _decorate_payments(page)
    if export_format:
        if export_format != "xlsx":
            frappe.throw("仅支持 XLSX 导出")
        return _export("Payment Entry", rows, columns, PAYMENT_COLUMNS)
    groups = {}
    for row in rows:
        group = (row["payment_type"], row["docstatus"], row["currency"])
        groups[group] = groups.get(group, Decimal(0)) + amount(row["amount"])
    totals = [{"payment_type": payment_type, "docstatus": status, "currency": currency, "amount": float(value)}
              for (payment_type, status, currency), value in sorted(groups.items())]
    # Whole bank-document amounts, never represented as procurement settlement.
    return {"rows": page, "total_count": len(rows),
            "totals": totals, "totals_label": "整张付款单银行币种金额（按付款类型、单据状态、币种分组）",
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
    drafts = [{"name": row["name"], "docstatus": 0} for row in invoices if row["docstatus"] == 0]
    can_invoice = bool(not incomplete and source_doctype == "Purchase Receipt" and doc.docstatus == 1
                       and not doc.get("is_return") and not drafts
                       and frappe.has_permission("Purchase Invoice", "read")
                       and frappe.has_permission("Purchase Invoice", "create"))
    if can_invoice:
        from deeplinkerp_branding.services.purchase_document_actions import _native
        try:
            with _quiet_link_errors():
                can_invoice = bool(_native(doc, "Purchase Invoice").items)
        except (frappe.ValidationError, frappe.PermissionError):
            can_invoice = False
    return {"source_doctype": source_doctype, "name": doc.name, "company": doc.company, "supplier": doc.supplier,
            "currency": doc.currency, "grand_total": doc.grand_total, "status": doc.status,
            "docstatus": doc.docstatus, "orders": orders, "order_progress": progress, "invoices": invoices, "balances": [] if incomplete else summarize(invoices), "incomplete_links": incomplete,
            "can_create_invoice": can_invoice, "draft_invoices": drafts,
            "payments": payments, "warnings": warnings, "can_create": can_create and bool(eligible) and not incomplete, "reason": reason,
            "settlement_label": "已付/核销（含预付款抵扣、贷项等）"}


@frappe.whitelist()
def get_receipt_list(filters=None, start=0, page_length=100, native_filters=None, or_filters=None, order_by=None,
                     search=None, export_format=None, columns=None, **unused):
    token = _record_reader.set(_RecordReader())
    try:
        return _receipt_list(filters, start, page_length, native_filters, or_filters, order_by, search, export_format, columns)
    finally:
        _record_reader.reset(token)


def _receipt_list(filters, start, page_length, native_filters, or_filters, order_by, search, export_format, columns):
    filters = json.loads(filters) if isinstance(filters, str) else filters or {}
    if not isinstance(filters, dict):
        frappe.throw("筛选条件必须为对象")
    query = {}
    for field in ("company", "supplier", "status"):
        if filters.get(field):
            query[field] = filters[field]
    if filters.get("from_date") or filters.get("to_date"):
        query["posting_date"] = ["between", [filters.get("from_date") or "1900-01-01", filters.get("to_date") or "2999-12-31"]]
    fields = RECEIPT_FIELDS
    _require_fields("Purchase Receipt", fields)
    start, page_length = _pagination(start, page_length)
    allowed = _query_fields("Purchase Receipt")
    query = _native_filters("Purchase Receipt", query, allowed) + _native_filters("Purchase Receipt", native_filters, allowed)
    ors = _native_filters("Purchase Receipt", or_filters, allowed)
    sorting = _order_by("Purchase Receipt", order_by, allowed)
    candidates = frappe.get_list("Purchase Receipt", filters=query, or_filters=ors, fields=fields, order_by=sorting, limit_page_length=0)
    keyword = str(search or filters.get("search") or "").casefold()
    candidates = [row for row in candidates if not keyword or keyword in " ".join(str(row.get(field) or "") for field in ("name", "supplier", "supplier_name")).casefold()]
    reader = _record_reader.get()
    reader.preload("Purchase Receipt", [row.name for row in candidates])
    reader.preload("Company", {row.company for row in candidates})
    visible = []
    for row in candidates:
        try:
            with _quiet_link_errors():
                _read("Purchase Receipt", row.name, fields)
            visible.append(row)
        except (frappe.PermissionError, frappe.DoesNotExistError):
            continue
    totals = {}
    for row in visible:
        totals[row.currency] = totals.get(row.currency, Decimal(0)) + amount(row.grand_total)
    rows = visible if export_format else visible[start:start + page_length]
    for row in rows:
        try:
            with _quiet_link_errors():
                chain = get_purchase_chain("Purchase Receipt", row.name, include_payments=False)
            row.update({key: chain[key] for key in ("orders", "balances", "can_create", "reason", "warnings", "incomplete_links")})
            row["can_create_invoice"] = chain["can_create_invoice"]
            row["draft_invoices"] = chain["draft_invoices"]
            row["shared_payable"] = bool(not chain["incomplete_links"] and any(invoice["shared"] for invoice in chain["invoices"]))
            row["settlement_state"] = "余额不可见" if chain["incomplete_links"] or (chain["warnings"] and not chain["balances"]) else "未形成应付"
            row["payment_state"] = ("关联缺失或无权读取" if chain["incomplete_links"] else "共享应付" if any(i["shared"] for i in chain["invoices"]) else "余额不可见" if chain["warnings"] else "未形成应付")
            if chain["balances"] and not chain["incomplete_links"]:
                balances = chain["balances"]
                row["settlement_state"] = "已付清" if all(b["outstanding"] <= 0 for b in balances) else "部分付款/核销" if any(b["settled"] > 0 for b in balances) else "未付款"
                if not chain["warnings"]:
                    row["payment_state"] = row["settlement_state"]
        except (frappe.PermissionError, frappe.DoesNotExistError):
            row.update(balances=[], orders=[], can_create=False, can_create_invoice=False, draft_invoices=[], shared_payable=False, settlement_state="余额不可见", reason=LINK_WARNING, payment_state="关联缺失或无权读取", warnings=[LINK_WARNING], incomplete_links=True)
    if export_format:
        if export_format != "xlsx":
            frappe.throw("仅支持 XLSX 导出")
        return _export("Purchase Receipt", rows, columns, RECEIPT_COLUMNS)
    return {"rows": rows, "total_count": len(visible), "totals": [{"currency": currency, "grand_total": float(value)} for currency, value in sorted(totals.items())]}


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
        _bank_account(bank_account, source.company, balance["currency"])
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
