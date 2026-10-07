"""Release-owner native acceptance on the existing isolated QA database only.

Run with FRAPPE_STREAM_LOGGING=1, initialized on the allowlisted site with
sites_path='/home/frappe/frappe-bench/sites'. Every test rolls back its native
PO/PI/PR/PE, test-only masters and configuration; this file never commits,
migrates, submits automatically, invokes a scheduler or contacts production.
"""
import unittest
import uuid

import frappe
from frappe.utils import add_days, nowdate
from erpnext.buying.doctype.purchase_order.purchase_order import make_purchase_receipt
from erpnext.controllers.sales_and_purchase_return import make_return_doc

from deeplinkerp_branding.services import purchase_document_actions as actions
from deeplinkerp_branding.services import purchase_payment_service as service
from deeplinkerp_branding.services.purchase_order_progress import get_order_progress

SITE = "operating-expenses-qa.localhost"
CHINA = "QA Operating China"
MEXICO = "QA Operating Mexico"
SUPPLIER = "QA Operating Supplier"
ITEM = "QA-JOINT-PO-ITEM"
COUNTS = ("Purchase Order", "Purchase Receipt", "Purchase Invoice", "Payment Entry", "GL Entry",
          "Payment Ledger Entry", "Advance Payment Ledger Entry", "Stock Ledger Entry", "Stock Entry", "Bin",
          "Company", "Supplier", "Customer", "Account", "Item", "Warehouse", "Sales Order", "Sales Invoice")
MASTERS = ("Company", "Supplier", "Customer", "Account", "Item", "Warehouse", "Sales Order", "Sales Invoice")
COMPANY_FIELDS = ["name", "default_currency", "default_payable_account", "default_expense_account",
                  "book_advance_payments_in_separate_party_account", "default_advance_paid_account",
                  "enable_perpetual_inventory", "default_inventory_account", "stock_received_but_not_billed"]


def require_qa():
    if frappe.local.site != SITE or frappe.conf.db_host != "db":
        raise RuntimeError("Strict operating-expenses synthetic QA site and db host only")


def configuration():
    return {"companies": frappe.db.get_values("Company", {}, COMPANY_FIELDS, as_dict=True, order_by="name"),
            "singles": frappe.db.sql("select doctype, field, value from `tabSingles` where doctype in "
                "('Buying Settings', 'Accounts Settings', 'System Settings') order by doctype, field", as_dict=True),
            "site_sync": frappe.conf.get("purchase_source_sync_enabled")}


