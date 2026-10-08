"""Procurement invariants after all native controller and finance hooks.

Native controllers own quantities, tax, stock valuation, GL and payment ledgers.
These checks compare their persisted results with native plans; they never post
replacement ledgers or manufacture documents in other business modules.
"""
from __future__ import annotations

import uuid
from copy import deepcopy
from decimal import Decimal, ROUND_HALF_UP

import frappe
from frappe.utils import getdate

from . import purchase_operation as operation
from . import purchase_payment_service as service


def is_procurement(doc):
    if doc.doctype in ("Purchase Order", "Purchase Receipt"):
        return True
    if doc.doctype == "Purchase Invoice":
        return any(row.get("purchase_order") or row.get("purchase_receipt") for row in doc.get("items") or [])
    if doc.doctype != "Payment Entry" or doc.get("party_type") != "Supplier":
        return False
    for row in doc.get("references") or []:
        if row.reference_doctype == "Purchase Order":
            return True
        if row.reference_doctype == "Purchase Invoice" and frappe.db.exists("Purchase Invoice Item",
            {"parent": row.reference_name, "purchase_order": ["is", "set"]}):
            return True
        if row.reference_doctype == "Purchase Invoice" and frappe.db.exists("Purchase Invoice Item",
            {"parent": row.reference_name, "purchase_receipt": ["is", "set"]}):
            return True
    return False


def equal(doc, field, actual, expected, label):
    precision = doc.precision(field)
    if precision is None:
        frappe.throw("原生业务精度不可用，不能确认采购操作")
    quantum = Decimal(1).scaleb(-precision)
    if service.amount(actual).quantize(quantum, ROUND_HALF_UP) != service.amount(expected).quantize(quantum, ROUND_HALF_UP):
        frappe.throw("采购一致性核对失败：" + label)


def snapshot(doc):
    return {"doctype": doc.doctype, "name": doc.name, "docstatus": doc.docstatus,
        "modified": str(doc.get("modified") or ""), "amount": doc.get("paid_amount") if doc.doctype == "Payment Entry" else doc.get("grand_total"),
        "currency": doc.get("paid_from_account_currency") if doc.doctype == "Payment Entry" else doc.get("currency"),
        "items": [{"key": row.get("name"), "qty": row.get("qty"), "rate": row.get("rate"),
            "warehouse": row.get("warehouse")} for row in doc.get("items") or []]}


def _state():
    return getattr(frappe.local, "purchase_consistency", None)


def _context():
    return operation.current() or {"operation_id": operation.identity(frappe.session.user, str(uuid.uuid4())),
        "user": frappe.session.user, "request_id": "native-form", "before": {}, "after": {},
        "documents": [], "amount": None, "currency": None, "quantity": [], "modules": []}


def register_document(doc, method=None):
    if not is_procurement(doc):
        return
    state = _state()
    if state is None:
        state = {"documents": {}, "before_documents": {}, "context": _context(), "explicit": operation.current() is not None}
        frappe.local.purchase_consistency = state
        frappe.db.before_commit.add(lambda: _before_commit(state))
        frappe.db.after_rollback.add(lambda: setattr(frappe.local, "purchase_consistency", None))
    key = (doc.doctype, doc.name)
    state["documents"][key] = doc
    context = state["context"]
    old = doc.get_doc_before_save()
    state["before_documents"].setdefault(key, old)
    context["before"].setdefault(doc.doctype + ":" + doc.name, snapshot(old) if old else {"exists": False})
    context["after"][doc.doctype + ":" + doc.name] = snapshot(doc)
    if {"doctype": doc.doctype, "name": doc.name} not in context["documents"]:
        context["documents"].append({"doctype": doc.doctype, "name": doc.name})
    facts = snapshot(doc)
    context.update(amount=facts["amount"], currency=facts["currency"], quantity=[row.get("qty") for row in doc.get("items") or []])


def bind_operation(context):
    state = _state()
    if state:
        for key in ("before", "after"):
            context[key].update(state["context"].get(key, {}))
        context["documents"] = list(state["context"].get("documents", []))
        state.update(context=context, explicit=True)


def _before_commit(state):
    try:
        check_registered(state)
        finish_native_audit(state)
    except Exception as error:
        frappe.db.rollback()
        operation.runtime_log(state["context"], "rolled_back_before_commit", error)
        raise
    finally:
        frappe.local.purchase_consistency = None


