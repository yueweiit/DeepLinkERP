"""40200 result equivalence and bounded performance on the isolated QA site only.
Run with an unmodified 40200 service file as argv[1]; all fixtures roll back.
"""
import collections
import importlib.util
import hashlib
from pathlib import Path
import json
import sys
import time
import uuid
from unittest.mock import patch
import frappe
from frappe.model.document import Document
from frappe.utils import nowdate, add_days
from deeplinkerp_branding.services import purchase_payment_service as service
from erpnext.buying.doctype.purchase_order.purchase_order import make_purchase_receipt
from erpnext.stock.doctype.purchase_receipt.purchase_receipt import make_purchase_invoice
from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry

SITE = "po-grid-qa.localhost"
COMPANY = "QA Second Company"
assert hashlib.sha256(Path(sys.argv[1]).read_bytes()).hexdigest() == "6d616e3d360fb96901fa48da61e02e649535cef85d6a15065e171e3d8fccf1fc", "Unmodified 40200 baseline required"
frappe.init(site=SITE, sites_path="/home/frappe/frappe-bench/sites")
frappe.connect()
assert frappe.local.site == SITE
frappe.set_user("Administrator")
frappe.flags.in_test = True
frappe.flags.mute_emails = True
spec = importlib.util.spec_from_file_location("baseline_40200", sys.argv[1])
baseline = importlib.util.module_from_spec(spec)
spec.loader.exec_module(baseline)
tracked = ["Purchase Order", "Purchase Receipt", "Purchase Invoice", "Payment Entry", "GL Entry", "Payment Ledger Entry", "China Accounting Voucher", "User Permission", "User", "Supplier"]
before = {dt: frappe.db.count(dt) for dt in tracked}
report = {"site": SITE, "baseline": "40200e2c9f1ccea8061df495569c7809ae540ee1", "samples": [], "scenarios": [], "equivalent_calls": 0}

def canonical(value):
    return json.loads(json.dumps(value, default=str, sort_keys=True))

def compare(label, **filters):
    old = baseline.get_payment_records(**filters)
    new = service.get_payment_records(**filters)
    assert canonical(old) == canonical(new), (label, old, new)
    assert service._record_reader.get() is None
    report["equivalent_calls"] += 1
    return new

def measure(module, **filters):
    count = 0
    original = frappe.db.sql
    def counted(query, *args, **kwargs):
        nonlocal count
        count += 1
        return original(query, *args, **kwargs)
    started = time.perf_counter()
    with patch.object(frappe.db, "sql", side_effect=counted):
        result = module.get_payment_records(company=COMPANY, page_length=10, **filters)
    return result, {"seconds": round(time.perf_counter()-started, 4), "sql_calls": count}

