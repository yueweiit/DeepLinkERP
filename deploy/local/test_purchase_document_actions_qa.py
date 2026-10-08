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
        self.types += ("Sales Order", "Stock Reservation Entry", "Submission Queue", "Repost Item Valuation")
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

    def commit_fixture(self):
        frappe.db.after_commit.reset()  # test fixture must not dispatch notifications/jobs
        frappe.db.commit()
        self.committed_names = {doctype: set(frappe.get_all(doctype, pluck="name", limit_page_length=0)) - self.initial_names[doctype]
            for doctype in self.types}
        self.assertTrue(self.committed_names["Purchase Order"])
        self.assertTrue(all(name.startswith("QA-ATOMIC-PO-") for name in self.committed_names["Purchase Order"]))

    def order(self, currency="CNY", conversion_rate=1, supplier="QA Test Supplier", transaction_date=None):
        po = frappe.get_doc({"doctype": "Purchase Order", "company": COMPANY,
            "transaction_date": transaction_date or nowdate(),
            "supplier": supplier, "currency": currency, "conversion_rate": conversion_rate, "schedule_date": add_days(nowdate(), 1),
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

    def test_native_savedocs_queue_is_stopped_before_dispatch(self):
        from deeplinkerp_branding.services import purchase_consistency as guard
        po = self.order()
        self.commit_fixture()
        payload = json.dumps(po.as_dict(), default=str)
        meta = frappe.get_meta("Purchase Order")
        with patch.object(meta, "queue_in_background", True), \
                patch("frappe.utils.scheduler.is_scheduler_inactive", return_value=False), \
                patch("frappe.desk.form.save.queue_submission", side_effect=AssertionError("No queue dispatch")):
            for key in (None, str(uuid.uuid4())):
                with self.subTest(request_id=key), self.assertRaises(frappe.ValidationError) as caught:
                    guard.savedocs(payload, "Submit", request_id=key)
                self.assertEqual(caught.exception.purchase_error_id, "native_background_submission_unsupported")
        self.assertEqual(frappe.db.get_value("Purchase Order", po.name, "docstatus"), 1)
        self.assertEqual(self.before["Submission Queue"], frappe.db.count("Submission Queue"))

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
            for doctype in ("Purchase Order", "Purchase Receipt", "Purchase Invoice", "Payment Entry", "China Accounting Voucher", "Integration Request", "Repost Item Valuation")
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
        po = self.order()
        pr = self.receipt(po)
        pi = make_purchase_invoice(pr.name).insert()
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
                {"source_key": "QA-ATOMIC-INVALID"}, {"total_debit": 999, "total_credit": 999}):
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