def finish_native_audit(state):
    if state["explicit"]:
        frappe.db.set_value("Integration Request", state["context"]["operation_id"],
            {"data": operation.encode(state["context"])}, update_modified=False)
        return
    context = state["context"]
    operation._reserve(context)
    doc = next(reversed(state["documents"].values()))
    operation.complete_audit(context, {"document": snapshot(doc)})
    operation.runtime_log(context, "success_pending_commit")


def check_registered(state=None):
    state = state or _state()
    if not state:
        return
    modules = []
    for key, doc in state["documents"].items():
        # Re-read after the complete hook chain, including auto PI creation.
        old = state["before_documents"][key]
        doc = frappe.get_doc(*key, for_update=True)
        doc._doc_before_save = old
        modules.extend(check_document(doc))
        state["context"]["after"][doc.doctype + ":" + doc.name] = snapshot(doc)
    state["context"]["modules"].extend(modules)


def _stage(doc, name, action):
    state = _state()
    context = operation.current() or (state["context"] if state else _context())
    facts = snapshot(doc)
    context.update(amount=facts["amount"], currency=facts["currency"], quantity=[row["qty"] for row in facts["items"]])
    return operation.trace(context, name, action, source={"doctype": doc.doctype, "name": doc.name},
        target={"doctype": doc.doctype, "name": doc.name})


def check_draft(doc):
    for ledger, filters in (("Stock Ledger Entry", {"voucher_type": doc.doctype, "voucher_no": doc.name}),
        ("GL Entry", {"voucher_type": doc.doctype, "voucher_no": doc.name}),
        ("Payment Ledger Entry", {"voucher_type": doc.doctype, "voucher_no": doc.name})):
        if frappe.db.exists(ledger, filters):
            frappe.throw("采购草稿不能形成库存或财务流水")
    if doc.doctype == "Purchase Order":
        for row in doc.items:
            equal(row, "received_qty", row.get("received_qty"), 0, "草稿订单实际收货数量")
        equal(doc, "advance_paid", doc.get("advance_paid"), 0, "草稿订单实际付款")


def finance_service(doc):
    if not frappe.db.exists("DocType", "China Finance Settings"):
        return None
    from china_finance.services import voucher
    settings = voucher.get_company_settings(doc.company)
    if not settings or getdate(voucher.get_posting_date(doc)) < getdate(settings.activation_date):
        return None
    return voucher


def _ledger(doc, doctype, **filters):
    return frappe.db.get_values(doctype, {"voucher_type": doc.doctype, "voucher_no": doc.name, **filters},
        "*", as_dict=True, for_update=True)


def _balanced(doc, rows, field="base_grand_total"):
    equal(doc, field, sum((service.amount(row.get("debit")) for row in rows), Decimal(0)),
        sum((service.amount(row.get("credit")) for row in rows), Decimal(0)), "原生总账借贷")


def _gl_map(rows):
    result = {}
    for row in rows:
        key = tuple(row.get(field) or "" for field in ("account", "party_type", "party", "account_currency",
            "cost_center", "project", "finance_book", "against_voucher_type", "against_voucher"))
        value = result.setdefault(key, [Decimal(0), Decimal(0)])
        value[0] += service.amount(row.get("debit")) - service.amount(row.get("credit"))
        value[1] += service.amount(row.get("debit_in_account_currency")) - service.amount(row.get("credit_in_account_currency"))
    return result


def _gl_precision(doc, field, currency=None):
    from frappe.model.meta import get_field_precision
    currency = currency or frappe.get_cached_value("Company", doc.company, "default_currency")
    return get_field_precision(frappe.get_meta("GL Entry").get_field(field), currency=currency)


def _compare_gl(doc, actual, expected, label, *, reverse=False):
    for key in actual.keys() | expected.keys():
        for index, field in enumerate(("debit", "debit_in_account_currency")):
            precision = _gl_precision(doc, field, key[3] if index else None)
            quantum = Decimal(1).scaleb(-precision)
            planned = service.amount(expected.get(key, [0, 0])[index]) * (-1 if reverse else 1)
            if service.amount(actual.get(key, [0, 0])[index]).quantize(quantum, ROUND_HALF_UP) != planned.quantize(quantum, ROUND_HALF_UP):
                frappe.throw("采购一致性核对失败：" + label)