try:
    po = frappe.get_doc({"doctype": "Purchase Order", "company": COMPANY, "supplier": "QA Test Supplier", "currency": "CNY", "schedule_date": add_days(nowdate(), 1), "items": [{"item_code": "QA-PO-ITEM", "qty": 2, "rate": 1000, "schedule_date": add_days(nowdate(), 1)}]}).insert()
    po.submit()
    pr = make_purchase_receipt(po.name); pr.items[0].qty = 1; pr.insert(); pr.submit()
    pi = make_purchase_invoice(pr.name); pi.insert(); pi.submit()
    args = dict(source_doctype="Purchase Receipt", source_name=pr.name, purchase_invoice=pi.name, amount_to_pay=1, bank_account="Cash - QAB")
    drafts = []
    for size in (10, 50, 100):
        while len(drafts) < size:
            drafts.append(service.create_payment_draft(**args, request_id=str(uuid.uuid4()))["name"])
        sample = {"synthetic_drafts": size, "runs": []}
        for label, filters in (("first", {}), ("warm", {}), ("unmatched_search", {"search": "QA-NO-SUCH-PAYMENT"})):
            old, old_perf = measure(baseline, **filters)
            new, new_perf = measure(service, **filters)
            assert canonical(old) == canonical(new)
            assert new_perf["sql_calls"] < old_perf["sql_calls"] / 3
            sample["total_matches"] = old["total_count"] if not filters else sample["total_matches"]
            sample["runs"].append({"label": label, "before": old_perf, "after": new_perf})
            report["equivalent_calls"] += 1
        report["samples"].append(sample)
    full = compare("full ordered result", company=COMPANY, page_length=100)
    pages = []
    for start in range(0, full["total_count"]+10, 10):
        page = compare("page", company=COMPANY, start=start, page_length=10)
        assert page["total_count"] == full["total_count"]
        pages.extend(row["name"] for row in page["rows"])
    assert len(pages) == len(set(pages)) == full["total_count"]
    assert pages[:100] == [r["name"] for r in full["rows"]]
    for keyword in ("qa test SUPPLIER", drafts[0].lower(), "QA-NO-SUCH-PAYMENT", "%", "_", "供方", "STRASSE"):
        compare("literal casefold search", company=COMPANY, search=keyword, page_length=10)
    report["scenarios"].append("ordered pagination, exact total, no overlap, empty tail, literal/casefold keyword search")
    advance = get_payment_entry("Purchase Order", po.name, bank_account="Cash - QAB", bank_amount=100)
    advance.paid_amount = advance.received_amount = 100
    advance.references[0].allocated_amount = 100
    advance.insert()
    cancelled = frappe.get_doc("Payment Entry", drafts[-1]); cancelled.submit(); cancelled.cancel()
    submitted = frappe.get_doc("Payment Entry", drafts[-2]); submitted.submit()
    for filters in ({"purchase_order": po.name}, {"purchase_receipt": pr.name}, {"supplier": "QA Test Supplier"}, {"company": COMPANY, "purchase_receipt": pr.name, "search": "qa test"}):
        result = compare("procurement filters", **filters)
    result = compare("native states", purchase_order=po.name)
    assert {r["docstatus"] for r in result["rows"]} == {0, 1, 2}
    assert any(r["name"] == advance.name and r["references"][0]["doctype"] == "Purchase Order" for r in result["rows"])
    report["scenarios"].append("draft/submitted/cancelled, PO advance through PR, PI references, vouchers, combined filters")
    def dirty(label, mutate):
        frappe.db.savepoint("record_equivalence")
        try:
            mutate()
            compare(label, company=COMPANY)
            compare(label, purchase_order=po.name)
        finally:
            frappe.db.rollback(save_point="record_equivalence")
        report["scenarios"].append(label)
    dirty("missing PI reference", lambda: frappe.db.set_value("Payment Entry Reference", {"parent": drafts[2]}, "reference_name", "QA-MISSING-PI"))
    dirty("missing PR association", lambda: frappe.db.set_value("Purchase Invoice Item", {"parent": pi.name}, "purchase_receipt", "QA-MISSING-PR"))
    foreign = frappe.get_list("Purchase Order", filters={"company": ["!=", COMPANY]}, pluck="name", limit_page_length=1)[0]
    dirty("cross-company PO association", lambda: frappe.db.set_value("Purchase Invoice Item", {"parent": pi.name}, "purchase_order", foreign))
    dirty("non-procurement PI excluded", lambda: frappe.db.set_value("Purchase Invoice Item", {"parent": pi.name}, {"purchase_order": None, "purchase_receipt": None}))
    dirty("Receive bank amount/currency preserved", lambda: frappe.db.set_value("Payment Entry", drafts[3], {"payment_type": "Receive", "received_amount": 7}))
    # Distinct shared payable and a supplier whose Unicode casefold differs from SQL LIKE.
    supplier = frappe.copy_doc(frappe.get_doc("Supplier", "QA Test Supplier"))
    supplier.supplier_name = "QA Straße_供方% " + uuid.uuid4().hex[:8]
    supplier.insert()
    shared_po = frappe.get_doc({"doctype": "Purchase Order", "company": COMPANY, "supplier": supplier.name, "currency": "CNY", "schedule_date": add_days(nowdate(), 1), "items": [{"item_code": "QA-PO-ITEM", "qty": 2, "rate": 1000, "schedule_date": add_days(nowdate(), 1)}]}).insert(); shared_po.submit()
    shared_receipts = []
    for _ in range(2):
        receipt = make_purchase_receipt(shared_po.name); receipt.items[0].qty = 1; receipt.insert(); receipt.submit(); shared_receipts.append(receipt)
    shared_pi = make_purchase_invoice(shared_receipts[0].name)
    shared_pi = make_purchase_invoice(shared_receipts[1].name, target_doc=shared_pi)
    shared_pi.insert(); shared_pi.submit()
    shared_payment = service.create_payment_draft(source_doctype="Purchase Receipt", source_name=shared_receipts[0].name, purchase_invoice=shared_pi.name, amount_to_pay=1, bank_account="Cash - QAB", request_id=str(uuid.uuid4()))["name"]
    for receipt in shared_receipts:
        result = compare("shared PI through either PR", purchase_receipt=receipt.name)
        assert any(row["name"] == shared_payment for row in result["rows"])
    for keyword in ("STRASSE", "_供方%", "%", supplier.name.lower()):
        result = compare("Unicode casefold and literal wildcard characters", search=keyword, page_length=100)
        assert any(row["name"] == shared_payment for row in result["rows"])
    report["scenarios"].append("shared PI across two PRs and nontrivial Unicode casefold/literal wildcard searches")
    real_check = Document.check_permission
    for dt, name in (("Payment Entry", drafts[4]), ("Purchase Invoice", pi.name), ("Purchase Order", po.name), ("Company", COMPANY)):
        def check(doc, *a, **kw):
            if doc.doctype == dt and doc.name == name:
                raise frappe.PermissionError
            return real_check(doc, *a, **kw)
        with patch.object(Document, "check_permission", check):
            result = compare("document/controller permission denial", company=COMPANY)
            if dt == "Company": assert not result["rows"] and result["total_count"] == 0
    report["scenarios"].append("normal per-document/controller permission checks on PE/PI/PO/Company")
    for dt, field in (("Payment Entry", "paid_amount"), ("Payment Entry", "party"), ("Payment Entry Reference", "allocated_amount"), ("Purchase Invoice Item", "purchase_order")):
        original = service.get_permitted_fields
        def fields(doctype, *a, **kw):
            return [f for f in original(doctype, *a, **kw) if not (doctype == dt and f == field)]
        with patch.object(service, "get_permitted_fields", fields), patch.object(baseline, "get_permitted_fields", fields):
            compare("parent/child field permission denial", company=COMPANY)
    report["scenarios"].append("parent/child field permission denial without target or amount leakage")
    # Keep existing test permissions untouched: new transaction-local accounting reader.
    reader_user = "qa-record-reader-" + uuid.uuid4().hex + "@example.invalid"
    frappe.get_doc({"doctype": "User", "email": reader_user, "first_name": "QA Records", "send_welcome_email": 0, "roles": [{"role": "Accounts User"}, {"role": "Purchase User"}]}).insert()
    frappe.get_doc({"doctype": "User Permission", "user": reader_user, "allow": "Company", "for_value": COMPANY, "apply_to_all_doctypes": 1}).insert()
    frappe.set_user(reader_user)
    result = compare("real company-restricted accounting user", page_length=100)
    assert result["rows"] and all(row["company"] == COMPANY for row in result["rows"])
    foreign_company = frappe.db.get_value("Purchase Order", foreign, "company")
    result = compare("restricted user explicit foreign company", company=foreign_company)
    assert not result["rows"] and result["total_count"] == 0
    for module in (baseline, service):
        try: module.get_payment_records(purchase_order=foreign)
        except frappe.PermissionError: pass
        else: raise AssertionError("cross-company source readable")
    frappe.set_user("qa-po-reader@example.invalid")
    for module in (baseline, service):
        try: module.get_payment_records()
        except frappe.PermissionError: pass
        else: raise AssertionError("purchase-only reader saw payment records")
    frappe.set_user("Administrator")
    assert service._record_reader.get() is None
    report["scenarios"].append("existing company-restricted user and forbidden source filters; request cache restored")
    report["status"] = "passed"
finally:
    frappe.set_user("Administrator")
    frappe.db.rollback()
    after = {dt: frappe.db.count(dt) for dt in tracked}
    assert before == after, (before, after)
    report["rollback_counts_unchanged"] = True
    print(json.dumps(report, ensure_ascii=False, default=str))
    frappe.destroy()
