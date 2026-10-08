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
        frappe.set_user("Administrator")
        frappe.flags.in_test = True
        frappe.flags.mute_emails = True
        self.types = ("Purchase Order", "Purchase Receipt", "Purchase Invoice", "Payment Entry", "GL Entry",
            "Payment Ledger Entry", "Stock Ledger Entry", "Bin", "China Accounting Voucher", "China Voucher Sync Issue", "Integration Request", "Item",
            "ToDo", "Version", "Notification Log", "China Cash Flow Assignment")
        self.before = {doctype: frappe.db.count(doctype) for doctype in self.types}
        self.initial_names = {doctype: set(frappe.get_all(doctype, pluck="name", limit_page_length=0)) for doctype in self.types}
        self.committed_names = None
        self.addCleanup(self.clean)
        self.item = "QA-ATOMIC-" + uuid.uuid4().hex[:10]
        frappe.get_doc({"doctype": "Item", "item_code": self.item, "item_name": self.item, "item_group": "All Item Groups",
            "stock_uom": "Nos", "is_stock_item": 1}).insert()

    def clean(self):
        frappe.db.rollback()
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

    def commit_fixture(self):
        frappe.db.after_commit.reset()  # test fixture must not dispatch notifications/jobs
        frappe.db.commit()
        self.committed_names = {doctype: set(frappe.get_all(doctype, pluck="name", limit_page_length=0)) - self.initial_names[doctype]
            for doctype in self.types}
        self.assertTrue(self.committed_names["Purchase Order"])
        self.assertTrue(all(name.startswith("QA-ATOMIC-PO-") for name in self.committed_names["Purchase Order"]))

    def order(self):
        po = frappe.get_doc({"doctype": "Purchase Order", "company": COMPANY,
            "supplier": "QA Test Supplier", "currency": "CNY", "schedule_date": add_days(nowdate(), 1),
            "items": [{"item_code": self.item, "qty": 10, "rate": 12.345,
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
        self.commit_fixture()
        stock = frappe.db.get_value("Bin", {"item_code": self.item, "warehouse": "Stores - QAB"}, "actual_qty")
        original = frappe.db.get_value("China Accounting Voucher", {"source_doctype": pr.doctype,
            "source_name": pr.name, "source_event": "Posting"}, "name")
        for outcome in ({"status": "pending", "error": "private QA detail"}, RuntimeError("private QA detail")):
            with self.subTest(outcome=type(outcome).__name__), patch.object(voucher, "process_cancellation_snapshot",
                **({"side_effect": outcome} if isinstance(outcome, Exception) else {"return_value": outcome})):
                with self.assertRaises((frappe.ValidationError, RuntimeError)):
                    cancel("Purchase Receipt", pr.name)
            self.assertEqual(frappe.db.get_value("Purchase Receipt", pr.name, "docstatus"), 1)
            self.assertEqual(frappe.db.get_value("Bin", {"item_code": self.item, "warehouse": "Stores - QAB"}, "actual_qty"), stock)
            self.assertFalse(frappe.db.get_value("China Accounting Voucher", original, "reversed_by"))
            self.assertFalse(frappe.db.exists("China Accounting Voucher", {"source_doctype": pr.doctype,
                "source_name": pr.name, "source_event": "Cancellation"}))

    def test_balanced_wrong_reversal_restores_committed_stock_and_posting(self):
        from china_finance.services import voucher
        from frappe.client import cancel
        po = self.order()
        pr = self.receipt(po)
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
                cancel("Purchase Receipt", pr.name)
        self.assertEqual(frappe.db.get_value("Purchase Receipt", pr.name, "docstatus"), 1)
        self.assertEqual(frappe.db.get_value("Bin", {"item_code": self.item, "warehouse": "Stores - QAB"}, "actual_qty"), 2)
        self.assertFalse(frappe.db.exists("China Accounting Voucher", {"source_doctype": pr.doctype,
            "source_name": pr.name, "source_event": "Cancellation"}))

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
