"""Native drawer actions on one synthetic site, always rolled back."""
import json
import subprocess
import sys
import uuid
import unittest
from unittest.mock import patch

import frappe
from erpnext.buying.doctype.purchase_order.purchase_order import make_purchase_receipt
from erpnext.stock.doctype.purchase_receipt.purchase_receipt import (
    make_purchase_invoice,
    make_purchase_return,
)
from frappe.utils import add_days, nowdate

from deeplinkerp_branding.services import purchase_payment_service as service

SITE = "po-grid-qa.localhost"
COMPANY = "QA Second Company"


def execute():
    if frappe.local.site != SITE:
        raise RuntimeError("Synthetic QA site only")
    frappe.set_user("Administrator")
    frappe.flags.in_test = True
    frappe.flags.mute_emails = True
    doctypes = ("Purchase Order", "Purchase Receipt", "Purchase Invoice", "Payment Entry", "GL Entry", "China Accounting Voucher", "China Voucher Sync Issue")
    before = {doctype: frappe.db.count(doctype) for doctype in doctypes}
    results = []
    try:
        po = frappe.get_doc({"doctype": "Purchase Order", "company": COMPANY,
            "supplier": "QA Test Supplier", "currency": "CNY", "schedule_date": add_days(nowdate(), 1),
            "items": [{"item_code": "QA-PO-ITEM", "qty": 10, "rate": 1000,
                "schedule_date": add_days(nowdate(), 1)}]}).insert()
        po.submit()
        pr = make_purchase_receipt(po.name)
        pr.items[0].qty = 4
        pr.insert()
        pr.submit()
        pi = make_purchase_invoice(pr.name)
        pi.items[0].qty = 2
        pi.insert()
        pi.submit()
        chain = service.get_purchase_chain("Purchase Receipt", pr.name, include_payments=False)
        assert chain["can_create_invoice"], "Submitted partial PI must permit native remaining quantity"
        assert chain["draft_invoices"] == [], "Submitted PI must not be a resume action"
        results.append("partial submitted invoice permits remaining native quantity")

        from unittest.mock import patch

        from deeplinkerp_branding.services import purchase_document_actions as actions
        original_fields = service._require_fields
        for denied_doctype, denied_parent in (("Purchase Receipt", None), ("Purchase Taxes and Charges", "Purchase Receipt")):
            def protect_source_tax(doctype, fields, parenttype=None):
                if doctype == denied_doctype and parenttype == denied_parent and (doctype == "Purchase Taxes and Charges" or "taxes" in fields):
                    raise frappe.PermissionError
                return original_fields(doctype, fields, parenttype)
            with patch.object(service, "_require_fields", side_effect=protect_source_tax):
                try:
                    actions.preview_document("Purchase Receipt", pr.name, "Purchase Invoice")
                except frappe.PermissionError:
                    pass
                else:
                    raise AssertionError("Protected source taxes leaked through mapped target totals")
        results.append("protected source header and child tax fields deny mapped preview")
        preview = actions.preview_document("Purchase Receipt", pr.name, "Purchase Invoice")
        item = preview["document"]["items"][0]
        assert item["qty"] == item["max_qty"] == 2
        assert "credit_to" not in preview["document"]
        assert "owner" not in preview["document"]
        request_id = str(uuid.uuid4())
        changes = {"items": [{"key": item["key"], "qty": 1, "rate": 1000}], "bill_no": "QA-DRAWER"}
        first = actions.save_document_draft("Purchase Receipt", pr.name, "Purchase Invoice", changes, request_id)
        retry = actions.save_document_draft("Purchase Receipt", pr.name, "Purchase Invoice", changes, request_id)
        assert first["document"]["name"] == retry["document"]["name"] and retry["reused"]
        draft = first["document"]
        for bad_request, bad_changes in (("bad", changes), (request_id, {"remarks": "changed request"})):
            try:
                actions.save_document_draft("Purchase Receipt", pr.name, "Purchase Invoice", bad_changes, bad_request)
            except frappe.ValidationError:
                pass
            else:
                raise AssertionError("Invalid or changed request identifier accepted")
        assert draft["docstatus"] == 0 and draft["grand_total"] == 1000
        chain = service.get_purchase_chain("Purchase Receipt", pr.name, include_payments=False)
        assert not chain["can_create_invoice"] and chain["draft_invoices"][0]["name"] == draft["name"]
        assert frappe.db.get_value("Purchase Invoice", pi.name, "outstanding_amount") == 2000
        assert not frappe.db.count("GL Entry", {"voucher_type": "Purchase Invoice", "voucher_no": draft["name"]})
        results.append("partial invoice draft resumes; duplicate request has no duplicate GL or invoice")
        for invalid in ({"items": [{"key": item["key"], "qty": qty}]} for qty in (-1, 0, 3)):
            try:
                actions.save_document_draft("Purchase Receipt", pr.name, "Purchase Invoice", invalid, str(uuid.uuid4()),
                    target_name=draft["name"], expected_modified=draft["modified"])
            except frappe.ValidationError:
                pass
            else:
                raise AssertionError("Unsafe drawer mutation accepted")
        try:
            actions.save_document_draft("Purchase Receipt", pr.name, "Purchase Invoice", {"credit_to": "arbitrary"}, str(uuid.uuid4()),
                target_name=draft["name"], expected_modified=draft["modified"])
        except frappe.ValidationError:
            pass
        else:
            raise AssertionError("Unrestricted payload update accepted")
        try:
            actions.save_document_draft("Purchase Receipt", pr.name, "Purchase Invoice", changes, str(uuid.uuid4()),
                target_name=draft["name"], expected_modified="1900-01-01 00:00:00")
        except frappe.ValidationError:
            pass
        else:
            raise AssertionError("Stale version accepted")
        results.append("latest native maximum, strict field whitelist, and version guard")
        receipt_preview = actions.preview_document("Purchase Order", po.name, "Purchase Receipt")
        receipt_item = receipt_preview["document"]["items"][0]
        assert receipt_item["max_qty"] == 6
        receipt_draft = actions.save_document_draft("Purchase Order", po.name, "Purchase Receipt",
            {"items": [{"key": receipt_item["key"], "qty": 2}]}, str(uuid.uuid4()), allow_another_draft=1)["document"]
        assert receipt_draft["docstatus"] == 0 and receipt_draft["grand_total"] == 2000
        assert frappe.db.get_value("Purchase Order", po.name, "per_received") == 40
        assert receipt_draft["allowed_actions"] == ["Submit"]
        received = actions.submit_document("Purchase Receipt", receipt_draft["name"], receipt_draft["modified"], request_id=str(uuid.uuid4()))
        assert received["document"]["docstatus"] == 1
        assert frappe.db.get_value("Purchase Order", po.name, "per_received") == 60
        results.append("explicit native receipt submission consumes remaining quantity once")
        changed = actions.save_document_draft("Purchase Receipt", pr.name, "Purchase Invoice",
            {"items": [{"key": item["key"], "qty": 2}]}, str(uuid.uuid4()),
            target_name=draft["name"], expected_modified=draft["modified"])["document"]
        assert changed["grand_total"] == 2000 and "Submit" in changed["allowed_actions"]
        posted = actions.submit_document("Purchase Invoice", changed["name"], changed["modified"])["document"]
        assert posted["docstatus"] == 1
        assert not service.get_purchase_chain("Purchase Receipt", pr.name, include_payments=False)["can_create_invoice"]
        results.append("explicit native PI submission consumes latest remaining quantity")
        args = dict(source_doctype="Purchase Receipt", source_name=pr.name, purchase_invoice=posted["name"],
            amount_to_pay=1000, bank_account="Cash - QAB", request_id=str(uuid.uuid4()))
        pe_name = service.create_payment_draft(**args)["name"]
        manual_payment = frappe.get_doc("Payment Entry", pe_name)
        manual_reference_date = add_days(nowdate(), -4)
        manual_payment.reference_date = manual_reference_date
        manual_payment.save()
        payment = actions.preview_payment(pe_name)["document"]
        assert payment["amount"] == 1000 and payment["currency"] == "CNY"
        bank_name = payment["bank_account"]
        foreign_company = frappe.db.get_value("Company", {"name": ["!=", COMPANY]}, "name")
        assert foreign_company
        for field, value in (("disabled", 1), ("account_currency", "USD"), ("account_type", "Receivable"), ("company", foreign_company)):
            frappe.db.savepoint("bank_guard")
            try:
                frappe.db.set_value("Account", bank_name, field, value)
                for action in (lambda: actions.preview_payment(pe_name),
                               lambda: actions.submit_document("Payment Entry", pe_name, payment["modified"]),
                               lambda: actions.update_payment_draft(pe_name, {"remarks": "must not save"}, payment["modified"])):
                    try:
                        action()
                    except (frappe.PermissionError, frappe.ValidationError):
                        pass
                    else:
                        raise AssertionError("Changed bank state accepted")
                guarded_record = service.get_payment_records(search=pe_name)["rows"][0]
                assert guarded_record["bank_account"] is None and not guarded_record["can_edit"] and not guarded_record["allowed_actions"]
            finally:
                frappe.db.rollback(save_point="bank_guard")
        original_read = service._read
        def denied_bank(doctype, name, fields=()):
            if doctype == "Account" and name == bank_name:
                frappe.throw("QA-PRIVATE-ACCOUNT " + name, frappe.PermissionError)
            return original_read(doctype, name, fields)
        before_messages = len(frappe.message_log)
        with patch.object(service, "_read", side_effect=denied_bank):
            try:
                actions.preview_payment(pe_name)
            except frappe.PermissionError as exc:
                assert bank_name not in str(exc)
            else:
                raise AssertionError("Revoked Account read accepted")
            hidden_bank = service.get_payment_records(search=pe_name)
            assert bank_name not in json.dumps(hidden_bank, default=str)
        assert all("QA-PRIVATE-ACCOUNT" not in str(message) and bank_name not in str(message) for message in frappe.message_log[before_messages:])
        results.append("bank read/state/type/currency revocation disables preview, submit and record controls without private names")
        for changes in ({"remarks": "QA preserve manual reference date"}, {"amount": 1000},
                        {"bank_account": bank_name}, {"posting_date": add_days(nowdate(), 1)}, {"posting_date": nowdate()}):
            payment = actions.update_payment_draft(pe_name, changes, payment["modified"])["document"]
            assert str(frappe.db.get_value("Payment Entry", pe_name, "reference_date")) == str(manual_reference_date), "Drawer edits must preserve native manual reference date"
        results.append("remarks, amount, account and posting-date edits preserve native manual reference date")
        from unittest.mock import patch
        read_only_payment = frappe.get_doc("Payment Entry", pe_name)
        original_permission = read_only_payment.has_permission
        with patch.object(read_only_payment, "has_permission", side_effect=lambda permission, *a, **kw: False if permission == "write" else original_permission(permission, *a, **kw)):
            assert actions._payment(read_only_payment)["editable_fields"] == [], "Read-only payment must expose no write controls"
        edited = actions.update_payment_draft(pe_name, {"amount": 1500, "remarks": "QA drawer edited"},
            payment["modified"])["document"]
        assert edited["amount"] == 1500 and edited["remarks"] == "QA drawer edited"
        assert frappe.db.get_value("Purchase Invoice", posted["name"], "outstanding_amount") == 2000
        posted_payment = actions.submit_document("Payment Entry", pe_name, edited["modified"])["document"]
        assert posted_payment["docstatus"] == 1
        assert frappe.db.get_value("Purchase Invoice", posted["name"], "outstanding_amount") == 500
        results.append("simple payment edits remain draft until explicit native submit; native balance changes once")
        listing = service.get_receipt_list(filters={"company": COMPANY},
            native_filters=[["name", "=", pr.name], ["owner", "=", "Administrator"]], order_by="`tabPurchase Receipt`.`grand_total` asc", page_length=2500)
        assert [row["name"] for row in listing["rows"]] == [pr.name], "Native filters must constrain authorized rows"
        assert listing["total_count"] == 1 and listing["totals"] == [{"currency": "CNY", "grand_total": 4000.0}]
        for field, operator, operand in (("posting_date", "Timespan", "today"), ("creation", "Timespan", "today"),
                                         ("posting_date", "previous", "1 week"), ("posting_date", "next", "1 week")):
            native_conditions = [["name", "=", pr.name], [field, operator, operand]]
            expected_names = frappe.get_list("Purchase Receipt", filters=native_conditions, pluck="name")
            actual_names = [row["name"] for row in service.get_receipt_list(native_filters=native_conditions)["rows"]]
            assert actual_names == expected_names, "Date operators must keep native Frappe normalization"
        assert "can_create_invoice" in listing["rows"][0] and "draft_invoices" in listing["rows"][0]
        service.get_receipt_list(filters={"company": COMPANY},
            native_filters=[["name", "=", pr.name]], export_format="xlsx", page_length=20,
            columns=["name", "grand_total", "currency"])
        from io import BytesIO

        from openpyxl import load_workbook
        workbook = load_workbook(BytesIO(frappe.response["filecontent"]))
        assert workbook.active.max_row == 2
        assert [cell.value for cell in workbook.active[2]] == [pr.name, 4000, "CNY"]
        assert workbook.active.cell(2, 2).number_format == "#,##0.00", "Money cells require two display decimals"
        service._export("Purchase Receipt", [{"name": pr.name, "grand_total": 4000.123456}],
            ["name", "grand_total"], service.RECEIPT_COLUMNS)
        precise_book = load_workbook(BytesIO(frappe.response["filecontent"]))
        assert precise_book.active.cell(2, 2).value == 4000.123456, "Export styles must not round raw values"
        assert precise_book.active.cell(2, 2).number_format == "#,##0.00"
        service.get_receipt_list(native_filters=[["name", "=", pr.name]], export_format="xlsx",
            columns=["name", "settled", "outstanding"])
        balances_book = load_workbook(BytesIO(frappe.response["filecontent"]))
        settled = json.loads(balances_book.active.cell(2, 2).value)
        outstanding = json.loads(balances_book.active.cell(2, 3).value)
        assert settled[0]["currency"] == "CNY" and settled[0]["settled"] == 1500
        assert outstanding[0]["currency"] == "CNY" and outstanding[0]["outstanding"] == 2500
        actual_permission = frappe.has_permission
        assert "System Manager" in frappe.get_roles(), "QA must exercise the installed System Manager export exception"
        with patch.object(frappe, "has_permission", side_effect=lambda doctype, ptype="read", *a, **kw: False if doctype == "Purchase Receipt" and ptype == "export" else actual_permission(doctype, ptype, *a, **kw)):
            assert not frappe.has_permission("Purchase Receipt", "export")
            assert frappe.permissions.can_export("Purchase Receipt"), "Native export capability must remain real"
            service.get_receipt_list(native_filters=[["name", "=", pr.name]], export_format="xlsx",
                columns=["name", "grand_total", "currency"])
            native_book = load_workbook(BytesIO(frappe.response["filecontent"]))
            assert native_book.active.max_row == 2
            assert [cell.value for cell in native_book.active[2]] == [pr.name, 4000, "CNY"]
        with patch.object(frappe.permissions, "can_export", return_value=False) as native_export:
            assert frappe.has_permission("Purchase Receipt", "read"), "Export denial must preserve real read permission"
            try:
                service.get_receipt_list(filters={"company": COMPANY}, export_format="xlsx")
            except frappe.PermissionError:
                pass
            else:
                raise AssertionError("Read permission must not imply export permission")
            native_export.assert_any_call("Purchase Receipt")
            native_export.assert_any_call("Purchase Receipt", is_owner=True)
        records = service.get_payment_records(company=COMPANY, from_date=nowdate(), to_date=nowdate(),
            status=1, search=pe_name, page_length=2500, order_by="`tabPayment Entry`.`posting_date` asc", native_filters=[["owner", "=", "Administrator"]])
        assert records["total_count"] == 1 and records["rows"][0]["name"] == pe_name
        assert "sync_issues" in records["rows"][0] and "can_edit" in records["rows"][0]
        service.create_payment_draft(**dict(args, amount_to_pay=100, remarks="<span>=1+1</span>", request_id=str(uuid.uuid4())))
        grouped = service.get_payment_records(purchase_receipt=pr.name)
        assert {(row["payment_type"], row["docstatus"], row["currency"], row["amount"]) for row in grouped["totals"]} == {("Pay", 0, "CNY", 100.0), ("Pay", 1, "CNY", 1500.0)}
        service.get_payment_records(purchase_receipt=pr.name, search=pe_name, export_format="xlsx",
            columns=["name", "amount", "allocation_currency"])
        payment_book = load_workbook(BytesIO(frappe.response["filecontent"]))
        assert payment_book.active.max_row == 2
        assert [cell.value for cell in payment_book.active[1]] == ["付款单", "金额", "核销币种", "付款币种"]
        assert [cell.value for cell in payment_book.active[2]] == [pe_name, 1500, "CNY", "CNY"]
        assert payment_book.active.cell(2, 2).number_format == "#,##0.00"
        service.get_payment_records(search=pe_name, export_format="xlsx", columns=["name", "amount"])
        appended_currency = load_workbook(BytesIO(frappe.response["filecontent"]))
        assert [cell.value for cell in appended_currency.active[1]] == ["付款单", "金额", "付款币种", "核销币种"]
        assert [cell.value for cell in appended_currency.active[2]] == [pe_name, 1500, "CNY", "CNY"]
        service.get_payment_records(purchase_receipt=pr.name, export_format="xlsx", start=1, page_length=1,
            columns=["name", "amount", "allocation_currency", "remarks"])
        full_book = load_workbook(BytesIO(frappe.response["filecontent"]))
        assert full_book.active.max_row == 3, "Export must include every filtered row regardless pagination"
        assert all(row[3].data_type != "f" for row in list(full_book.active.rows)[1:]), "Source HTML must not become an Excel formula"
        issue = frappe.get_doc({"doctype": "China Voucher Sync Issue", "company": COMPANY,
            "posting_date": nowdate(), "status": "Pending", "source_doctype": "Payment Entry", "source_name": pe_name,
            "issue_key": "QA-DRAWER-" + str(uuid.uuid4()), "last_error": "QA-PRIVATE-ERROR"}).insert()
        issue_records = service.get_payment_records(search=pe_name)
        assert issue_records["rows"][0]["sync_issues"][0]["name"] == issue.name
        assert "QA-PRIVATE-ERROR" not in json.dumps(issue_records, default=str)
        real_require = service._require_fields
        def deny_issue_fields(doctype, fields, parenttype=None):
            if doctype == "China Voucher Sync Issue":
                raise frappe.PermissionError
            return real_require(doctype, fields, parenttype)
        with patch.object(service, "_require_fields", side_effect=deny_issue_fields):
            hidden_issues = service.get_payment_records(search=pe_name)
        assert hidden_issues["rows"][0]["sync_issues"] == [] and issue.name not in json.dumps(hidden_issues, default=str)
        results.append("whole bank totals separate native payment states; ordered payment export and sync privacy")
        results.append("native receipt filters/count/currency totals/export allow and deny; payment record filters/capabilities")
        pi.reload()
        pi.cancel()
        returned = make_purchase_return(pr.name)
        returned.items[0].qty = -1
        returned.insert()
        returned.submit()
        remaining = actions.preview_document("Purchase Receipt", pr.name, "Purchase Invoice")["document"]["items"][0]
        expected_remaining = 2 if frappe.db.get_single_value("Buying Settings", "bill_for_rejected_quantity_in_purchase_invoice") else 1
        assert remaining["qty"] == remaining["max_qty"] == expected_remaining, remaining
        assert service.get_purchase_chain("Purchase Receipt", pr.name, include_payments=False)["can_create_invoice"]
        results.append("cancelled partial invoices ignored and native returns reduce remaining invoice quantity")
        frappe.set_user("qa-po-reader@example.invalid")
        try:
            actions.preview_document("Purchase Receipt", pr.name, "Purchase Invoice", target_name=posted["name"])
        except frappe.PermissionError:
            pass
        else:
            raise AssertionError("Other company drawer leaked")
        frappe.set_user("Administrator")
        results.append("drawer source/company permissions")
        print(json.dumps({"site": SITE, "tests": results, "status": "passed"}))
    finally:
        frappe.db.rollback()
        after = {doctype: frappe.db.count(doctype) for doctype in doctypes}
        assert before == after, (before, after)
        print(json.dumps({"rollback_counts_unchanged": True, "counts": after}))


