"""Prepared native checks, run only by the release owner on the synthetic QA site.

No migration or production connection. Tests create isolated native drafts and
test-only masters inside their rollback transaction; the APIs themselves must
leave PO/PR/PI/PE/GL/stock/master counts unchanged.
"""
import json
import unittest
from unittest.mock import patch

import frappe
from frappe.client import get as native_get
from deeplinkerp_branding.services import purchase_fulfilment_service as service
from deeplinkerp_branding.services.purchase_order_progress import get_order_progress

BUYER = "QA Operating China"
FACTORY = "QA Operating Mexico"
ITEM = "QA-JOINT-PO-ITEM"


def require_qa():
    if frappe.local.site != "operating-expenses-qa.localhost" or frappe.conf.db_host != "db":
        raise RuntimeError("Strict isolated synthetic QA site only")


class NativeCrossborderProgressQA(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        require_qa()
        if not frappe.db.exists("DocType", service.DOCTYPE):
            raise RuntimeError("Release owner must install the new DocType on QA before this test")
        for doctype, name in (("Company", BUYER), ("Company", FACTORY), ("Item", ITEM),
                              ("Supplier", "QA Operating Supplier")):
            if not frappe.db.exists(doctype, name):
                raise RuntimeError("Existing synthetic procurement fixture is required")

    def setUp(self):
        require_qa(); frappe.set_user("Administrator")
        supplier = frappe.get_all("Supplier", filters={"is_internal_supplier": 1, "represents_company": BUYER},
                                  pluck="name", limit_page_length=1)
        self.supplier = supplier[0] if supplier else frappe.get_doc({"doctype": "Supplier",
            "supplier_name": "QA Fulfilment China Seller", "supplier_type": "Company",
            "supplier_group": frappe.db.get_value("Supplier", "QA Operating Supplier", "supplier_group"),
            "is_internal_supplier": 1, "represents_company": BUYER,
            "companies": [{"company": FACTORY}]}).insert().name
        self.external = self.po(BUYER, "QA Operating Supplier", 10)
        self.internal = self.po(FACTORY, self.supplier, 10)
        self.counts = {dt: frappe.db.count(dt) for dt in ("Purchase Order", "Sales Order", "Purchase Receipt",
            "Purchase Invoice", "Sales Invoice", "Payment Entry", "GL Entry", "Stock Ledger Entry", "Stock Entry",
            "Company", "Supplier", "Customer", "Item", "Warehouse")}

    def tearDown(self):
        frappe.db.rollback(); frappe.set_user("Administrator")

    def po(self, company, supplier, qty):
        currency = frappe.db.get_value("Company", company, "default_currency")
        return frappe.get_doc({"doctype": "Purchase Order", "company": company, "supplier": supplier,
            "currency": currency, "schedule_date": "2026-10-08", "items": [{"item_code": ITEM,
                "qty": qty, "uom": "Nos", "rate": 10, "schedule_date": "2026-10-08"}]}).insert()

    def associate(self, qty=10):
        return service.save_link(external_order=self.external.name, external_item=self.external.items[0].name,
            purchasing_company=BUYER, beneficiary_company=FACTORY, flow_kind="external_internal",
            internal_order=self.internal.name, internal_item=self.internal.items[0].name, allocated_qty=qty,
            expected_modified=str(self.external.modified), expected_internal_modified=str(self.internal.modified))

    def no_business_writes(self):
        for doctype, count in self.counts.items():
            self.assertEqual(frappe.db.count(doctype), count, doctype)

    def user(self, companies):
        name = "qa-fulfilment-purchase@example.test"
        if not frappe.db.exists("User", name):
            frappe.get_doc({"doctype": "User", "email": name, "first_name": "QA Fulfilment",
                "send_welcome_email": 0, "roles": [{"role": "Purchase User"}, {"role": "Purchase Manager"}]}).insert()
        for company in companies:
            if not frappe.db.exists("User Permission", {"user": name, "allow": "Company", "for_value": company}):
                frappe.get_doc({"doctype": "User Permission", "user": name, "allow": "Company", "for_value": company}).insert()
        frappe.set_user(name)
        return name

    def test_native_draft_quote_price_confirmation_and_no_business_writes(self):
        linked = self.associate()
        confirmed = service.confirm_native_price(linked["name"], str(self.external.modified),
            str(self.internal.modified), linked["modified"])
        progress = get_order_progress([self.external.name])[self.external.name]
        self.assertEqual(progress["internal"][0]["state"], "draft_quote")
        self.assertIsNone(progress["internal"][0]["payable_outstanding"])
        self.assertEqual(confirmed["active"], 1)
        self.no_business_writes()

    def test_native_current_allocation_cap_and_version_refuse(self):
        self.associate(6)
        with self.assertRaises(frappe.ValidationError): self.associate(5)
        self.external.items[0].qty = 9; self.external.save()
        with self.assertRaises(frappe.ValidationError):
            service.save_link(external_order=self.external.name, external_item=self.external.items[0].name,
                purchasing_company=BUYER, beneficiary_company=FACTORY, flow_kind="external_internal",
                internal_order=self.internal.name, internal_item=self.internal.items[0].name, allocated_qty=3,
                expected_modified="old", expected_internal_modified=str(self.internal.modified))
        self.no_business_writes()

    def test_native_rest_import_delete_rename_cannot_forge_managed_association(self):
        linked = self.associate()
        doc = frappe.get_doc(service.DOCTYPE, linked["name"])
        doc.allocated_qty = "999"
        with self.assertRaises(frappe.PermissionError): doc.save()
        with self.assertRaises(frappe.PermissionError): frappe.delete_doc(service.DOCTYPE, doc.name)
        with self.assertRaises(frappe.PermissionError): service.protect_link_identity(doc)
        self.no_business_writes()

    def test_native_purchase_user_can_confirm_but_raw_rest_has_no_private_json(self):
        self.user([BUYER, FACTORY])
        linked = self.associate()
        service.confirm_native_price(linked["name"], str(self.external.modified), str(self.internal.modified), linked["modified"])
        self.assertTrue(frappe.db.get_value(service.DOCTYPE, linked["name"], "price_confirmation_json"))
        raw = native_get(service.DOCTYPE, linked["name"])
        for field in service.PRIVATE_FIELDS:
            # Native field permission removes the value. Frappe's as_dict may
            # still serialize schema-known fields with None; no private JSON
            # content is permitted in either serialization shape.
            self.assertIsNone(raw.get(field), field)
        detail = service.get_link_detail(linked["name"])
        self.assertTrue(detail["price_confirmation"]["by"])
        self.no_business_writes()

    def test_native_denied_company_has_generic_warning_and_no_internal_names(self):
        self.associate()
        self.user([BUYER])
        progress = get_order_progress([self.external.name])[self.external.name]
        payload = json.dumps(progress)
        self.assertNotIn(FACTORY, payload); self.assertNotIn(self.internal.name, payload)
        self.assertEqual(progress["internal"][0]["state"], "restricted")
        self.no_business_writes()

    def test_native_manual_node_refresh_keeps_server_audit_and_no_receipt_or_gl(self):
        linked = self.associate()
        updated = service.set_manual_node(linked["name"], linked["modified"], "reported_arrival", "QA 电话核对", qty=4, uom="Nos")
        before = frappe.db.get_value(service.DOCTYPE, linked["name"], "manual_nodes_json")
        service.refresh_logistics(linked["name"], updated["modified"])
        self.assertEqual(frappe.db.get_value(service.DOCTYPE, linked["name"], "manual_nodes_json"), before)
        self.assertEqual(json.loads(before)[0]["by"], "Administrator")
        self.no_business_writes()

    def test_native_unrelated_parent_save_preserves_price_but_real_price_change_invalidates(self):
        linked = self.associate()
        service.confirm_native_price(linked["name"], str(self.external.modified), str(self.internal.modified), linked["modified"])
        self.internal.remarks = "QA receipt/payment progress note"; self.internal.save()
        row = get_order_progress([self.external.name])[self.external.name]["internal"][0]
        self.assertEqual(row["state"], "draft_quote")
        self.internal.items[0].rate = 11; self.internal.save()
        row = get_order_progress([self.external.name])[self.external.name]["internal"][0]
        self.assertEqual(row["state"], "price_stale")
        self.no_business_writes()

    def test_native_optional_refresh_skips_stale_allocation_without_rolling_back_source_cache(self):
        from deeplinkerp_branding.services import purchase_fulfilment_logistics as logistics
        from deeplinkerp_branding.services import purchase_source_service as sources

        bad = self.associate()
        good_external = self.po(BUYER, "QA Operating Supplier", 4)
        good_internal = self.po(FACTORY, self.supplier, 4)
        good = service.save_link(external_order=good_external.name, external_item=good_external.items[0].name,
            purchasing_company=BUYER, beneficiary_company=FACTORY, flow_kind="external_internal",
            internal_order=good_internal.name, internal_item=good_internal.items[0].name, allocated_qty=4,
            expected_modified=str(good_external.modified), expected_internal_modified=str(good_internal.modified))
        context = {"root_kind": "logistics", "root_source_id": "qa-source", "corp_id": "qa-corp",
            "instance_id": "qa-instance", "fingerprint": "qa-version", "available": True,
            "approved": True, "invalid": False}
        snapshot = {"version": 1, "state": "reported", "warnings": [], "timeline": [],
            "quantities": [], "confirmed": False, "erp_received": False, "source_context": context}
        # The optional upstream adapter is stubbed; authorization, allocation
        # locks, savepoints and managed writes use the actual synthetic DB.
        with patch.object(logistics, "local_source", return_value={"context": context, "warning": ""}):
            for linked in (bad, good):
                doc = frappe.get_doc(service.DOCTYPE, linked["name"])
                versions = json.loads(doc.source_versions_json)
                versions["logistics"] = context
                doc.cost_batch = "QA-FULFILMENT-TIMER-BATCH"
                doc.source_versions_json = json.dumps(versions)
                with service.managed_write():
                    doc.save()
            self.external.items[0].qty = 1
            self.external.save()
            marker = "QA-source-cache-survived"
            def cache_source():
                frappe.db.set_value("Purchase Order", self.external.name, "title", marker,
                    update_modified=False)
            with patch.dict(frappe.conf, {"purchase_source_sync_enabled": True}), \
                    patch.object(sources, "sync_purchase_sources", side_effect=cache_source), \
                    patch.object(logistics, "_available", return_value=True), \
                    patch.object(logistics, "_fresh_snapshot", return_value=snapshot) as fresh:
                sources.scheduled_sync()
            self.assertEqual(frappe.db.get_value("Purchase Order", self.external.name, "title"), marker)
            self.assertEqual(json.loads(frappe.db.get_value(service.DOCTYPE, good["name"], "snapshot_json"))["state"], "reported")
            self.assertEqual(json.loads(frappe.db.get_value(service.DOCTYPE, bad["name"], "snapshot_json") or "{}"), {})
            fresh.assert_called_once()
        for dt in ("Purchase Receipt", "Purchase Invoice", "Payment Entry", "GL Entry", "Stock Ledger Entry", "Stock Entry"):
            self.assertEqual(frappe.db.count(dt), self.counts[dt], dt)


if __name__ == "__main__":
    unittest.main()