def check_finance(doc, rows):
    field = "base_paid_amount" if doc.doctype == "Payment Entry" else "base_grand_total"
    _balanced(doc, rows, field)
    if doc.doctype == "Purchase Receipt":
        import erpnext
        from erpnext.stock import get_warehouse_account_map
        expected = doc.get_gl_entries(get_warehouse_account_map(doc.company)) if erpnext.is_perpetual_inventory_enabled(doc.company) or frappe.db.get_value(
            "Company", doc.company, "enable_provisional_accounting_for_non_stock_items") else []
    elif doc.doctype == "Purchase Invoice":
        expected = doc.get_gl_entries()
    elif doc.doctype == "Payment Entry":
        from erpnext.accounts.general_ledger import process_gl_map
        expected = process_gl_map(doc.build_gl_map(), merge_entries=frappe.get_single_value("Accounts Settings", "merge_similar_account_heads"))
    else:
        expected = []
    actual_map, expected_map = _gl_map(rows), _gl_map(expected)
    _compare_gl(doc, actual_map, expected_map, "总账与原生控制器分录")
    finance = finance_service(doc)
    if not rows:
        return {"module": "China Finance", "result": "N/A", "reason": "native controller produces no GL"}
    if not finance:
        return {"module": "China Finance", "result": "N/A", "reason": "company finance settings inactive for posting date"}
    name = finance.create_voucher_from_source(doc, "Posting")
    if not name:
        frappe.throw("中国会计凭证未生成，采购操作不能提交")
    voucher = frappe.get_doc("China Accounting Voucher", name, for_update=True)
    if voucher.docstatus != 1 or voucher.company != doc.company:
        frappe.throw("中国会计凭证状态或公司不一致")
    equal(voucher, "total_debit", voucher.total_debit, voucher.total_credit, "中国会计凭证借贷")
    # Compare individual native GL allocations too; balanced totals alone are insufficient.
    _compare_gl(doc, _gl_map(voucher.entries), actual_map, "中国会计凭证与总账")
    return {"module": "China Finance", "result": "verified", "voucher": voucher.name}


def check_cancellation(doc, cancelled_gl):
    finance = finance_service(doc)
    if not cancelled_gl:
        return {"module": "China Finance cancellation", "result": "N/A", "reason": "source has no GL"}
    if not finance:
        return {"module": "China Finance cancellation", "result": "N/A", "reason": "company finance settings inactive"}
    result = finance.process_cancellation_snapshot(doc.doctype, doc.name)
    if result.get("status") != "resolved" or not result.get("voucher"):
        frappe.throw("中国会计凭证冲销尚未完成，采购取消已回滚")
    reversal = frappe.get_doc("China Accounting Voucher", result["voucher"], for_update=True)
    if reversal.docstatus != 1 or not reversal.reversal_of:
        frappe.throw("中国会计凭证冲销关联不完整")
    original = frappe.get_doc("China Accounting Voucher", reversal.reversal_of, for_update=True)
    if original.reversed_by != reversal.name or original.status != "Reversed":
        frappe.throw("中国会计凭证原凭证尚未完成冲销")
    for voucher, event in ((original, "Posting"), (reversal, "Cancellation")):
        if (voucher.company, voucher.source_doctype, voucher.source_name, voucher.source_event) != (doc.company, doc.doctype, doc.name, event):
            frappe.throw("中国会计凭证冲销来源或公司不一致")
    equal(reversal, "total_debit", reversal.total_debit, reversal.total_credit, "冲销凭证借贷")
    _compare_gl(doc, _gl_map(reversal.entries), _gl_map(original.entries), "冲销凭证与原凭证反向金额", reverse=True)
    return {"module": "China Finance cancellation", "result": "verified", "voucher": reversal.name}


def check_sources(doc):
    """Validate every supplied native row identity, including native forms/multi-PO."""
    for row in doc.get("items") or []:
        for doctype, link, detail in (("Purchase Order", "purchase_order", "purchase_order_item" if doc.doctype == "Purchase Receipt" else "po_detail"),
            ("Purchase Receipt", "purchase_receipt", "pr_detail")):
            name, identity = row.get(link), row.get(detail)
            if not name and not identity:
                continue
            if not name or not identity:
                frappe.throw("采购来源父单据与明细身份必须同时存在")
            source = service._current(doctype, name)
            original = next((item for item in source.items if item.name == identity), None)
            if not original or original.item_code != row.item_code or original.get("stock_uom") != row.get("stock_uom"):
                frappe.throw("采购来源明细、物料或库存单位不一致")
            if source.company != doc.company or source.supplier != doc.supplier or source.docstatus != 1:
                frappe.throw("采购来源状态、公司或供应商不一致")
            if doctype == "Purchase Order":
                from .purchase_source_service import validate_source_before_submit
                validate_source_before_submit(source)
                reason = service.order_execution_reason(source)
                if reason and source.status != "Completed":
                    frappe.throw(reason)
    if doc.doctype == "Purchase Invoice" and doc.get("update_stock") and any(row.get("purchase_receipt") for row in doc.items):
        frappe.throw("已入库来源应付不能重复更新库存")