class NativeAtomicPurchaseTests(unittest.TestCase):
    """The shared drawer/native-form boundary, restricted to the new isolated clone."""
    def setUp(self):
        if frappe.local.site != SITE or frappe.conf.db_name != "qa_procurement_5" or frappe.conf.db_host != "db":
            raise RuntimeError("Isolated synthetic procurement database only")
        self.assertFalse(frappe.in_test, "Native stock reposts must follow the production branch")
        frappe.set_user("Administrator")
        frappe.flags.in_test = True
        frappe.flags.mute_emails = True
        from deeplinkerp_branding.services.purchase_repost_boundary import initialize
        initialize()  # BEFORE this fixture's first synthetic business insert.
        frappe.db.after_commit.reset()  # BEFORE any fixture acquires a lease.
        self.types = ("Purchase Order", "Purchase Receipt", "Purchase Invoice", "Payment Entry", "GL Entry",
            "Payment Ledger Entry", "Stock Ledger Entry", "Bin", "China Accounting Voucher", "China Voucher Sync Issue", "Integration Request", "Item",
            "ToDo", "Version", "Notification Log", "China Cash Flow Assignment", "User", "Warehouse",
            "Workflow", "Workflow State", "Workflow Action Master", "Custom Field", "Advance Payment Ledger Entry", "Account", "Supplier")
        self.types += ("Sales Order", "Stock Reservation Entry", "Submission Queue", "Repost Item Valuation",
            "Material Request", "Purchase Fulfilment Link", "China Cash Equivalent Scope", "Delivery Note", "Customer", "Price List", "Item Price", "Sales Invoice")
        self.types += ("Stock Entry",)
        self.types += ("Stock Entry Type", "Project")  # exact new native default/opaque fixtures
        self.types += ("Product Bundle",)  # exact new native late-packed-items fixture
        self.types += ("Putaway Rule",)  # exact new late warehouse native fixture
        self.types += ("OA Purchase Request", "Comment")  # exact source recheck/write boundary fixture
        self.before = {doctype: frappe.db.count(doctype) for doctype in self.types}
        self.initial_names = {doctype: set(frappe.get_all(doctype, pluck="name", limit_page_length=0)) for doctype in self.types}
        self.committed_names = None
        self.addCleanup(self.clean)
        self.item = "QA-ATOMIC-" + uuid.uuid4().hex[:10]
        frappe.get_doc({"doctype": "Item", "item_code": self.item, "item_name": self.item, "item_group": "All Item Groups",
            "stock_uom": "Nos", "is_stock_item": 1}).insert()

    def clean(self):
        frappe.db.rollback()
        for doctype in ("Accounts Settings", "Buying Settings", "System Settings", "Stock Reposting Settings"):
            frappe.clear_document_cache(doctype, doctype)
        frappe.clear_document_cache("Company", COMPANY)
        if self.committed_names:
            # Only exact identities created by this isolated synthetic fixture;
            # never run this cleanup on another site/database or production.
            if frappe.local.site != SITE or frappe.conf.db_name != "qa_procurement_5" or frappe.conf.db_host != "db":
                raise RuntimeError("Synthetic cleanup scope changed")
            for doctype, names in self.committed_names.items():
                for field in frappe.get_meta(doctype).get_table_fields():
                    frappe.db.delete(field.options, {"parenttype": doctype, "parent": ["in", sorted(names)]})
                frappe.db.delete(doctype, {"name": ["in", sorted(names)]})
            frappe.db.commit()
        self.assertEqual(self.before, {doctype: frappe.db.count(doctype) for doctype in self.types})

    def commit_fixture(self, primary_doctype="Purchase Order", name_prefix="QA-ATOMIC-PO-"):
        frappe.db.commit()
        self.remember_new_names()
        self.assertTrue(self.committed_names[primary_doctype])
        self.assertTrue(all(name.startswith(name_prefix) for name in self.committed_names[primary_doctype]))

    def remember_new_names(self):
        """Immediate exact deltas, including subjects of a failed subTest."""
        if self.committed_names is None:
            self.committed_names = {doctype: set() for doctype in self.types}
        for doctype in self.types:
            self.committed_names[doctype] |= set(frappe.get_all(doctype, pluck="name", limit_page_length=0)) - self.initial_names[doctype]

    def order(self, currency="CNY", conversion_rate=1, supplier="QA Test Supplier", transaction_date=None, qty=10, rate=12.345, items=None, submit=True):
        po = frappe.get_doc({"doctype": "Purchase Order", "company": COMPANY,
            "transaction_date": transaction_date or nowdate(),
            "supplier": supplier, "currency": currency, "conversion_rate": conversion_rate, "schedule_date": add_days(nowdate(), 1),
            "items": items or [{"item_code": self.item, "qty": qty, "rate": rate,
                "warehouse": "Stores - QAB", "schedule_date": add_days(nowdate(), 1)}]}).insert(
                    set_name="QA-ATOMIC-PO-" + uuid.uuid4().hex[:16])
        if submit:
            po.submit()
        return po

    def test_native_source_same_link_recheck_pending_blocks_evidence_and_comment_then_nested_write_rolls_back(self):
        from deeplinkerp_branding.services import purchase_source_service as sources, purchase_repost_boundary as boundary
        po = self.order(submit=False)
        raw = {"version": "QA-ATOMIC-SOURCE-OLD", "eligible": True, "currency": "CNY", "items": []}
        with sources.managed_write():
            oa = frappe.get_doc({"doctype": "OA Purchase Request", "oa_code": "QA-ATOMIC-OA-" + uuid.uuid4().hex,
                "purchase_order": po.name, "target_company": COMPANY,
                sources.SOURCE_FIELD: json.dumps(raw), sources.BOUND_FIELD: raw["version"]}).insert()
        frappe.db.set_value(po.doctype, po.name, "custom_oa_purchase_expense", oa.name, update_modified=False)
        owner = self.pending_owner()
        frappe.db.set_value(po.doctype, po.name, boundary.POINTER, owner.name, update_modified=False)
        self.commit_fixture()
        comments, before = frappe.db.count("Comment"), frappe.get_doc(oa.doctype, oa.name).as_dict()
        fresh = {**raw, "version": "QA-ATOMIC-SOURCE-NEW"}
        with self.assertRaisesRegex(frappe.ValidationError, "相关采购来源待完成"):
            sources._bind(oa, po.reload(), fresh, {}, "QA-ATOMIC-source recheck")
        self.assertEqual(frappe.get_doc(oa.doctype, oa.name).as_dict(), before)
        self.assertEqual(frappe.db.count("Comment"), comments)
        with boundary.execution(), boundary.acquire((boundary.fence_key(),)):
            with boundary.acquire((boundary.lock_key("document", po.doctype, po.name),)):
                frappe.db.set_value(po.doctype, po.name, boundary.POINTER, None, update_modified=False)
        self.commit_fixture()
        modified = frappe.db.get_value(po.doctype, po.name, "modified")
        sources._bind(oa, po.reload(), fresh, {}, "QA-ATOMIC-source recheck")
        self.assertEqual(frappe.db.get_value(po.doctype, po.name, "modified"), modified)
        self.assertEqual(frappe.db.get_value(oa.doctype, oa.name, sources.BOUND_FIELD), fresh["version"])
        self.assertEqual(frappe.db.count("Comment"), comments + 1)
        self.commit_fixture()
        # Changed-link still uses native PO save and its existing audit flow.
        # A later OA failure rolls both nested writes back as one execution.
        frappe.db.set_value(po.doctype, po.name, "custom_oa_purchase_expense", None, update_modified=False)
        self.commit_fixture()
        sql_set = frappe.db.set_value
        def fail_source(doctype, *args, **kwargs):
            if doctype == oa.doctype:
                raise RuntimeError("QA-ATOMIC source evidence failure")
            return sql_set(doctype, *args, **kwargs)
        audits = frappe.db.count("Integration Request")
        with patch.object(frappe.db, "set_value", side_effect=fail_source), self.assertRaisesRegex(RuntimeError, "source evidence failure"):
            sources._bind(oa, po.reload(), {**fresh, "version": "QA-ATOMIC-SOURCE-NEXT"}, {})
        self.assertFalse(frappe.db.get_value(po.doctype, po.name, "custom_oa_purchase_expense"))
        self.assertEqual(frappe.db.count("Integration Request"), audits)
        self.assertEqual(frappe.db.get_value(oa.doctype, oa.name, sources.BOUND_FIELD), fresh["version"])
        sources._bind(oa, po.reload(), fresh, {})
        self.assertEqual(frappe.db.get_value(po.doctype, po.name, "custom_oa_purchase_expense"), oa.name)

    def boundary_database(self):
        """Actual second mysqlclient business adapter, never a lock-only service."""
        from frappe.database import get_db
        database = get_db(socket=frappe.conf.db_socket, host=frappe.conf.db_host, port=frappe.conf.db_port,
            user=frappe.conf.db_user, password=frappe.conf.db_password, cur_db_name=frappe.conf.db_name)
        database.connect()
        self.addCleanup(lambda: database.close())
        return database

    def test_native_session_lease_sql_epochs_callbacks_and_two_connection_authority(self):
        from deeplinkerp_branding.services import purchase_repost_boundary as boundary
        left, right = self.boundary_database(), self.boundary_database()
        first = boundary.initialize(left)
        second = boundary.initialize(right)
        self.assertNotEqual(first.connection_id, second.connection_id)
        self.assertEqual(type(first.connection).__module__, "MySQLdb.connections")
        key, later = boundary.lock_key("qa-lease", self.item), boundary.lock_key("qa-later", self.item)
        def assert_owner(owner):
            self.assertEqual(right.sql("SELECT IS_USED_LOCK(%s)", (key,))[0][0], owner)
        with boundary.execution(db=left), boundary.acquire((key,), db=left):
            left.commit(); assert_owner(first.connection_id)
            left.rollback(); assert_owner(first.connection_id)
            left.savepoint("scope_test"); left.rollback(save_point="scope_test"); assert_owner(first.connection_id)
            with self.assertRaises(frappe.ValidationError):
                with boundary.execution(db=right), boundary.acquire((key,), db=right): pass
        assert_owner(first.connection_id)
        left.before_commit.add(lambda: (_ for _ in ()).throw(RuntimeError("native early callback")))
        with self.assertRaisesRegex(RuntimeError, "native early callback"): left.commit()
        assert_owner(None)
        left.before_commit.reset()
        with boundary.execution(db=left), boundary.acquire((key,), db=left): pass
        left.before_rollback.add(lambda: (_ for _ in ()).throw(RuntimeError("native rollback callback")))
        with self.assertRaisesRegex(RuntimeError, "native rollback callback"): left.rollback()
        assert_owner(None)
        left.before_rollback.reset()
        with boundary.execution(db=left), boundary.acquire((key,), db=left): pass
        def next_epoch():
            with boundary.execution(db=left), boundary.acquire((later,), db=left): pass
            raise RuntimeError("after physical commit")
        left.after_commit.add(next_epoch)
        with self.assertRaisesRegex(RuntimeError, "after physical commit"): left.commit()
        assert_owner(None)
        self.assertEqual(right.sql("SELECT IS_USED_LOCK(%s)", (later,))[0][0], first.connection_id)
        left.commit()
        self.assertIsNone(right.sql("SELECT IS_USED_LOCK(%s)", (later,))[0][0])
        with boundary.execution(db=left), boundary.acquire((key,), db=left): pass
        left.close()
        assert_owner(None)
        with self.assertRaises(frappe.ValidationError): boundary.initialize(left)

    def test_native_killed_session_cannot_reconnect_or_reacquire(self):
        from deeplinkerp_branding.services import purchase_repost_boundary as boundary
        left, right = self.boundary_database(), self.boundary_database()
        state = boundary.initialize(left)
        key = boundary.lock_key("qa-kill", self.item)
        with boundary.execution(db=left), boundary.acquire((key,), db=left):
            right.sql("KILL CONNECTION %s", (state.connection_id,))
            with self.assertRaises(Exception): left.sql("SELECT CONNECTION_ID()")
            self.assertTrue(state.poisoned)
            with self.assertRaises(frappe.ValidationError): boundary.initialize(left)
        self.assertIsNone(right.sql("SELECT IS_USED_LOCK(%s)", (key,))[0][0])

    def test_native_killed_before_first_handshake_poisons_execution_without_reconnect(self):
        from deeplinkerp_branding.services import purchase_repost_boundary as boundary
        left, right = self.boundary_database(), self.boundary_database()
        physical = left._conn
        right.sql("KILL CONNECTION %s", (physical.thread_id(),))
        with self.assertRaises(Exception): boundary.initialize(left)
        self.assertTrue(left._purchase_session.poisoned)
        self.assertFalse(physical.open)
        with self.assertRaises(frappe.ValidationError): boundary.initialize(left)
        self.assertIs(left._conn, physical)

    def test_nested_native_before_commit_rollback_then_new_writes_fail_physically_cleaned(self):
        from deeplinkerp_branding.services import purchase_repost_boundary as boundary
        self.commit_fixture(primary_doctype="Item", name_prefix="QA-ATOMIC-")
        left, right = self.boundary_database(), self.boundary_database()
        state = boundary.initialize(left)
        key = boundary.lock_key("qa-nested-callback", self.item)
        committed_markers = []
        with boundary.execution(db=left), boundary.acquire((key,), db=left): pass
        def callback():
            left.rollback()
            with boundary.execution(db=left), boundary.acquire((key,), db=left):
                left.sql("UPDATE tabItem SET item_name=%s WHERE name=%s", ("QA-ATOMIC-PENDING", self.item))
                left.after_commit.add(lambda: committed_markers.append("rolled-back business"))
            raise RuntimeError("original nested callback failure")
        left.before_commit.add(callback)
        with self.assertRaisesRegex(RuntimeError, "original nested callback failure"):
            left.commit()
        self.assertFalse(state.poisoned)
        self.assertIsNone(right.sql("SELECT IS_USED_LOCK(%s)", (key,))[0][0])
        self.assertEqual(right.sql("SELECT item_name FROM tabItem WHERE name=%s", (self.item,))[0][0], self.item)
        left.commit()  # genuine later native status/error-path commit
        self.assertEqual(committed_markers, [])

    def test_native_before_rollback_nested_commit_and_after_commit_new_epoch_data(self):
        from deeplinkerp_branding.services import purchase_repost_boundary as boundary
        self.commit_fixture(primary_doctype="Item", name_prefix="QA-ATOMIC-")
        left, right = self.boundary_database(), self.boundary_database()
        state = boundary.initialize(left)
        key, later = boundary.lock_key("qa-before-rollback", self.item), boundary.lock_key("qa-after-commit", self.item)
        markers = []
        def before():
            left.commit()  # actually commits prior chunk, cannot undo it
            left.sql("UPDATE tabItem SET item_name=%s WHERE name=%s", ("QA-ATOMIC-ROLLBACK-PENDING", self.item))
            left.after_commit.add(lambda: markers.append("rolled-back callback"))
            raise RuntimeError("original before rollback nested failure")
        with boundary.execution(db=left), boundary.acquire((key,), db=left):
            left.sql("UPDATE tabItem SET item_name=%s WHERE name=%s", ("QA-ATOMIC-COMMITTED-CHUNK", self.item))
            left.before_rollback.add(before)
            with self.assertRaisesRegex(RuntimeError, "original before rollback nested failure"):
                left.rollback()
            self.assertEqual(right.sql("SELECT IS_USED_LOCK(%s)", (key,))[0][0], state.connection_id)
            self.assertEqual(right.sql("SELECT item_name FROM tabItem WHERE name=%s", (self.item,))[0][0], "QA-ATOMIC-COMMITTED-CHUNK")
            left.commit()  # native status/error commit, still active lease
            self.assertEqual(markers, [])
        left.commit()
        self.assertIsNone(right.sql("SELECT IS_USED_LOCK(%s)", (key,))[0][0])
        def after():
            with boundary.execution(db=left), boundary.acquire((later,), db=left):
                left.sql("UPDATE tabItem SET item_name=%s WHERE name=%s", ("QA-ATOMIC-NEXT-EPOCH", self.item))
            raise RuntimeError("after own real commit")
        left.after_commit.add(after)
        with self.assertRaisesRegex(RuntimeError, "after own real commit"): left.commit()
        self.assertEqual(right.sql("SELECT IS_USED_LOCK(%s)", (later,))[0][0], state.connection_id)
        right.rollback()
        self.assertEqual(right.sql("SELECT item_name FROM tabItem WHERE name=%s", (self.item,))[0][0], "QA-ATOMIC-COMMITTED-CHUNK")
        left.commit()  # only NEXT actual commit publishes/releases new epoch
        right.rollback()
        self.assertEqual(right.sql("SELECT item_name FROM tabItem WHERE name=%s", (self.item,))[0][0], "QA-ATOMIC-NEXT-EPOCH")
        self.assertIsNone(right.sql("SELECT IS_USED_LOCK(%s)", (later,))[0][0])

        for cleanup_failure in (False, True):
            with self.subTest(nested_rollback_cleanup_failure=cleanup_failure):
                left, right = self.boundary_database(), self.boundary_database()
                state = boundary.initialize(left)
                key = boundary.lock_key("qa-before-rollback-nested", self.item, cleanup_failure)
                previous = right.sql("SELECT item_name FROM tabItem WHERE name=%s", (self.item,))[0][0]
                markers = []
                def nested_rollback():
                    left.rollback()  # nested SQL is not the enclosing rollback's SQL
                    left.sql("UPDATE tabItem SET item_name=%s WHERE name=%s", ("QA-ATOMIC-NESTED-PENDING", self.item))
                    left.after_commit.add(lambda: markers.append("rolled-back business"))
                    if cleanup_failure:
                        left.after_rollback.add(lambda: (_ for _ in ()).throw(RuntimeError("unsafe cleanup")))
                    raise RuntimeError("original nested rollback failure")
                with boundary.execution(db=left), boundary.acquire((key,), db=left):
                    left.before_rollback.add(nested_rollback)
                    with self.assertRaisesRegex(RuntimeError, "original nested rollback failure"):
                        left.rollback()
                    right.rollback()
                    self.assertEqual(right.sql("SELECT item_name FROM tabItem WHERE name=%s", (self.item,))[0][0], previous)
                    if cleanup_failure:
                        self.assertTrue(state.poisoned)
                        self.assertFalse(state.connection.open)
                        self.assertIsNone(right.sql("SELECT IS_USED_LOCK(%s)", (key,))[0][0])
                        with self.assertRaises(frappe.ValidationError): left.commit()
                    else:
                        self.assertFalse(state.poisoned)
                        self.assertEqual(right.sql("SELECT IS_USED_LOCK(%s)", (key,))[0][0], state.connection_id)
                        left.commit()  # allowed native follow-up cannot carry stale callbacks
                    self.assertEqual(markers, [])
                if not cleanup_failure:
                    left.commit()
                    self.assertIsNone(right.sql("SELECT IS_USED_LOCK(%s)", (key,))[0][0])

    def test_real_fresh_public_payment_and_source_entries_handshake_before_first_lock(self):
        from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry
        po = self.order()
        pr = self.receipt(po)
        pi = make_purchase_invoice(pr.name).insert()
        pi.submit()
        pe = get_payment_entry(pi.doctype, pi.name, bank_account="Cash - QAB", bank_amount=10).insert()
        self.commit_fixture()
        for action in ("entry-payment-update", "entry-payment-submit", "entry-source-create"):
            with self.subTest(action=action):
                pe.reload()
                result = self.native_peer({"action": action, "item": self.item, "name": pe.name,
                    "modified": str(pe.modified)})
                self.assertLess(result["identity_query"], result["first_lock"])
                self.assertTrue(result["same_physical"])
                self.assertTrue(result["execution_id"])
                frappe.db.rollback()  # only this fixture's read epoch, no pending business writes

    def pending_owner(self):
        return frappe.get_doc({"doctype": "Integration Request", "integration_request_service": "QA Boundary Pointer",
            "status": "Queued", "data": "{}"}).insert(ignore_permissions=True)

    def native_peer(self, payload):
        process = subprocess.run([sys.executable, __file__, "--boundary-peer", json.dumps(payload)],
            capture_output=True, text=True, timeout=30)
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
        result = json.loads(process.stdout.strip().splitlines()[-1])
        # A may still own an old RR snapshot. Register the peer's exact typed
        # committed delta immediately, even if the next assertion fails.
        for doctype, names in result["created"].items():
            self.committed_names.setdefault(doctype, set()).update(names)
        return result

    def test_pending_bin_blocks_real_native_stock_draft_but_unrelated_first_stock_works(self):
        from deeplinkerp_branding.services import purchase_repost_boundary as boundary
        po = self.order()
        owner = self.pending_owner()
        frappe.db.set_value("Bin", {"item_code": self.item, "warehouse": "Stores - QAB"}, boundary.POINTER, owner.name)
        self.commit_fixture()
        blocked = frappe.get_doc({"doctype": "Stock Entry", "purpose": "Material Receipt", "stock_entry_type": "Material Receipt", "company": COMPANY,
            "items": [{"item_code": self.item, "qty": 1, "t_warehouse": "Stores - QAB"}]})
        blocked.flags.purchase_reversal_internal = True
        with self.assertRaises(frappe.ValidationError): blocked.insert(ignore_permissions=True)
        extra = self.scope_item()
        self.assertFalse(frappe.db.exists("Bin", {"item_code": extra, "warehouse": "Stores - QAB"}))
        ordinary = frappe.get_doc({"doctype": "Stock Entry", "purpose": "Material Receipt", "stock_entry_type": "Material Receipt", "company": COMPANY,
            "items": [{"item_code": extra, "qty": 1, "t_warehouse": "Stores - QAB"}]}).insert()
        self.assertEqual(ordinary.docstatus, 0)
        self.assertEqual(ordinary.items[0].stock_uom, "Nos")
        self.assertFalse(frappe.db.exists("Bin", {"item_code": extra, "warehouse": "Stores - QAB"}))

    def test_pointer_rewrite_is_rejected_before_native_ignore_permission_save(self):
        from deeplinkerp_branding.services import purchase_repost_boundary as boundary
        po, owner = self.order(), self.pending_owner()
        self.commit_fixture()
        po.reload()
        po.set(boundary.POINTER, owner.name)
        po.flags.purchase_reversal_internal = True
        with self.assertRaises(frappe.PermissionError): po.save(ignore_permissions=True)
        self.assertFalse(frappe.db.get_value(po.doctype, po.name, boundary.POINTER))

    def test_pending_bin_unchanged_pointer_blocks_native_qty_api_and_same_pair_insert(self):
        from deeplinkerp_branding.services import purchase_repost_boundary as boundary
        from frappe.client import set_value
        self.order()
        owner = self.pending_owner()
        name = frappe.db.get_value("Bin", {"item_code": self.item, "warehouse": "Stores - QAB"}, "name")
        frappe.db.set_value("Bin", name, boundary.POINTER, owner.name, update_modified=False)
        self.commit_fixture()
        for action in ("native", "rpc", "insert"):
            with self.subTest(action=action):
                original = frappe.get_doc("Bin", name)
                before = original.actual_qty
                with self.assertRaisesRegex(frappe.ValidationError, "相关库存范围待完成"):
                    if action == "native":
                        original.actual_qty = before + 7
                        original.flags.purchase_reversal_internal = True
                        original.save(ignore_permissions=True)
                    elif action == "rpc":
                        set_value("Bin", name, "actual_qty", before + 7)
                    else:
                        frappe.get_doc({"doctype": "Bin", "item_code": self.item, "warehouse": "Stores - QAB",
                            "actual_qty": 7}).insert(ignore_permissions=True)
                self.assertEqual(frappe.db.get_value("Bin", name, "actual_qty"), before)
                self.assertEqual(frappe.db.count("Bin", {"item_code": self.item, "warehouse": "Stores - QAB"}), 1)

    def test_material_request_real_purchase_backlink_pointer_blocks_native_save(self):
        from deeplinkerp_branding.services import purchase_repost_boundary as boundary
        mr, po = self.material_request_order()
        po.submit()
        owner = self.pending_owner()
        frappe.db.set_value(po.doctype, po.name, boundary.POINTER, owner.name, update_modified=False)
        self.commit_fixture()
        mr.reload()
        with self.assertRaises(frappe.ValidationError): mr.save(ignore_permissions=True)

    def test_native_material_request_status_rpc_pending_bin_and_backlinks_then_native_resume(self):
        from deeplinkerp_branding.services import purchase_repost_boundary as boundary
        from erpnext.stock.doctype.material_request.material_request import update_status
        mr, po = self.material_request_order()
        owner = self.pending_owner()
        bin_name = frappe.db.get_value("Bin", {"item_code": self.item, "warehouse": "Stores - QAB"}, "name")
        self.commit_fixture()
        for doctype, name in (("Bin", bin_name), (po.doctype, po.name)):
            frappe.db.set_value(doctype, name, boundary.POINTER, owner.name, update_modified=False)
            self.commit_fixture()
            before = (frappe.db.get_value(mr.doctype, mr.name, "status"),
                frappe.db.get_value("Bin", bin_name, "indented_qty"),
                frappe.db.get_value("Purchase Order Item", po.items[0].name, "material_request_item"))
            with self.assertRaisesRegex(frappe.ValidationError, "相关.*待完成"):
                update_status(mr.name, "Stopped")
            self.assertEqual(before, (frappe.db.get_value(mr.doctype, mr.name, "status"),
                frappe.db.get_value("Bin", bin_name, "indented_qty"),
                frappe.db.get_value("Purchase Order Item", po.items[0].name, "material_request_item")))
            frappe.db.set_value(doctype, name, boundary.POINTER, None, update_modified=False)
            self.commit_fixture()
        update_status(mr.name, "Stopped")
        self.assertEqual(frappe.db.get_value("Bin", bin_name, "indented_qty"), 0)
        self.commit_fixture()
        update_status(mr.name, "Pending")
        self.assertEqual(frappe.db.get_value("Bin", bin_name, "indented_qty"), 10)
        self.commit_fixture()
        po.reload().submit()
        pr = make_purchase_receipt(po.name).insert()
        frappe.db.set_value(pr.doctype, pr.name, boundary.POINTER, owner.name, update_modified=False)
        self.commit_fixture()
        before = (frappe.db.get_value(mr.doctype, mr.name, "status"), frappe.db.get_value("Bin", bin_name, "indented_qty"))
        with self.assertRaisesRegex(frappe.ValidationError, "相关.*待完成"):
            update_status(mr.name, "Stopped")
        self.assertEqual((frappe.db.get_value(mr.doctype, mr.name, "status"),
            frappe.db.get_value("Bin", bin_name, "indented_qty")), before)

    def test_native_purchase_status_rpc_and_bulk_preflight_all_before_any_write(self):
        from deeplinkerp_branding.services import purchase_repost_boundary as boundary
        first, second = self.order(), self.order()
        receipt = self.receipt(first)
        owner = self.pending_owner()
        self.commit_fixture()
        cases = [("Purchase Order", second.name,
            "erpnext.buying.doctype.purchase_order.purchase_order.update_status", {"name": second.name, "status": "Closed"}),
            ("Purchase Receipt", receipt.name,
            "erpnext.stock.doctype.purchase_receipt.purchase_receipt.update_purchase_receipt_status",
            {"docname": receipt.name, "status": "Closed"})]
        for doctype, name, path, kwargs in cases:
            frappe.db.set_value(doctype, name, boundary.POINTER, owner.name, update_modified=False)
            self.commit_fixture()
            before = frappe.db.get_value(doctype, name, "status")
            with self.assertRaisesRegex(frappe.ValidationError, "相关.*待完成"):
                frappe.get_attr(frappe.override_whitelisted_method(path))(**kwargs)
            self.assertEqual(frappe.db.get_value(doctype, name, "status"), before)
            frappe.db.set_value(doctype, name, boundary.POINTER, None, update_modified=False)
            self.commit_fixture()
        frappe.db.set_value(second.doctype, second.name, boundary.POINTER, owner.name, update_modified=False)
        self.commit_fixture()
        path = "erpnext.buying.doctype.purchase_order.purchase_order.close_or_unclose_purchase_orders"
        before = [frappe.db.get_value("Purchase Order", doc.name, "status") for doc in (first, second)]
        with self.assertRaisesRegex(frappe.ValidationError, "相关.*待完成"):
            frappe.get_attr(frappe.override_whitelisted_method(path))(json.dumps([first.name, second.name]), "Closed")
        self.assertEqual([frappe.db.get_value("Purchase Order", doc.name, "status") for doc in (first, second)], before)
        frappe.db.set_value(second.doctype, second.name, boundary.POINTER, None, update_modified=False)
        self.commit_fixture()
        audits = set(frappe.get_all("Integration Request", pluck="name"))
        frappe.get_attr(frappe.override_whitelisted_method(path))(json.dumps([first.name, second.name]), "Closed")
        self.assertEqual([frappe.db.get_value("Purchase Order", doc.name, "status") for doc in (first, second)], ["Closed", "Closed"])
        new_audits = set(frappe.get_all("Integration Request", pluck="name")) - audits
        self.assertEqual(len(new_audits), 1)  # one existing operation/postcheck graph, not per-doc queues
        facts = json.loads(frappe.get_doc("Integration Request", next(iter(new_audits))).data)
        for doc in (first, second):
            self.assertEqual(facts["after"][doc.doctype + ":" + doc.name]["status"], "Closed")

    def test_native_order_update_child_qty_rate_guards_before_delete_or_child_writes_and_validates_parent(self):
        from deeplinkerp_branding.services import purchase_repost_boundary as boundary
        from erpnext.controllers import accounts_controller as native
        po = self.order(items=[{"item_code": self.item, "qty": qty, "rate": 12.345,
            "warehouse": "Stores - QAB", "schedule_date": add_days(nowdate(), 1)} for qty in (10, 2)])
        other = self.order()
        owner = self.pending_owner()
        frappe.db.set_value(po.doctype, po.name, boundary.POINTER, owner.name, update_modified=False)
        self.commit_fixture()
        path = "erpnext.controllers.accounts_controller.update_child_qty_rate"
        def data(rows, qty=8):
            return json.dumps([{"docname": row.name, "item_code": row.item_code, "qty": qty,
                "rate": row.rate, "uom": row.uom, "conversion_factor": row.conversion_factor,
                "schedule_date": str(row.schedule_date), "description": row.description} for row in rows])
        for rows in (po.items, po.items[:1]):
            with patch.object(native, "validate_and_delete_children", wraps=native.validate_and_delete_children) as deletion:
                with self.assertRaisesRegex(frappe.ValidationError, "相关.*待完成"):
                    frappe.get_attr(frappe.override_whitelisted_method(path))(po.doctype, data(rows), po.name)
                deletion.assert_not_called()  # actual native early delete helper must not run
            self.assertEqual([row.qty for row in frappe.get_doc(po.doctype, po.name).items], [10, 2])
        frappe.db.set_value(po.doctype, po.name, boundary.POINTER, None, update_modified=False)
        self.commit_fixture()
        with patch.object(native, "validate_and_delete_children", wraps=native.validate_and_delete_children) as deletion:
            with self.assertRaisesRegex(frappe.ValidationError, "明细.*所属"):
                frappe.get_attr(frappe.override_whitelisted_method(path))(po.doctype, data(other.items), po.name)
            deletion.assert_not_called()
        self.assertEqual(frappe.db.get_value("Purchase Order Item", other.items[0].name, "qty"), 10)
        frappe.get_attr(frappe.override_whitelisted_method(path))(po.doctype, data(po.items, 8), po.name)
        self.assertEqual([row.qty for row in frappe.get_doc(po.doctype, po.name).items], [8, 8])
        self.commit_fixture()
        po.reload()
        frappe.get_attr(frappe.override_whitelisted_method(path))(po.doctype, data(po.items[:1], 7), po.name)
        self.assertEqual([row.qty for row in frappe.get_doc(po.doctype, po.name).items], [7])

    def test_native_order_update_child_qty_rate_cross_parent_refused_before_native_helper(self):
        from erpnext.controllers import accounts_controller as native
        po, other = self.order(), self.order()
        self.commit_fixture()
        row = other.items[0]
        data = json.dumps([{"docname": row.name, "item_code": row.item_code, "qty": 8, "rate": row.rate,
            "uom": row.uom, "conversion_factor": row.conversion_factor, "schedule_date": str(row.schedule_date),
            "description": row.description}])
        with patch.object(native, "validate_and_delete_children", wraps=native.validate_and_delete_children) as deletion:
            with self.assertRaisesRegex(frappe.ValidationError, "明细.*所属"):
                frappe.get_attr(frappe.override_whitelisted_method("erpnext.controllers.accounts_controller.update_child_qty_rate"))(
                    po.doctype, data, po.name)
            deletion.assert_not_called()

    def test_native_purchase_invoice_hold_db_set_pending_refuses_entire_block_and_clear_works(self):
        from deeplinkerp_branding.services import purchase_repost_boundary as boundary
        from erpnext.accounts.doctype.purchase_invoice.purchase_invoice import block_invoice, unblock_invoice, change_release_date
        po = self.order()
        pi = make_purchase_invoice(self.receipt(po).name).insert()
        owner = self.pending_owner()
        frappe.db.set_value(pi.doctype, pi.name, boundary.POINTER, owner.name, update_modified=False)
        self.commit_fixture()
        before = frappe.db.get_value(pi.doctype, pi.name, ["on_hold", "hold_comment", "release_date"])
        for call in (lambda: block_invoice(pi.name, add_days(nowdate(), 2), "QA hold"),
                lambda: unblock_invoice(pi.name), lambda: change_release_date(pi.name, add_days(nowdate(), 3))):
            with self.assertRaisesRegex(frappe.ValidationError, "相关.*待完成"):
                call()
            self.assertEqual(frappe.db.get_value(pi.doctype, pi.name, ["on_hold", "hold_comment", "release_date"]), before)
        frappe.db.set_value(pi.doctype, pi.name, boundary.POINTER, None, update_modified=False)
        self.commit_fixture()
        block_invoice(pi.name, add_days(nowdate(), 2), "QA hold")
        self.assertEqual(frappe.db.get_value(pi.doctype, pi.name, ["on_hold", "hold_comment"]), (1, "QA hold"))
        self.commit_fixture()
        change_release_date(pi.name, add_days(nowdate(), 3))
        self.assertEqual(str(frappe.db.get_value(pi.doctype, pi.name, "release_date")), add_days(nowdate(), 3))
        unblock_invoice(pi.name)
        self.assertEqual(frappe.db.get_value(pi.doctype, pi.name, ["on_hold", "release_date"]), (0, None))

    def test_native_purchase_invoice_partial_hold_failure_rolls_back_prior_real_fields(self):
        from erpnext.accounts.doctype.purchase_invoice.purchase_invoice import block_invoice, unblock_invoice, change_release_date
        po = self.order()
        pi = make_purchase_invoice(self.receipt(po).name).insert()
        self.commit_fixture()
        fields = ["on_hold", "hold_comment", "release_date", "modified", "modified_by"]
        for action, failed_field, after_write in (("block", "hold_comment", False),
                ("block", "release_date", False), ("unblock", "release_date", False),
                ("change-release", "release_date", True)):
            with self.subTest(action=action, failed_field=failed_field):
                if action == "block":
                    unblock_invoice(pi.name)
                else:
                    block_invoice(pi.name, add_days(nowdate(), 2), "QA original hold")
                self.commit_fixture()  # distinct real request baseline, never inside tested failure
                before = frappe.db.get_value(pi.doctype, pi.name, fields)
                counts = {doctype: frappe.db.count(doctype) for doctype in self.types}
                self.remember_effects()  # shared native stock/financial/source/audit evidence
                written, partial = [], []
                native_set = frappe.db.set_value
                first_error = RuntimeError("QA-ATOMIC first hold failure " + action + " " + failed_field)
                def fail_field(doctype, name, fieldname, *args, **kwargs):
                    target = doctype == pi.doctype and name == pi.name and fieldname in fields[:3]
                    if target and fieldname == failed_field and not after_write:
                        partial.append(frappe.db.get_value(pi.doctype, pi.name, fields))
                        raise first_error
                    result = native_set(doctype, name, fieldname, *args, **kwargs)
                    if target:
                        written.append(fieldname)
                        if fieldname == failed_field:
                            partial.append(frappe.db.get_value(pi.doctype, pi.name, fields))
                            raise first_error
                    return result
                with patch.object(frappe.db, "set_value", side_effect=fail_field), self.assertRaises(RuntimeError) as caught:
                    if action == "block":
                        block_invoice(pi.name, add_days(nowdate(), 4), "QA changed hold")
                    elif action == "unblock":
                        unblock_invoice(pi.name)
                    else:
                        change_release_date(pi.name, add_days(nowdate(), 4))
                self.assertIs(caught.exception, first_error)
                expected = ["on_hold", "hold_comment"] if action == "block" and failed_field == "release_date" else (
                    ["release_date"] if action == "change-release" else ["on_hold"])
                self.assertEqual(written, expected)  # preceding native SQL really ran
                self.assertEqual(len(partial), 1)
                self.assertNotEqual(partial[0][:3], before[:3])
                # No test-side rollback: the actual boundary has restored the
                # whole request, including prior db_set writes and timestamps.
                self.assertEqual(frappe.db.get_value(pi.doctype, pi.name, fields), before)
                self.assertEqual({doctype: frappe.db.count(doctype) for doctype in self.types}, counts)
                self.assert_effects_unchanged()

    def test_material_request_backlink_requires_actual_detail_and_shared_union_budget(self):
        from deeplinkerp_branding.services import purchase_reversal_scope as scope
        mr, po = self.material_request_order()
        detail = po.items[0].material_request_item
        self.commit_fixture()
        audit_before = frappe.db.count("Integration Request")
        frappe.db.set_value("Purchase Order Item", po.items[0].name, "material_request_item",
            "QA-ATOMIC-DETAIL-MISSING-" + uuid.uuid4().hex, update_modified=False)
        self.commit_fixture()
        with self.assertRaises(frappe.ValidationError) as caught:
            mr.reload().save(ignore_permissions=True)
        self.assertEqual(caught.exception.purchase_error_id, "native_source_identity_mismatch")
        self.assertEqual(frappe.db.count("Integration Request"), audit_before)
        # A parent-only historical string is not a native detail updater edge.
        # Do not repair history, and do not permanently disable an ordinary MR.
        frappe.db.set_value("Purchase Order Item", po.items[0].name, "material_request_item", None, update_modified=False)
        self.commit_fixture()
        mr.reload().save(ignore_permissions=True)
        self.assertEqual(frappe.db.get_value("Bin", {"item_code": self.item, "warehouse": "Stores - QAB"}, "indented_qty"), 10)
        frappe.db.set_value("Purchase Order Item", po.items[0].name, "material_request_item", detail, update_modified=False)
        self.commit_fixture()
        with patch.object(scope, "MAX_VOUCHERS", 2):
            mr.reload().save(ignore_permissions=True)  # duplicate old/new MR counts once
        with patch.object(scope, "MAX_VOUCHERS", 1), self.assertRaises(frappe.ValidationError):
            mr.reload().save(ignore_permissions=True)  # real PO backlink is identity two

    def test_current_scope_sees_peer_native_transfer_and_rejects_expansion_before_write(self):
        from deeplinkerp_branding.services import purchase_repost_boundary as boundary
        po, prior, future = self.future_receipts()
        frappe.db.rollback()  # release only commit_fixture's evidence read locks, BEFORE tested scope
        original, peer = boundary._scopes, {}
        def interleave(roots, *, current, opaque):
            result = original(roots, current=current, opaque=opaque)
            if not current and not peer:
                peer.update(self.native_peer({"action": "transfer", "item": self.item}))
            return result
        audit_before = frappe.db.count("Integration Request")
        with patch.object(boundary, "_scopes", side_effect=interleave):
            with self.assertRaises((frappe.QueryDeadlockError, frappe.ValidationError)) as caught:
                prior.save(ignore_permissions=True)
        if isinstance(caught.exception, frappe.QueryDeadlockError):
            self.assertEqual(caught.exception.args[0].args[0], 1020)
        else:
            self.assertIn("范围已扩大", str(caught.exception))
        # Exact peer-created synthetic identities, collected before any failure
        # rolls A back; no historical record or broad cleanup target is added.
        frappe.db.rollback()
        self.remember_new_names()
        fresh = boundary._scopes([prior], current=True, opaque=False)
        self.assertIn(peer["name"], {row.name for scope in fresh for row in scope.vouchers})
        self.assertEqual(frappe.db.count("Integration Request"), audit_before)

    def test_current_scope_peer_native_source_replacement_refuses_old_snapshot_then_fresh_reads_new_identity(self):
        from deeplinkerp_branding.services import purchase_repost_boundary as boundary
        first = self.order()
        second = self.order(items=[{"item_code": self.item, "qty": 10, "rate": 12.345,
            "warehouse": "Work In Progress - QAB", "schedule_date": add_days(nowdate(), 1)}])
        receipt = make_purchase_receipt(first.name).insert()
        self.commit_fixture()
        frappe.db.rollback()  # fixture-only evidence epoch, before A's tested initial scope
        original, peer = boundary._scopes, {}
        def interleave(roots, *, current, opaque):
            result = original(roots, current=current, opaque=opaque)
            if not current and not peer:
                peer.update(self.native_peer({"action": "source", "item": self.item, "name": receipt.name,
                    "source": second.name, "detail": second.items[0].name}))
            return result
        with patch.object(boundary, "_scopes", side_effect=interleave):
            with self.assertRaises((frappe.QueryDeadlockError, frappe.ValidationError)):
                receipt.save(ignore_permissions=True)
        frappe.db.rollback()
        current = frappe.get_doc(receipt.doctype, receipt.name)
        scopes = boundary._scopes([current], current=True, opaque=False)
        sources = {(row.doctype, row.name) for scope in scopes for row in scope.sources}
        self.assertIn((second.doctype, second.name), sources)
        self.assertNotIn((first.doctype, first.name), sources)
        self.assertEqual((current.items[0].purchase_order, current.items[0].purchase_order_item,
            current.items[0].warehouse), (second.name, second.items[0].name, "Work In Progress - QAB"))

    def test_real_rpc_payment_reference_and_party_replacement_cannot_hide_old_pending_purchase_invoice(self):
        from deeplinkerp_branding.services import purchase_repost_boundary as boundary
        from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry
        from frappe.client import save
        po = self.order()
        pr = self.receipt(po)
        pi = make_purchase_invoice(pr.name).insert()
        pi.submit()
        pe = get_payment_entry(pi.doctype, pi.name, bank_account="Cash - QAB", bank_amount=10).insert()
        owner = self.pending_owner()
        frappe.db.set_value(pi.doctype, pi.name, boundary.POINTER, owner.name, update_modified=False)
        self.commit_fixture()
        pe.reload()
        before = [(row.reference_doctype, row.reference_name) for row in pe.references]
        pe.set("references", [])
        pe.party_type, pe.party = "Customer", "QA Purchase Payments Customer"
        pe.flags.ignore_permissions = True
        pe.flags.purchase_reversal_internal = True
        with self.assertRaisesRegex(frappe.ValidationError, "相关采购来源待完成"):
            save(json.dumps(pe.as_dict(), default=str))
        stored = frappe.get_doc(pe.doctype, pe.name)
        self.assertEqual(stored.party_type, "Supplier")
        self.assertEqual([(row.reference_doctype, row.reference_name) for row in stored.references], before)

    def test_native_cached_type_and_item_snapshot_mismatch_refuses_then_new_request_works(self):
        from deeplinkerp_branding.services import purchase_repost_boundary as boundary
        entry_type = frappe.get_doc({"doctype": "Stock Entry Type", "name": "QA-ATOMIC-TYPE-" + uuid.uuid4().hex[:10],
            "purpose": "Material Receipt", "is_standard": 0}).insert()
        self.commit_fixture(primary_doctype="Item", name_prefix="QA-ATOMIC-")
        entry_type.purpose = "Material Transfer"
        with self.assertRaises(frappe.CannotChangeConstantError): entry_type.save()
        frappe.db.rollback()  # native immutable-default proof, before A's tested snapshot
        frappe.get_cached_value(entry_type.doctype, entry_type.name, "purpose")
        frappe.db.get_value(entry_type.doctype, entry_type.name, ("name", "purpose"), as_dict=True, cache=True)
        self.assertEqual(frappe.db.get_value("Item", self.item, "stock_uom"), "Nos")
        self.native_peer({"action": "defaults", "item": self.item, "entry_type": entry_type.name})
        draft = frappe.get_doc({"doctype": "Stock Entry", "company": COMPANY, "stock_entry_type": entry_type.name,
            "items": [{"item_code": self.item, "qty": 1, "t_warehouse": "Stores - QAB"}]})
        with self.assertRaises((frappe.QueryDeadlockError, frappe.ValidationError)) as caught: draft.insert()
        if isinstance(caught.exception, frappe.QueryDeadlockError):
            self.assertEqual(caught.exception.args[0].args[0], 1020)
        else:
            self.assertIn("快照", str(caught.exception))
        # A genuinely new native process/physical session, not clearing the old
        # execution identity or changing isolation in-place.
        peer = self.native_peer({"action": "draft", "item": self.item, "entry_type": entry_type.name})
        self.assertEqual((peer["purpose"], peer["stock_uom"]), ("Material Receipt", "Kg"))
        frappe.db.rollback()
        self.remember_new_names()

    def test_all_six_pointer_fields_reject_real_rpc_rewrite_clear_and_db_set_flags(self):
        from deeplinkerp_branding.services import purchase_repost_boundary as boundary, purchase_operation as operation
        from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry
        from frappe.client import insert, save
        from frappe.model.document import Document
        po = self.order()
        pr = self.receipt(po)
        pi = make_purchase_invoice(pr.name).insert()
        pe = get_payment_entry(po.doctype, po.name, bank_account="Cash - QAB", party_amount=10).insert()
        stock_bin = frappe.get_doc("Bin", {"item_code": self.item, "warehouse": "Stores - QAB"})
        riv = frappe.get_doc({"doctype": "Repost Item Valuation", "company": COMPANY,
            "based_on": "Item and Warehouse", "item_code": self.item, "warehouse": "Stores - QAB",
            "posting_date": nowdate(), "posting_time": "00:00:00"}).insert()
        owner = self.pending_owner()
        docs = [riv, stock_bin, po, pr, pi, pe]
        self.assertEqual({doc.doctype for doc in docs}, set(boundary.POINTER_TYPES))
        for doc in docs:
            frappe.db.set_value(doc.doctype, doc.name, boundary.POINTER, owner.name, update_modified=False)
        self.commit_fixture()
        names = {doctype: set(frappe.get_all(doctype, pluck="name", limit_page_length=0)) for doctype in self.types}
        owned = {doc.doctype: set(frappe.get_all(doc.doctype, filters={boundary.POINTER: owner.name},
            pluck="name", limit_page_length=0)) for doc in docs}
        native_insert = Document.insert
        def rpc_payload(subject):
            data = subject.as_dict()
            data["flags"] = {"ignore_permissions": True, "purchase_reversal_internal": True}
            return json.dumps(data, default=str)
        def reject_action(doc, action, expected_owner):
            current = frappe.get_doc(doc.doctype, doc.name)
            current.flags.purchase_reversal_internal = True
            current.flags.ignore_permissions = True
            inserted = []
            def observe_insert(subject, *args, **kwargs):
                inserted.append((subject.doctype, subject.name))
                return native_insert(subject, *args, **kwargs)
            try:
                with patch.object(Document, "insert", new=observe_insert), patch.object(
                        operation, "_reserve", wraps=operation._reserve) as reserved:
                    with self.assertRaises(frappe.PermissionError):
                        if action == "native-insert-new":
                            current.insert(set_name="QA-ATOMIC-COPY-" + uuid.uuid4().hex, ignore_permissions=True)
                        elif action == "rpc-insert-old":
                            insert(rpc_payload(current))
                        elif action.endswith(("-zero", "-false")):
                            value = 0 if action.endswith("-zero") else False
                            current.set(boundary.POINTER, value)
                            if action.startswith("rpc-insert"):
                                created = insert(rpc_payload(current))
                                identity = (created["doctype"], created["name"])
                            elif action.startswith("rpc-save"):
                                save(rpc_payload(current))
                                identity = (current.doctype, current.name)
                            elif action.startswith("native-save"):
                                current.save(ignore_permissions=True)
                                identity = (current.doctype, current.name)
                            else:
                                current.db_set(boundary.POINTER, value)
                                identity = (current.doctype, current.name)
                            # RED observes actual persisted values before rollback;
                            # GREEN rejects before reaching any native write.
                            print("FALSY_POINTER_WRITE=" + json.dumps({"doctype": identity[0],
                                "name": identity[1], "action": action, "stored_pointer":
                                frappe.db.get_value(*identity, boundary.POINTER)}))
                        elif action in ("rpc-save-local", "native-save-local"):
                            current.set("__islocal", 1)
                            if action == "rpc-save-local":
                                save(rpc_payload(current))
                            else:
                                current.save(ignore_permissions=True)
                        elif action == "rpc-save-no-name":
                            current.name = None
                            save(rpc_payload(current))
                        elif action == "native-copy-owner":
                            frappe.copy_doc(current).save(ignore_permissions=True)
                        elif action == "rpc-clear":
                            current.set(boundary.POINTER, None)
                            save(rpc_payload(current))
                        elif action == "native-rewrite":
                            current.set(boundary.POINTER, "QA-ATOMIC-CLIENT-" + uuid.uuid4().hex)
                            current.save(ignore_permissions=True)
                        else:
                            current.db_set(boundary.POINTER, None)
                        self.assertEqual(set(frappe.get_all(doc.doctype, filters={boundary.POINTER: owner.name},
                            pluck="name", limit_page_length=0)), owned[doc.doctype], "Owner copied into a new identity")
                    self.assertEqual(inserted, [], "Rejected before native insert")
                    reserved.assert_not_called()  # including _save -> insert, not merely late rejection
            finally:
                self.remember_new_names()
                frappe.db.rollback()
            self.assertEqual(frappe.db.get_value(doc.doctype, doc.name, boundary.POINTER), expected_owner)
            self.assertEqual(names, {doctype: set(frappe.get_all(doctype, pluck="name", limit_page_length=0))
                for doctype in self.types})
            self.assertEqual({subject.doctype: set(frappe.get_all(subject.doctype,
                filters={boundary.POINTER: owner.name}, pluck="name", limit_page_length=0)) for subject in docs}, owned)
        for doc in docs:
            for action in ("native-insert-new", "rpc-insert-old", "rpc-save-local", "native-save-local",
                    "rpc-save-no-name", "native-copy-owner", "rpc-insert-zero", "rpc-insert-false",
                    "rpc-clear", "native-rewrite", "db-set"):
                with self.subTest(doctype=doc.doctype, action=action):
                    reject_action(doc, action, owner.name)
            # Native copy/amend preparation honors metadata no_copy, independent
            # of whether this particular original is currently frozen.
            safe = frappe.copy_doc(frappe.get_doc(doc.doctype, doc.name), ignore_no_copy=False)
            self.assertFalse(safe.get(boundary.POINTER))
            self.assertTrue(safe.get("__islocal"))
            self.assertFalse(safe.name)
            self.assertEqual(frappe.db.get_value(doc.doctype, doc.name, boundary.POINTER), owner.name)
        # The same ordinary-save rule also protects previously unowned stored
        # identities. Only this exact synthetic fixture changes its baseline.
        for doc in docs:
            frappe.db.set_value(doc.doctype, doc.name, boundary.POINTER, None, update_modified=False)
        self.commit_fixture()
        owned = {doc.doctype: set() for doc in docs}
        for doc in docs:
            for action in ("rpc-save-zero", "rpc-save-false", "native-save-zero", "native-save-false",
                    "db-set-zero", "db-set-false"):
                with self.subTest(doctype=doc.doctype, action=action, previous_owner=None):
                    reject_action(doc, action, None)
        for doc in docs:
            frappe.db.set_value(doc.doctype, doc.name, boundary.POINTER, owner.name, update_modified=False)
        self.commit_fixture()
        # Existing same-identity RIV saves keep generation ownership; a genuine
        # native no-copy draft gets its own identity without that ownership.
        original = frappe.get_doc(riv.doctype, riv.name)
        original.save(ignore_permissions=True)
        copied = frappe.copy_doc(original, ignore_no_copy=False).insert(ignore_permissions=True)
        self.assertNotEqual(copied.name, original.name)
        self.assertFalse(copied.get(boundary.POINTER))
        self.assertEqual(frappe.db.get_value(original.doctype, original.name, boundary.POINTER), owner.name)
        # Actual ordinary amendment on a distinct unfrozen stock pair still
        # uses native no-copy/naming/validation; no old identity is rewritten.
        code = self.scope_item()
        amended_source = self.order(items=[{"item_code": code, "qty": 2, "rate": 12,
            "warehouse": "Stores - QAB", "schedule_date": add_days(nowdate(), 1)}], submit=False)
        self.assertEqual(amended_source.meta.get_field("transaction_time").fieldtype, "Time")
        amended_source.transaction_time = "00:11:22.123456"
        amended_source.submit()
        amended_source.cancel()
        amended = frappe.copy_doc(amended_source, ignore_no_copy=False)
        amended.amended_from = amended_source.name
        amended.insert(ignore_permissions=True)
        self.assertNotEqual(amended.name, amended_source.name)
        self.assertFalse(amended.get(boundary.POINTER))
        self.assertEqual(frappe.db.get_value(amended_source.doctype, amended_source.name, "docstatus"), 2)

    def test_real_rpc_old_source_and_warehouse_replacement_cannot_escape_pending(self):
        from deeplinkerp_branding.services import purchase_repost_boundary as boundary
        from frappe.client import save
        po = self.order()
        pr = make_purchase_receipt(po.name).insert()
        owner = self.pending_owner()
        frappe.db.set_value(po.doctype, po.name, boundary.POINTER, owner.name, update_modified=False)
        self.commit_fixture()
        pr.reload()
        old_pair = (pr.items[0].purchase_order, pr.items[0].warehouse)
        pr.items[0].purchase_order = None
        pr.items[0].purchase_order_item = None
        pr.items[0].warehouse = "Work In Progress - QAB"
        pr.flags.purchase_reversal_internal = True
        pr.flags.ignore_permissions = True
        with self.assertRaisesRegex(frappe.ValidationError, "相关采购来源待完成"):
            save(json.dumps(pr.as_dict(), default=str))
        stored = frappe.get_doc(pr.doctype, pr.name)
        self.assertEqual((stored.items[0].purchase_order, stored.items[0].warehouse), old_pair)
        # The native Material Request really changes requested Bin quantity;
        # both its pair and actual PR backlink must participate, no MR pointer.
        mr, second_po = self.material_request_order()
        self.assertEqual(frappe.db.get_value("Bin", {"item_code": self.item, "warehouse": "Stores - QAB"}, "indented_qty"), 10)
        second_po.submit()
        second_pr = make_purchase_receipt(second_po.name).insert()
        self.assertEqual(second_pr.items[0].material_request, mr.name)
        frappe.db.set_value(second_pr.doctype, second_pr.name, boundary.POINTER, owner.name, update_modified=False)
        self.commit_fixture()
        mr.reload()
        mr.items[0].qty += 1
        with self.assertRaisesRegex(frappe.ValidationError, "相关采购来源待完成"):
            mr.save(ignore_permissions=True)
        self.assertEqual(frappe.db.get_value("Material Request Item", mr.items[0].name, "qty"), 10)

    def test_opaque_native_and_stored_mes_zero_pending_fence_blocks_cross_company_publication(self):
        from deeplinkerp_branding.services import purchase_repost_boundary as boundary
        from deeplinkerp_branding.services.purchase_reversal_scope import collect_document_scope
        project = frappe.get_doc({"doctype": "Project", "project_name": "QA-ATOMIC-PROJECT-" + uuid.uuid4().hex[:10],
            "company": COMPANY}).insert()
        mr = frappe.get_doc({"doctype": "Material Request", "company": "Yuewei", "material_request_type": "Purchase",
            "transaction_date": nowdate(), "schedule_date": add_days(nowdate(), 1),
            "items": [{"item_code": self.item, "qty": 3, "warehouse": "Stores - Y", "schedule_date": add_days(nowdate(), 1)}]}).insert()
        # Exact synthetic stored classification, not an actor flag exemption.
        frappe.db.set_value(mr.doctype, mr.name, "custom_request_source", "MES", update_modified=False)
        owner = self.pending_owner()
        self.commit_fixture(primary_doctype="Item", name_prefix="QA-ATOMIC-")
        mr.reload()
        mr.flags.mes_integration_request = False
        mr.submit()  # installed performance mixin delegates this ordinary branch
        self.assertEqual(frappe.db.get_value("Bin", {"item_code": self.item, "warehouse": "Stores - Y"}, "indented_qty"), 3)
        with self.assertRaisesRegex(frappe.ValidationError, "MES"):
            collect_document_scope(mr)  # still NOT an async cancellation adapter
        frappe.db.commit()
        # B1 resolver refusal is read-only; no scope/audit/business rollback.
        self.remember_new_names()
        opaque = frappe.get_doc({"doctype": "Stock Entry", "company": COMPANY, "project": project.name,
            "stock_entry_type": "Material Receipt", "items": [{"item_code": self.item, "qty": 1,
                "t_warehouse": "Stores - QAB", "allow_zero_valuation_rate": 1}]}).insert()
        self.assertEqual(opaque.docstatus, 0)  # genuine native no-pending compatibility
        right = self.boundary_database()
        with self.assertRaises(frappe.ValidationError):
            with boundary.execution(db=right), boundary.acquire((boundary.fence_key(),), db=right): pass
        frappe.db.commit()  # method return alone did NOT free the dormant fence
        self.remember_new_names()
        name = frappe.db.get_value("Bin", {"item_code": self.item, "warehouse": "Stores - Y"}, "name")
        with boundary.execution(db=right), boundary.acquire((boundary.fence_key(),), db=right):
            # Native QB-backed set_value resolves frappe.db, not this peer
            # instance. Explicit SQL is essential to prove B really commits.
            right.sql("UPDATE `tabBin` SET custom_purchase_reversal_operation=%s WHERE name=%s", (owner.name, name))
        right.commit()  # D-style fixture publication, NOT implemented D authority
        self.assertEqual(right.sql("SELECT custom_purchase_reversal_operation FROM `tabBin` WHERE name=%s", (name,))[0][0], owner.name)
        with self.assertRaises((frappe.QueryDeadlockError, frappe.ValidationError)):
            opaque.reload().save(ignore_permissions=True)
        mr.reload()
        self.assertTrue(boundary._opaque(mr), mr.custom_request_source)
        self.assertEqual(frappe.db.get_value("Bin", name, boundary.POINTER), owner.name)
        with self.assertRaisesRegex(frappe.ValidationError, "未核查的原生关联路径"):
            mr.save(ignore_permissions=True)
        with boundary.execution(db=right), boundary.acquire((boundary.fence_key(),), db=right):
            right.sql("UPDATE `tabBin` SET custom_purchase_reversal_operation=NULL WHERE name=%s", (name,))
        right.commit()
        opaque.reload().save(ignore_permissions=True)
        mr.reload().save(ignore_permissions=True)

    def test_native_bundle_late_packed_pairs_and_real_mes_source_use_fence_absence_gate(self):
        from deeplinkerp_branding.services import purchase_repost_boundary as boundary
        from erpnext.stock.doctype.material_request.material_request import make_purchase_order
        parent = self.scope_item()
        item = frappe.get_doc("Item", parent)
        item.is_stock_item = 0
        item.save()
        frappe.get_doc({"doctype": "Product Bundle", "new_item_code": parent,
            "items": [{"item_code": self.item, "qty": 1, "uom": "Nos"}]}).insert()
        mr = frappe.get_doc({"doctype": "Material Request", "company": COMPANY, "material_request_type": "Purchase",
            "transaction_date": nowdate(), "schedule_date": add_days(nowdate(), 1), "items": [
                {"item_code": self.item, "qty": 4, "warehouse": "Stores - QAB", "schedule_date": add_days(nowdate(), 1)}]}).insert()
        mr.submit()
        frappe.db.set_value(mr.doctype, mr.name, "custom_request_source", "MES", update_modified=False)
        self.commit_fixture(primary_doctype="Item", name_prefix="QA-ATOMIC-")
        mr.reload()
        po = make_purchase_order(mr.name)
        po.supplier = "QA Test Supplier"
        po.items[0].rate = 10
        po.insert(set_name="QA-ATOMIC-PO-" + uuid.uuid4().hex[:16])
        self.assertEqual(po.items[0].material_request, mr.name)
        self.assertIn(boundary.fence_key(), boundary.initialize().locks)
        # Parent Item is non-stock and packed_items is initially EMPTY. The
        # untouched native calculator really creates the late stock child.
        dn = frappe.get_doc({"doctype": "Delivery Note", "company": COMPANY, "customer": "QA Purchase Payments Customer",
            "currency": "CNY", "conversion_rate": 1, "selling_price_list": "Standard Selling",
            "items": [{"item_code": parent, "qty": 1, "rate": 10, "warehouse": "Stores - QAB"}]}).insert()
        self.assertEqual([(row.item_code, row.warehouse) for row in dn.packed_items], [(self.item, "Stores - QAB")])
        owner = self.pending_owner()
        name = frappe.db.get_value("Bin", {"item_code": self.item, "warehouse": "Stores - QAB"}, "name")
        frappe.db.set_value("Bin", name, boundary.POINTER, owner.name, update_modified=False)
        self.commit_fixture()
        for doc in (po, dn):
            with self.subTest(doctype=doc.doctype), self.assertRaisesRegex(frappe.ValidationError, "未核查的原生关联路径"):
                doc.reload().save(ignore_permissions=True)
        # Fixture-only final publication/unlock also borrows the same fence.
        with boundary.execution(), boundary.acquire((boundary.fence_key(),)):
            frappe.db.set_value("Bin", name, boundary.POINTER, None, update_modified=False)
        self.commit_fixture()
        po.reload().save(ignore_permissions=True)
        dn.reload().save(ignore_permissions=True)

    def test_empty_incoming_bundle_packing_cannot_late_create_pending_child_pair(self):
        from deeplinkerp_branding.services import purchase_repost_boundary as boundary
        parent = self.scope_item()
        item = frappe.get_doc("Item", parent)
        item.is_stock_item = 0
        item.save()
        frappe.get_doc({"doctype": "Product Bundle", "new_item_code": parent,
            "items": [{"item_code": self.item, "qty": 1, "uom": "Nos"}]}).insert()
        self.order()  # real native ordered Bin for the late stock child
        def draft():
            return frappe.get_doc({"doctype": "Delivery Note", "company": COMPANY, "customer": "QA Purchase Payments Customer",
                "currency": "CNY", "conversion_rate": 1, "selling_price_list": "Standard Selling",
                "items": [{"item_code": parent, "qty": 1, "rate": 10, "warehouse": "Stores - QAB"}]})
        normal = draft().insert()
        self.assertEqual([(row.item_code, row.warehouse) for row in normal.packed_items], [(self.item, "Stores - QAB")])
        owner = self.pending_owner()
        name = frappe.db.get_value("Bin", {"item_code": self.item, "warehouse": "Stores - QAB"}, "name")
        frappe.db.set_value("Bin", name, boundary.POINTER, owner.name, update_modified=False)
        self.commit_fixture()
        incoming = draft()
        self.assertFalse(incoming.packed_items)
        with self.assertRaisesRegex(frappe.ValidationError, "未核查的原生关联路径"):
            incoming.insert(ignore_permissions=True)
        with boundary.execution(), boundary.acquire((boundary.fence_key(),)):
            frappe.db.set_value("Bin", name, boundary.POINTER, None, update_modified=False)
        self.commit_fixture()
        self.assertTrue(draft().insert().packed_items)

    def test_union_budget_real_old_new_native_pairs_and_sources_refuse_before_audit_sql(self):
        from deeplinkerp_branding.services import purchase_reversal_scope as scope
        first = self.order()
        second = self.order(items=[{"item_code": self.item, "qty": 10, "rate": 12.345,
            "warehouse": "Work In Progress - QAB", "schedule_date": add_days(nowdate(), 1)}])
        receipt = make_purchase_receipt(first.name).insert()
        self.commit_fixture()
        for kind in ("pairs", "identities"):
            with self.subTest(kind=kind):
                doc = frappe.get_doc(first.doctype, first.name) if kind == "pairs" else frappe.get_doc(receipt.doctype, receipt.name)
                doc.items[0].warehouse = "Work In Progress - QAB"
                if kind == "identities":
                    doc.items[0].purchase_order, doc.items[0].purchase_order_item = second.name, second.items[0].name
                statements, sql = [], frappe.db.sql
                def observe(query, *args, **kwargs):
                    statements.append(str(query))
                    return sql(query, *args, **kwargs)
                with patch.object(scope, "MAX_PAIRS" if kind == "pairs" else "MAX_VOUCHERS", 1 if kind == "pairs" else 2), \
                        patch.object(frappe.db, "sql", side_effect=observe):
                    with self.assertRaisesRegex(frappe.ValidationError, "范围超过安全上限"):
                        doc.save(ignore_permissions=True)
                self.assertFalse(any("INSERT INTO `tabIntegration Request`" in query for query in statements))

    def test_header_only_stock_entry_native_warehouse_fill_respects_pending_absence_fence(self):
        from deeplinkerp_branding.services import purchase_repost_boundary as boundary
        self.order()
        def draft():
            return frappe.get_doc({"doctype": "Stock Entry", "company": COMPANY, "stock_entry_type": "Material Receipt",
                "to_warehouse": "Stores - QAB", "items": [{"item_code": self.item, "qty": 1, "allow_zero_valuation_rate": 1}]})
        normal = draft().insert()
        self.assertEqual(normal.items[0].t_warehouse, "Stores - QAB")
        owner = self.pending_owner()
        name = frappe.db.get_value("Bin", {"item_code": self.item, "warehouse": "Stores - QAB"}, "name")
        frappe.db.set_value("Bin", name, boundary.POINTER, owner.name, update_modified=False)
        self.commit_fixture()
        with self.assertRaisesRegex(frappe.ValidationError, "未核查的原生关联路径"):
            draft().insert(ignore_permissions=True)
        with boundary.execution(), boundary.acquire((boundary.fence_key(),)):
            frappe.db.set_value("Bin", name, boundary.POINTER, None, update_modified=False)
        self.commit_fixture()
        self.assertEqual(draft().insert().items[0].t_warehouse, "Stores - QAB")

    def test_real_putaway_rule_late_stock_entry_and_receipt_warehouse_use_absence_fence(self):
        from deeplinkerp_branding.services import purchase_repost_boundary as boundary
        source = self.order()
        self.order(items=[{"item_code": self.item, "qty": 10, "rate": 12.345,
            "warehouse": "Work In Progress - QAB", "schedule_date": add_days(nowdate(), 1)}])
        frappe.get_doc({"doctype": "Putaway Rule", "company": COMPANY, "item_code": self.item,
            "warehouse": "Work In Progress - QAB", "capacity": 100, "priority": 1, "uom": "Nos", "conversion_factor": 1}).insert()
        def draft(doctype):
            if doctype == "Purchase Receipt":
                doc = make_purchase_receipt(source.name)
                doc.apply_putaway_rule = 1
                return doc
            return frappe.get_doc({"doctype": "Stock Entry", "company": COMPANY, "stock_entry_type": "Material Receipt",
                "apply_putaway_rule": 1, "items": [{"item_code": self.item, "qty": 1, "transfer_qty": 1,
                    "uom": "Nos", "stock_uom": "Nos", "conversion_factor": 1, "t_warehouse": "Stores - QAB",
                    "allow_zero_valuation_rate": 1}]})
        for doctype in ("Stock Entry", "Purchase Receipt"):
            doc = draft(doctype).insert()
            self.assertEqual(doc.items[0].get("t_warehouse" if doctype == "Stock Entry" else "warehouse"), "Work In Progress - QAB")
        owner = self.pending_owner()
        name = frappe.db.get_value("Bin", {"item_code": self.item, "warehouse": "Work In Progress - QAB"}, "name")
        frappe.db.set_value("Bin", name, boundary.POINTER, owner.name, update_modified=False)
        self.commit_fixture()
        for doctype in ("Stock Entry", "Purchase Receipt"):
            with self.subTest(doctype=doctype), self.assertRaisesRegex(frappe.ValidationError, "未核查的原生关联路径"):
                draft(doctype).insert(ignore_permissions=True)
        with boundary.execution(), boundary.acquire((boundary.fence_key(),)):
            frappe.db.set_value("Bin", name, boundary.POINTER, None, update_modified=False)
        self.commit_fixture()
        for doctype in ("Stock Entry", "Purchase Receipt"):
            draft(doctype).insert()

    def receipt(self, po):
        from deeplinkerp_branding.services import purchase_document_actions as actions
        key = po.items[0].name
        native_draft = frappe.db.get_value("Purchase Receipt Item", {"purchase_order": po.name, "docstatus": 0}, "parent")
        args = {"target_name": native_draft, "expected_modified": frappe.db.get_value("Purchase Receipt", native_draft, "modified")} if native_draft else {}
        result = actions.record_receipt(po.name, {"items": [{"key": key, "qty": 2, "warehouse": "Stores - QAB"}]}, str(uuid.uuid4()), **args)
        self.assertFalse(result.get("failed"), result)
        self.assertEqual(result["document"]["docstatus"], 1)
        return frappe.get_doc("Purchase Receipt", result["document"]["name"])

    def test_stocked_receipt_invoice_payment_native_form_and_precommit(self):
        from deeplinkerp_branding.services import purchase_document_actions as actions
        from deeplinkerp_branding.services import purchase_consistency as guard
        po = self.order()
        pr = self.receipt(po)
        self.assertEqual(frappe.db.get_value("Bin", {"item_code": self.item, "warehouse": "Stores - QAB"}, "actual_qty"), 2)
        pi = make_purchase_invoice(pr.name).insert()
        from frappe.client import submit
        submit(pi.as_dict())
        pi.reload()
        guard.check_registered()
        args = dict(source_doctype="Purchase Receipt", source_name=pr.name, purchase_invoice=pi.name,
            amount_to_pay=10, bank_account="Cash - QAB", request_id=str(uuid.uuid4()))
        paid = actions.record_payment(**args)
        self.assertFalse(paid.get("failed"), paid)
        pe = frappe.get_doc("Payment Entry", paid["document"]["name"])
        self.assertEqual(pe.docstatus, 1)
        guard.check_registered()
        frappe.db.before_commit.run()  # exercise final form hooks, without committing test data
        self.assertEqual(frappe.db.get_value("Bin", {"item_code": self.item, "warehouse": "Stores - QAB"}, "actual_qty"), 2)

    def test_zero_amount_native_invoice_without_financial_movement_is_legal(self):
        for automatic in (0, 1):
            with self.subTest(automatic=automatic):
                if not frappe.db.exists("Item", self.item):
                    frappe.get_doc({"doctype": "Item", "item_code": self.item, "item_name": self.item,
                        "item_group": "All Item Groups", "stock_uom": "Nos", "is_stock_item": 0}).insert()
                else:
                    frappe.db.set_value("Item", self.item, "is_stock_item", 0)
                    frappe.clear_document_cache("Item", self.item)
                frappe.db.set_value("China Finance Settings", COMPANY, "auto_submit_purchase_invoice", automatic)
                try:
                    po = self.order(qty=2, rate=0)
                    pr = make_purchase_receipt(po.name).insert()
                    pr.submit()
                    if automatic:
                        name = frappe.db.get_value("Purchase Invoice Item", {"purchase_receipt": pr.name}, "parent")
                        self.assertTrue(name)
                        pi = frappe.get_doc("Purchase Invoice", name)
                    else:
                        pi = make_purchase_invoice(pr.name).insert()
                        pi.submit()
                    self.assertEqual((pi.docstatus, pi.grand_total, pi.outstanding_amount), (1, 0, 0))
                    self.assertEqual(pi.items[0].qty, 2)
                    self.assertEqual(pi.items[0].rate, 0)
                    for doctype in ("GL Entry", "Payment Ledger Entry"):
                        self.assertFalse(frappe.db.count(doctype, {"voucher_type": pi.doctype, "voucher_no": pi.name}))
                    self.assertFalse(frappe.db.count("China Accounting Voucher", {"source_doctype": pi.doctype, "source_name": pi.name}))
                finally:
                    frappe.db.rollback()
                    frappe.clear_document_cache("Item", self.item)

    def test_order_inventory_bin_changes_are_bound_to_native_replay(self):
        from deeplinkerp_branding.services import purchase_consistency as guard
        from deeplinkerp_branding.services import purchase_operation as kernel
        po = self.order()
        payload = json.dumps(po.as_dict(), default=str)
        key = str(uuid.uuid4())
        guard.savedocs(payload, "Update", request_id=key)
        self.commit_fixture()
        audit = frappe.get_doc("Integration Request", kernel.identity("Administrator", key))
        self.assertTrue(any(row["doctype"] == "Purchase Order" for row in json.loads(audit.output)["artifacts"]))
        self.assertFalse(frappe.db.count("Stock Ledger Entry", {"voucher_type": po.doctype, "voucher_no": po.name}))
        for field in ("ordered_qty", "indented_qty"):
            with self.subTest(field=field):
                quantity = frappe.db.get_value("Bin", {"item_code": self.item, "warehouse": "Stores - QAB"}, field)
                frappe.db.set_value("Bin", {"item_code": self.item, "warehouse": "Stores - QAB"}, field, quantity + 1, update_modified=False)
                try:
                    with self.assertRaises(frappe.ValidationError) as caught:
                        guard.savedocs(payload, "Update", request_id=key)
                    self.assertEqual(caught.exception.purchase_error_id, "replay_evidence_changed")
                finally:
                    frappe.db.set_value("Bin", {"item_code": self.item, "warehouse": "Stores - QAB"}, field, quantity, update_modified=False)

    def test_nonzero_invoice_requires_native_supplier_payment_ledger(self):
        from deeplinkerp_branding.services import purchase_consistency as guard
        po = self.order()
        pr = self.receipt(po)
        pi = make_purchase_invoice(pr.name).insert()
        native = guard.check_invoice_balance
        def lose_ledger(doc):
            if (doc.doctype, doc.name) == (pi.doctype, pi.name):
                self.assertTrue(frappe.db.count("Payment Ledger Entry", {"voucher_type": pi.doctype, "voucher_no": pi.name}))
                frappe.db.delete("Payment Ledger Entry", {"voucher_type": pi.doctype, "voucher_no": pi.name})
            return native(doc)
        with patch.object(guard, "check_invoice_balance", side_effect=lose_ledger), self.assertRaises(frappe.ValidationError) as caught:
            pi.submit()
        self.assertEqual(caught.exception.purchase_error_id, "purchase_invoice_ple_missing")
        self.assertFalse(frappe.db.exists("Purchase Invoice", pi.name))

    def material_request_order(self):
        from erpnext.stock.doctype.material_request.material_request import make_purchase_order
        mr = frappe.get_doc({"doctype": "Material Request", "company": COMPANY, "material_request_type": "Purchase",
            "transaction_date": nowdate(), "schedule_date": add_days(nowdate(), 1),
            "items": [{"item_code": self.item, "qty": 10, "warehouse": "Stores - QAB", "schedule_date": add_days(nowdate(), 1)}]}).insert()
        mr.submit()
        po = make_purchase_order(mr.name)
        po.supplier = "QA Test Supplier"
        po.items[0].rate = 12.345
        po.insert(set_name="QA-ATOMIC-PO-" + uuid.uuid4().hex[:16])
        return mr, po

    def test_native_order_material_request_updates_are_replay_artifacts(self):
        from deeplinkerp_branding.services import purchase_consistency as guard
        from deeplinkerp_branding.services import purchase_operation as kernel
        mr, po = self.material_request_order()
        key = str(uuid.uuid4())
        payload = json.dumps(po.as_dict(), default=str)
        guard.savedocs(payload, "Submit", key)
        self.commit_fixture()
        artifacts = json.loads(frappe.get_doc("Integration Request", kernel.identity("Administrator", key)).output)["artifacts"]
        self.assertTrue(any(row["doctype"] == mr.doctype and row["name"] == mr.name for row in artifacts))
        self.assertEqual(frappe.db.get_value("Material Request Item", mr.items[0].name, "ordered_qty"), 10)
        self.assertEqual(frappe.db.get_value(mr.doctype, mr.name, "per_ordered"), 100)
        for doctype, name, field in (("Material Request Item", mr.items[0].name, "ordered_qty"), (mr.doctype, mr.name, "per_ordered")):
            with self.subTest(field=field):
                frappe.db.set_value(doctype, name, field, frappe.db.get_value(doctype, name, field) + 1, update_modified=False)
                with self.assertRaises(frappe.ValidationError) as caught:
                    guard.savedocs(payload, "Submit", key)
                self.assertEqual(caught.exception.purchase_error_id, "replay_evidence_changed")

    def test_native_receipt_material_request_updates_are_replay_artifacts(self):
        from deeplinkerp_branding.services import purchase_consistency as guard
        from deeplinkerp_branding.services import purchase_operation as kernel
        mr, po = self.material_request_order()
        po.submit()
        self.commit_fixture()
        pr = make_purchase_receipt(po.name).insert()
        key = str(uuid.uuid4())
        payload = json.dumps(pr.as_dict(), default=str)
        guard.savedocs(payload, "Submit", key)
        self.commit_fixture()
        artifact = json.loads(frappe.get_doc("Integration Request", kernel.identity("Administrator", key)).output)["artifacts"]
        self.assertTrue(any(row["doctype"] == mr.doctype and row["name"] == mr.name for row in artifact))
        for doctype, name, field in (("Material Request Item", mr.items[0].name, "received_qty"),
                (mr.doctype, mr.name, "per_received")):
            with self.subTest(field=field):
                frappe.db.set_value(doctype, name, field, frappe.db.get_value(doctype, name, field) + 1, update_modified=False)
                with self.assertRaises(frappe.ValidationError) as caught:
                    guard.savedocs(payload, "Submit", key)
                self.assertEqual(caught.exception.purchase_error_id, "replay_evidence_changed")

    def test_receipt_native_source_invoice_quantity_is_a_replay_artifact(self):
        from erpnext.buying.doctype.purchase_order.purchase_order import make_purchase_invoice as invoice_from_order
        from erpnext.accounts.doctype.purchase_invoice.purchase_invoice import make_purchase_receipt as receipt_from_invoice
        from deeplinkerp_branding.services import purchase_consistency as guard
        from deeplinkerp_branding.services import purchase_operation as kernel
        frappe.db.set_value("Item", self.item, "is_stock_item", 0)
        frappe.clear_document_cache("Item", self.item)
        po = self.order()
        pi = invoice_from_order(po.name).insert()
        pi.submit()
        self.commit_fixture()
        pr = receipt_from_invoice(pi.name).insert()
        self.assertEqual(pr.items[0].purchase_invoice, pi.name)
        key = str(uuid.uuid4())
        payload = json.dumps(pr.as_dict(), default=str)
        guard.savedocs(payload, "Submit", key)
        self.commit_fixture()
        artifacts = json.loads(frappe.get_doc("Integration Request", kernel.identity("Administrator", key)).output)["artifacts"]
        self.assertTrue(any(row["doctype"] == pi.doctype and row["name"] == pi.name for row in artifacts))
        for doctype, name, field in (("Purchase Invoice Item", pi.items[0].name, "received_qty"), (pi.doctype, pi.name, "per_received")):
            with self.subTest(field=field):
                frappe.db.set_value(doctype, name, field, frappe.db.get_value(doctype, name, field) + 1, update_modified=False)
                with self.assertRaises(frappe.ValidationError) as caught:
                    guard.savedocs(payload, "Submit", key)
                self.assertEqual(caught.exception.purchase_error_id, "replay_evidence_changed")

    def test_managed_fulfilment_invalidation_is_a_replay_artifact(self):
        from deeplinkerp_branding.services import purchase_consistency as guard
        from deeplinkerp_branding.services import purchase_fulfilment_service as fulfilment
        from deeplinkerp_branding.services import purchase_operation as kernel
        po = self.order()
        result = fulfilment.save_link(po.name, po.items[0].name, COMPANY, COMPANY, "trade_custody", 2,
            str(po.modified), custody_company=COMPANY, custody_warehouse="Stores - QAB")
        name = result["name"]
        key = str(uuid.uuid4())
        payload = json.dumps(po.as_dict(), default=str)
        guard.cancel(po.doctype, po.name, request_id=key, doc=payload)
        self.commit_fixture()
        artifacts = json.loads(frappe.get_doc("Integration Request", kernel.identity("Administrator", key)).output)["artifacts"]
        self.assertTrue(any(row["doctype"] == fulfilment.DOCTYPE and row["name"] == name for row in artifacts))
        frappe.db.set_value(fulfilment.DOCTYPE, name, "source_versions_json", "{}", update_modified=False)
        with self.assertRaises(frappe.ValidationError) as caught:
            guard.cancel(po.doctype, po.name, request_id=key, doc=payload)
        self.assertEqual(caught.exception.purchase_error_id, "replay_evidence_changed")

    def cash_assignment_payment(self):
        from china_finance.services import cash_flow_assignment, cash_equivalent_scope, voucher
        from deeplinkerp_branding.services import purchase_document_actions as actions
        if "Cash - QAB" not in cash_equivalent_scope.get_cash_scope_accounts(COMPANY, nowdate()):
            frappe.get_doc({"doctype": "China Cash Equivalent Scope", "company": COMPANY, "account": "Cash - QAB",
                "classification": "库存现金", "included": 1, "policy_basis": "QA synthetic cash scope",
                "effective_from": nowdate()}).insert()
        po = self.order()
        pr = self.receipt(po)
        pi = make_purchase_invoice(pr.name).insert()
        pi.submit()
        settings = frappe.get_doc(voucher.get_company_settings(COMPANY).as_dict())
        settings.cash_flow_assignment_activation_date = nowdate()
        key = str(uuid.uuid4())
        # Local policy fixture only; native voucher/assignment writers run real.
        with patch.object(cash_flow_assignment, "get_company_settings", return_value=settings):
            result = actions.record_payment(source_doctype=pr.doctype, source_name=pr.name, purchase_invoice=pi.name,
                amount_to_pay=10, bank_account="Cash - QAB", request_id=key)
        self.assertFalse(result.get("failed"), result)
        pe = frappe.get_doc("Payment Entry", result["document"]["name"])
        assignment = frappe.get_doc("China Cash Flow Assignment", {"source_doctype": pe.doctype, "source_name": pe.name})
        self.assertEqual((assignment.docstatus, assignment.status), (0, "Draft"))
        self.commit_fixture()
        return pe, assignment, key

    def test_native_finance_posting_cash_assignment_is_a_system_artifact(self):
        from deeplinkerp_branding.services import purchase_operation as kernel
        pe, assignment, key = self.cash_assignment_payment()
        artifacts = json.loads(frappe.get_doc("Integration Request", kernel.identity("Administrator", key)).output)["artifacts"]
        found = [row for row in artifacts if (row["doctype"], row["name"]) == (assignment.doctype, assignment.name)]
        self.assertEqual(len(found), 1)
        self.assertTrue(found[0]["system_effect"])
        frappe.db.set_value(assignment.items[0].doctype, assignment.items[0].name, "cash_amount", assignment.items[0].cash_amount + 1, update_modified=False)
        with self.assertRaises(frappe.ValidationError) as caught:
            kernel.replay_artifacts({"artifacts": artifacts})
        self.assertEqual(caught.exception.purchase_error_id, "replay_evidence_changed")

    def test_native_finance_cancellation_issue_and_cash_assignment_are_system_artifacts(self):
        from deeplinkerp_branding.services import purchase_consistency as guard
        from deeplinkerp_branding.services import purchase_operation as kernel
        pe, assignment, _ = self.cash_assignment_payment()
        key = str(uuid.uuid4())
        payload = json.dumps(pe.as_dict(), default=str)
        guard.cancel(pe.doctype, pe.name, request_id=key, doc=payload)
        self.commit_fixture()
        issue = frappe.get_doc("China Voucher Sync Issue", {"issue_key": f"Cancellation|{pe.doctype}|{pe.name}"})
        artifacts = json.loads(frappe.get_doc("Integration Request", kernel.identity("Administrator", key)).output)["artifacts"]
        for target, status in ((issue, "Resolved"), (assignment, "Cancelled")):
            with self.subTest(doctype=target.doctype):
                found = [row for row in artifacts if (row["doctype"], row["name"]) == (target.doctype, target.name)]
                self.assertEqual(len(found), 1)
                self.assertTrue(found[0]["system_effect"])
                self.assertEqual(frappe.db.get_value(target.doctype, target.name, "status"), status)
                frappe.db.set_value(target.doctype, target.name, "status", "Pending" if target is issue else "Draft", update_modified=False)
                with self.assertRaises(frappe.ValidationError) as caught:
                    guard.cancel(pe.doctype, pe.name, request_id=key, doc=payload)
                self.assertEqual(caught.exception.purchase_error_id, "replay_evidence_changed")

    def test_native_resource_cancel_cannot_strip_procurement_identity_or_change_business_facts(self):
        from frappe.api import v1, v2
        from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry
        frappe.db.set_value("Item", self.item, "is_stock_item", 0)
        frappe.clear_document_cache("Item", self.item)
        po = self.order()
        pr = self.receipt(po)
        pi = make_purchase_invoice(pr.name).insert()
        pi.submit()
        pe = get_payment_entry(po.doctype, po.name, bank_account="Cash - QAB", party_amount=10)
        pe.insert()
        pe.submit()
        self.commit_fixture()
        self.remember_effects()
        for api in (v1, v2):
            for source, change in ((pi, "links"), (pi, "amount"), (pe, "references"), (pe, "party_type")):
                with self.subTest(api=api.__name__, source=source.doctype, change=change):
                    payload = frappe.get_doc(source.doctype, source.name).as_dict(convert_dates_to_str=True)
                    payload["docstatus"] = 2
                    if change == "links":
                        for row in payload["items"]:
                            for field in ("purchase_order", "po_detail", "purchase_receipt", "pr_detail"):
                                row[field] = None
                    elif change == "amount":
                        payload["items"][0]["qty"] += 1
                    elif change == "references":
                        payload["references"] = []
                    else:
                        payload["party_type"] = "Customer"
                        payload["party"] = "QA Purchase Payments Customer"
                    try:
                        if api is v1:
                            with patch.object(v1, "get_request_form_data", return_value=payload), self.assertRaises(frappe.ValidationError) as caught:
                                api.update_doc(source.doctype, source.name)
                        else:
                            with patch.object(frappe.local, "form_dict", frappe._dict(payload)), self.assertRaises(frappe.ValidationError) as caught:
                                api.update_doc(source.doctype, source.name)
                        self.assertEqual(caught.exception.purchase_error_id, "cancellation_business_facts_changed")
                    finally:
                        frappe.db.rollback()
                    self.assert_effects_unchanged()

    def test_native_resource_docstatus_only_cancellation_keeps_finance_atomic(self):
        from datetime import timedelta
        from frappe.api import v1, v2
        from deeplinkerp_branding.services import purchase_consistency as guard
        frappe.db.set_value("Item", self.item, "is_stock_item", 0)
        frappe.clear_document_cache("Item", self.item)
        po = self.order()
        pr = self.receipt(po)
        pi = make_purchase_invoice(pr.name)
        pi.set_posting_time = 1
        pi.posting_time = "00:11:22.123456"
        pi.remarks = "0:11:22.123456"
        pi.insert()
        pi.submit()
        self.commit_fixture()
        self.assertEqual(pi.meta.get_field("posting_time").fieldtype, "Time")
        self.assertNotEqual(pi.meta.get_field("remarks").fieldtype, "Time")
        self.assertEqual(frappe.db.get_value(pi.doctype, pi.name, "posting_time"),
            timedelta(minutes=11, seconds=22, microseconds=123456))
        self.remember_effects()
        for api in (v1, v2):
            for change, allowed in (({}, True), ({"posting_time": "00:11:22.123456"}, True),
                    ({"posting_time": "0:11:22.123456"}, True), ({"posting_time": "00:11:22.123457"}, False),
                    ({"posting_time": "not-a-time"}, False), ({"remarks": "00:11:22.123456"}, False)):
                with self.subTest(api=api.__name__, change=change):
                    payload = {"docstatus": 2, **change}
                    def cancel():
                        if api is v1:
                            with patch.object(v1, "get_request_form_data", return_value=payload):
                                return api.update_doc(pi.doctype, pi.name)
                        with patch.object(frappe.local, "form_dict", frappe._dict(payload)):
                            return api.update_doc(pi.doctype, pi.name)
                    try:
                        if allowed:
                            cancel()
                            guard.check_registered()
                            self.assertEqual(frappe.db.get_value(pi.doctype, pi.name, "docstatus"), 2)
                            issue = frappe.get_doc("China Voucher Sync Issue", {"issue_key": f"Cancellation|{pi.doctype}|{pi.name}"})
                            self.assertEqual(issue.status, "Resolved")
                            self.assertTrue(issue.cancellation_voucher)
                        else:
                            with self.assertRaises(frappe.ValidationError) as caught:
                                cancel()
                            self.assertEqual(caught.exception.purchase_error_id, "cancellation_business_facts_changed")
                            self.assert_effects_unchanged()
                    finally:
                        frappe.db.rollback()

    def test_zero_movement_native_cancellation_cannot_hide_a_pending_finance_issue(self):
        from frappe.api import v1
        frappe.db.set_value("Item", self.item, "is_stock_item", 0)
        frappe.clear_document_cache("Item", self.item)
        po = self.order(qty=2, rate=0)
        pr = make_purchase_receipt(po.name).insert()
        pr.submit()
        pi = make_purchase_invoice(pr.name).insert()
        pi.submit()
        self.commit_fixture()
        self.remember_effects()
        with patch.object(v1, "get_request_form_data", return_value={"docstatus": 2}), self.assertRaises(frappe.ValidationError) as caught:
            v1.update_doc(pi.doctype, pi.name)
        self.assertEqual(caught.exception.purchase_error_id, "finance_zero_movement_cancellation_unsupported")
        self.assertFalse(frappe.db.exists("China Voucher Sync Issue", {"issue_key": f"Cancellation|{pi.doctype}|{pi.name}"}))
        self.assert_effects_unchanged()

    def test_native_payment_invoice_cancellation_then_receipt_repost_refuses_atomically(self):
        """Synchronous PE/PI cancellation; stock PR cancellation is not fake success."""
        from collections import defaultdict
        from decimal import Decimal
        from deeplinkerp_branding.services import purchase_document_actions as actions
        from deeplinkerp_branding.services import purchase_consistency as guard
        from frappe.client import cancel

        po = self.order()
        pr = self.receipt(po)
        pi = make_purchase_invoice(pr.name).insert()
        pi.submit()
        paid = actions.record_payment(source_doctype="Purchase Receipt", source_name=pr.name,
            purchase_invoice=pi.name, amount_to_pay=10, bank_account="Cash - QAB", request_id=str(uuid.uuid4()))
        self.assertFalse(paid.get("failed"), paid)
        pe = frappe.get_doc("Payment Entry", paid["document"]["name"])
        full_balance = pi.grand_total
        self.commit_fixture()
        self.remember_effects()

        # Native PR.on_cancel refuses a submitted PI (and its real payment chain)
        # before stock/GL/repost. No automatic downstream cancellation is added.
        pr = frappe.get_doc("Purchase Receipt", pr.name)
        with self.assertRaisesRegex(frappe.ValidationError, "Purchase Invoice.*already submitted"):
            pr.cancel()
        self.assert_effects_unchanged()
        pr = frappe.get_doc("Purchase Receipt", pr.name)

        def amounts(snapshot):
            result = defaultdict(lambda: [Decimal(0)] * 4)
            for row in snapshot.entries:
                key = tuple(row.get(field) or "" for field in ("account", "account_currency", "party_type",
                    "party", "cost_center", "project", "finance_book", "against_voucher_type", "against_voucher")) + (
                    json.dumps(json.loads(row.get("dimensions_json") or "{}"), sort_keys=True),)
                for index, field in enumerate(("debit", "credit", "debit_in_account_currency", "credit_in_account_currency")):
                    result[key][index] += Decimal(str(row.get(field) or 0))
            return dict(result)

        for source in (pe, pi):
            with self.subTest(doctype=source.doctype):
                posting_name = frappe.db.get_value("China Accounting Voucher",
                    {"source_key": f"Posting|{source.doctype}|{source.name}", "docstatus": 1}, "name")
                self.assertTrue(posting_name, "Real posting must exist before cancellation")
                before = frappe.get_doc("China Accounting Voucher", posting_name)
                before_amounts = amounts(before)
                self.assertTrue(any(any(values) for values in before_amounts.values()))
                cancel(source.doctype, source.name)
                guard.check_registered()
                # Evaluate the final controller/finance hook chain without committing QA business rows.
                frappe.db.before_commit.run()
                self.assertEqual(frappe.db.get_value(source.doctype, source.name, "docstatus"), 2)
                reversal_name = frappe.db.get_value("China Accounting Voucher",
                    {"source_key": f"Cancellation|{source.doctype}|{source.name}"}, "name")
                reversal = frappe.get_doc("China Accounting Voucher", reversal_name)
                self.assertEqual(reversal.docstatus, 1)
                self.assertEqual(reversal.reversal_of, posting_name)
                self.assertEqual(amounts(reversal), {key: [values[1], values[0], values[3], values[2]]
                    for key, values in before_amounts.items()})
                before.reload()
                self.assertEqual((before.status, before.reversed_by), ("Reversed", reversal.name))
                self.assertEqual(amounts(before), before_amounts, "Original posted entries are immutable")
                # ERPNext retains BOTH original and reverse GL as is_cancelled=1;
                # the China snapshot must reverse only the original, never their combined net zero.
                self.assertTrue(frappe.db.count("GL Entry",
                    {"voucher_type": source.doctype, "voucher_no": source.name, "is_cancelled": 1}))
                self.assertFalse(frappe.db.count("GL Entry",
                    {"voucher_type": source.doctype, "voucher_no": source.name, "is_cancelled": 0}))
                if source.doctype == "Payment Entry":
                    self.assertEqual(frappe.db.get_value("Purchase Invoice", pi.name, "outstanding_amount"), full_balance)
                    self.assertFalse(frappe.db.count("Payment Ledger Entry",
                        {"voucher_type": "Payment Entry", "voucher_no": pe.name, "delinked": 0}))
                elif source.doctype == "Purchase Invoice":
                    self.assertFalse(frappe.db.count("Payment Ledger Entry",
                        {"voucher_type": "Purchase Invoice", "voucher_no": pi.name, "delinked": 0}))
                    self.assertEqual(frappe.db.get_value("Bin",
                        {"item_code": self.item, "warehouse": "Stores - QAB"}, "actual_qty"), 2)
        with self.assertRaises(frappe.ValidationError) as caught:
            cancel(pr.doctype, pr.name)
        self.assertEqual(caught.exception.purchase_error_id, "native_stock_repost_incomplete")
        self.assertEqual(frappe.db.get_value("Purchase Receipt", pr.name, "docstatus"), 1)
        self.assertEqual(frappe.db.get_value("Purchase Invoice", pi.name, "docstatus"), 1)
        self.assertEqual(frappe.db.get_value("Payment Entry", pe.name, "docstatus"), 1)
        self.assert_effects_unchanged()  # the refused final action restores this entire uncommitted transaction

    def test_native_form_stock_corruption_rolls_back_complete_transaction(self):
        from deeplinkerp_branding.services import purchase_consistency as guard
        po = self.order()
        pr = make_purchase_receipt(po.name).insert()
        pr.submit()
        frappe.db.set_value("Bin", {"item_code": self.item, "warehouse": "Stores - QAB"}, "actual_qty", 999)
        with self.assertRaises(frappe.ValidationError):
            frappe.db.before_commit.run()
        self.assertFalse(frappe.db.exists("Purchase Receipt", pr.name))
        self.assertFalse(frappe.db.exists("Purchase Order", po.name))

    def test_native_rejected_receipt_uses_total_received_quantity(self):
        from deeplinkerp_branding.services import purchase_consistency as guard
        po = self.order()
        pr = make_purchase_receipt(po.name)
        pr.items[0].qty = 3
        pr.items[0].received_qty = 5
        pr.items[0].rejected_qty = 2
        rejected = frappe.get_doc({"doctype": "Warehouse", "warehouse_name": "QA-ATOMIC-REJECT-" + uuid.uuid4().hex[:10],
            "company": COMPANY}).insert()
        pr.items[0].rejected_warehouse = rejected.name
        pr.insert()
        pr.submit()
        guard.check_registered()
        self.assertEqual(frappe.db.get_value("Purchase Order Item", po.items[0].name, "received_qty"), 5)
        returned = make_purchase_return(pr.name).insert()
        returned.submit()
        guard.check_registered()
        self.assertEqual(frappe.db.get_value("Purchase Order Item", po.items[0].name, "received_qty"), 0)

    def test_real_native_sales_order_row_dependency_fails_closed(self):
        from deeplinkerp_branding.services import purchase_consistency as guard
        so = frappe.get_doc({"doctype": "Sales Order", "company": COMPANY,
            "customer": "QA Purchase Payments Customer", "delivery_date": add_days(nowdate(), 1),
            "items": [{"item_code": self.item, "qty": 2, "rate": 20, "warehouse": "Stores - QAB", "delivery_date": add_days(nowdate(), 1)}]}).insert()
        so.submit()
        po = frappe.get_doc({"doctype": "Purchase Order", "company": COMPANY,
            "supplier": "QA Test Supplier", "schedule_date": add_days(nowdate(), 1),
            "items": [{"item_code": self.item, "qty": 2, "rate": 12.345, "sales_order": so.name,
                "sales_order_item": so.items[0].name, "warehouse": "Stores - QAB", "schedule_date": add_days(nowdate(), 1)}]})
        with self.assertRaises(frappe.ValidationError) as caught:
            po.insert(set_name="QA-ATOMIC-PO-" + uuid.uuid4().hex[:16])
        self.assertEqual(caught.exception.purchase_error_id, "sales_dependency_unsupported")
        self.assertFalse(frappe.db.exists("Purchase Order", po.name))

    def internal_sales_parties(self):
        """Real, same-currency cross-company parties shared by native Sales fixtures."""
        selling_company = "Yuewei"
        self.assertEqual(frappe.db.get_value("Company", selling_company, "default_currency"), "CNY")
        frappe.db.set_value("Item", self.item, "is_stock_item", 0)
        customer = frappe.get_doc({"doctype": "Customer", "customer_name": "QA-ATOMIC-CUSTOMER-" + uuid.uuid4().hex[:10],
            "customer_type": "Company", "customer_group": "Government", "territory": "Rest Of The World",
            "is_internal_customer": 1, "represents_company": COMPANY, "companies": [{"company": selling_company}]}).insert()
        supplier = frappe.get_doc({"doctype": "Supplier", "supplier_name": "QA-ATOMIC-SUPPLIER-" + uuid.uuid4().hex[:10],
            "supplier_group": "All Supplier Groups", "supplier_type": "Company", "is_internal_supplier": 1,
            "represents_company": selling_company, "companies": [{"company": COMPANY}]}).insert()
        price_list = frappe.get_doc({"doctype": "Price List", "price_list_name": "QA-ATOMIC-PRICE-" + uuid.uuid4().hex[:10],
            "enabled": 1, "buying": 1, "selling": 1, "currency": "CNY"}).insert()
        return selling_company, customer, supplier, price_list

    def test_real_native_delivery_note_receipt_dependency_fails_closed(self):
        from deeplinkerp_branding.services import purchase_consistency as guard
        from erpnext.stock.doctype.delivery_note.delivery_note import make_inter_company_purchase_receipt
        selling_company, customer, supplier, price_list = self.internal_sales_parties()
        dn = frappe.get_doc({"doctype": "Delivery Note", "company": selling_company, "customer": customer.name,
            "currency": "CNY", "conversion_rate": 1, "selling_price_list": price_list.name,
            "items": [{"item_code": self.item, "qty": 2, "rate": 20}]}).insert(
                set_name="QA-ATOMIC-DN-" + uuid.uuid4().hex[:16])
        dn.submit()
        self.commit_fixture("Delivery Note", "QA-ATOMIC-DN-")
        original = guard.artifact_evidence(frappe.get_doc("Delivery Note", dn.name))
        counts = {doctype: frappe.db.count(doctype) for doctype in self.types}
        self.assertEqual(frappe.db.get_value("Delivery Note Item", dn.items[0].name, "received_qty"), 0)
        pr = make_inter_company_purchase_receipt(dn.name)
        self.assertEqual(pr.inter_company_reference, dn.name)
        self.assertEqual(pr.items[0].delivery_note_item, dn.items[0].name)
        self.assertFalse(any(row.get(field) for row in pr.items for field in (
            "purchase_order", "purchase_order_item", "material_request", "material_request_item", "purchase_invoice", "purchase_invoice_item")))
        try:
            pr.insert()
            pr.submit()
        except frappe.ValidationError as caught:
            self.assertEqual(caught.purchase_error_id, "sales_dependency_unsupported")
        else:
            self.assertEqual(frappe.db.get_value("Purchase Receipt", pr.name, "docstatus"), 1)
            self.assertEqual(frappe.db.get_value("Delivery Note Item", dn.items[0].name, "received_qty"), 2)
            self.fail("Native standalone DN -> PR submitted and changed DN received_qty without the Sales dependency guard")
        self.assertFalse(frappe.db.exists("Purchase Receipt", pr.name))
        self.assertEqual(guard.artifact_evidence(frappe.get_doc("Delivery Note", dn.name)), original)
        self.assertEqual({doctype: frappe.db.count(doctype) for doctype in self.types}, counts)

    def test_real_native_sales_invoice_with_purchase_order_dependency_fails_closed(self):
        from deeplinkerp_branding.services import purchase_consistency as guard
        from erpnext.accounts.doctype.sales_invoice.sales_invoice import make_inter_company_purchase_invoice
        selling_company, customer, supplier, price_list = self.internal_sales_parties()
        po = self.order(supplier=supplier.name, qty=2, rate=20)
        si = frappe.get_doc({"doctype": "Sales Invoice", "company": selling_company, "customer": customer.name,
            "currency": "CNY", "conversion_rate": 1, "selling_price_list": price_list.name, "update_stock": 0,
            "items": [{"item_code": self.item, "qty": 2, "rate": 20}]}).insert(
                set_name="QA-ATOMIC-SI-" + uuid.uuid4().hex[:16])
        si.submit()
        self.commit_fixture()
        self.remember_effects()
        counts = {doctype: frappe.db.count(doctype) for doctype in self.types}
        pi = make_inter_company_purchase_invoice(si.name)
        self.assertEqual(pi.inter_company_invoice_reference, si.name)
        self.assertEqual(pi.items[0].sales_invoice_item, si.items[0].name)
        self.assertFalse(si.items[0].get("sales_order") or si.items[0].get("dn_detail"))
        pi.items[0].purchase_order, pi.items[0].po_detail = po.name, po.items[0].name
        try:
            pi.insert()
        except frappe.ValidationError as caught:
            self.assertEqual(caught.purchase_error_id, "sales_dependency_unsupported")
        else:
            self.assertEqual(frappe.db.get_value("Purchase Invoice", pi.name, "docstatus"), 0)
            self.assertTrue(any(row["module"] == "Sales/procurement review" and row["result"] == "N/A"
                for row in guard.invalidate_reviews(frappe.get_doc("Purchase Invoice", pi.name))))
            self.fail("Native SI -> PI with a valid PO source saved and falsely reported Sales N/A")
        self.assertFalse(frappe.db.exists("Purchase Invoice", pi.name))
        self.assert_effects_unchanged()
        self.assertEqual({doctype: frappe.db.count(doctype) for doctype in self.types}, counts)

    def test_real_native_parent_only_intercompany_order_cancellation_fails_closed(self):
        from deeplinkerp_branding.services import purchase_consistency as guard
        from erpnext.selling.doctype.sales_order.sales_order import make_inter_company_purchase_order
        selling_company, customer, supplier, price_list = self.internal_sales_parties()
        # Create a synthetic already-existing unsupported association. Only our
        # app guard is paused during setup; all native mapping/validation/effects run.
        with patch.object(guard, "check_sales_dependencies"):
            so = frappe.get_doc({"doctype": "Sales Order", "company": selling_company, "customer": customer.name,
                "currency": "CNY", "conversion_rate": 1, "selling_price_list": price_list.name,
                "delivery_date": add_days(nowdate(), 1), "items": [{"item_code": self.item, "qty": 2, "rate": 20,
                    "delivery_date": add_days(nowdate(), 1)}]}).insert(set_name="QA-ATOMIC-SO-" + uuid.uuid4().hex[:16])
            po = make_inter_company_purchase_order(so.name)
            self.assertEqual(po.inter_company_order_reference, so.name)
            po.schedule_date = add_days(nowdate(), 1)
            for row in po.items:
                row.schedule_date = po.schedule_date
                row.sales_order = row.sales_order_item = row.sales_order_packed_item = None
            po.insert(set_name="QA-ATOMIC-PO-" + uuid.uuid4().hex[:16])
            so.inter_company_order_reference = po.name
            so.save()
            so.submit()
            po.reload().submit()
            self.commit_fixture()
        self.remember_effects()
        counts = {doctype: frappe.db.count(doctype) for doctype in self.types}
        try:
            po.cancel()
        except frappe.ValidationError as caught:
            self.assertEqual(caught.purchase_error_id, "sales_dependency_unsupported")
        else:
            self.assertEqual(frappe.db.get_value("Purchase Order", po.name, "docstatus"), 2)
            self.assertFalse(frappe.db.get_value("Sales Order", so.name, "inter_company_order_reference"))
            self.assertFalse(frappe.db.get_value("Purchase Order", po.name, "inter_company_order_reference"))
            self.fail("Native parent-only PO cancellation cleared the real Sales Order header without a Sales guard")
        self.assert_effects_unchanged()
        self.assertEqual({doctype: frappe.db.count(doctype) for doctype in self.types}, counts)

    def test_real_native_parent_only_intercompany_invoice_cancellation_fails_closed(self):
        from deeplinkerp_branding.services import purchase_consistency as guard
        from erpnext.accounts.doctype.sales_invoice.sales_invoice import make_inter_company_purchase_invoice
        selling_company, customer, supplier, price_list = self.internal_sales_parties()
        with patch.object(guard, "check_sales_dependencies"):
            po = self.order(supplier=supplier.name, qty=2, rate=20)
            si = frappe.get_doc({"doctype": "Sales Invoice", "company": selling_company, "customer": customer.name,
                "currency": "CNY", "conversion_rate": 1, "selling_price_list": price_list.name, "update_stock": 0,
                "items": [{"item_code": self.item, "qty": 2, "rate": 20}]}).insert(
                    set_name="QA-ATOMIC-SI-" + uuid.uuid4().hex[:16])
            pi = make_inter_company_purchase_invoice(si.name)
            self.assertEqual(pi.inter_company_invoice_reference, si.name)
            pi.items[0].purchase_order, pi.items[0].po_detail = po.name, po.items[0].name
            pi.items[0].sales_invoice_item = None
            pi.insert()
            si.inter_company_invoice_reference = pi.name
            si.save()
            si.submit()
            pi.submit()
            self.commit_fixture()
        self.remember_effects()
        counts = {doctype: frappe.db.count(doctype) for doctype in self.types}
        try:
            pi.cancel()
        except frappe.ValidationError as caught:
            self.assertEqual(caught.purchase_error_id, "sales_dependency_unsupported")
        else:
            self.assertEqual(frappe.db.get_value("Purchase Invoice", pi.name, "docstatus"), 2)
            self.assertFalse(frappe.db.get_value("Sales Invoice", si.name, "inter_company_invoice_reference"))
            self.assertFalse(frappe.db.get_value("Purchase Invoice", pi.name, "inter_company_invoice_reference"))
            self.fail("Native parent-only PI cancellation cleared the real Sales Invoice header without a Sales guard")
        self.assert_effects_unchanged()
        self.assertEqual({doctype: frappe.db.count(doctype) for doctype in self.types}, counts)

    def test_native_savedocs_queue_is_stopped_before_dispatch(self):
        from deeplinkerp_branding.services import purchase_consistency as guard
        from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry
        po = self.order()
        pr = self.receipt(po)
        pi = make_purchase_invoice(pr.name).insert()
        pi.submit()
        pe = get_payment_entry(pi.doctype, pi.name, bank_account="Cash - QAB", bank_amount=10).insert()
        self.commit_fixture()
        for document in (po, pi, pe):
            payload = document.as_dict()
            if document.doctype == "Purchase Invoice":
                for row in payload["items"]:
                    for field in ("purchase_order", "po_detail", "purchase_receipt", "pr_detail"):
                        row[field] = None
            elif document.doctype == "Payment Entry":
                payload["references"] = []
            with patch.object(frappe.get_meta(document.doctype), "queue_in_background", True), \
                    patch("frappe.utils.scheduler.is_scheduler_inactive", return_value=False), \
                    patch("frappe.desk.form.save.queue_submission", side_effect=AssertionError("No queue dispatch")):
                for key in (None, str(uuid.uuid4())):
                    with self.subTest(doctype=document.doctype, request_id=key), self.assertRaises(frappe.ValidationError) as caught:
                        guard.savedocs(json.dumps(payload, default=str), "Submit", request_id=key)
                    self.assertEqual(caught.exception.purchase_error_id, "native_background_submission_unsupported")
        self.assertEqual(frappe.db.get_value("Purchase Order", po.name, "docstatus"), 1)
        self.assertEqual(self.before["Submission Queue"], frappe.db.count("Submission Queue"))

    def unrelated_financial_documents(self):
        frappe.db.set_value("Item", self.item, "is_stock_item", 0)
        frappe.clear_document_cache("Item", self.item)
        pi = frappe.get_doc({"doctype": "Purchase Invoice", "company": COMPANY,
            "supplier": "QA Test Supplier", "currency": "CNY", "conversion_rate": 1, "update_stock": 0,
            "items": [{"item_code": self.item, "qty": 2, "rate": 20}]}).insert(
                set_name="QA-ATOMIC-PI-" + uuid.uuid4().hex[:16])
        pe = frappe.get_doc({"doctype": "Payment Entry", "company": COMPANY, "payment_type": "Receive",
            "party_type": "Customer", "party": "QA Purchase Payments Customer",
            "paid_from": frappe.get_cached_value("Company", COMPANY, "default_receivable_account"),
            "paid_to": "Cash - QAB", "paid_amount": 10, "received_amount": 10,
            "source_exchange_rate": 1, "target_exchange_rate": 1,
            "reference_no": "QA-UNRELATED", "reference_date": nowdate()}).insert()
        return pi, pe

    def test_unrelated_native_savedocs_preserves_real_submission_queue_with_or_without_key(self):
        from deeplinkerp_branding.services import purchase_consistency as guard
        from frappe.core.doctype.submission_queue.submission_queue import SubmissionQueue
        pi, pe = self.unrelated_financial_documents()
        self.commit_fixture("Purchase Invoice", "QA-ATOMIC-PI-")
        counts = {doctype: frappe.db.count(doctype) for doctype in self.types}
        for document in (pi, pe):
            self.assertFalse(guard.is_procurement(document))
            for key in (None, str(uuid.uuid4())):
                with self.subTest(doctype=document.doctype, request_id=key):
                    try:
                        with patch.object(frappe.get_meta(document.doctype), "queue_in_background", True), \
                                patch("frappe.utils.scheduler.is_scheduler_inactive", return_value=False), \
                                patch("frappe.desk.form.save.is_scheduler_inactive", return_value=False), \
                                patch.object(SubmissionQueue, "queue_action"):  # isolate external dispatch, not native queue insertion
                            guard.savedocs(json.dumps(document.as_dict(), default=str), "Submit", request_id=key)
                        queues = frappe.get_all("Submission Queue", filters={"ref_doctype": document.doctype,
                            "ref_docname": document.name}, fields=["name", "status"])
                        self.assertEqual(len(queues), 1)
                        self.assertEqual(queues[0].status, "Queued")
                        self.assertEqual(frappe.db.get_value(document.doctype, document.name, "docstatus"), 0)
                        self.assertEqual(frappe.db.count("Integration Request"), counts["Integration Request"])
                    finally:
                        frappe.db.rollback()
        self.assertEqual(counts, {doctype: frappe.db.count(doctype) for doctype in self.types})

    def test_unrelated_native_savedocs_and_cancel_keep_native_results_and_acl(self):
        from deeplinkerp_branding.services import purchase_consistency as guard
        from frappe import permissions
        native_permission = permissions.has_permission
        def denied_permission(doctype, ptype="read", *args, **kwargs):
            if doctype in ("Purchase Invoice", "Payment Entry") and ptype in ("write", "cancel"):
                return False
            return native_permission(doctype, ptype, *args, **kwargs)
        pi, pe = self.unrelated_financial_documents()
        self.commit_fixture("Purchase Invoice", "QA-ATOMIC-PI-")
        for document in (pi, pe):
            for key in (None, str(uuid.uuid4())):
                with self.subTest(doctype=document.doctype, action="Save", request_id=key):
                    payload = frappe.get_doc(document.doctype, document.name).as_dict()
                    payload["remarks"] = "QA unrelated native save " + str(key)
                    before = frappe.db.count("Integration Request")
                    with patch.object(permissions, "has_permission", side_effect=denied_permission), self.assertRaises(frappe.PermissionError):
                        guard.savedocs(json.dumps(payload, default=str), "Save", request_id=key)
                    self.assertEqual(frappe.db.count("Integration Request"), before)
                    guard.savedocs(json.dumps(payload, default=str), "Save", request_id=key)
                    self.assertEqual(frappe.response.docs[-1]["name"], document.name)
                    self.assertEqual(frappe.db.count("Integration Request"), before)
                    # Distinct real requests each commit their own successful
                    # native save. A later denied request's full rollback must
                    # not erase a previous uncommitted fixture mutation.
                    self.commit_fixture("Purchase Invoice", "QA-ATOMIC-PI-")
            document.reload().submit()
            self.commit_fixture("Purchase Invoice", "QA-ATOMIC-PI-")
        self.commit_fixture("Purchase Invoice", "QA-ATOMIC-PI-")
        for document in (pi, pe):
            for key in (None, str(uuid.uuid4())):
                with self.subTest(doctype=document.doctype, action="Cancel", request_id=key):
                    try:
                        before = frappe.db.count("Integration Request")
                        with patch.object(permissions, "has_permission", side_effect=denied_permission), self.assertRaises(frappe.PermissionError):
                            guard.cancel(document.doctype, document.name, request_id=key)
                        self.assertEqual(frappe.db.get_value(document.doctype, document.name, "docstatus"), 1)
                        self.assertEqual(frappe.db.count("Integration Request"), before)
                        guard.cancel(document.doctype, document.name, request_id=key)  # native cancel needs no supplied snapshot
                        self.assertEqual(frappe.response.docs[-1]["docstatus"], 2)
                        self.assertEqual(frappe.db.get_value(document.doctype, document.name, "docstatus"), 2)
                        self.assertEqual(frappe.db.count("Integration Request"), before)
                    finally:
                        frappe.db.rollback()

    def test_auto_invoice_rejects_real_purchase_user_without_invoice_create(self):
        po = self.order()
        user = "qa-atomic-" + uuid.uuid4().hex[:12] + "@example.invalid"
        frappe.get_doc({"doctype": "User", "email": user, "first_name": "Atomic QA", "send_welcome_email": 0,
            "roles": [{"role": "Purchase User"}]}).insert()
        self.commit_fixture()
        frappe.db.set_value("China Finance Settings", COMPANY, "auto_submit_purchase_invoice", 1)
        pr = make_purchase_receipt(po.name).insert()
        frappe.set_user(user)
        self.assertTrue(frappe.has_permission("Purchase Receipt", "submit", doc=pr))
        self.assertFalse(frappe.has_permission("Purchase Invoice", "create"))
        try:
            with self.assertRaises(frappe.PermissionError):
                pr.submit()
        finally:
            frappe.set_user("Administrator")
            frappe.clear_cache(user=user)
        self.assertFalse(frappe.db.exists("Purchase Receipt", pr.name))
        self.assertFalse(frappe.db.exists("Purchase Invoice Item", {"purchase_receipt": pr.name}))

    def test_auto_invoice_noop_cannot_acknowledge_receipt(self):
        from china_finance.services import auto_invoice
        po = self.order()
        self.commit_fixture()
        frappe.db.set_value("China Finance Settings", COMPANY, "auto_submit_purchase_invoice", 1)
        pr = make_purchase_receipt(po.name).insert()
        with patch.object(auto_invoice, "_create_and_submit", return_value=None):
            with self.assertRaisesRegex(frappe.ValidationError, "完整覆盖"):
                pr.submit()
        self.assertFalse(frappe.db.exists("Purchase Receipt", pr.name))

    def test_new_auto_invoice_requires_actual_document_submit_permission(self):
        from frappe import permissions
        po = self.order()
        user = "qa-atomic-" + uuid.uuid4().hex[:12] + "@example.invalid"
        frappe.get_doc({"doctype": "User", "email": user, "first_name": "Atomic QA", "send_welcome_email": 0,
            "roles": [{"role": "Purchase User"}, {"role": "Accounts User"}]}).insert()
        self.commit_fixture()
        frappe.db.set_value("China Finance Settings", COMPANY, "auto_submit_purchase_invoice", 1)
        pr = make_purchase_receipt(po.name).insert()
        original = permissions.has_controller_permissions
        def deny_mapped_invoice_submit(doc, ptype, **kwargs):
            if doc.doctype == "Purchase Invoice" and ptype == "submit" and any(
                    row.purchase_receipt == pr.name for row in doc.items):
                return False
            return original(doc, ptype, **kwargs)
        frappe.set_user(user)
        try:
            self.assertTrue(frappe.has_permission("Purchase Invoice", "create"))
            self.assertTrue(frappe.has_permission("Purchase Invoice", "submit"))
            with patch.object(permissions, "has_controller_permissions", side_effect=deny_mapped_invoice_submit):
                with self.assertRaises(frappe.PermissionError) as caught:
                    pr.submit()
            self.assertEqual(caught.exception.purchase_error_id, "auto_pi_permission_missing")
        finally:
            frappe.set_user("Administrator")
            frappe.clear_cache(user=user)
        self.assertFalse(frappe.db.exists("Purchase Receipt", pr.name))
        self.assertFalse(frappe.db.exists("Purchase Invoice Item", {"purchase_receipt": pr.name}))

    def test_partial_existing_auto_invoice_draft_is_preserved_on_failure(self):
        from frappe.client import save
        po = self.order()
        pr = make_purchase_receipt(po.name).insert()
        pi = frappe.get_doc({"doctype": "Purchase Invoice", "company": COMPANY, "supplier": pr.supplier,
            "currency": pr.currency, "conversion_rate": pr.conversion_rate, "bill_no": "QA-ATOMIC-MANUAL",
            "bill_date": add_days(nowdate(), -2), "items": [{"item_code": self.item, "qty": 1, "rate": po.items[0].rate,
                "purchase_order": po.name, "po_detail": po.items[0].name, "purchase_receipt": pr.name,
                "pr_detail": pr.items[0].name, "warehouse": "Stores - QAB"}]}).insert()
        self.commit_fixture()
        pi.remarks = "QA-ATOMIC-native draft PR reference"
        save(json.dumps(pi.as_dict(), default=str))  # real ordinary RPC draft succeeds
        self.commit_fixture()  # that successful request is committed independently
        with self.assertRaises(frappe.ValidationError):
            pi.reload().submit()  # no draft-source submit capability is granted
        self.assertEqual(frappe.db.get_value(pi.doctype, pi.name, "docstatus"), 0)
        self.assertEqual(frappe.db.get_value(pr.doctype, pr.name, "docstatus"), 0)
        before = pi.as_dict()
        frappe.db.set_value("China Finance Settings", COMPANY, "auto_submit_purchase_invoice", 1)
        with self.assertRaisesRegex(frappe.ValidationError, "完整覆盖"):
            pr.submit()
        pi.reload()
        self.assertEqual(pi.docstatus, 0)
        self.assertEqual((pi.items[0].qty, pi.items[0].rate, pi.bill_no, str(pi.bill_date), pi.taxes),
            (before["items"][0].qty, before["items"][0].rate, before["bill_no"], str(before["bill_date"]), []))
        self.assertEqual(frappe.db.get_value("Purchase Receipt", pr.name, "docstatus"), 0)
        self.assertEqual(frappe.db.count("Purchase Invoice Item", {"purchase_receipt": pr.name}), 1)

    def test_auto_invoice_success_records_all_native_and_finance_effects(self):
        from deeplinkerp_branding.services import purchase_document_actions as actions
        from deeplinkerp_branding.services import purchase_operation as kernel
        po = self.order()
        self.commit_fixture()
        frappe.db.set_value("China Finance Settings", COMPANY, "auto_submit_purchase_invoice", 1)
        key = str(uuid.uuid4())
        changes = {"items": [{"key": po.items[0].name, "qty": 2, "warehouse": "Stores - QAB"}]}
        target = frappe.db.get_value("Purchase Receipt Item", {"purchase_order": po.name, "docstatus": 0}, "parent")
        args = {"target_name": target, "expected_modified": frappe.db.get_value("Purchase Receipt", target, "modified")} if target else {}
        result = actions.record_receipt(po.name, changes, key, **args)
        self.assertFalse(result.get("failed"), result)
        pr = frappe.get_doc("Purchase Receipt", result["document"]["name"])
        pi = frappe.get_doc("Purchase Invoice", frappe.db.get_value("Purchase Invoice Item", {"purchase_receipt": pr.name}, "parent"))
        self.assertEqual(pi.docstatus, 1)
        self.assertEqual(pi.items[0].qty, 2)
        audit = frappe.get_doc("Integration Request", kernel.identity("Administrator", key))
        evidence = json.loads(audit.output)["artifacts"]
        self.assertTrue(any(row["doctype"] == "Purchase Invoice" and row["name"] == pi.name for row in evidence))
        finance = [row for row in evidence if row["doctype"] == "China Accounting Voucher"]
        self.assertEqual(len(finance), 2)
        self.assertTrue(all(row["system_effect"] for row in finance))
        replay = actions.record_receipt(po.name, changes, key, **args)
        self.assertTrue(replay["reused"])
        frappe.db.set_value("China Accounting Voucher", finance[0]["name"], "source_name", "QA-ATOMIC-TAMPER")
        with self.assertRaises(frappe.ValidationError):
            actions.record_receipt(po.name, changes, key, **args)

    def test_auto_invoice_respects_an_installed_native_workflow(self):
        from frappe.model.workflow import get_workflow_name
        po = self.order()
        self.commit_fixture()
        # Existing status column avoids fixture DDL/implicit commits.
        for state in ("Draft", "Submitted"):
            if not frappe.db.exists("Workflow State", state):
                frappe.get_doc({"doctype": "Workflow State", "workflow_state_name": state}).insert()
        action = "QA-ATOMIC-APPROVE-" + uuid.uuid4().hex[:10]
        frappe.get_doc({"doctype": "Workflow Action Master", "workflow_action_name": action}).insert()
        workflow = frappe.get_doc({"doctype": "Workflow", "workflow_name": "QA-ATOMIC-WORKFLOW-" + uuid.uuid4().hex[:10],
            "document_type": "Purchase Invoice", "is_active": 1, "workflow_state_field": "status", "states": [
                {"state": "Draft", "doc_status": "0", "allow_edit": "Accounts User"},
                {"state": "Submitted", "doc_status": "1", "allow_edit": "Accounts User"}],
            "transitions": [{"state": "Draft", "action": action, "next_state": "Submitted", "allowed": "Accounts User"}]}).insert()
        self.assertEqual(get_workflow_name("Purchase Invoice"), workflow.name)
        frappe.db.set_value("China Finance Settings", COMPANY, "auto_submit_purchase_invoice", 1)
        pr = make_purchase_receipt(po.name).insert()
        try:
            with self.assertRaisesRegex(frappe.ValidationError, "原生工作流"):
                pr.submit()
        finally:
            frappe.clear_cache(doctype="Purchase Invoice")
        self.assertFalse(frappe.db.exists("Purchase Receipt", pr.name))

    def test_replay_rejects_actual_revoked_automatic_invoice_submit_permission(self):
        from deeplinkerp_branding.services import purchase_document_actions as actions
        po = self.order()
        user = "qa-atomic-" + uuid.uuid4().hex[:12] + "@example.invalid"
        frappe.get_doc({"doctype": "User", "email": user, "first_name": "Atomic QA", "send_welcome_email": 0,
            "roles": [{"role": "Purchase User"}, {"role": "Accounts User"}]}).insert()
        self.commit_fixture()
        frappe.db.set_value("China Finance Settings", COMPANY, "auto_submit_purchase_invoice", 1)
        target = frappe.db.get_value("Purchase Receipt Item", {"purchase_order": po.name, "docstatus": 0}, "parent")
        args = {"target_name": target, "expected_modified": frappe.db.get_value("Purchase Receipt", target, "modified")} if target else {}
        key = str(uuid.uuid4())
        changes = {"items": [{"key": po.items[0].name, "qty": 2, "warehouse": "Stores - QAB"}]}
        frappe.set_user(user)
        try:
            result = actions.record_receipt(po.name, changes, key, **args)
            self.assertFalse(result.get("failed"), result)
            frappe.db.delete("Has Role", {"parent": user, "role": "Accounts User"})
            frappe.clear_cache(user=user)
            frappe.set_user("Administrator"); frappe.set_user(user)
            self.assertTrue(frappe.has_permission("Purchase Invoice", "read"))
            self.assertFalse(frappe.has_permission("Purchase Invoice", "submit"))
            with self.assertRaises(frappe.PermissionError):
                actions.record_receipt(po.name, changes, key, **args)
        finally:
            frappe.set_user("Administrator")
            frappe.clear_cache(user=user)

    def test_native_direct_stock_invoice_and_return_preserve_received_and_billed(self):
        from erpnext.buying.doctype.purchase_order.purchase_order import make_purchase_invoice as from_order
        from erpnext.controllers.sales_and_purchase_return import make_return_doc
        from deeplinkerp_branding.services import purchase_consistency as guard
        po = self.order()
        pi = from_order(po.name)
        pi.update_stock = 1
        pi.items[0].qty = 2
        pi.items[0].warehouse = "Stores - QAB"
        pi.insert(); pi.submit()
        guard.check_registered()
        self.assertEqual(frappe.db.get_value("Purchase Order Item", po.items[0].name, "received_qty"), 2)
        returned = make_return_doc("Purchase Invoice", pi.name)
        returned.update_billed_amount_in_purchase_order = 1
        returned.insert(); returned.submit()
        guard.check_registered()
        self.assertEqual(frappe.db.get_value("Purchase Order Item", po.items[0].name, "received_qty"), 0)
        self.assertEqual(frappe.db.get_value("Purchase Order Item", po.items[0].name, "billed_amt"), 0)

    def test_native_fx_invoice_and_payment_match_both_currency_ledgers(self):
        from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry
        from deeplinkerp_branding.services import purchase_consistency as guard
        account = frappe.get_doc({"doctype": "Account", "account_name": "QA-ATOMIC-USD-" + uuid.uuid4().hex[:10],
            "company": COMPANY, "parent_account": "Accounts Payable - QAB", "account_type": "Payable", "account_currency": "USD"}).insert()
        supplier = frappe.get_doc({"doctype": "Supplier", "supplier_name": "QA-ATOMIC-USD-" + uuid.uuid4().hex[:10],
            "supplier_type": "Company", "supplier_group": "All Supplier Groups", "default_currency": "USD",
            "accounts": [{"company": COMPANY, "account": account.name}]}).insert()
        po = self.order(currency="USD", conversion_rate=7.15, supplier=supplier.name)
        pr = self.receipt(po)
        pi = make_purchase_invoice(pr.name)
        pi.currency, pi.conversion_rate, pi.credit_to = "USD", 7.15, account.name
        pi.items[0].rate = 12.345
        pi.insert(); pi.submit()
        pe = get_payment_entry("Purchase Invoice", pi.name, bank_account="Cash - QAB")
        pe.reference_no, pe.reference_date = "QA-FX", nowdate()
        pe.insert(); pe.submit()
        guard.check_registered()
        self.assertEqual(pe.paid_from_account_currency, "CNY")
        self.assertEqual(pe.paid_to_account_currency, "USD")
        self.assertEqual(frappe.db.get_value("Purchase Invoice", pi.name, "outstanding_amount"), 0)

    def test_existing_no_update_return_then_new_invoice_uses_native_submitted_rows(self):
        from deeplinkerp_branding.services import purchase_consistency as guard
        from erpnext.accounts.doctype.purchase_invoice.purchase_invoice import make_debit_note
        po = self.order()
        pr = make_purchase_receipt(po.name).insert()
        pr.submit()
        first = make_purchase_invoice(pr.name)
        first.items[0].qty = 2
        first.insert().submit()
        original = first.grand_total
        returned = make_debit_note(first.name)
        returned.items[0].qty = -1
        returned.update_billed_amount_in_purchase_order = 0
        returned.update_billed_amount_in_purchase_receipt = 0
        returned.insert().submit()
        # These flags skip this return's updater, not the return in future sums.
        self.assertEqual(frappe.db.get_value("Purchase Order Item", po.items[0].name, "billed_amt"), original)
        self.assertEqual(frappe.db.get_value("Purchase Receipt Item", pr.items[0].name, "billed_amt"), original)
        self.commit_fixture()
        next_invoice = make_purchase_invoice(pr.name)
        next_invoice.items[0].qty = 1
        next_invoice.insert().submit()
        guard.check_registered()
        expected = first.items[0].amount + returned.items[0].amount + next_invoice.items[0].amount
        self.assertEqual(frappe.db.get_value("Purchase Order Item", po.items[0].name, "billed_amt"), expected)
        self.assertEqual(frappe.db.get_value("Purchase Receipt Item", pr.items[0].name, "billed_amt"), expected)
        from deeplinkerp_branding.services import purchase_reversal_scope as scope
        frappe.db.set_single_value("Buying Settings", "set_landed_cost_based_on_purchase_invoice_rate", 1)
        frappe.clear_document_cache("Buying Settings", "Buying Settings")
        try:
            result = self.read_reversal_scope(returned)
            self.assertEqual(result.vouchers, (scope.DocumentIdentity(returned.doctype, returned.name),))
            self.assertIn(scope.DocumentIdentity(pr.doctype, pr.name), result.sources)
        finally:
            frappe.db.set_single_value("Buying Settings", "set_landed_cost_based_on_purchase_invoice_rate", 0)
            frappe.clear_document_cache("Buying Settings", "Buying Settings")

    def test_native_invoice_rate_calculator_on_copy_cannot_write_or_repost(self):
        from deeplinkerp_branding.services import purchase_consistency as guard
        from erpnext.stock.doctype.purchase_receipt.purchase_receipt import PurchaseReceipt
        po = self.order()
        pr = self.receipt(po)
        pi = make_purchase_invoice(pr.name).insert()
        pi.submit()  # normal native rate path; no queued cost adjustment
        self.commit_fixture()
        frappe.db.set_single_value("Buying Settings", "set_landed_cost_based_on_purchase_invoice_rate", 1)
        frappe.clear_document_cache("Buying Settings", "Buying Settings")
        self.assertEqual(frappe.db.get_value("Purchase Receipt", pr.name, "per_billed"), 100)
        sql = frappe.db.sql
        def read_only(query, *args, **kwargs):
            self.assertNotIn(str(query).strip().split()[0].lower(), {"insert", "update", "delete", "replace", "alter"})
            return sql(query, *args, **kwargs)
        with patch.object(frappe.db, "sql", side_effect=read_only), \
                patch.object(frappe.db, "set_value", side_effect=AssertionError("No validation DB write")), \
                patch.object(frappe, "enqueue", side_effect=AssertionError("No validation queue")), \
                patch.object(PurchaseReceipt, "update_valuation_rate", side_effect=AssertionError("No validation valuation")), \
                patch.object(PurchaseReceipt, "repost_future_sle_and_gle", side_effect=AssertionError("No validation repost")):
            guard.check_billing(frappe.get_doc("Purchase Invoice", pi.name))
        frappe.db.rollback()
        frappe.clear_document_cache("Buying Settings", "Buying Settings")

    def future_receipts(self):
        po = self.order(transaction_date=add_days(nowdate(), -3))
        receipts = []
        for days in (-2, -1):
            pr = make_purchase_receipt(po.name)
            pr.items[0].qty = 2
            pr.set_posting_time = 1
            pr.posting_date, pr.posting_time = add_days(nowdate(), days), "12:00:00"
            pr.insert().submit()
            receipts.append(pr)
        self.commit_fixture()
        self.remember_effects()
        return po, *receipts

    def scope_item(self):
        code = "QA-ATOMIC-" + uuid.uuid4().hex[:10]
        return frappe.get_doc({"doctype": "Item", "item_code": code, "item_name": code,
            "item_group": "All Item Groups", "stock_uom": "Nos", "is_stock_item": 1}).insert().name

    def scope_stock_entry(self, purpose, date, rows, **headers):
        return frappe.get_doc({"doctype": "Stock Entry", "company": COMPANY, "stock_entry_type": purpose,
            "set_posting_time": 1, "posting_date": date, "posting_time": "12:00:00", "items": rows, **headers}).insert().submit()

    def read_reversal_scope(self, doc, *, cancellation=True):
        from deeplinkerp_branding.services import purchase_reversal_scope as scope
        sql = frappe.db.sql
        def read_only(query, *args, **kwargs):
            text = str(query).strip().lower()
            self.assertNotIn(text.split()[0], {"insert", "update", "delete", "replace", "alter"})
            self.assertNotIn("for update", text)
            return sql(query, *args, **kwargs)
        with patch.object(frappe.db, "sql", side_effect=read_only), \
                patch.object(frappe.db, "set_value", side_effect=AssertionError("scope cannot write")), \
                patch.object(frappe.db, "commit", side_effect=AssertionError("scope cannot commit")), \
                patch.object(frappe, "enqueue", side_effect=AssertionError("scope cannot enqueue")):
            return (scope.collect_cancellation_scope if cancellation else scope.collect_document_scope)(doc)

    def test_reversal_scope_native_transfer_repack_new_item_warehouse_full_set_is_read_only(self):
        from deeplinkerp_branding.services import purchase_reversal_scope as scope
        po = self.order(transaction_date=add_days(nowdate(), -4))
        root = make_purchase_receipt(po.name)
        root.items[0].qty = 2
        root.set_posting_time = 1
        root.posting_date, root.posting_time = add_days(nowdate(), -3), "12:00:00"
        root.insert().submit()
        warehouse2, warehouse3 = "Finished Goods - QAB", "Work In Progress - QAB"
        output, extra = self.scope_item(), self.scope_item()
        transfer = self.scope_stock_entry("Material Transfer", add_days(nowdate(), -2), [
            {"item_code": self.item, "qty": 1, "s_warehouse": "Stores - QAB", "t_warehouse": warehouse2}])
        repack = self.scope_stock_entry("Repack", add_days(nowdate(), -1), [
            {"item_code": self.item, "qty": 1, "s_warehouse": warehouse2},
            {"item_code": output, "qty": 1, "t_warehouse": warehouse2, "is_finished_item": 1,
                "set_basic_rate_manually": 1, "basic_rate": 6},
            {"item_code": extra, "qty": 1, "t_warehouse": warehouse3, "set_basic_rate_manually": 1, "basic_rate": 6}])
        repack_sles = frappe.db.get_values("Stock Ledger Entry", {"voucher_type": repack.doctype, "voucher_no": repack.name},
            ["item_code", "warehouse", "dependant_sle_voucher_detail_no", "actual_qty"], as_dict=True)
        self.assertTrue(any(row.dependant_sle_voucher_detail_no for row in repack_sles), repack_sles)
        future = self.scope_stock_entry("Material Issue", nowdate(), [
            {"item_code": extra, "qty": 1, "s_warehouse": warehouse3}])
        self.commit_fixture()
        self.remember_effects()
        before = {dt: frappe.db.count(dt) for dt in self.types}
        result = self.read_reversal_scope(root)
        self.assertEqual(result.company, COMPANY)
        self.assertEqual(set(result.sources), {scope.DocumentIdentity("Purchase Order", po.name)})
        self.assertEqual(set(result.vouchers), {scope.DocumentIdentity(doc.doctype, doc.name)
            for doc in (root, transfer, repack, future)})
        self.assertEqual(set(result.pairs), {scope.StockPair(self.item, "Stores - QAB"),
            scope.StockPair(self.item, warehouse2), scope.StockPair(output, warehouse2), scope.StockPair(extra, warehouse3)})
        self.assertEqual(before, {dt: frappe.db.count(dt) for dt in self.types})
        self.assert_effects_unchanged()

    def test_reversal_document_first_stock_draft_needs_no_bin_but_freeze_refuses_missing_bin(self):
        from deeplinkerp_branding.services import purchase_reversal_scope as scope
        draft = frappe.get_doc({"doctype": "Purchase Receipt", "company": COMPANY, "supplier": "QA Test Supplier",
            "posting_date": nowdate(), "posting_time": "12:00:00", "items": [{"item_code": self.item,
                "stock_uom": "Nos", "qty": 1, "warehouse": "Stores - QAB"}]})
        self.assertFalse(frappe.db.exists("Bin", {"item_code": self.item, "warehouse": "Stores - QAB"}))
        result = scope.collect_document_scope(draft)
        self.assertEqual(result.pairs, (scope.StockPair(self.item, "Stores - QAB"),))
        po = self.order()
        root = self.receipt(po)
        frappe.db.delete("Bin", {"item_code": self.item, "warehouse": "Stores - QAB"})
        with self.assertRaises(frappe.ValidationError):
            scope.collect_cancellation_scope(root)

    def test_reversal_scope_native_same_item_warehouse_is_bound_to_exact_receipt_detail(self):
        from deeplinkerp_branding.services import purchase_reversal_scope as scope
        warehouses = ("Stores - QAB", "Work In Progress - QAB")
        po = self.order(items=[{"item_code": self.item, "qty": 1, "rate": 10, "warehouse": warehouse,
            "schedule_date": add_days(nowdate(), 1)} for warehouse in warehouses])
        root = make_purchase_receipt(po.name).insert().submit()
        self.commit_fixture()
        self.remember_effects()
        result = self.read_reversal_scope(root)
        self.assertEqual(set(result.pairs), {scope.StockPair(self.item, warehouse) for warehouse in warehouses})
        entry = frappe.db.get_value("Stock Ledger Entry", {"voucher_type": root.doctype, "voucher_no": root.name,
            "voucher_detail_no": root.items[0].name}, "name")
        self.assertTrue(entry)
        original = frappe.db.get_value("Stock Ledger Entry", entry, "warehouse")
        try:
            other = next(warehouse for warehouse in warehouses if warehouse != original)
            frappe.db.set_value("Stock Ledger Entry", entry, "warehouse", other, update_modified=False)
            with self.assertRaises(frappe.ValidationError): self.read_reversal_scope(root)
        finally:
            frappe.db.set_value("Stock Ledger Entry", entry, "warehouse", original, update_modified=False)
        self.assert_effects_unchanged()

    def test_reversal_scope_native_gl_cartesian_whole_voucher_does_not_seed_extra_stock_frontier(self):
        from deeplinkerp_branding.services import purchase_reversal_scope as scope
        second, extra = self.scope_item(), self.scope_item()
        warehouse2, warehouse3 = "Finished Goods - QAB", "Work In Progress - QAB"
        po = self.order(transaction_date=add_days(nowdate(), -4), items=[
            {"item_code": code, "qty": 2, "rate": 10, "warehouse": warehouse, "schedule_date": add_days(nowdate(), 1)}
            for code, warehouse in ((self.item, "Stores - QAB"), (second, warehouse2))])
        root = make_purchase_receipt(po.name)
        root.set_posting_time = 1
        root.posting_date, root.posting_time = add_days(nowdate(), -3), "12:00:00"
        root.insert().submit()
        cross = self.scope_stock_entry("Material Receipt", add_days(nowdate(), -2), [
            {"item_code": self.item, "qty": 1, "t_warehouse": warehouse2, "basic_rate": 10},
            {"item_code": extra, "qty": 1, "t_warehouse": warehouse3, "basic_rate": 10}])
        future = self.scope_stock_entry("Material Issue", add_days(nowdate(), -1), [
            {"item_code": extra, "qty": 1, "s_warehouse": warehouse3}])
        self.commit_fixture()
        self.remember_effects()
        result = scope.collect_cancellation_scope(root)
        self.assertEqual(set(result.vouchers), {scope.DocumentIdentity(root.doctype, root.name),
            scope.DocumentIdentity(cross.doctype, cross.name)})
        self.assertNotIn(scope.DocumentIdentity(future.doctype, future.name), result.vouchers)
        self.assertEqual(set(result.pairs), {scope.StockPair(self.item, "Stores - QAB"),
            scope.StockPair(second, warehouse2), scope.StockPair(self.item, warehouse2), scope.StockPair(extra, warehouse3)})
        self.assertNotIn(scope.StockPair(second, "Stores - QAB"), result.pairs)
        self.assert_effects_unchanged()

    def test_reversal_scope_native_billing_receipts_and_cancelled_raw_seed(self):
        from deeplinkerp_branding.services import purchase_reversal_scope as scope
        po, prior, future = self.future_receipts()
        invoice = frappe.get_doc({"doctype": "Purchase Invoice", "company": COMPANY, "supplier": po.supplier,
            "posting_date": nowdate(), "items": [{"item_code": self.item, "qty": 1, "rate": 10, "stock_uom": "Nos",
                "purchase_order": po.name, "po_detail": po.items[0].name} ]})
        result = scope.collect_document_scope(invoice)
        self.assertEqual(set(result.sources), {scope.DocumentIdentity(doc.doctype, doc.name) for doc in (po, prior, future)})
        frappe.db.set_value("Stock Ledger Entry", {"voucher_type": prior.doctype, "voucher_no": prior.name}, "is_cancelled", 1)
        result = scope.collect_cancellation_scope(prior)
        self.assertEqual(set(result.vouchers), {scope.DocumentIdentity(doc.doctype, doc.name) for doc in (prior, future)})
        self.assertEqual(result.pairs, (scope.StockPair(self.item, "Stores - QAB"),))

    def test_reversal_scope_resolves_native_material_request_and_persists_no_business_effect(self):
        from deeplinkerp_branding.services import purchase_reversal_scope as scope
        from erpnext.stock.doctype.material_request.material_request import make_purchase_order
        request = frappe.get_doc({"doctype": "Material Request", "company": COMPANY, "material_request_type": "Purchase",
            "transaction_date": nowdate(), "schedule_date": add_days(nowdate(), 1), "items": [{"item_code": self.item,
                "qty": 2, "warehouse": "Stores - QAB", "schedule_date": add_days(nowdate(), 1)}]}).insert().submit()
        order = make_purchase_order(request.name)
        order.supplier = "QA Test Supplier"
        order.insert(set_name="QA-ATOMIC-PO-" + uuid.uuid4().hex[:16]).submit()
        result = scope.collect_document_scope(order)
        self.assertEqual(result.sources, (scope.DocumentIdentity("Material Request", request.name),))
        self.assertEqual(result.pairs, (scope.StockPair(self.item, "Stores - QAB"),))
        self.assertEqual(result.vouchers, ())
        frappe.db.set_value("Material Request", request.name, "custom_request_source", "MES")
        with self.assertRaises(frappe.ValidationError): scope.collect_document_scope(order)

    def test_reversal_scope_native_stock_entry_direct_transit_mr_and_old_supply_sources(self):
        from deeplinkerp_branding.services import purchase_reversal_scope as scope
        po, prior, future = self.future_receipts()
        request = frappe.get_doc({"doctype": "Material Request", "company": COMPANY, "material_request_type": "Material Transfer",
            "transaction_date": nowdate(), "schedule_date": nowdate(), "items": [{"item_code": self.item, "qty": 1,
                "from_warehouse": "Stores - QAB", "warehouse": "Work In Progress - QAB", "schedule_date": nowdate()}]}).insert().submit()
        outgoing = self.scope_stock_entry("Material Transfer", nowdate(), [{"item_code": self.item, "qty": 1,
            "s_warehouse": "Stores - QAB", "t_warehouse": "Goods In Transit - QAB",
            "material_request": request.name, "material_request_item": request.items[0].name}], add_to_transit=1)
        self.assertEqual(self.read_reversal_scope(outgoing, cancellation=False).sources,
            (scope.DocumentIdentity(request.doctype, request.name),))
        incoming = self.scope_stock_entry("Material Transfer", nowdate(), [{"item_code": self.item, "qty": 1,
            "s_warehouse": "Goods In Transit - QAB", "t_warehouse": "Work In Progress - QAB",
            "against_stock_entry": outgoing.name, "ste_detail": outgoing.items[0].name}], outgoing_stock_entry=outgoing.name)
        result = self.read_reversal_scope(incoming, cancellation=False)
        self.assertEqual(set(result.sources), {scope.DocumentIdentity(doc.doctype, doc.name) for doc in (request, outgoing)})
        self.assertIn(scope.StockPair(self.item, "Work In Progress - QAB"), result.pairs)
        frappe.db.set_value("Material Request", request.name, "custom_request_source", "MES")
        with self.assertRaises(frappe.ValidationError): self.read_reversal_scope(incoming, cancellation=False)
        frappe.db.set_value("Material Request", request.name, "custom_request_source", "手动创建")
        finished = self.scope_item()
        order = self.order(items=[{"item_code": finished, "qty": 10, "rate": 10, "warehouse": "Stores - QAB", "schedule_date": nowdate()}])
        # Exact new synthetic old-PO source records; no historical PO/BOM repair.
        frappe.db.set_value("Purchase Order", order.name, {"is_subcontracted": 1, "is_old_subcontracting_flow": 1})
        supplied = frappe.get_doc({"doctype": "Purchase Order Item Supplied", "parent": order.name, "parenttype": "Purchase Order",
            "parentfield": "supplied_items", "rm_item_code": self.item, "main_item_code": finished,
            "docstatus": 1, "stock_uom": "Nos", "reserve_warehouse": "Work In Progress - QAB", "required_qty": 10, "idx": 1})
        self.assertTrue(frappe.get_meta(supplied.doctype).has_field("stock_uom"))
        self.assertFalse(frappe.get_meta(supplied.doctype).has_field("uom"))
        supplied.db_insert()
        sent = self.scope_stock_entry("Send to Subcontractor", nowdate(), [{"item_code": self.item, "qty": 1,
            "s_warehouse": "Stores - QAB", "t_warehouse": "Finished Goods - QAB", "po_detail": supplied.name,
            "subcontracted_item": finished}], purchase_order=order.name, supplier=order.supplier)
        result = self.read_reversal_scope(sent, cancellation=False)
        self.assertEqual(result.sources, (scope.DocumentIdentity(order.doctype, order.name),))
        self.assertIn(scope.StockPair(self.item, "Work In Progress - QAB"), result.pairs)
        frappe.db.set_value(supplied.doctype, supplied.name, "stock_uom", "Kg", update_modified=False)
        with self.assertRaises(frappe.ValidationError): self.read_reversal_scope(sent, cancellation=False)
        frappe.db.set_value(supplied.doctype, supplied.name, "stock_uom", "Nos", update_modified=False)

    def test_reversal_scope_native_invoice_cost_setting_direct_and_fifo_potential_seeds(self):
        from deeplinkerp_branding.services import purchase_reversal_scope as scope
        from erpnext.buying.doctype.purchase_order.purchase_order import make_purchase_invoice as from_order
        po, prior, future = self.future_receipts()
        invoice = make_purchase_invoice(prior.name)
        invoice.items[0].qty = 1
        invoice.insert().submit()
        fifo = from_order(po.name)
        fifo.items[0].qty = 1
        fifo.insert().submit()
        stock = from_order(po.name)
        stock.update_stock = 1; stock.items[0].qty = 1; stock.items[0].warehouse = "Stores - QAB"
        stock.insert().submit()
        self.commit_fixture()
        self.remember_effects()
        for enabled in (0, 1):
            frappe.db.set_single_value("Buying Settings", "set_landed_cost_based_on_purchase_invoice_rate", enabled)
            frappe.clear_document_cache("Buying Settings", "Buying Settings")
            for root in (invoice, fifo, stock):
                with self.subTest(enabled=enabled, update_stock=root.update_stock, direct=bool(root.items[0].pr_detail)):
                    result = self.read_reversal_scope(root)
                    expected = {scope.DocumentIdentity(root.doctype, root.name)}
                    if enabled:
                        expected |= {scope.DocumentIdentity(doc.doctype, doc.name) for doc in (prior, future, stock)}
                        self.assertEqual(result.posting_datetime, str(prior.posting_date) + " " + str(prior.posting_time))
                    self.assertEqual(set(result.vouchers), expected)
        # Real native cancellation invokes the PR force-repost path and the
        # strict floor rejects it atomically; never run its native executor.
        from erpnext.stock.doctype.purchase_receipt.purchase_receipt import PurchaseReceipt
        native = PurchaseReceipt.repost_future_sle_and_gle
        with patch.object(PurchaseReceipt, "repost_future_sle_and_gle", autospec=True, side_effect=native) as repost:
            with self.assertRaises(frappe.ValidationError) as caught: invoice.reload().cancel()
        self.assertEqual(caught.exception.purchase_error_id, "native_stock_repost_incomplete")
        self.assertTrue(any(call.kwargs.get("force") for call in repost.call_args_list))
        self.assert_effects_unchanged()

    def remember_effects(self):
        from deeplinkerp_branding.services import purchase_consistency as guard
        self.fixture_effects = {(doctype, name): guard.artifact_evidence(frappe.get_doc(doctype, name))
            for doctype in ("Purchase Order", "Purchase Receipt", "Purchase Invoice", "Payment Entry", "China Accounting Voucher", "Integration Request", "Repost Item Valuation", "Delivery Note", "Sales Order", "Sales Invoice", "Stock Entry")
            for name in self.committed_names[doctype]}

    def assert_effects_unchanged(self):
        from deeplinkerp_branding.services import purchase_consistency as guard
        for identity, evidence in self.fixture_effects.items():
            self.assertEqual(guard.artifact_evidence(frappe.get_doc(*identity)), evidence, str(identity))

    def test_pending_native_repost_with_future_sle_refuses_receipt_cancellation(self):
        po, prior, future = self.future_receipts()
        frappe.flags.dont_execute_stock_reposts = True  # native production-equivalent RIV.on_submit branch
        try:
            with self.assertRaises(frappe.ValidationError) as caught:
                prior.cancel()
            self.assertEqual(caught.exception.purchase_error_id, "native_stock_repost_incomplete")
        finally:
            frappe.flags.dont_execute_stock_reposts = False
        self.assertEqual(frappe.db.get_value("Purchase Receipt", prior.name, "docstatus"), 1)
        self.assertEqual(frappe.db.get_value("Bin", {"item_code": self.item, "warehouse": "Stores - QAB"}, "actual_qty"), 4)
        self.assertEqual(self.before["Repost Item Valuation"], frappe.db.count("Repost Item Valuation"))
        self.assert_effects_unchanged()

    def test_pending_native_repost_refuses_invoice_rate_cost_adjustment(self):
        po, prior, future = self.future_receipts()
        frappe.db.set_single_value("Buying Settings", "set_landed_cost_based_on_purchase_invoice_rate", 1)
        frappe.db.set_single_value("Buying Settings", "maintain_same_rate", 0)
        frappe.clear_document_cache("Buying Settings", "Buying Settings")
        pi = make_purchase_invoice(prior.name)
        pi.items[0].rate -= 1
        pi.insert()
        frappe.flags.dont_execute_stock_reposts = True
        try:
            with self.assertRaises(frappe.ValidationError) as caught:
                pi.submit()
            self.assertEqual(caught.exception.purchase_error_id, "native_stock_repost_incomplete")
        finally:
            frappe.flags.dont_execute_stock_reposts = False
            frappe.clear_document_cache("Buying Settings", "Buying Settings")
        self.assertFalse(frappe.db.exists("Purchase Invoice", pi.name))
        self.assertEqual(frappe.db.get_value("Purchase Receipt", prior.name, "per_billed"), 0)
        self.assertEqual(self.before["Repost Item Valuation"], frappe.db.count("Repost Item Valuation"))
        self.assert_effects_unchanged()

    def test_existing_item_based_repost_blocks_forward_invoice_without_history_changes(self):
        po, prior, future = self.future_receipts()
        repost = frappe.get_doc({"doctype": "Repost Item Valuation", "based_on": "Item and Warehouse",
            "company": COMPANY, "item_code": self.item, "warehouse": "Stores - QAB",
            "posting_date": prior.posting_date, "posting_time": prior.posting_time})
        repost.flags.dont_run_in_test = True
        repost.insert().submit()  # synthetic historical pending task, outside a procurement operation
        self.assertEqual(repost.status, "Queued")
        for status in ("Queued", "Skipped"):
            with self.subTest(status=status):
                frappe.db.set_value(repost.doctype, repost.name, "status", status)
                self.commit_fixture()
                self.remember_effects()
                pi = make_purchase_invoice(prior.name).insert()
                with self.assertRaises(frappe.ValidationError) as caught:
                    pi.submit()
                self.assertEqual(caught.exception.purchase_error_id, "native_stock_repost_pending")
                self.assertFalse(frappe.db.exists("Purchase Invoice", pi.name))
                self.assertEqual(frappe.db.get_value(repost.doctype, repost.name, "status"), status)
                self.assert_effects_unchanged()

    def test_native_po_advance_ledger_submit_cancel_and_corruption(self):
        from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry
        from deeplinkerp_branding.services import purchase_consistency as guard
        from frappe.client import cancel
        po = self.order()
        self.commit_fixture()
        account = frappe.get_doc({"doctype": "Account", "account_name": "QA-ATOMIC-ADVANCE-" + uuid.uuid4().hex[:10],
            "company": COMPANY, "parent_account": "Current Assets - QAB", "account_type": "Payable", "account_currency": "CNY"}).insert()
        frappe.db.set_value("Company", COMPANY, {"book_advance_payments_in_separate_party_account": 1,
            "default_advance_paid_account": account.name})
        frappe.clear_document_cache("Company", COMPANY)
        pe = get_payment_entry("Purchase Order", po.name, bank_account="Cash - QAB", bank_amount=10)
        pe.paid_amount = pe.received_amount = 10
        pe.references[0].allocated_amount = 10
        pe.reference_no, pe.reference_date = "QA-ADVANCE", nowdate()
        pe.insert(); pe.submit()
        guard.check_registered()
        self.assertEqual(frappe.db.get_value("Purchase Order", po.name, "advance_paid"), 10)
        cancel(pe.doctype, pe.name)
        guard.check_registered()
        self.assertEqual(frappe.db.get_value("Purchase Order", po.name, "advance_paid"), 0)
        other = get_payment_entry("Purchase Order", po.name, bank_account="Cash - QAB", bank_amount=10)
        other.paid_amount = other.received_amount = 10
        other.references[0].allocated_amount = 10
        other.reference_no, other.reference_date = "QA-ADVANCE-CORRUPT", nowdate()
        other.insert()
        native = guard.check_document
        def corrupt(doc):
            if doc.doctype == "Payment Entry" and doc.docstatus == 1:
                frappe.db.set_value("Purchase Order", po.name, "advance_paid", 999)
            return native(doc)
        try:
            with patch.object(guard, "check_document", side_effect=corrupt), self.assertRaises(frappe.ValidationError):
                other.submit()
        finally:
            frappe.clear_document_cache("Company", COMPANY)
        self.assertEqual(frappe.db.get_value("Purchase Order", po.name, "advance_paid"), 0)

    def test_mutable_cancellation_preserves_original_and_reverse_payment_ledgers(self):
        from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry
        from deeplinkerp_branding.services import purchase_consistency as guard
        from frappe.client import cancel
        for ledger in ("Payment Ledger Entry", "Advance Payment Ledger Entry"):
            for target in ("original", "reverse"):
                with self.subTest(ledger=ledger, target=target):
                    if not frappe.db.exists("Item", self.item):
                        frappe.get_doc({"doctype": "Item", "item_code": self.item, "item_name": self.item,
                            "item_group": "All Item Groups", "stock_uom": "Nos", "is_stock_item": 1}).insert()
                    po = self.order()
                    account = frappe.get_doc({"doctype": "Account", "account_name": "QA-ATOMIC-ADVANCE-" + uuid.uuid4().hex[:10],
                        "company": COMPANY, "parent_account": "Current Assets - QAB", "account_type": "Payable", "account_currency": "CNY"}).insert()
                    frappe.db.set_value("Company", COMPANY, {"book_advance_payments_in_separate_party_account": 1,
                        "default_advance_paid_account": account.name})
                    frappe.clear_document_cache("Company", COMPANY)
                    pe = get_payment_entry("Purchase Order", po.name, bank_account="Cash - QAB", bank_amount=10)
                    pe.paid_amount = pe.received_amount = pe.references[0].allocated_amount = 10
                    pe.reference_no, pe.reference_date = "QA-ADVANCE-INTEGRITY", nowdate()
                    pe.insert(); pe.submit()
                    originals = set(frappe.get_all(ledger, filters={"voucher_type": pe.doctype, "voucher_no": pe.name}, pluck="name"))
                    self.assertTrue(originals)
                    native = guard.check_cancelled_ledgers
                    def corrupt(doc):
                        if (doc.doctype, doc.name) == (pe.doctype, pe.name):
                            rows = frappe.get_all(ledger, filters={"voucher_type": pe.doctype, "voucher_no": pe.name}, pluck="name")
                            selected = next(name for name in rows if (name in originals) == (target == "original"))
                            frappe.db.set_value(ledger, selected, "amount", 999, update_modified=False)
                        return native(doc)
                    try:
                        with patch.object(guard, "check_cancelled_ledgers", side_effect=corrupt), self.assertRaises(frappe.ValidationError):
                            cancel(pe.doctype, pe.name)
                    finally:
                        frappe.db.rollback()
                        frappe.clear_document_cache("Company", COMPANY)
                    self.assertEqual(self.before, {doctype: frappe.db.count(doctype) for doctype in self.types})
    def test_keyed_native_cancel_retransmission_keeps_one_reversal(self):
        from deeplinkerp_branding.services import purchase_consistency as guard
        po = self.order()
        pr = self.receipt(po)
        pi = make_purchase_invoice(pr.name).insert()
        pi.submit()
        payload, key = json.dumps(pi.as_dict(), default=str), str(uuid.uuid4())
        frappe.response.docs = []
        guard.cancel(pi.doctype, pi.name, request_id=key, doc=payload)
        frappe.response.docs = []
        guard.cancel(pi.doctype, pi.name, request_id=key, doc=payload)
        self.assertEqual(frappe.response.docs[-1]["docstatus"], 2)
        self.assertEqual(frappe.db.count("China Accounting Voucher", {"source_doctype": pi.doctype,
            "source_name": pi.name, "source_event": "Cancellation"}), 1)

    def test_native_savedocs_retransmission_binds_complete_payload(self):
        from deeplinkerp_branding.services import purchase_consistency as guard
        from frappe.handler import execute_cmd
        from werkzeug.test import EnvironBuilder
        from werkzeug.wrappers import Request
        payload = {"doctype": "Purchase Order", "name": "new-purchase-order-" + uuid.uuid4().hex,
            "__islocal": 1, "company": COMPANY, "supplier": "QA Test Supplier", "currency": "CNY",
            "schedule_date": add_days(nowdate(), 1), "items": [{"doctype": "Purchase Order Item", "item_code": self.item,
                "qty": 2, "rate": 12.345, "warehouse": "Stores - QAB", "schedule_date": add_days(nowdate(), 1)}]}
        self.assertTrue(callable(getattr(guard, "savedocs", None)), "Native savedocs stable request bridge missing")
        key = str(uuid.uuid4())
        self.assertEqual(frappe.override_whitelisted_method("frappe.desk.form.save.savedocs"),
            "deeplinkerp_branding.services.purchase_consistency.savedocs")
        def endpoint(value):
            with patch.object(frappe, "form_dict", frappe._dict(doc=json.dumps(value), action="Save", request_id=key)), \
                    patch.object(frappe.local, "request", Request(EnvironBuilder(method="POST",
                        path="/api/method/frappe.desk.form.save.savedocs", base_url="http://" + SITE).get_environ()), create=True):
                return execute_cmd("frappe.desk.form.save.savedocs")
        frappe.response.docs = []
        self.assertIsNone(endpoint(payload))
        first = frappe.response.docs[-1]
        frappe.response.docs = []  # discard the first response, as a client network loss would
        self.assertIsNone(endpoint(payload))
        self.assertEqual(frappe.response.docs[-1]["name"], first["name"])
        self.assertEqual(frappe.response.docs[-1]["localname"], payload["name"])
        self.assertEqual(frappe.db.count("Purchase Order Item", {"item_code": self.item}), 1)
        changed = json.loads(json.dumps(payload))
        changed["items"][0]["rate"] += 1
        with self.assertRaises(frappe.ValidationError):
            endpoint(changed)

    def test_actual_system_rounding_policy_is_used_by_quantity_guard(self):
        from deeplinkerp_branding.services import purchase_consistency as guard
        from frappe.utils import flt
        from frappe.core.doctype.system_settings.system_settings import clear_system_settings_cache
        try:
            frappe.db.set_single_value("System Settings", {"rounding_method": "Banker's Rounding", "float_precision": "3"})
            clear_system_settings_cache()
            frappe.clear_document_cache("System Settings", "System Settings")
            self.assertEqual(frappe.get_system_settings("rounding_method"), "Banker's Rounding")
            # Real client-local RLock holds background Redis invalidations. A
            # document-cache-only fixture can read the previous rounding policy.
            with frappe.client_cache.lock:
                for policy, expected in (("Banker's Rounding", .002), ("Commercial Rounding", .003)):
                    with self.subTest(policy=policy):
                        frappe.db.set_single_value("System Settings", {"rounding_method": policy, "float_precision": "3"})
                        clear_system_settings_cache()
                        frappe.clear_document_cache("System Settings", "System Settings")
                        row = frappe.new_doc("Purchase Order Item")
                        self.assertEqual(row.precision("qty"), 3)
                        self.assertEqual(flt(.0025, 3), expected)
                        guard.equal(row, "qty", .0025, expected, "实际系统舍入")
        finally:
            frappe.db.rollback()
            clear_system_settings_cache()
            frappe.clear_document_cache("System Settings", "System Settings")

    def test_identical_new_native_docs_with_distinct_requests_both_insert(self):
        from deeplinkerp_branding.services import purchase_consistency as guard
        self.assertTrue(callable(getattr(guard, "savedocs", None)), "Native savedocs stable request bridge missing")
        payload = {"doctype": "Purchase Order", "name": "new-purchase-order-" + uuid.uuid4().hex,
            "__islocal": 1, "company": COMPANY, "supplier": "QA Test Supplier", "currency": "CNY",
            "schedule_date": add_days(nowdate(), 1), "items": [{"doctype": "Purchase Order Item", "item_code": self.item,
                "qty": 2, "rate": 12.345, "warehouse": "Stores - QAB", "schedule_date": add_days(nowdate(), 1)}]}
        for _ in range(2):
            frappe.response.docs = []
            guard.savedocs(json.dumps(payload), "Save", request_id=str(uuid.uuid4()))
        self.assertEqual(frappe.db.count("Purchase Order Item", {"item_code": self.item}), 2)

    def test_missing_own_payment_ledger_cannot_hide_behind_restored_invoice_balance(self):
        from deeplinkerp_branding.services import purchase_document_actions as actions
        from deeplinkerp_branding.services import purchase_consistency as guard
        po = self.order()
        pr = self.receipt(po)
        pi = make_purchase_invoice(pr.name).insert()
        pi.submit()
        self.commit_fixture()
        original = guard.check_document

        def lose_payment_ledger(doc):
            if doc.doctype == "Payment Entry" and doc.docstatus == 1:
                frappe.db.delete("Payment Ledger Entry", {"voucher_type": doc.doctype, "voucher_no": doc.name})
                frappe.db.set_value("Purchase Invoice", pi.name, "outstanding_amount", pi.grand_total)
            return original(doc)

        with patch.object(guard, "check_document", side_effect=lose_payment_ledger):
            result = actions.record_payment(source_doctype="Purchase Receipt", source_name=pr.name,
                purchase_invoice=pi.name, amount_to_pay=10, bank_account="Cash - QAB", request_id=str(uuid.uuid4()))
        self.assertTrue(result.get("failed"), "Missing PE's own PLE must roll back even when PI and its remaining PLE agree")
        self.assertEqual(frappe.db.get_value("Purchase Invoice", pi.name, "outstanding_amount"), pi.grand_total)

    def test_native_billed_row_and_percent_corruption_roll_back_invoice(self):
        from deeplinkerp_branding.services import purchase_consistency as guard
        for doctype, field in (("Purchase Order Item", "billed_amt"), ("Purchase Receipt Item", "billed_amt"),
                ("Purchase Order", "per_billed"), ("Purchase Receipt", "per_billed")):
            with self.subTest(doctype=doctype, field=field):
                po = self.order()
                pr = self.receipt(po)
                original = guard.check_document
                def corrupt(doc):
                    if doc.doctype == "Purchase Invoice" and doc.docstatus == 1:
                        target = po.items[0].name if doctype == "Purchase Order Item" else pr.items[0].name if doctype == "Purchase Receipt Item" else po.name if doctype == "Purchase Order" else pr.name
                        frappe.db.set_value(doctype, target, field, 999)
                    return original(doc)
                with patch.object(guard, "check_document", side_effect=corrupt):
                    pi = make_purchase_invoice(pr.name).insert()
                    with self.assertRaises(frappe.ValidationError):
                        pi.submit()
                self.assertFalse(frappe.db.exists("Purchase Invoice", pi.name))
                # A failed uncommitted synthetic operation rolls back its fixture too.
                frappe.get_doc({"doctype": "Item", "item_code": self.item, "item_name": self.item,
                    "item_group": "All Item Groups", "stock_uom": "Nos", "is_stock_item": 1}).insert()

    def test_immutable_native_cancellation_reverses_gl_and_finance(self):
        from deeplinkerp_branding.services import purchase_consistency as guard
        from frappe.client import cancel
        po = self.order(transaction_date=add_days(nowdate(), -1))
        pr = self.receipt(po)
        pi = make_purchase_invoice(pr.name).insert()
        pi.set_posting_time = 1
        pi.posting_date = add_days(nowdate(), -1)
        pi.save()
        pi.submit()
        self.commit_fixture()
        frappe.db.set_single_value("Accounts Settings", "enable_immutable_ledger", 1)
        frappe.clear_document_cache("Accounts Settings", "Accounts Settings")
        cancel(pi.doctype, pi.name)
        guard.check_registered()
        self.assertEqual(frappe.db.get_value(pi.doctype, pi.name, "docstatus"), 2)
        self.assertTrue(frappe.db.count("GL Entry", {"voucher_type": pi.doctype, "voucher_no": pi.name, "is_cancelled": 0}))
        self.assertFalse(frappe.db.count("GL Entry", {"voucher_type": pi.doctype, "voucher_no": pi.name, "is_cancelled": 1}))
        self.assertTrue(frappe.db.exists("China Accounting Voucher", {"source_doctype": pi.doctype,
            "source_name": pi.name, "source_event": "Cancellation", "docstatus": 1}))
        self.assertEqual(str(frappe.db.get_value("China Accounting Voucher", {"source_doctype": pi.doctype,
            "source_name": pi.name, "source_event": "Cancellation"}, "posting_date")), pi.posting_date)
        dates = {str(row.posting_date) for row in frappe.db.get_values("GL Entry", {"voucher_type": pi.doctype,
            "voucher_no": pi.name}, ["posting_date"], as_dict=True)}
        self.assertEqual(dates, {pi.posting_date, nowdate()}, "Immutable GL reversal date differs from native Finance source date")

    def test_native_controller_failure_rolls_back_audit_and_stock(self):
        from deeplinkerp_branding.services import purchase_document_actions as actions
        from erpnext.stock.doctype.purchase_receipt.purchase_receipt import PurchaseReceipt
        po = self.order()
        original = PurchaseReceipt.on_submit
        def fail_after_native(doc):
            original(doc)
            raise RuntimeError("QA fault after real stock and GL")
        with patch.object(PurchaseReceipt, "on_submit", fail_after_native):
            with self.assertRaises(RuntimeError):
                self.receipt(po)
        self.assertEqual(self.before, {doctype: frappe.db.count(doctype) for doctype in self.types})

    def test_database_receipt_recovers_without_redis_and_without_second_native_write(self):
        from deeplinkerp_branding.services import purchase_document_actions as actions
        from deeplinkerp_branding.services import purchase_operation as kernel
        po = self.order()
        key = str(uuid.uuid4())
        native_draft = frappe.db.get_value("Purchase Receipt Item", {"purchase_order": po.name, "docstatus": 0}, "parent")
        args = dict(source_name=po.name, changes={"items": [{"key": po.items[0].name, "qty": 2}]}, request_id=key,
            target_name=native_draft, expected_modified=frappe.db.get_value("Purchase Receipt", native_draft, "modified"))
        first = actions.record_receipt(**args)
        self.assertFalse(first.get("failed"), first)
        audit = frappe.get_doc("Integration Request", kernel.identity("Administrator", key))
        self.assertEqual(audit.status, "Completed")
        self.commit_fixture()  # a new request transaction must recover the committed receipt
        with patch.object(frappe.cache, "lock", side_effect=ConnectionError("QA Redis lock unavailable")):
            second = actions.record_receipt(**args)
        self.assertTrue(second["reused"])
        self.assertEqual(first["document"]["name"], second["document"]["name"])
        self.assertEqual(frappe.db.count("Purchase Receipt", {"name": first["document"]["name"]}), 1)
        self.assertEqual(frappe.db.get_value("Purchase Order Item", po.items[0].name, "received_qty"), 2)

    def test_native_savedocs_deadlock_retry_discards_rolled_back_artifacts(self):
        from deeplinkerp_branding.services import purchase_consistency as guard
        from deeplinkerp_branding.services import purchase_operation as kernel
        from frappe.desk.form.save import savedocs as native
        po = self.order()
        self.commit_fixture()
        payload = frappe.copy_doc(po).as_dict()
        payload.update(name="new-purchase-order-" + uuid.uuid4().hex, __islocal=1)
        response_docs_before = len(frappe.response.get("docs") or [])
        names = []
        def retry_once(*args, **kwargs):
            native(*args, **kwargs)
            names.append(frappe.response.docs[-1]["name"])
            if len(names) == 1:
                raise frappe.QueryDeadlockError(Exception(1213, "synthetic native deadlock after insert"))
        key = str(uuid.uuid4())
        from erpnext.buying.doctype.purchase_order.purchase_order import PurchaseOrder
        def random_name(doc):
            doc.name = "QA-ATOMIC-PO-" + uuid.uuid4().hex[:16]
        with patch("frappe.desk.form.save.savedocs", side_effect=retry_once), \
             patch.object(PurchaseOrder, "autoname", random_name, create=True):
            guard.savedocs(json.dumps(payload, default=str), "Save", key)
        self.assertEqual(len(names), 2)
        self.assertNotEqual(*names)
        self.assertFalse(frappe.db.exists("Purchase Order", names[0]))
        self.assertEqual([row["name"] for row in frappe.response.docs[response_docs_before:]], [names[1]])
        audit = frappe.get_doc("Integration Request", kernel.identity("Administrator", key))
        artifacts = json.loads(audit.output)["artifacts"]
        self.assertEqual({row["name"] for row in artifacts}, {names[1]})
        self.assertNotIn(names[0], audit.data)

    def test_payment_receipt_records_invoice_effect_and_refuses_changed_source_replay(self):
        from deeplinkerp_branding.services import purchase_document_actions as actions
        from deeplinkerp_branding.services import purchase_operation as kernel
        po = self.order()
        pr = self.receipt(po)
        pi = make_purchase_invoice(pr.name).insert()
        pi.submit()
        self.commit_fixture()
        key = str(uuid.uuid4())
        args = dict(source_doctype="Purchase Receipt", source_name=pr.name, purchase_invoice=pi.name,
            amount_to_pay=10, bank_account="Cash - QAB", request_id=key)
        paid = actions.record_payment(**args)
        self.assertFalse(paid.get("failed"), paid)
        audit = frappe.get_doc("Integration Request", kernel.identity("Administrator", key))
        artifacts = json.loads(audit.output)["artifacts"]
        invoice_effects = [row for row in artifacts if (row["doctype"], row["name"]) == (pi.doctype, pi.name)]
        self.assertEqual(len(invoice_effects), 1)
        self.assertEqual(invoice_effects[0]["permission"], "read")
        replay = actions.record_payment(**args)
        self.assertTrue(replay["reused"])
        outstanding = frappe.db.get_value(pi.doctype, pi.name, "outstanding_amount")
        frappe.db.set_value(pi.doctype, pi.name, "outstanding_amount", outstanding + 1, update_modified=False)
        with self.assertRaises(frappe.ValidationError) as caught:
            actions.record_payment(**args)
        self.assertEqual(caught.exception.purchase_error_id, "replay_evidence_changed")

    def test_direct_payment_draft_replay_rechecks_acknowledged_evidence_and_write_acl(self):
        from deeplinkerp_branding.services import purchase_consistency as guard
        from deeplinkerp_branding.services import purchase_payment_service as service
        from deeplinkerp_branding.services import purchase_document_actions as actions
        from deeplinkerp_branding.services import purchase_operation as kernel
        po = self.order()
        pr = self.receipt(po)
        pi = make_purchase_invoice(pr.name).insert()
        pi.submit()
        self.commit_fixture()
        for change in ({"remarks": "QA legitimate changed draft"}, {"amount": 11}):
            with self.subTest(change=change):
                args = dict(source_doctype="Purchase Receipt", source_name=pr.name, purchase_invoice=pi.name,
                    amount_to_pay=10, bank_account="Cash - QAB", request_id=str(uuid.uuid4()))
                original = service.create_payment_draft(**args)
                self.commit_fixture()
                receipt = json.loads(frappe.get_doc("Integration Request",
                    kernel.identity("Administrator", args["request_id"])).output)
                self.assertTrue(any(row["name"] == original["name"] for row in receipt["artifacts"]))
                self.assertEqual(service.create_payment_draft(**args), {**original, "reused": True})
                from frappe import permissions
                native_permission = permissions.has_permission
                def deny_write(doctype, ptype="read", *args, **kwargs):
                    if doctype == "Payment Entry" and ptype == "write":
                        return False
                    return native_permission(doctype, ptype, *args, **kwargs)
                with patch.object(permissions, "has_permission", side_effect=deny_write), self.assertRaises(frappe.PermissionError):
                    service.create_payment_draft(**args)
                current = actions.preview_payment(original["name"])["document"]
                actions.update_payment_draft(original["name"], change, current["modified"])
                self.commit_fixture()
                before = guard.artifact_evidence(frappe.get_doc("Payment Entry", original["name"]))
                counts = {doctype: frappe.db.count(doctype) for doctype in self.types}
                with self.assertRaises(frappe.ValidationError) as caught:
                    service.create_payment_draft(**args)
                self.assertEqual(caught.exception.purchase_error_id, "replay_evidence_changed")
                self.assertEqual(before, guard.artifact_evidence(frappe.get_doc("Payment Entry", original["name"])))
                self.assertEqual(counts, {doctype: frappe.db.count(doctype) for doctype in self.types})

    def test_existing_finance_posting_cannot_be_stranded_when_settings_turn_inactive(self):
        from china_finance.services import voucher
        from frappe.client import cancel
        po = self.order()
        pr = self.receipt(po)
        pi = make_purchase_invoice(pr.name).insert()
        pi.submit()
        self.commit_fixture()
        self.remember_effects()
        settings = voucher.get_company_settings(COMPANY)
        frappe.db.set_value(settings.doctype, settings.name, "enabled", 0)
        frappe.clear_document_cache(settings.doctype, settings.name)
        with self.assertRaises(frappe.ValidationError) as caught:
            cancel(pi.doctype, pi.name)
        self.assertEqual(caught.exception.purchase_error_id, "finance_cancellation_settings_inactive")
        self.assert_effects_unchanged()

    def test_posting_snapshot_header_must_match_native_finance_effect(self):
        from china_finance.services import voucher
        from deeplinkerp_branding.services import purchase_consistency as guard
        po = self.order()
        self.commit_fixture()
        self.remember_effects()
        native = voucher.create_voucher_from_source
        for altered in ({"currency": "USD"}, {"status": "Reversed"}, {"reversal_of": "QA-ATOMIC-INVALID"},
                {"source_key": "QA-ATOMIC-INVALID"}, {"total_debit": 999, "total_credit": 999},
                {"posting_date": add_days(nowdate(), -1)}, {"fiscal_year": "1900"},
                {"accounting_period": "1900-01"}, {"reversed_by": "QA-ATOMIC-INVALID"}):
            with self.subTest(fields=tuple(altered)):
                pr = make_purchase_receipt(po.name).insert()
                def corrupt(source, event):
                    name = native(source, event)
                    if name and (source.doctype, source.name, event) == (pr.doctype, pr.name, "Posting"):
                        frappe.db.set_value("China Accounting Voucher", name, altered, update_modified=False)
                    return name
                try:
                    with patch.object(guard, "finance_service", return_value=frappe._dict(create_voucher_from_source=corrupt)), \
                            self.assertRaises(frappe.ValidationError):
                        pr.submit()
                finally:
                    frappe.db.rollback()
                self.assertFalse(frappe.db.exists("Purchase Receipt", pr.name))
                self.assert_effects_unchanged()

    def test_china_voucher_failure_after_real_stock_and_gl_rolls_back_everything(self):
        from china_finance.services import voucher
        po = self.order()
        with patch.object(voucher, "create_voucher_from_source", side_effect=RuntimeError("QA finance fault after native stock/GL")):
            with self.assertRaises(RuntimeError):
                self.receipt(po)
        self.assertEqual(self.before, {doctype: frappe.db.count(doctype) for doctype in self.types})

    def test_pending_or_exception_cancellation_restores_committed_native_state(self):
        from china_finance.services import voucher
        from frappe.client import cancel
        po = self.order()
        pr = self.receipt(po)
        pi = make_purchase_invoice(pr.name).insert()
        pi.submit()
        self.commit_fixture()
        stock = frappe.db.get_value("Bin", {"item_code": self.item, "warehouse": "Stores - QAB"}, "actual_qty")
        original = frappe.db.get_value("China Accounting Voucher", {"source_doctype": pi.doctype,
            "source_name": pi.name, "source_event": "Posting"}, "name")
        for outcome in ({"status": "pending", "error": "private QA detail"}, RuntimeError("private QA detail")):
            with self.subTest(outcome=type(outcome).__name__), patch.object(voucher, "process_cancellation_snapshot",
                **({"side_effect": outcome} if isinstance(outcome, Exception) else {"return_value": outcome})) as process:
                with self.assertRaises((frappe.ValidationError, RuntimeError)):
                    cancel(pi.doctype, pi.name)
                self.assertTrue(process.called, "The Finance failure must be reached, not masked by the stock-repost guard")
            self.assertEqual(frappe.db.get_value(pi.doctype, pi.name, "docstatus"), 1)
            self.assertEqual(frappe.db.get_value("Purchase Receipt", pr.name, "docstatus"), 1)
            self.assertEqual(frappe.db.get_value("Bin", {"item_code": self.item, "warehouse": "Stores - QAB"}, "actual_qty"), stock)
            self.assertFalse(frappe.db.get_value("China Accounting Voucher", original, "reversed_by"))
            self.assertFalse(frappe.db.exists("China Accounting Voucher", {"source_doctype": pi.doctype,
                "source_name": pi.name, "source_event": "Cancellation"}))

    def test_balanced_wrong_reversal_restores_committed_stock_and_posting(self):
        from china_finance.services import voucher
        from frappe.client import cancel
        po = self.order()
        pr = self.receipt(po)
        pi = make_purchase_invoice(pr.name).insert()
        pi.submit()
        self.commit_fixture()
        process = voucher.process_cancellation_snapshot

        def corrupt_reversal(*args, **kwargs):
            result = process(*args, **kwargs)
            self.assertEqual(result["status"], "resolved")
            reversal = frappe.get_doc("China Accounting Voucher", result["voucher"])
            for row in reversal.entries:
                frappe.db.set_value(row.doctype, row.name, {field: (row.get(field) or 0) * 2 for field in
                    ("debit", "credit", "debit_in_account_currency", "credit_in_account_currency")})
            frappe.db.set_value(reversal.doctype, reversal.name,
                {"total_debit": reversal.total_debit * 2, "total_credit": reversal.total_credit * 2})
            return result

        with patch.object(voucher, "process_cancellation_snapshot", side_effect=corrupt_reversal):
            with self.assertRaisesRegex(frappe.ValidationError, "反向金额"):
                cancel(pi.doctype, pi.name)
        self.assertEqual(frappe.db.get_value(pi.doctype, pi.name, "docstatus"), 1)
        self.assertEqual(frappe.db.get_value("Purchase Receipt", pr.name, "docstatus"), 1)
        self.assertEqual(frappe.db.get_value("Bin", {"item_code": self.item, "warehouse": "Stores - QAB"}, "actual_qty"), 2)
        self.assertFalse(frappe.db.exists("China Accounting Voucher", {"source_doctype": pi.doctype,
            "source_name": pi.name, "source_event": "Cancellation"}))

    def test_audit_retention_and_normal_delete_protection(self):
        from deeplinkerp_branding.services import purchase_operation as kernel
        self.order()
        name = frappe.db.get_value("Integration Request", {"integration_request_service": kernel.SERVICE}, "name")
        audit = frappe.get_doc("Integration Request", name)
        with patch.object(frappe.db, "delete") as delete:
            type(audit).clear_old_logs(30)
        predicate = str(delete.call_args.kwargs["filters"])
        self.assertIn(kernel.SERVICE, predicate)
        self.assertIn("integration_request_service", predicate)
        with self.assertRaises(frappe.PermissionError):
            audit.delete()