class NativeCrossborderDocumentsQA(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        require_qa()
        frappe.set_user("Administrator")
        for doctype, name in (("Company", CHINA), ("Company", MEXICO), ("Supplier", SUPPLIER), ("Item", ITEM),
                              ("Account", "Cash - QOC"), ("Account", "Creditors - QOC"),
                              ("Account", "Cash - QOM"), ("Warehouse", "Stores - QOC")):
            if not frappe.db.exists(doctype, name):
                raise RuntimeError("Existing known synthetic procurement fixtures are required")
        if frappe.db.get_single_value("System Settings", "enable_scheduler"):
            raise RuntimeError("Global QA scheduler must remain disabled")
        if frappe.db.get_single_value("Buying Settings", "pr_required") != "No":
            raise RuntimeError("Expected QA receipt requirement baseline changed; preserve it")
        for company, currency in ((CHINA, "CNY"), (MEXICO, "MXN")):
            row = frappe.db.get_value("Company", company,
                ["default_currency", "book_advance_payments_in_separate_party_account", "default_advance_paid_account"], as_dict=True)
            if row.default_currency != currency or row.book_advance_payments_in_separate_party_account or row.default_advance_paid_account:
                raise RuntimeError("Expected QA currency / unconfigured advance baseline changed; preserve it")

    def setUp(self):
        require_qa()
        frappe.set_user("Administrator")
        self.original_flags = {field: frappe.flags.get(field) for field in ("in_test", "mute_emails")}
        frappe.flags.in_test = True
        frappe.flags.mute_emails = True
        self.before = {doctype: frappe.db.count(doctype) for doctype in COUNTS}
        self.before_configuration = configuration()
        # Cleanup runs even when fixture preparation or a native assertion fails.
        self.addCleanup(self.restore_baseline)

    def restore_baseline(self):
        frappe.db.rollback()
        frappe.set_user("Administrator")
        for doctype, name in (("Company", CHINA), ("Company", MEXICO), ("Supplier", SUPPLIER)):
            frappe.clear_document_cache(doctype, name)
        for field, value in self.original_flags.items():
            frappe.flags[field] = value
        self.assertEqual({doctype: frappe.db.count(doctype) for doctype in COUNTS}, self.before)
        self.assertEqual(configuration(), self.before_configuration)
        self.assertFalse(frappe.db.get_single_value("System Settings", "enable_scheduler"))

    def po(self, company=CHINA, supplier=SUPPLIER, qty=10, rate=10, item=ITEM):
        currency = "CNY" if company == CHINA else "MXN"
        abbreviation = "QOC" if company == CHINA else "QOM"
        doc = frappe.get_doc({"doctype": "Purchase Order", "company": company, "supplier": supplier,
            "currency": currency, "conversion_rate": 1, "price_list_currency": currency, "plc_conversion_rate": 1,
            "schedule_date": add_days(nowdate(), 1), "items": [{"item_code": item, "qty": qty, "rate": rate,
                "uom": "Nos", "warehouse": "Stores - " + abbreviation, "schedule_date": add_days(nowdate(), 1)}]}).insert()
        doc.submit()
        return doc

    def invoice(self, source, qty, *, submit=False, request_id=None):
        preview = actions.preview_document(source.doctype, source.name, "Purchase Invoice")
        result = actions.save_document_draft(source.doctype, source.name, "Purchase Invoice",
            {"items": [{"key": preview["document"]["items"][0]["key"], "qty": qty}]}, request_id or str(uuid.uuid4()),
            expected_source_modified=preview["source_modified"])
        self.assertEqual(result["document"]["docstatus"], 0)
        doc = frappe.get_doc("Purchase Invoice", result["document"]["name"])
        self.assertEqual(doc.update_stock, 0)
        self.assertFalse(frappe.db.count("GL Entry", {"voucher_type": "Purchase Invoice", "voucher_no": doc.name}))
        if submit:
            result = actions.submit_document("Purchase Invoice", doc.name, str(doc.modified), "Submit")
            self.assertEqual(result["document"]["docstatus"], 1)
            doc.reload()
        return doc, preview

    def payment(self, source, invoice, amount):
        account = "Cash - QOC" if source.company == CHINA else "Cash - QOM"
        draft = service.create_payment_draft(source.doctype, source.name, purchase_invoice=invoice.name,
            amount_to_pay=amount, bank_account=account, request_id=str(uuid.uuid4()))
        doc = frappe.get_doc("Payment Entry", draft["name"])
        self.assertEqual(doc.docstatus, 0)
        self.assertFalse(frappe.db.count("GL Entry", {"voucher_type": "Payment Entry", "voucher_no": doc.name}))
        result = actions.submit_document("Payment Entry", doc.name, str(doc.modified), "Submit")
        self.assertEqual(result["document"]["docstatus"], 1)
        return doc

    def stock_item(self):
        return frappe.get_doc({"doctype": "Item", "item_code": "QA-CROSSBORDER-STOCK-" + uuid.uuid4().hex[:10],
            "item_name": "QA rollback crossborder stock", "item_group": frappe.db.get_value("Item", ITEM, "item_group"),
            "stock_uom": "Nos", "is_stock_item": 1, "valuation_method": "FIFO", "item_defaults": [{"company": CHINA,
                "default_warehouse": "Stores - QOC", "expense_account": "Cost of Goods Sold - QOC"}]}).insert().name

    def bins(self, item):
        return frappe.db.get_values("Bin", {"item_code": item},
            ["warehouse", "actual_qty", "ordered_qty", "reserved_qty", "projected_qty", "valuation_rate"],
            as_dict=True, order_by="warehouse")

    def test_stock_po_partial_invoice_payment_then_real_receipt_keeps_one_obligation(self):
        receipts_before = self.before["Purchase Receipt"]
        stock = self.stock_item()
        po = self.po(item=stock)
        # Installed OA's native stock-PO submit hook creates one receipt draft.
        # Keep its provenance and edit it; never bypass the duplicate guard.
        receipt_parents = frappe.db.get_values("Purchase Receipt Item",
            {"purchase_order": po.name, "docstatus": 0}, ["parent"], as_dict=True, distinct=True)
        self.assertEqual(len(receipt_parents), 1)
        self.assertEqual(frappe.db.count("Purchase Receipt"), receipts_before + 1)
        pending_receipt = service._read("Purchase Receipt", receipt_parents[0].parent,
            {"company", "supplier", "items"})
        self.assertEqual(pending_receipt.docstatus, 0)
        self.assertEqual((pending_receipt.company, pending_receipt.supplier), (po.company, po.supplier))
        self.assertEqual([(row.purchase_order, row.purchase_order_item) for row in pending_receipt.items],
            [(po.name, po.items[0].name)])
        masters = {dt: frappe.db.count(dt) for dt in MASTERS}
        config = configuration()
        bins_before = self.bins(stock)
        sle_before = frappe.db.count("Stock Ledger Entry")
        pi, _ = self.invoice(po, 4)
        self.assertEqual(self.bins(stock), bins_before)
        self.assertEqual(frappe.db.count("Stock Ledger Entry"), sle_before)
        actions.submit_document("Purchase Invoice", pi.name, str(pi.modified), "Submit")
        pi.reload()
        self.assertEqual(pi.update_stock, 0)
        self.assertEqual(pi.outstanding_amount, 40)
        self.assertEqual(self.bins(stock), bins_before)
        self.assertEqual(frappe.db.count("Stock Ledger Entry"), sle_before)
        first_payment = self.payment(po, pi, 10)
        self.assertEqual(frappe.db.get_value("Purchase Invoice", pi.name, "outstanding_amount"), 30)

        preview = actions.preview_document("Purchase Order", po.name, "Purchase Receipt", target_name=pending_receipt.name)
        draft = actions.save_document_draft("Purchase Order", po.name, "Purchase Receipt",
            {"items": [{"key": preview["document"]["items"][0]["key"], "qty": 10}]}, str(uuid.uuid4()),
            target_name=pending_receipt.name, expected_modified=preview["document"]["modified"])["document"]
        self.assertEqual(draft["name"], pending_receipt.name)
        self.assertEqual(frappe.db.count("Purchase Receipt"), receipts_before + 1)
        invoices_before_receipt = frappe.db.count("Purchase Invoice")
        self.assertEqual(self.bins(stock), bins_before)
        actions.submit_document("Purchase Receipt", draft["name"], draft["modified"], "Submit", request_id=str(uuid.uuid4()))
        pr = frappe.get_doc("Purchase Receipt", draft["name"])
        self.assertEqual(frappe.db.get_value("Bin", {"item_code": stock, "warehouse": "Stores - QOC"}, "actual_qty"), 10)
        self.assertGreater(frappe.db.count("Stock Ledger Entry"), sle_before)
        self.assertEqual(frappe.db.count("Purchase Invoice"), invoices_before_receipt)
        self.assertEqual(frappe.db.get_value("Purchase Invoice", pi.name, "outstanding_amount"), 30)
        chain = service.get_purchase_chain("Purchase Receipt", pr.name)
        previous = next(row for row in chain["invoices"] if row["name"] == pi.name)
        self.assertTrue(previous["shared"])
        self.assertEqual(previous["outstanding"], 30)
        self.assertTrue(any(row["name"] == first_payment.name for row in chain["payments"]))
        later = actions.preview_document("Purchase Receipt", pr.name, "Purchase Invoice")
        self.assertEqual(later["document"]["items"][0]["max_qty"], 6)
        with self.assertRaises(frappe.ValidationError):
            actions.save_document_draft("Purchase Receipt", pr.name, "Purchase Invoice",
                {"items": [{"key": later["document"]["items"][0]["key"], "qty": 10}]}, str(uuid.uuid4()),
                expected_source_modified=later["source_modified"])
        self.assertEqual(frappe.db.count("Purchase Invoice"), invoices_before_receipt)
        self.payment(pr, pi, 5)
        self.assertEqual(frappe.db.get_value("Purchase Invoice", pi.name, "outstanding_amount"), 25)
        self.assertEqual(configuration(), config)
        self.assertEqual({dt: frappe.db.count(dt) for dt in MASTERS}, masters)

    def test_unconfigured_prepaid_is_disabled_but_order_invoice_draft_is_available(self):
        po = self.po()
        config = configuration()
        chain = service.get_purchase_chain("Purchase Order", po.name, include_payments=False)
        self.assertFalse(chain["can_prepay"])
        self.assertIn("预付", chain["advance_reason"])
        self.assertTrue(chain["can_create_invoice"])
        pi, _ = self.invoice(po, 2)
        self.assertEqual(pi.update_stock, 0)
        self.assertEqual(configuration(), config)
        self.assertEqual(frappe.db.count("Payment Entry"), self.before["Payment Entry"])

    def test_source_cas_acknowledged_retry_and_target_drafts_are_separate(self):
        po = self.po()
        preview = actions.preview_document("Purchase Order", po.name, "Purchase Invoice")
        # A receipt draft must not be confused with an invoice draft.
        pr = make_purchase_receipt(po.name).insert()
        args = {"source_doctype": "Purchase Order", "source_name": po.name, "target_doctype": "Purchase Invoice",
                "changes": {"items": [{"key": preview["document"]["items"][0]["key"], "qty": 2}]},
                "request_id": str(uuid.uuid4()), "expected_source_modified": preview["source_modified"]}
        first = actions.save_document_draft(**args)
        po.db_set("title", "QA source CAS drift")
        before = frappe.db.count("Purchase Invoice")
        retry = actions.save_document_draft(**args)
        self.assertTrue(retry["reused"])
        self.assertEqual(retry["document"]["name"], first["document"]["name"])
        self.assertEqual(frappe.db.count("Purchase Invoice"), before)
        with self.assertRaises(frappe.ValidationError):
            actions.save_document_draft(**{**args, "request_id": str(uuid.uuid4()), "allow_another_draft": 1})
        self.assertEqual(frappe.db.count("Purchase Invoice"), before)
        self.assertEqual(frappe.db.get_value("Purchase Receipt", pr.name, "docstatus"), 0)
        self.assertEqual(frappe.db.count("GL Entry"), self.before["GL Entry"])

    def test_configured_native_advance_reconciliation_is_counted_once(self):
        advance = frappe.get_doc({"doctype": "Account", "account_name": "QA Crossborder Advance " + uuid.uuid4().hex[:8],
            "company": CHINA, "parent_account": "Loans and Advances (Assets) - QOC", "is_group": 0,
            "root_type": "Asset", "report_type": "Balance Sheet", "account_type": "Payable", "account_currency": "CNY"}).insert()
        frappe.db.set_value("Company", CHINA, {"book_advance_payments_in_separate_party_account": 1,
                                              "default_advance_paid_account": advance.name})
        frappe.clear_document_cache("Company", CHINA)
        config = configuration()
        po = self.po()
        self.assertTrue(service.get_purchase_chain("Purchase Order", po.name, include_payments=False)["can_prepay"])
        draft = service.create_payment_draft("Purchase Order", po.name, amount_to_pay=20,
            bank_account="Cash - QOC", request_id=str(uuid.uuid4()))
        pe = frappe.get_doc("Payment Entry", draft["name"])
        self.assertEqual(pe.paid_to, advance.name)
        self.assertEqual(pe.docstatus, 0)
        self.assertFalse(frappe.db.count("GL Entry", {"voucher_type": "Payment Entry", "voucher_no": pe.name}))
        actions.submit_document("Payment Entry", pe.name, str(pe.modified), "Submit")
        self.assertEqual(get_order_progress([po.name])[po.name]["external"]["settled"], 20)
        pi, _ = self.invoice(po, 4)
        # Explicit native form choice; the quick editor never invents advances.
        pi.allocate_advances_automatically = 1
        pi.set_advances()
        pi.save()
        self.assertEqual(sum(row.allocated_amount for row in pi.advances), 20)
        actions.submit_document("Purchase Invoice", pi.name, str(pi.modified), "Submit")
        pi.reload()
        self.assertEqual(pi.outstanding_amount, 20)
        chain = service.get_purchase_chain("Purchase Order", po.name)
        self.assertFalse(chain["can_prepay"])
        self.assertEqual(chain["balances"], [{"currency": "CNY", "total": 40.0, "settled": 20.0, "outstanding": 20.0}])
        self.assertEqual(get_order_progress([po.name])[po.name]["external"]["settled"], 20,
            "Reconciled native PO advances must not be added again to the invoice settlement")
        self.payment(po, pi, 20)
        self.assertEqual(service.get_purchase_chain("Purchase Order", po.name)["balances"][0]["settled"], 40)
        self.assertEqual(get_order_progress([po.name])[po.name]["external"]["settled"], 40)
        self.assertEqual(configuration(), config)

    def test_crosscompany_internal_invoice_remains_independent_of_external_payment(self):
        # ERPNext permits only one internal Supplier per represented company.
        # Reuse the authorized synthetic master; never rewrite it for this test.
        existing = frappe.db.get_value("Supplier",
            {"is_internal_supplier": 1, "represents_company": CHINA}, "name")
        supplier = frappe.get_doc("Supplier", existing) if existing else frappe.get_doc({
            "doctype": "Supplier", "supplier_name": "QA Crossborder China Seller " + uuid.uuid4().hex[:8],
            "supplier_type": "Company", "supplier_group": frappe.db.get_value("Supplier", SUPPLIER, "supplier_group"),
            "is_internal_supplier": 1, "represents_company": CHINA, "companies": [{"company": MEXICO}]}).insert()
        self.assertFalse(supplier.disabled)
        self.assertIn(MEXICO, {row.company for row in supplier.companies})
        external = self.po()
        internal = self.po(MEXICO, supplier.name, rate=20)
        masters = {dt: frappe.db.count(dt) for dt in MASTERS}
        config = configuration()
        external_pi, _ = self.invoice(external, 5, submit=True)
        internal_pi, _ = self.invoice(internal, 5, submit=True)
        self.assertNotEqual(internal_pi.represents_company, internal_pi.company)
        self.assertEqual(internal_pi.company, MEXICO)
        self.assertEqual(internal_pi.currency, "MXN")
        self.assertEqual(internal_pi.items[0].rate, 20)
        self.assertEqual(internal_pi.outstanding_amount, 100)
        self.payment(external, external_pi, 25)
        self.assertEqual(frappe.db.get_value("Purchase Invoice", internal_pi.name, "outstanding_amount"), 100)
        chain = service.get_purchase_chain("Purchase Order", internal.name)
        self.assertEqual(chain["balances"][0]["outstanding"], 100)
        self.assertFalse(chain["payments"])
        self.assertEqual({dt: frappe.db.count(dt) for dt in MASTERS}, masters)
        self.assertEqual(configuration(), config)

    def test_signed_native_invoice_returns_and_cancellation_restore_quantity_caps(self):
        po = self.po()
        pi, _ = self.invoice(po, 4, submit=True)
        returned = make_return_doc("Purchase Invoice", pi.name)
        returned.items[0].qty = -1
        returned.update_stock = 0
        returned.insert(); returned.submit()
        self.assertEqual(actions._current_maximum(frappe.get_doc("Purchase Order", po.name, for_update=True), "Purchase Invoice")[po.items[0].name], 7)
        returned.cancel()
        pi.reload(); pi.cancel()
        self.assertEqual(actions._current_maximum(frappe.get_doc("Purchase Order", po.name, for_update=True), "Purchase Invoice")[po.items[0].name], 10)

    def test_native_uom_differences_fall_back_without_quantity_or_amount_conversion(self):
        po = self.po()
        pr = make_purchase_receipt(po.name).insert()
        pr.submit()
        pr.items[0].conversion_factor = 2
        with self.assertRaises(frappe.ValidationError): actions._current_maximum(pr, "Purchase Invoice")
        pi = frappe.get_doc("Purchase Invoice", self.invoice(po, 2)[0].name)
        pi.items[0].conversion_factor = 2
        self.assertTrue(actions._advanced(pi, frappe.get_doc("Purchase Order", po.name)))
        self.assertFalse(frappe.db.count("GL Entry", {"voucher_type": "Purchase Invoice", "voucher_no": pi.name}))


if __name__ == "__main__":
    unittest.main(verbosity=2)