def check_stock(doc):
    rows = _ledger(doc, "Stock Ledger Entry", is_cancelled=0)
    if doc.doctype == "Purchase Invoice" and not doc.get("update_stock"):
        if rows:
            frappe.throw("非库存采购应付不能重复形成库存流水")
        return
    expected = {}
    for row in doc.items:
        if not frappe.get_cached_value("Item", row.item_code, "is_stock_item"):
            continue
        for warehouse, qty in ((row.get("warehouse"), row.get("stock_qty")),
            (row.get("rejected_warehouse"), service.amount(row.get("rejected_qty")) * service.amount(row.get("conversion_factor")))):
            if not warehouse or not service.amount(qty):
                continue
            key = (row.name, row.item_code, warehouse)
            expected[key] = (row, service.amount(qty) if doc.docstatus == 1 else Decimal(0))
            warehouse_doc = service._read("Warehouse", warehouse, {"company", "is_group", "disabled"})
            if warehouse_doc.company != doc.company or warehouse_doc.is_group or warehouse_doc.disabled:
                frappe.throw("原生库存仓库公司或状态不一致")
    actual = {}
    for entry in rows:
        key = (entry.voucher_detail_no, entry.item_code, entry.warehouse)
        if key not in expected:
            frappe.throw("采购库存流水没有明确对应原生物料明细和仓库")
        actual[key] = actual.get(key, Decimal(0)) + service.amount(entry.actual_qty)
    for key, (row, qty) in expected.items():
        equal(row, "stock_qty", actual.get(key, 0), qty, "入库流水与原生库存数量")
    for item, warehouse in sorted({(key[1], key[2]) for key in expected}):
        entries = frappe.db.get_values("Stock Ledger Entry", {"item_code": item, "warehouse": warehouse, "is_cancelled": 0},
            ["actual_qty"], as_dict=True, for_update=True)
        bins = frappe.db.get_values("Bin", {"item_code": item, "warehouse": warehouse}, ["actual_qty"], as_dict=True, for_update=True)
        if len(bins) != 1:
            frappe.throw("原生库存 Bin 缺失或重复")
        row = next(value[0] for key, value in expected.items() if key[1:] == (item, warehouse))
        equal(row, "stock_qty", bins[0].actual_qty,
            sum((service.amount(entry.actual_qty) for entry in entries), Decimal(0)), "Bin 与库存流水")


def check_order_received(doc):
    names = {row.get("purchase_order") for row in doc.items if row.get("purchase_order")}
    for name in sorted(names):
        order = service._current("Purchase Order", name)
        receipts = frappe.db.get_values("Purchase Receipt Item", {"purchase_order": name, "docstatus": 1},
            ["purchase_order_item", "qty", "conversion_factor", "stock_uom"], as_dict=True, for_update=True)
        invoices = frappe.db.get_values("Purchase Invoice Item", {"purchase_order": name, "docstatus": 1},
            ["po_detail", "qty", "conversion_factor", "stock_uom", "parent"], as_dict=True, for_update=True)
        totals = {}
        for row in receipts:
            original = next((item for item in order.items if item.name == row.purchase_order_item), None)
            if not original or row.stock_uom != original.stock_uom:
                frappe.throw("订单收货来源明细或库存单位不一致")
            totals[original.name] = totals.get(original.name, Decimal(0)) + service.amount(row.qty) * service.amount(row.conversion_factor) / service.amount(original.conversion_factor)
        for row in invoices:
            if not frappe.db.get_value("Purchase Invoice", row.parent, "update_stock"):
                continue
            original = next((item for item in order.items if item.name == row.po_detail), None)
            if not original or row.stock_uom != original.stock_uom:
                frappe.throw("库存应付来源明细或库存单位不一致")
            totals[original.name] = totals.get(original.name, Decimal(0)) + service.amount(row.qty) * service.amount(row.conversion_factor) / service.amount(original.conversion_factor)
        for row in order.items:
            equal(row, "received_qty", row.received_qty, totals.get(row.name, 0), "采购订单已收数量与原生来源")


