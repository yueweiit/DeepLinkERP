"""Native drawer actions on one synthetic site, always rolled back."""
import json
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
        self.types = ("Purchase Order", "Purchase Receipt", "Purchase Invoice", "Payment Entry", "GL Entry",
            "Payment Ledger Entry", "Stock Ledger Entry", "Bin", "China Accounting Voucher", "China Voucher Sync Issue", "Integration Request", "Item",
            "ToDo", "Version", "Notification Log", "China Cash Flow Assignment", "User", "Warehouse",
            "Workflow", "Workflow State", "Workflow Action Master", "Custom Field", "Advance Payment Ledger Entry", "Account", "Supplier")
        self.types += ("Sales Order", "Stock Reservation Entry", "Submission Queue", "Repost Item Valuation",
            "Material Request", "Purchase Fulfilment Link", "China Cash Equivalent Scope", "Delivery Note", "Customer", "Price List", "Item Price", "Sales Invoice")
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
        frappe.db.after_commit.reset()  # test fixture must not dispatch notifications/jobs
        frappe.db.commit()
        self.committed_names = {doctype: set(frappe.get_all(doctype, pluck="name", limit_page_length=0)) - self.initial_names[doctype]
            for doctype in self.types}
        self.assertTrue(self.committed_names[primary_doctype])
        self.assertTrue(all(name.startswith(name_prefix) for name in self.committed_names[primary_doctype]))

    def order(self, currency="CNY", conversion_rate=1, supplier="QA Test Supplier", transaction_date=None, qty=10, rate=12.345):
        po = frappe.get_doc({"doctype": "Purchase Order", "company": COMPANY,
            "transaction_date": transaction_date or nowdate(),
            "supplier": supplier, "currency": currency, "conversion_rate": conversion_rate, "schedule_date": add_days(nowdate(), 1),
            "items": [{"item_code": self.item, "qty": qty, "rate": rate,
                "warehouse": "Stores - QAB", "schedule_date": add_days(nowdate(), 1)}]}).insert(
                    set_name="QA-ATOMIC-PO-" + uuid.uuid4().hex[:16])
        po.submit()
        return po

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
        from frappe.api import v1, v2
        from deeplinkerp_branding.services import purchase_consistency as guard
        frappe.db.set_value("Item", self.item, "is_stock_item", 0)
        frappe.clear_document_cache("Item", self.item)
        po = self.order()
        pr = self.receipt(po)
        pi = make_purchase_invoice(pr.name).insert()
        pi.submit()
        self.commit_fixture()
        for api in (v1, v2):
            with self.subTest(api=api.__name__):
                if api is v1:
                    with patch.object(v1, "get_request_form_data", return_value={"docstatus": 2}):
                        api.update_doc(pi.doctype, pi.name)
                else:
                    with patch.object(frappe.local, "form_dict", frappe._dict(docstatus=2)):
                        api.update_doc(pi.doctype, pi.name)
                guard.check_registered()
                self.assertEqual(frappe.db.get_value(pi.doctype, pi.name, "docstatus"), 2)
                issue = frappe.get_doc("China Voucher Sync Issue", {"issue_key": f"Cancellation|{pi.doctype}|{pi.name}"})
                self.assertEqual(issue.status, "Resolved")
                self.assertTrue(issue.cancellation_voucher)
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
            document.reload().submit()
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
        po = self.order()
        pr = make_purchase_receipt(po.name).insert()
        pi = frappe.get_doc({"doctype": "Purchase Invoice", "company": COMPANY, "supplier": pr.supplier,
            "currency": pr.currency, "conversion_rate": pr.conversion_rate, "bill_no": "QA-ATOMIC-MANUAL",
            "bill_date": add_days(nowdate(), -2), "items": [{"item_code": self.item, "qty": 1, "rate": po.items[0].rate,
                "purchase_order": po.name, "po_detail": po.items[0].name, "purchase_receipt": pr.name,
                "pr_detail": pr.items[0].name, "warehouse": "Stores - QAB"}]}).insert()
        self.commit_fixture()
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

    def remember_effects(self):
        from deeplinkerp_branding.services import purchase_consistency as guard
        self.fixture_effects = {(doctype, name): guard.artifact_evidence(frappe.get_doc(doctype, name))
            for doctype in ("Purchase Order", "Purchase Receipt", "Purchase Invoice", "Payment Entry", "China Accounting Voucher", "Integration Request", "Repost Item Valuation", "Delivery Note", "Sales Order", "Sales Invoice")
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
        try:
            for policy, expected in (("Banker's Rounding", .002), ("Commercial Rounding", .003)):
                with self.subTest(policy=policy):
                    frappe.db.set_single_value("System Settings", {"rounding_method": policy, "float_precision": "3"})
                    frappe.clear_document_cache("System Settings", "System Settings")
                    row = frappe.new_doc("Purchase Order Item")
                    self.assertEqual(row.precision("qty"), 3)
                    self.assertEqual(flt(.0025, 3), expected)
                    guard.equal(row, "qty", .0025, expected, "实际系统舍入")
        finally:
            frappe.db.rollback()
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


if __name__ == "__main__":
    frappe.init(site=SITE, sites_path="/home/frappe/frappe-bench/sites")
    frappe.connect()
    try:
        # The legacy single-transaction harness predates whole-request rollback.
        # Run explicit native transaction scenarios on the guarded isolated clone.
        result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(NativeAtomicPurchaseTests))
        raise SystemExit(not result.wasSuccessful())
    finally:
        frappe.destroy()