def boundary_peer(payload):
    """One native peer in the SAME guarded synthetic QA harness, no executor."""
    from deeplinkerp_branding.services import purchase_repost_boundary as boundary
    if frappe.local.site != SITE or frappe.conf.db_name != "qa_procurement_5" or frappe.conf.db_host != "db":
        raise RuntimeError("Isolated synthetic procurement database only")
    if not str(payload.get("item") or "").startswith("QA-ATOMIC-"):
        raise RuntimeError("Exact new synthetic item only")
    frappe.in_test = False
    frappe.flags.in_test = True
    frappe.flags.mute_emails = True
    if not payload["action"].startswith("entry-"):
        boundary.initialize()
    frappe.db.after_commit.reset()  # before any peer document acquires leases
    # Reuse the same harness's cleanup inventory without executing setUp or
    # creating another cancellation fixture/test class.
    import ast
    import inspect
    import textwrap
    method = ast.parse(textwrap.dedent(inspect.getsource(NativeAtomicPurchaseTests.setUp))).body[0]
    types = ()
    for node in method.body:
        target = node.targets[0] if isinstance(node, ast.Assign) else node.target if isinstance(node, ast.AugAssign) else None
        if isinstance(target, ast.Attribute) and target.attr == "types":
            value = ast.literal_eval(node.value)
            types = types + value if isinstance(node, ast.AugAssign) else value
    before = {doctype: set(frappe.get_all(doctype, pluck="name", limit_page_length=0)) for doctype in types}
    action = payload["action"]
    if action.startswith("entry-"):
        from deeplinkerp_branding.services import purchase_document_actions as actions, purchase_source_service as sources
        queries = []
        native_sql = frappe.local.db.sql
        def observe(query, *args, **kwargs):
            queries.append(str(query).upper())
            return native_sql(query, *args, **kwargs)
        frappe.local.db.sql = observe
        physical = frappe.local.db._conn
        if action == "entry-payment-update":
            actions.update_payment_draft(payload["name"], {"remarks": "QA-ATOMIC-EARLY"}, payload["modified"])
        elif action == "entry-payment-submit":
            actions.submit_document("Payment Entry", payload["name"], payload["modified"])
        elif action == "entry-source-create":
            try:
                sources.create_purchase_order_from_source("QA-ATOMIC-SOURCE-MISSING-" + uuid.uuid4().hex,
                    "", COMPANY, "QA Test Supplier", "CNY", add_days(nowdate(), 1), [])
            except frappe.DoesNotExistError:
                pass  # exact nonexistent source: still exercises real earliest locked public entry
            else:
                raise AssertionError("Missing source unexpectedly accepted")
        else:
            raise RuntimeError("Unknown public entry")
        state = boundary.initialize()
        result = {"identity_query": next(i for i, query in enumerate(queries) if "CONNECTION_ID()" in query),
            "first_lock": next(i for i, query in enumerate(queries) if "FOR UPDATE" in query),
            "same_physical": state.connection is physical, "execution_id": state.execution_id}
    elif action == "defaults":
        entry_type = frappe.get_doc("Stock Entry Type", payload["entry_type"])
        if not entry_type.name.startswith("QA-ATOMIC-TYPE-"):
            raise RuntimeError("Exact new synthetic Stock Entry Type only")
        # Purpose is native set_only_once. This positive peer changes only the
        # legally mutable Item stock_uom, through its real save/cache hooks.
        item = frappe.get_doc("Item", payload["item"])
        item.stock_uom = "Kg"
        item.save()
        result = {"updated": True}
    elif action == "source":
        receipt = frappe.get_doc("Purchase Receipt", payload["name"])
        receipt.items[0].purchase_order = payload["source"]
        receipt.items[0].purchase_order_item = payload["detail"]
        receipt.items[0].warehouse = "Work In Progress - QAB"
        receipt.save()
        result = {"name": receipt.name, "detail": receipt.items[0].name}
    elif action in ("transfer", "draft"):
        draft = frappe.get_doc({"doctype": "Stock Entry", "company": COMPANY,
            "stock_entry_type": payload.get("entry_type") or "Material Transfer",
            "set_posting_time": 1, "posting_date": add_days(nowdate(), 2), "posting_time": "12:00:00",
            "items": [{"item_code": payload["item"], "qty": 1, "s_warehouse": "Stores - QAB",
                "t_warehouse": "Work In Progress - QAB"}]}).insert()
        if action == "transfer":
            draft.submit()
        result = {"name": draft.name, "detail": draft.items[0].name, "purpose": draft.purpose,
            "stock_uom": draft.items[0].stock_uom}
    else:
        raise RuntimeError("Unknown synthetic peer action")
    frappe.db.commit()
    result["created"] = {doctype: sorted(set(frappe.get_all(doctype, pluck="name", limit_page_length=0)) - before[doctype])
        for doctype in types}
    print(json.dumps(result))


if __name__ == "__main__":
    frappe.init(site=SITE, sites_path="/home/frappe/frappe-bench/sites")
    frappe.connect()
    try:
        # The legacy single-transaction harness predates whole-request rollback.
        # Run explicit native transaction scenarios on the guarded isolated clone.
        if len(sys.argv) == 3 and sys.argv[1] == "--boundary-peer":
            boundary_peer(json.loads(sys.argv[2]))
        else:
            result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(NativeAtomicPurchaseTests))
            raise SystemExit(not result.wasSuccessful())
    finally:
        frappe.destroy()
