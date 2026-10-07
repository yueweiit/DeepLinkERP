"""Optional native cost capability and existing trusted approval adapters."""
import importlib
import copy
import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import frappe
from deeplinkerp_branding.tests import test_crossborder_progress as native_boundary
from deeplinkerp_branding.services import purchase_source_service, purchase_order_progress


def logistics():
    try:
        return importlib.import_module("deeplinkerp_branding.services.purchase_fulfilment_logistics")
    except ImportError:
        raise AssertionError("The optional native logistics capability adapter is missing") from None


def source_context(**values):
    return dict(root_kind="logistics", root_source_id="source-1", corp_id="corp", instance_id="instance",
        source_snapshot="snapshot", fingerprint="source-version-1", available=True, approved=True, invalid=False, **values)


LINK = native_boundary.LINK
api = native_boundary.api


class FulfilmentLogisticsTests(unittest.TestCase):
    setUp = native_boundary.CrossborderProgressTests.setUp
    association = native_boundary.CrossborderProgressTests.association
    def cost(self):
        self.memory.installed_cost = True
        self.memory.add("Overseas Cost Batch", "BATCH", source_type="oa_logistics", source_data_id="source-1",
            source_corp_id="corp", source_instance_id="instance", source_approval_status="COMPLETED", current_version="CV",
            extra_json="{}")
        self.stack.enter_context(patch.object(frappe, "get_installed_apps", return_value=["deeplinkerp_branding", "overseas_costing"]))
        self.context = source_context()
        self.detail = {"ok": True, "source_updated_at": "2026-10-07", "main_approval": {
            "corp_id": "corp", "instance_id": "instance", "excluded": False, "effective_status": "APPROVED",
            "timeline": [{"source_id": "comment-1", "user_name": "Operator", "user_id": "1",
                "operation_time": "2026-10-07", "remark": "10 Nos 已到 FACTORY"}]}}
        self.effective = SimpleNamespace(current_source_bundle=Mock(side_effect=lambda *args, **kwargs: {"context": self.context}),
                                        approval_detail_for_bundle=Mock(return_value=self.detail))
        self.approval = SimpleNamespace(get_batch_dingtalk_approval_detail=Mock(side_effect=lambda *args: self.detail))
        self.stack.enter_context(patch.object(logistics(), "_cost_modules", return_value=(self.effective, self.approval)))

    def test_missing_native_cost_doctype_is_capability_warning_before_any_upstream_import(self):
        module = logistics()
        with patch.object(module, "_cost_modules") as upstream:
            result = module.local_source("PRIVATE-BATCH")
        self.assertTrue(result["warning"])
        self.assertNotIn("PRIVATE-BATCH", json.dumps(result))
        upstream.assert_not_called()

    def test_existing_link_on_site_without_cost_schema_has_capability_warning_without_overlay(self):
        self.cost()
        self.association(cost_batch="BATCH")
        self.memory.installed_cost = False
        result = purchase_order_progress.get_order_progress(["EXT"])["EXT"]
        self.assertIn("海外成本", json.dumps(result, ensure_ascii=False))
        self.assertNotIn("BATCH", json.dumps(result))

    def test_list_reads_cache_only_and_completed_comments_refresh_through_existing_adapter(self):
        self.cost()
        record = self.association(cost_batch="BATCH")
        first = api().refresh_logistics(record["name"], record["modified"])
        self.assertEqual(self.approval.get_batch_dingtalk_approval_detail.call_count, 1)
        self.detail["main_approval"]["timeline"].append({**self.detail["main_approval"]["timeline"][0]})
        api().refresh_logistics(record["name"], first["modified"])
        self.assertEqual(self.approval.get_batch_dingtalk_approval_detail.call_count, 2)
        result = purchase_order_progress.get_order_progress(["EXT"])["EXT"]
        self.assertEqual(self.approval.get_batch_dingtalk_approval_detail.call_count, 2)
        self.assertEqual(result["receipt_logistics"][0]["state"], "reported")
        self.assertEqual(result["receipt_logistics"][0]["native_receipt"]["state"], "none")
        snapshot = json.loads(self.memory.records[LINK, record["name"]]["snapshot_json"])
        self.assertEqual(len(snapshot["timeline"]), 1)

    def test_expense_root_cannot_masquerade_as_international_logistics(self):
        self.cost()
        self.context["root_kind"] = "expense"
        snapshot = logistics().refresh_source("BATCH", self.context)
        self.assertEqual(snapshot["state"], "unavailable")
        self.assertEqual(snapshot["quantities"], [])
        self.effective.approval_detail_for_bundle.assert_called_once()
        self.approval.get_batch_dingtalk_approval_detail.assert_not_called()

    def test_batch_calculation_status_is_never_shipping_state_and_source_changes_are_stale(self):
        self.cost()
        record = self.association(cost_batch="BATCH")
        api().refresh_logistics(record["name"], record["modified"])
        self.memory.records["Overseas Cost Batch", "BATCH"]["status"] = "Calculated"
        self.context["fingerprint"] = "changed"
        result = purchase_order_progress.get_order_progress(["EXT"])["EXT"]
        self.assertEqual(result["receipt_logistics"][0]["state"], "stale")
        self.assertEqual(result["receipt_logistics"][0]["reported_quantities"], [])

    def test_detail_and_same_batch_rebind_cannot_make_changed_source_evidence_current(self):
        self.cost()
        record = self.association(cost_batch="BATCH")
        record = api().refresh_logistics(record["name"], record["modified"])
        record = api().set_manual_node(record["name"], record["modified"], "review", "独立手工核对")
        original = copy.deepcopy(self.memory.records[LINK, record["name"]])
        original_context = dict(self.context)
        changes = (("fingerprint", "changed"), ("root_source_id", "source-2"),
            ("source_snapshot", "snapshot-2"), ("cost_version", "version-2"),
            ("binding_revision", 2), ("approved", False), ("available", False), ("invalid", True))
        for field, value in changes:
            with self.subTest(field=field):
                self.memory.records[LINK, record["name"]] = copy.deepcopy(original)
                self.context = {**original_context, field: value}
                detail = api().get_link_detail(record["name"])
                self.assertEqual(detail["snapshot"]["state"], "stale")
                self.assertEqual(detail["snapshot"]["quantities"], [])
                progress = purchase_order_progress.get_order_progress(["EXT"])["EXT"]
                self.assertEqual(progress["receipt_logistics"][0]["state"], "stale")
                self.assertEqual(progress["receipt_logistics"][0]["reported_quantities"], [])
                self.assertEqual(self.memory.records[LINK, record["name"]]["snapshot_json"], original["snapshot_json"])
                rebound = api().save_link(external_order="EXT", external_item="EXT-I", purchasing_company="BUYER",
                    beneficiary_company="FACTORY", flow_kind="external_internal", internal_order="INT",
                    internal_item="INT-I", allocated_qty=10, expected_modified="v1", expected_internal_modified="v1",
                    name=record["name"], expected_link_modified=record["modified"], cost_batch="BATCH")
                stored = self.memory.records[LINK, record["name"]]
                self.assertEqual(json.loads(stored["snapshot_json"]), {})
                self.assertIn("comment-1", stored["audit_json"], "prior evidence is retained only as private audit")
                self.assertEqual(stored["manual_nodes_json"], original["manual_nodes_json"])
                self.assertNotEqual(api().get_link_detail(record["name"])["snapshot"].get("state"), "reported")
                progress = purchase_order_progress.get_order_progress(["EXT"])["EXT"]
                self.assertEqual(progress["receipt_logistics"][0]["reported_quantities"], [])
                if field == "fingerprint":
                    api().refresh_logistics(record["name"], rebound["modified"])
                    self.assertEqual(api().get_link_detail(record["name"])["snapshot"]["state"], "reported")

    def test_old_snapshot_is_stale_even_if_binding_was_already_updated_to_current_context(self):
        self.cost()
        record = self.association(cost_batch="BATCH")
        record = api().refresh_logistics(record["name"], record["modified"])
        self.context = {**self.context, "fingerprint": "current"}
        stored = self.memory.records[LINK, record["name"]]
        versions = json.loads(stored["source_versions_json"])
        versions["logistics"] = self.context
        stored["source_versions_json"] = json.dumps(versions)
        self.assertEqual(api().get_link_detail(record["name"])["snapshot"]["state"], "stale")
        self.assertEqual(purchase_order_progress.get_order_progress(["EXT"])["EXT"]["receipt_logistics"][0]["state"], "stale")

    def test_cost_capability_and_context_checks_are_request_local_not_repeated_per_link(self):
        self.cost()
        record = self.association(cost_batch="BATCH", allocated_qty=4)
        original = self.memory.records[LINK, record["name"]]
        self.memory.records[LINK, "LINK-OTHER"] = {**original, "name": "LINK-OTHER",
            "allocated_qty": "6", "allocated_stock_qty": "6"}
        self.effective.current_source_bundle.reset_mock()
        with patch.object(frappe.db, "exists", wraps=self.memory.exists) as exists:
            purchase_order_progress.get_order_progress(["EXT"])
        self.assertEqual(sum(call.args == ("DocType", "Overseas Cost Batch") for call in exists.call_args_list), 1)
        self.assertEqual(self.effective.current_source_bundle.call_count, 1)
        self.effective.current_source_bundle.reset_mock()
        with patch.object(frappe.db, "exists", wraps=self.memory.exists) as exists:
            api().get_link_detail(record["name"])
        self.assertEqual(sum(call.args == ("DocType", "Overseas Cost Batch") for call in exists.call_args_list), 1)
        self.assertEqual(self.effective.current_source_bundle.call_count, 1)

    def test_reported_destination_must_match_the_linked_native_company(self):
        self.cost()
        self.detail["main_approval"]["timeline"][0]["remark"] = "10 Nos 已到 OTHER FACTORY"
        record = self.association(cost_batch="BATCH")
        api().refresh_logistics(record["name"], record["modified"])
        result = purchase_order_progress.get_order_progress(["EXT"])["EXT"]
        self.assertEqual(result["receipt_logistics"][0]["state"], "review")
        self.assertEqual(result["receipt_logistics"][0]["reported_quantities"], [])

    def test_upstream_pending_approval_does_not_inherit_cached_approved_eligibility(self):
        self.cost()
        self.detail["main_approval"]["effective_status"] = "RUNNING"
        snapshot = logistics().refresh_source("BATCH", self.context)
        self.assertEqual(snapshot["state"], "stale")
        self.assertEqual(snapshot["quantities"], [])

    def test_complete_refresh_and_list_review_negation_damage_and_ambiguous_quantities(self):
        self.cost()
        record = self.association(cost_batch="BATCH")
        negative_phrases = ("hadn't arrived at", "weren't received at", "couldn't have arrived at",
            "didn't say it arrived at", "don't confirm it arrived at", "isn't received at", "aren't received at",
            "wasn't received at", "can't have arrived at", "won't be received at", "wouldn't have arrived at",
            "hasn't arrived at", "haven't arrived at")
        english = tuple("10 Nos " + change(phrase).replace("'", quote) + " FACTORY"
            for phrase in negative_phrases for quote in ("'", "’", "‘") for change in (str.lower, str.upper))
        shortage = ("10 Nos llegó FACTORY, faltaron piezas", "10 Nos llegó FACTORY, FALTABAN piezas",
            "10 Nos llegó FACTORY, faltó material", "10 Nos 已到 FACTORY，少了",
            "10 Nos 已到 FACTORY，缺件", "10 Nos 已到 FACTORY，数量不足", "10 Nos had not arrived at FACTORY")
        for text in ("10 Nos never arrived at FACTORY", "10 Nos nunca llegó FACTORY",
                     "10 Nos 不曾到达 FACTORY", "10 Nos 已到 FACTORY，但破损",
                     "1.000 件 已到 FACTORY", "-10 件；2 Nos 已到 FACTORY",
                     "10 Nos haven't arrived at FACTORY", "10 Nos HASN’T arrived at FACTORY",
                     "10 Nos haven’t arrived at FACTORY", "10 Nos Ya llegó FACTORY, faltan piezas",
                     "1 234 件 已到 FACTORY", "1\u202f234 件 已到 FACTORY") + english + shortage:
            with self.subTest(text=text):
                self.detail["main_approval"]["timeline"][0]["remark"] = text
                record = api().refresh_logistics(record["name"], record["modified"])
                result = purchase_order_progress.get_order_progress(["EXT"])["EXT"]
                self.assertEqual(result["receipt_logistics"][0]["state"], "review")
                self.assertEqual(result["receipt_logistics"][0]["reported_quantities"], [])
                snapshot = json.loads(self.memory.records[LINK, record["name"]]["snapshot_json"])
                self.assertEqual(snapshot["timeline"][0]["raw"]["remark"], text)
                self.assertEqual(snapshot["timeline"][0]["raw"]["user_name"], "Operator")

    def test_missing_optional_schema_keeps_evidence_and_allows_manual_disable_and_remove_binding(self):
        self.cost()
        record = self.association(cost_batch="BATCH")
        record = api().refresh_logistics(record["name"], record["modified"])
        original = copy.deepcopy(self.memory.records[LINK, record["name"]])
        self.memory.installed_cost = False
        for action in ("manual", "disable", "remove", "refresh", "detail"):
            with self.subTest(action=action):
                self.memory.records[LINK, record["name"]] = copy.deepcopy(original)
                try:
                    if action == "manual":
                        result = api().set_manual_node(record["name"], record["modified"], "review", "独立人工核对")
                    elif action == "disable":
                        result = api().disable_link(record["name"], record["modified"], "能力暂时缺失")
                    elif action == "remove":
                        result = api().save_link(external_order="EXT", external_item="EXT-I", purchasing_company="BUYER",
                            beneficiary_company="FACTORY", flow_kind="external_internal", internal_order="INT",
                            internal_item="INT-I", allocated_qty=10, expected_modified="v1", expected_internal_modified="v1",
                            name=record["name"], expected_link_modified=record["modified"], cost_batch=None)
                    elif action == "refresh":
                        result = api().refresh_logistics(record["name"], record["modified"])
                    else:
                        result = api().get_link_detail(record["name"])
                except frappe.ValidationError as error:
                    self.fail("Missing optional schema must not block independent actions: " + str(error))
                self.assertIn("海外成本", json.dumps(result.get("warnings", []), ensure_ascii=False))
                stored = self.memory.records[LINK, record["name"]]
                if action == "remove":
                    self.assertFalse(stored.get("cost_batch"))
                    self.assertIn("comment-1", stored["audit_json"], "old evidence remains in private audit storage")
                else:
                    self.assertEqual(stored["snapshot_json"], original["snapshot_json"])
                if action == "detail":
                    self.assertNotEqual(result["snapshot"]["state"], "reported")
                    self.assertEqual(result["snapshot"]["quantities"], [])
                progress = purchase_order_progress.get_order_progress(["EXT"])["EXT"]
                self.assertNotIn('"state": "reported"', json.dumps(progress))

    def test_new_cost_binding_requires_capability_and_existing_native_batch_denial_is_never_bypassed(self):
        self.cost()
        record = self.association(cost_batch="BATCH")
        self.memory.installed_cost = False
        self.memory.po("EXT2")
        with self.assertRaisesRegex(frappe.ValidationError, "海外成本"):
            api().save_link(external_order="EXT2", external_item="EXT2-I", purchasing_company="BUYER",
                beneficiary_company="FACTORY", flow_kind="external_internal", internal_order="INT", internal_item="INT-I",
                allocated_qty=1, expected_modified="v1", expected_internal_modified="v1", cost_batch="BATCH")
        self.memory.installed_cost = True
        self.memory.denied.add(("Overseas Cost Batch", "BATCH", "read"))
        with patch.object(frappe, "get_installed_apps", return_value=["deeplinkerp_branding"]):
            with self.assertRaises(frappe.PermissionError):
                api().set_manual_node(record["name"], record["modified"], "review", "不可绕过存在的原生权限")

    def test_denied_cost_batch_or_hidden_source_fields_have_no_names_or_payload(self):
        self.cost()
        record = self.association(cost_batch="BATCH")
        for denied in (True, False):
            if denied:
                self.memory.denied.add(("Overseas Cost Batch", "BATCH", "read"))
            else:
                self.memory.denied.clear(); self.memory.hidden["Overseas Cost Batch", "read"] = {"extra_json"}
            result = purchase_order_progress.get_order_progress(["EXT"])["EXT"]
            self.assertNotIn("BATCH", json.dumps(result))
            self.assertEqual(result["internal"][0]["state"], "restricted")
        self.approval.get_batch_dingtalk_approval_detail.assert_not_called()

    def test_bounded_refresh_fetches_distinct_batch_once_and_preserves_all_manual_nodes(self):
        self.cost()
        record = self.association(cost_batch="BATCH", allocated_qty=4)
        api().set_manual_node(record["name"], record["modified"], "reported_arrival", "电话核对", qty=4, uom="Nos")
        raw = self.memory.records[LINK, record["name"]]
        other = {**raw, "name": "LINK-OTHER", "allocated_qty": "6", "allocated_stock_qty": "6"}
        self.memory.records[LINK, "LINK-OTHER"] = other
        original_manual = raw["manual_nodes_json"]
        with patch.object(logistics().time, "monotonic", return_value=100):
            result = logistics().refresh_cached_logistics(deadline=200)
        self.assertEqual(result["batches"], 1)
        self.assertEqual(self.approval.get_batch_dingtalk_approval_detail.call_count, 1)
        self.assertEqual(self.memory.records[LINK, record["name"]]["manual_nodes_json"], original_manual)
        self.assertEqual(self.memory.records[LINK, "LINK-OTHER"]["manual_nodes_json"], original_manual)
        with patch.object(logistics().time, "monotonic", return_value=199):
            result = logistics().refresh_cached_logistics(deadline=200)
        self.assertEqual(result["batches"], 0)

    def test_quota_failure_rolls_back_one_link_and_retains_source_sync_and_other_batches(self):
        self.cost()
        bad = self.association(cost_batch="BATCH")
        for index, batch in ((2, "BATCH"), (3, "BATCH2")):
            self.memory.po("EXT" + str(index))
            self.memory.po("INT" + str(index), "FACTORY", "INTERNAL", currency="MXN")
            if batch == "BATCH2":
                self.memory.add("Overseas Cost Batch", batch, **{key: value for key, value in
                    self.memory.records["Overseas Cost Batch", "BATCH"].items() if key not in ("doctype", "name")})
            api().save_link(external_order="EXT" + str(index), external_item="EXT" + str(index) + "-I",
                purchasing_company="BUYER", beneficiary_company="FACTORY", flow_kind="external_internal",
                internal_order="INT" + str(index), internal_item="INT" + str(index) + "-I", allocated_qty=10,
                expected_modified="v1", expected_internal_modified="v1", cost_batch=batch)
        original_bad = copy.deepcopy(self.memory.records[LINK, bad["name"]])
        self.memory.records["Purchase Order", "EXT"]["items"][0]["qty"] = 4
        self.approval.get_batch_dingtalk_approval_detail.reset_mock()

        def sync_marker():
            self.memory.records["Purchase Order", "EXT"]["title"] = "source cache already synced"

        with patch.object(frappe, "conf", frappe._dict(purchase_source_sync_enabled=True)), \
             patch.object(frappe, "set_user"), patch.object(purchase_source_service, "sync_purchase_sources", side_effect=sync_marker), \
             patch.object(logistics().time, "monotonic", return_value=100), patch.object(api(), "_save", wraps=api()._save) as save:
            try:
                purchase_source_service.scheduled_sync()
            except frappe.ValidationError as error:
                self.fail("one expected native quota conflict must not abort source sync: " + str(error))
        self.assertEqual(self.memory.records["Purchase Order", "EXT"]["title"], "source cache already synced")
        self.assertEqual(self.memory.records[LINK, bad["name"]], original_bad)
        good = [row for (dt, name), row in self.memory.records.items() if dt == LINK and name != bad["name"]]
        self.assertEqual([json.loads(row["snapshot_json"])["state"] for row in good], ["reported", "reported"])
        self.assertEqual(save.call_count, 2, "the rejected link never reaches save or post-save callback registration")
        self.assertEqual(len(self.memory.rollbacks), 1)
        self.assertEqual(self.memory.savepoints, {})
        self.assertEqual(self.approval.get_batch_dingtalk_approval_detail.call_count, 2)

    def test_scheduler_cas_change_returns_generic_warning_after_parent_and_link_locks(self):
        self.cost()
        record = self.association(cost_batch="BATCH")
        original_get_doc = self.memory.get_doc

        def concurrently_changed(dt, name=None, **kwargs):
            if dt == LINK and kwargs.get("for_update"):
                self.memory.records[dt, name]["modified"] = "concurrent"
            return original_get_doc(dt, name, **kwargs)

        with patch.object(frappe, "get_doc", side_effect=concurrently_changed), \
             patch.object(logistics().time, "monotonic", return_value=100):
            try:
                result = logistics().refresh_cached_logistics(deadline=200)
            except frappe.ValidationError as error:
                self.fail("expected stale CAS must be isolated to its savepoint: " + str(error))
        self.assertEqual(result["links"], 0)
        self.assertTrue(result["warnings"])
        self.assertNotIn(record["name"], json.dumps(result["warnings"]))
        self.assertNotIn("BATCH", json.dumps(result["warnings"]))
        self.assertEqual(len(self.memory.rollbacks), 1)
        self.assertEqual(self.memory.locks[-3:], [("Purchase Order", "EXT"), ("Purchase Order", "INT"), (LINK, record["name"])])

    def test_unexpected_permission_and_database_errors_are_not_masked_as_skipped_refresh(self):
        from pymysql.err import OperationalError
        self.cost()
        self.association(cost_batch="BATCH")
        self.memory.denied.add(("Company", "FACTORY", "read"))
        with patch.object(logistics().time, "monotonic", return_value=100):
            with self.assertRaises(frappe.PermissionError):
                logistics().refresh_cached_logistics(deadline=200)
        self.memory.denied.clear()
        with patch.object(frappe.db, "sql", side_effect=OperationalError(1213, "deadlock; transaction aborted")), \
             patch.object(logistics().time, "monotonic", return_value=100):
            with self.assertRaises(OperationalError):
                logistics().refresh_cached_logistics(deadline=200)
        self.assertEqual(self.memory.rollbacks, [], "do not claim a destroyed DB transaction was preserved by a savepoint")

    def test_missing_optional_source_is_a_generic_scheduler_warning_not_a_permission_bypass(self):
        self.cost()
        self.association(cost_batch="BATCH")
        del self.memory.records["Overseas Cost Batch", "BATCH"]
        with patch.object(logistics().time, "monotonic", return_value=100):
            try:
                result = logistics().refresh_cached_logistics(deadline=200)
            except frappe.DoesNotExistError as error:
                self.fail("a disappeared optional source must not abort unrelated source-sync work: " + str(error))
        self.assertEqual(result["links"], 0)
        self.assertTrue(result["warnings"])
        self.assertNotIn("BATCH", json.dumps(result["warnings"]))
        self.approval.get_batch_dingtalk_approval_detail.assert_not_called()

    def test_existing_source_sync_keeps_switch_and_user_restore_and_adds_only_bounded_refresh(self):
        module = logistics()
        with patch.object(frappe, "conf", frappe._dict(purchase_source_sync_enabled=True)), \
             patch.object(frappe, "set_user") as user, patch.object(purchase_source_service, "sync_purchase_sources") as source, \
             patch.object(module, "refresh_cached_logistics", return_value={"batches": 0}) as refresh:
            purchase_source_service.scheduled_sync()
        source.assert_called_once(); refresh.assert_called_once()
        self.assertEqual(user.call_args_list[-1].args, ("buyer@example.test",))
        with patch.object(frappe, "conf", frappe._dict(purchase_source_sync_enabled=False)), \
             patch.object(module, "refresh_cached_logistics") as refresh:
            purchase_source_service.scheduled_sync()
        refresh.assert_not_called()


if __name__ == "__main__":
    unittest.main()