def check_invoice_balance(doc):
    from erpnext.accounts.utils import QueryPaymentLedger
    ple = frappe.qb.DocType("Payment Ledger Entry")
    outstanding = QueryPaymentLedger().get_voucher_outstandings([frappe._dict(voucher_type=doc.doctype, voucher_no=doc.name)],
        common_filter=[ple.party_type == "Supplier", ple.party == doc.supplier, ple.account == doc.credit_to])
    if not outstanding:
        frappe.throw("采购应付缺少原生付款账簿")
    equal(doc, "outstanding_amount", doc.outstanding_amount, outstanding[0]["outstanding_in_account_currency"], "应付余额与原生付款账簿")


def check_document(doc):
    if doc.get("custom_operating_source") or doc.get("custom_operating_recognition"):
        frappe.throw("采购与经营费用关联尚无同步适配，操作已停止，请核对原生关联")
    if doc.docstatus == 0:
        _stage(doc, "native draft / stock / GL / AP", lambda: check_draft(doc))
        return [{"module": "native ledgers", "result": "verified", "reason": "draft has no real movement"},
            *_stage(doc, "Sales / procurement review / Operating applicability", lambda: invalidate_reviews(doc))]
    if doc.doctype == "Purchase Order":
        from .purchase_source_service import validate_source_before_submit
        if doc.docstatus == 1:
            _stage(doc, "procurement / source guards", lambda: validate_source_before_submit(doc))
        return [{"module": "procurement source", "result": "verified"},
            *_stage(doc, "Sales / procurement review / Operating applicability", lambda: invalidate_reviews(doc))]
    if doc.doctype == "Payment Entry":
        doc.validate_duplicate_entry()
        if {row.reference_doctype for row in doc.references} - {"Purchase Invoice", "Purchase Order"}:
            frappe.throw("混合采购与其他模块付款引用尚无同步适配，操作已停止")
        for row in doc.references:
            source = service._current(row.reference_doctype, row.reference_name)
            if source.company != doc.company or source.supplier != doc.party:
                frappe.throw("付款引用公司或供应商不一致")
            if row.reference_doctype == "Purchase Invoice" and source.docstatus == 1:
                _stage(source, "AP / Payment Ledger", lambda: check_invoice_balance(source))
    else:
        if doc.docstatus == 1:
            _stage(doc, "procurement source / row identities", lambda: check_sources(doc))
        _stage(doc, "Inventory / SLE / Bin / warehouse", lambda: check_stock(doc))
        _stage(doc, "procurement / authoritative received quantities", lambda: check_order_received(doc))
    gl = _ledger(doc, "GL Entry", is_cancelled=0)
    if doc.docstatus == 2:
        if gl or _ledger(doc, "Payment Ledger Entry", delinked=0):
            frappe.throw("采购取消后仍有有效财务流水")
        modules = [_stage(doc, "China Finance / synchronous cancellation", lambda: check_cancellation(doc, _ledger(doc, "GL Entry", is_cancelled=1)))]
    else:
        modules = [_stage(doc, "GL / China Finance", lambda: check_finance(doc, gl))]
        if doc.doctype == "Purchase Invoice":
            _stage(doc, "AP / Payment Ledger", lambda: check_invoice_balance(doc))
    modules.extend(_stage(doc, "Sales / procurement review / Operating applicability", lambda: invalidate_reviews(doc)))
    return modules


