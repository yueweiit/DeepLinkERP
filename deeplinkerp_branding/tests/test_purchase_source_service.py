"""Native boundary tests: source evidence must not bypass purchase permissions."""
import json
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

import frappe
from deeplinkerp_branding.services import purchase_source_service as service


class PurchaseSourceServiceTests(unittest.TestCase):
    def setUp(self):
        # These boundary tests run both with an initialized native site and in
        # CI's site-free pytest process. Do not depend on thread-local DB/flags.
        self.db = Mock()
        self.db_patch = patch.object(frappe, "db", self.db)
        self.db_patch.start(); self.addCleanup(self.db_patch.stop)
        def throw(message, exc=frappe.ValidationError, **kwargs):
            raise exc(message)
        self.throw_patch = patch.object(frappe, "throw", side_effect=throw)
        self.throw_patch.start(); self.addCleanup(self.throw_patch.stop)
        date_patch=patch.object(frappe.utils,"nowdate",return_value="2026-10-06")
        date_patch.start(); self.addCleanup(date_patch.stop)
        self.source = dict(version="source-v1", eligible=True, currency="CNY", items=[dict(item_code="I",qty="2",uom="个",amount="100")],issues=[])
        self.doc = frappe._dict(name="OA", target_company="China", purchase_order=None,
                                custom_purchase_source_json=json.dumps(self.source), custom_cashier_payment_evidence="{}")

    def test_unapproved_or_changed_source_never_creates_order(self):
        for raw, expected in (({**self.source,"eligible":False},"source-v1"),(self.source,"old")):
            with patch.object(service,"_source",return_value=self.doc), patch.object(service,"_fresh_source",return_value=(raw,{})), patch.object(service,"_native") as native:
                with self.assertRaises(frappe.ValidationError):
                    service.create_purchase_order_from_source("OA",expected,"China","Supplier","CNY","2026-10-08",[{"item_code":"I","qty":2,"uom":"个","rate":50}])
                native.assert_not_called()

    def test_creation_uses_native_insert_draft_and_no_internal_commit(self):
        order = Mock(name="order"); order.name="PO-1"; order.docstatus=0
        with patch.object(service,"_source",return_value=self.doc), patch.object(service,"_fresh_source",return_value=(self.source,{})), patch.object(service,"_version",return_value="v1"), patch.object(service,"_native",return_value=frappe._dict(disabled=0)), patch.object(service,"_validate_items"), patch.object(service,"_write_fields"), patch.object(service,"_bind") as bind, patch.object(frappe,"new_doc",return_value=order), patch.object(frappe,"has_permission",return_value=True), patch.object(frappe.db,"commit") as commit:
            result=service.create_purchase_order_from_source("OA","v1","China","Supplier","CNY","2026-10-08",[{"item_code":"I","qty":2,"uom":"个","rate":50}])
            self.assertEqual(result,{"name":"PO-1","doctype":"Purchase Order"})
            order.insert.assert_called_once_with()
            order.submit.assert_not_called(); commit.assert_not_called()
            bind.assert_called_once()

    def test_company_mismatch_cannot_be_overridden_by_reason(self):
        with patch.object(service,"_source",return_value=self.doc), patch.object(service,"_fresh_source",return_value=(self.source,{})):
            with self.assertRaises(frappe.ValidationError):
                service.create_purchase_order_from_source("OA","source-v1","Mexico","Supplier","CNY","2026-10-08",[{"item_code":"I","qty":2,"uom":"个","rate":50}],"manual")

    def test_existing_link_is_idempotent_not_second_order(self):
        self.doc.purchase_order="PO-existing"
        with patch.object(service,"_source",return_value=self.doc), patch.object(service,"_native") as native, patch.object(frappe,"new_doc") as new:
            self.assertEqual(service.create_purchase_order_from_source("OA","v1","China","Supplier","CNY","2026-10-08",[])["name"],"PO-existing")
            native.assert_called_once_with("Purchase Order","PO-existing","read")
            new.assert_not_called()

    def test_historical_paid_evidence_requires_explicit_reconciliation(self):
        self.assertTrue(service.cashier_payment_reason({"paid_amount":"20","payment_evidence_status":"recorded"},None))
        self.assertTrue(service.cashier_payment_reason({"paid_amount":None,"payment_evidence_status":"unknown"},None))
        self.assertFalse(service.cashier_payment_reason({"paid_amount":"0","payment_evidence_status":"recorded"},None))
        self.assertFalse(service.cashier_payment_reason({"paid_amount":"20","payment_evidence_status":"recorded"},{"verified":True}))

    def test_cashier_snapshot_accepts_equivalent_timezone_serializations(self):
        from deeplinkerp_branding.services import operating_expenses
        until = "2026-10-06T09:00:00.123456+00:00"
        for returned in ("2026-10-06T09:00:00.123456Z", "2026-10-06T17:00:00.123456+08:00"):
            with self.subTest(returned=returned), patch.object(operating_expenses, "_request", return_value={
                "until": returned, "items": [{"source_id": "purchase-1"}], "end": True,
            }) as request:
                self.assertEqual(service._cashier_snapshot(until), [{"source_id": "purchase-1"}])
                self.assertEqual(request.call_args.args[1]["until"], until)
        self.db.commit.assert_not_called()

    def test_cashier_snapshot_rejects_different_or_unverifiable_instant(self):
        from deeplinkerp_branding.services import operating_expenses
        until = "2026-10-06T09:00:00.123456+00:00"
        for returned in ("2026-10-06T09:00:00.123457Z", "2026-10-06T09:00:00.123456", "invalid", None):
            with self.subTest(returned=returned), patch.object(operating_expenses, "_request", return_value={
                "until": returned, "items": [], "end": True,
            }):
                with self.assertRaisesRegex(frappe.ValidationError, "快照时间不符"):
                    service._cashier_snapshot(until)
        self.db.commit.assert_not_called()

    def test_source_refresh_does_not_overwrite_manual_fields(self):
        incoming={**self.source,"source_id":"oa:test","oa_identity":{"corp_id":"corp","process_instance_id":"instance"},"status":"COMPLETED","result":"agree"}
        self.doc.items=[{"qty":99}]; self.doc.target_company="Manual Company"
        with patch.object(service,"_cached_doc",return_value=self.doc), patch.object(frappe.db,"set_value") as save:
            service._cache_source(incoming,{},"Suggested Company")
            values=save.call_args.args[2]
            self.assertNotIn("items",values); self.assertNotIn("target_company",values)
            self.assertNotIn("payment_amount",values); self.assertNotIn("purchase_order",values)

    def test_source_sync_uses_small_pages_without_dropping_or_duplicating_sources(self):
        from deeplinkerp_branding.services import operating_expenses
        rows = [{"source_id": "source-" + str(index)} for index in range(201)]
        def read_page(connection, limit, until, cursor=None, **kwargs):
            start = int(cursor or 0)
            end = min(start + limit, len(rows))
            return rows[start:end], str(end) if end < len(rows) else None
        applicant = {"user_id": "u", "employee_name": "Synthetic"}
        def resolve(path, data):
            return {"items": [{**value, "status": "unknown"} for value in data["applicants"]]}
        with patch.object(frappe,"cache",Mock(lock=Mock(return_value=MagicMock()))), \
             patch.object(frappe,"local",SimpleNamespace(site="synthetic-source-test")), \
             patch.object(frappe,"get_meta",return_value=SimpleNamespace(has_field=lambda _: True)), \
             patch.object(operating_expenses,"_manager"), \
             patch.object(operating_expenses,"_oa_connection",return_value=SimpleNamespace(_connection=object())), \
             patch.object(operating_expenses,"_request",side_effect=resolve), \
             patch.object(service,"_cashier_snapshot",return_value=[]), \
             patch.object(service.oa,"read_page",side_effect=read_page) as read, \
             patch.object(service.oa,"resolution_applicant",return_value=applicant), \
             patch.object(service.contract,"in_scope",return_value=True), \
             patch.object(service,"_normalize",side_effect=lambda row: dict(row)), \
             patch.object(service.contract,"payment_evidence",return_value={}), \
             patch.object(service,"_cache_source") as save, \
             patch.object(service,"_reconcile_cached_sources") as reconcile:
            result = service.sync_purchase_sources()
        self.assertEqual(result["count"], 201)
        self.assertEqual([call.args[0]["source_id"] for call in save.call_args_list], [row["source_id"] for row in rows])
        self.assertEqual([call.args[1] for call in read.call_args_list], [100, 100, 100])
        self.assertEqual([call.kwargs["cursor"] for call in read.call_args_list], [None, "100", "200"])
        self.assertEqual(reconcile.call_args.args[2], {row["source_id"] for row in rows})
        self.db.commit.assert_not_called()

    def test_small_page_sync_keeps_original_twenty_thousand_source_bound(self):
        from deeplinkerp_branding.services import operating_expenses
        with patch.object(frappe,"cache",Mock(lock=Mock(return_value=MagicMock()))), \
             patch.object(frappe,"local",SimpleNamespace(site="synthetic-source-test")), \
             patch.object(frappe,"get_meta",return_value=SimpleNamespace(has_field=lambda _: True)), \
             patch.object(operating_expenses,"_manager"), \
             patch.object(operating_expenses,"_oa_connection",return_value=SimpleNamespace(_connection=object())), \
             patch.object(service,"_cashier_snapshot",return_value=[]), \
             patch.object(service.oa,"read_page",side_effect=lambda *args,**kwargs: ([], str(int(kwargs.get("cursor") or 0) + args[1]))) as read, \
             patch.object(service,"_reconcile_cached_sources") as reconcile:
            with self.assertRaisesRegex(frappe.ValidationError, "超过本次同步上限"):
                service.sync_purchase_sources()
        self.assertEqual(len(read.call_args_list), 200)
        self.assertEqual({call.args[1] for call in read.call_args_list}, {100})
        self.assertEqual(len(read.call_args_list) * read.call_args.args[1], 20000)
        reconcile.assert_not_called()
        self.db.commit.assert_not_called()

    def test_clearing_managed_payload_cannot_erase_provenance_guard(self):
        changed=frappe._dict(self.doc); changed.custom_purchase_source_json=""
        changed.get_doc_before_save=lambda:self.doc
        with self.assertRaises(frappe.PermissionError):
            service.validate_managed_source(changed)

    def test_native_approval_and_identity_fields_remain_protected(self):
        for key in ("approval_status","source_invalid","source_pending","source_stale","process_instance_id"):
            changed=frappe._dict(self.doc); changed[key]="changed"; changed.get_doc_before_save=lambda:self.doc
            with self.subTest(field=key), self.assertRaises(frappe.PermissionError): service.validate_managed_source(changed)

    def test_managed_company_permissions_are_registered(self):
        from deeplinkerp_branding import hooks
        self.assertEqual(hooks.permission_query_conditions.get("OA Purchase Request"),"deeplinkerp_branding.services.purchase_source_service.permission_query_conditions")
        self.assertEqual(hooks.has_permission.get("OA Purchase Request"),"deeplinkerp_branding.services.purchase_source_service.has_permission")

    def test_unmanaged_oa_retains_native_controller_permission(self):
        self.assertIs(service.has_permission(frappe._dict(name="legacy")),True)

    def test_managed_order_link_and_company_cannot_be_changed_via_native_save(self):
        old=frappe._dict(custom_oa_purchase_expense="OA",company="China")
        for changed in (frappe._dict(custom_oa_purchase_expense="",company="China"),frappe._dict(custom_oa_purchase_expense="Other",company="China"),frappe._dict(custom_oa_purchase_expense="OA",company="Mexico")):
            changed.get_doc_before_save=lambda:old
            with patch.object(frappe,"get_meta",return_value=Mock(has_field=lambda field:True)),patch.object(frappe.db,"get_value",return_value="source-1"),self.assertRaises(frappe.PermissionError):
                service.validate_managed_order(changed)

    def test_managed_order_link_updates_use_narrow_authorized_context(self):
        order=frappe._dict(custom_oa_purchase_expense="OA",company="China")
        order.get_doc_before_save=lambda:None
        with service.managed_write():
            service.validate_managed_order(order)

    def test_orders_without_source_do_not_require_optional_oa_app(self):
        order=frappe._dict(company="China"); order.get_doc_before_save=lambda:None
        with patch.object(frappe,"get_meta",side_effect=AssertionError("optional OA missing")):
            service.validate_managed_order(order)

    def test_managed_source_cannot_be_renamed_or_deleted_even_by_admin(self):
        for event in ("before_rename","on_trash"):
            with self.subTest(event=event),self.assertRaises(frappe.PermissionError):
                service.protect_managed_source_identity(self.doc,event,"old","new",False)

    def test_legacy_source_identity_operations_keep_native_behavior(self):
        service.protect_managed_source_identity(frappe._dict(name="legacy"),"before_rename")

    def test_binding_checks_native_field_write_permissions_before_any_mutation(self):
        order=frappe._dict(name="PO",company="China"); order.get=lambda key:None
        with patch.object(service,"_write_fields",side_effect=frappe.PermissionError), patch.object(frappe.db,"set_value") as save:
            with self.assertRaises(frappe.PermissionError): service._bind(self.doc,order,self.source,{})
            save.assert_not_called()

    def test_same_submitted_order_recheck_does_not_rewrite_native_provenance_field(self):
        order=Mock(); order.name="PO"; order.company="China"; order.docstatus=1
        order.get.return_value=self.doc.name
        order.meta.get_field.return_value=frappe._dict(allow_on_submit=0)
        with patch.object(service,"_write_fields"):
            service._bind(self.doc,order,self.source,{})
        order.save.assert_not_called()
        self.assertEqual(self.db.set_value.call_args.args[2][service.BOUND_FIELD],"source-v1")

    def test_original_payment_json_requires_native_payment_field_scope(self):
        self.doc.check_permission=Mock()
        fields={"target_company","purchase_order","approval_status","process_instance_id","currency","payment_amount",
                "detail_total_amount","items_json","processors_json","payee","description"}
        with patch.object(frappe,"get_doc",return_value=self.doc),patch.object(service,"get_permitted_fields",return_value=fields),patch.object(service,"_native"):
            with self.assertRaises(frappe.PermissionError): service.get_purchase_source_detail("OA")

    def test_attachment_denied_after_payment_permission_revoked_before_transport(self):
        from deeplinkerp_branding.services import operating_expenses
        with patch.object(operating_expenses,"_finance"),patch.object(service,"_source",return_value=self.doc),patch.object(frappe,"has_permission",return_value=False),patch.object(service,"_fresh_source") as fresh,patch.object(operating_expenses,"_request") as transport:
            with self.assertRaises(frappe.PermissionError): service.download_source_attachment("OA","file-1","v1")
            fresh.assert_not_called(); transport.assert_not_called()

    def test_attachment_control_is_disabled_without_finance_role(self):
        source={**self.source,"oa_identity":{"process_instance_id":"instance"}}
        self.doc.custom_purchase_source_json=json.dumps(source)
        self.doc.custom_cashier_payment_evidence=json.dumps({"version":"v1","attachments":[{"source_id":"file-1","url":"/api/integrations/erp/purchase-expenses/attachments/1"}]})
        self.doc.has_permission=lambda permission:True
        from deeplinkerp_branding.services import unified_purchase_service
        with patch.object(service,"_source",return_value=self.doc),patch.object(unified_purchase_service,"cashier_evidence_readable",return_value=True),patch.object(frappe,"session",frappe._dict(user="purchase@example.test")),patch.object(frappe,"get_roles",return_value=["Purchase User"]),patch.object(frappe,"has_permission",return_value=True):
            payload=service.get_purchase_source_detail("OA")
        self.assertFalse(payload["cashier"]["attachments"][0]["downloadable"])
        self.assertFalse(payload["can_reconcile"])

    def test_missing_source_is_invalidated_without_removing_manual_values(self):
        cached={**self.source,"source_id":"source-1","oa_identity":{"corp_id":"corp","process_instance_id":"instance"},"status":"COMPLETED"}
        row=frappe._dict(name="OA",custom_purchase_source_json=json.dumps(cached))
        with patch.object(frappe,"get_all",return_value=[row]),patch.object(service.oa,"read_page",return_value=([],None)),patch.object(service,"_cache_source") as save:
            service._reconcile_cached_sources(Mock(),"2026-10-06T00:00:00Z",set(),[])
            invalid=save.call_args.args[0]
            self.assertFalse(invalid["eligible"])
            self.assertEqual(invalid["items"],cached["items"])
            self.assertIn("不存在", "；".join(invalid["issues"]))

    def test_duplicate_local_legacy_instances_never_choose_arbitrary_binding(self):
        source={**self.source,"source_id":"source-1","oa_identity":{"corp_id":"corp","process_instance_id":"instance"},"instance_count":1}
        with patch.object(frappe.db,"get_value",side_effect=[None,"legacy-first"]),patch.object(frappe,"get_all",return_value=[frappe._dict(name="legacy-first"),frappe._dict(name="legacy-second")]),patch.object(frappe,"get_doc") as read:
            with self.assertRaises(frappe.ValidationError):service._cached_doc(source)
            read.assert_not_called()

    def test_explicit_detail_refresh_returns_current_version_without_cache_write(self):
        self.doc.has_permission=lambda permission:True
        current={**self.source,"oa_identity":{"process_instance_id":"instance"},"version":"new"}
        from deeplinkerp_branding.services import unified_purchase_service
        with patch.object(service,"_source",return_value=self.doc),patch.object(service,"_fresh_source",return_value=(current,{})) as fresh,patch.object(unified_purchase_service,"cashier_evidence_readable",return_value=False),patch.object(frappe,"session",frappe._dict(user="Administrator")),patch.object(frappe,"has_permission",return_value=True):
            payload=service.get_purchase_source_detail("OA",fresh=1)
        fresh.assert_called_once_with(self.doc)
        self.assertEqual(payload["version"],service._version(current,{}))
        self.assertEqual(payload["source"]["version"],"new")
        self.db.set_value.assert_not_called(); self.db.commit.assert_not_called()


if __name__ == "__main__": unittest.main()