def invalidate_reviews(doc):
    """Invalidate existing managed review versions; never overwrite native prices."""
    from . import purchase_fulfilment_service as fulfilment
    if doc.doctype != "Purchase Order":
        return [{"module": "Sales/procurement review", "result": "N/A", "reason": "receipt/payment does not change confirmed native order price or quantity"},
            {"module": "Operating", "result": "N/A", "reason": "no registered Operating dependency"}]
    old = doc.get_doc_before_save()
    fields = ("company", "supplier", "currency", "grand_total")
    changed = not old or any(doc.get(field) != old.get(field) for field in fields) or [
        (row.name, row.item_code, row.qty, row.rate, row.get("uom"), row.get("conversion_factor")) for row in doc.items] != [
        (row.name, row.item_code, row.qty, row.rate, row.get("uom"), row.get("conversion_factor")) for row in old.items]
    if not changed and doc.docstatus != 2:
        return [{"module": "Sales/procurement review", "result": "N/A", "reason": "native order terms unchanged"}]
    order_names = {doc.name}
    links = []
    if order_names and frappe.db.exists("DocType", fulfilment.DOCTYPE):
        links = frappe.db.sql("SELECT name FROM `tabPurchase Fulfilment Link` WHERE active=1 AND "
            "(external_order IN %(orders)s OR internal_order IN %(orders)s) ORDER BY name FOR UPDATE", {"orders": tuple(sorted(order_names))}, as_dict=True)
    for row in links:
        link = frappe.get_doc(fulfilment.DOCTYPE, row.name, for_update=True)
        versions = fulfilment._json(link.source_versions_json)
        marker = doc.doctype + ":" + doc.name + ":" + str(doc.modified)
        if versions.get("procurement_review_invalidated") == marker:
            continue
        fulfilment._audit(link, "native_procurement_change", {"source": marker,
            "previous_price_confirmation": fulfilment._json(link.price_confirmation_json)})
        versions.update(procurement_review_invalidated=marker, external_item_version="invalidated:" + marker)
        frappe.db.set_value(fulfilment.DOCTYPE, link.name, {"source_versions_json": fulfilment._dump(versions),
            "price_confirmation_json": "{}", "price_confirmed_by": None, "price_confirmed_on": None,
            "audit_json": link.audit_json})
    return [{"module": "Sales/procurement review", "result": "invalidated" if links else "N/A",
        "reason": "existing managed fulfilment links" if links else "no existing dependent fulfilment link"},
        {"module": "Operating", "result": "N/A", "reason": "native procurement has no registered Operating dependency"}]


class ProcurementControllerBoundary:
    """Also roll back native form/import controller failures, without touching other PE flows."""
    def _procurement_call(self, method, *args, **kwargs):
        if not is_procurement(self):
            return method(*args, **kwargs)
        initial = deepcopy(self.as_dict())
        initial_flags, initial_action = dict(self.flags), getattr(self, "_action", None)
        result, attempts = {}, 0

        def write():
            nonlocal attempts
            if attempts:
                # A deadlock retries the complete native operation on a fresh
                # transaction, without keeping controller-mutated child rows.
                self.__init__(deepcopy(initial))
                self.flags.update(initial_flags)
                self._action = initial_action
            attempts += 1
            prepare_document(self)
            context = operation.current()
            if self.name and {"doctype": self.doctype, "name": self.name} not in context["documents"]:
                context["documents"].append({"doctype": self.doctype, "name": self.name})
            if self.name and not self.is_new() and method.__name__ != "insert":
                old = service._current(self.doctype, self.name)
                context["before"].setdefault(self.doctype + ":" + self.name, snapshot(old))
            try:
                result["doc"] = method(*args, **kwargs)
                return {"document": snapshot(result["doc"])}
            finally:
                context["after"][self.doctype + ":" + str(self.name)] = snapshot(self)

        if operation.current() is not None:
            write()
        else:
            operation.run(str(uuid.uuid4()), {"doctype": self.doctype, "name": self.name,
                "modified": self.get("modified"), "docstatus": self.docstatus}, write,
                lambda previous: frappe.get_doc(previous["doctype"], previous["name"]))
        return result["doc"]

    def insert(self, *args, **kwargs):
        return self._procurement_call(super().insert, *args, **kwargs)

    def _save(self, *args, **kwargs):
        return self._procurement_call(super()._save, *args, **kwargs)


def prepare_document(doc):
    """Acquire the same PO -> PR -> PI source locks before native validation."""
    orders, receipts, invoices = set(), set(), set()
    for row in doc.get("items") or []:
        if row.get("purchase_order"):
            orders.add(row.purchase_order)
        if row.get("purchase_receipt"):
            receipts.add(row.purchase_receipt)
    for row in doc.get("references") or []:
        if row.reference_doctype == "Purchase Order":
            orders.add(row.reference_name)
        elif row.reference_doctype == "Purchase Invoice":
            invoices.add(row.reference_name)
            invoice = service._read("Purchase Invoice", row.reference_name)
            orders.update(item.purchase_order for item in invoice.items if item.get("purchase_order"))
            receipts.update(item.purchase_receipt for item in invoice.items if item.get("purchase_receipt"))
    for name in sorted(receipts):
        receipt = service._read("Purchase Receipt", name)
        orders.update(item.purchase_order for item in receipt.items if item.get("purchase_order"))
    for doctype, names in (("Purchase Order", orders), ("Purchase Receipt", receipts), ("Purchase Invoice", invoices)):
        for name in sorted(names):
            service._current(doctype, name)
