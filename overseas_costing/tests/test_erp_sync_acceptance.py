"""多站点 ERP 迁移与受控联调的离线验收测试。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from overseas_costing import install
from overseas_costing.scripts import test_purchase_order_writeback as local_writeback
from overseas_costing.services.batch_service import _build_erp_work_detail_state
from overseas_costing.services.erp_sync_service import (
    InMemorySyncStore,
    reconcile_legacy_document_candidates,
    verify_legacy_site_links_read_only,
)


ROOT = Path(__file__).resolve().parents[1]


def test_legacy_success_is_only_marked_unverified_and_fee_todos_are_preserved() -> None:
    original_extra = {
        "fee_work": {"affected_fee_count": 1, "todos": [{"code": "ACTUAL_AMOUNT_REQUIRED"}]},
        "other": {"keep": True},
    }

    result = install.build_legacy_erp_migration_update(
        {
            "name": "B-OLD",
            "writeback_status": "Success",
            "erp_target_doc": "PO-OLD",
            "extra_json": json.dumps(original_extra, ensure_ascii=False),
        }
    )
    migrated = json.loads(result["extra_json"])

    assert result["changed"] is True
    assert migrated["erp_sync_migration"]["legacy_link_status"] == "UNVERIFIED"
    assert migrated["fee_work"] == original_extra["fee_work"]
    assert migrated["other"] == original_extra["other"]
    work = _build_erp_work_detail_state(current_hash="H2", site_codes=["PROD"], links=[], requests=[])
    assert work["overall"] == "PENDING"
    assert work["sites"][0]["state"] == "CREATE_REQUIRED"

    legacy_work = _build_erp_work_detail_state(
        current_hash="H2",
        site_codes=["PROD"],
        links=[],
        requests=[],
        legacy_link_status="UNVERIFIED",
    )
    assert legacy_work["sites"][0]["state"] == "MANUAL_REQUIRED"


def test_legacy_migration_is_idempotent_and_never_touches_item_quantity_provenance() -> None:
    first = install.build_legacy_erp_migration_update(
        {"name": "B-OLD", "writeback_status": "Success", "extra_json": "{}"}
    )
    second = install.build_legacy_erp_migration_update(
        {"name": "B-OLD", "writeback_status": "Success", "extra_json": first["extra_json"]}
    )

    assert first["changed"] is True
    assert second["changed"] is False
    assert "actual_shipped_qty_mode" not in first["extra_json"]
    assert "quantity" not in first["extra_json"]


def test_migration_uses_local_database_only_without_password_or_http_access() -> None:
    class FakeDB:
        def __init__(self):
            self.updates = []
            self.commits = 0

        def exists(self, doctype, filters=None):
            if doctype == "DocType":
                return True
            if doctype == "Overseas Cost ERP Document Link":
                return False
            return False

        def set_value(self, doctype, name, fieldname, value, **kwargs):
            self.updates.append((doctype, name, fieldname, value, kwargs))

        def commit(self):
            self.commits += 1

    class FakeFrappe:
        def __init__(self):
            self.db = FakeDB()
            self.reads = 0

        def get_all(self, doctype, **kwargs):
            self.reads += 1
            assert doctype == "Overseas Cost Batch"
            return [{"name": "B-OLD", "writeback_status": "Success", "erp_target_doc": "PO-OLD", "extra_json": "{}"}]

        def get_doc(self, *args, **kwargs):  # Password/document reads are forbidden in migration.
            raise AssertionError("migration must not read site documents or Password fields")

    fake = FakeFrappe()
    result = install.mark_legacy_erp_links_unverified(frappe_module=fake)

    assert result == {"ok": True, "scanned": 1, "changed": 1}
    assert fake.db.commits == 1
    assert fake.db.updates[0][:3] == ("Overseas Cost Batch", "B-OLD", "extra_json")


def test_legacy_link_is_created_only_for_one_exact_read_only_candidate() -> None:
    expected = [
        {"stable_line_key": "L1", "quantity": 2},
        {"stable_line_key": "L2", "quantity": 3},
    ]
    candidate = {
        "name": "PO-LEGACY-1",
        "docstatus": 0,
        "items": [
            {"stable_line_key": "L1", "quantity": 2, "remote_row": "ROW-1"},
            {"stable_line_key": "L2", "quantity": 3, "remote_row": "ROW-2"},
        ],
    }
    store = InMemorySyncStore()

    result = reconcile_legacy_document_candidates(
        batch="B-OLD",
        site_code="PROD",
        expected_items=expected,
        candidates=[candidate],
        store=store,
    )

    assert result["status"] == "VERIFIED"
    assert {row["stable_line_key"] for row in store.links} == {"L1", "L2"}
    assert all(row["status"] == "VERIFIED" for row in store.links)
    assert {row["remote_row"] for row in store.links} == {"ROW-1", "ROW-2"}


def test_ambiguous_legacy_candidates_require_manual_work_and_create_no_link() -> None:
    expected = [{"stable_line_key": "L1", "quantity": 2}]
    candidates = [
        {"name": "PO-1", "items": expected},
        {"name": "PO-2", "items": expected},
    ]
    store = InMemorySyncStore()

    result = reconcile_legacy_document_candidates(
        batch="B-OLD", site_code="PROD", expected_items=expected, candidates=candidates, store=store
    )

    assert result["status"] == "MANUAL_REQUIRED"
    assert store.links == []


def test_legacy_site_verification_reads_each_site_and_links_only_exact_candidate() -> None:
    class ReadOnlyClient:
        def __init__(self):
            self.calls = []

        def lookup_legacy_purchase_candidates(self, payload, config):
            self.calls.append((payload, config["site_code"]))
            item = {"stable_line_key": payload["expected_items"][0]["stable_line_key"], "quantity": 1, "remote_row": "ROW-1"}
            if config["site_code"] == "PROD":
                return [{"name": "PO-P", "items": [item]}]
            return [{"name": "PO-E1", "items": [item]}, {"name": "PO-E2", "items": [item]}]

    preview = {
        "sites": [
            {"site_code": "PROD", "groups": [{"items": [{"stable_line_key": "P1", "effective_shipped_qty": 1}]}]},
            {"site_code": "ECOM", "groups": [{"items": [{"stable_line_key": "E1", "effective_shipped_qty": 1}]}]},
        ]
    }
    store = InMemorySyncStore()
    client = ReadOnlyClient()

    result = verify_legacy_site_links_read_only(
        batch="B-OLD",
        preview=preview,
        site_configs={"PROD": {"site_code": "PROD"}, "ECOM": {"site_code": "ECOM"}},
        client=client,
        store=store,
    )

    assert result["status"] == "MANUAL_REQUIRED"
    assert [site for _payload, site in client.calls] == ["PROD", "ECOM"]
    assert {row["site_code"] for row in store.links} == {"PROD"}


def test_local_draft_scope_requires_explicit_local_site_and_erptest_prefix() -> None:
    assert local_writeback.validate_controlled_test_scope(
        site_name="development.localhost", test_batch_no="ERPTEST-B1-20260907"
    )["ok"] is True
    with pytest.raises(ValueError, match="development.localhost"):
        local_writeback.validate_controlled_test_scope(
            site_name="deeplinkerp.com", test_batch_no="ERPTEST-B1-20260907"
        )
    with pytest.raises(ValueError, match="ERPTEST-"):
        local_writeback.validate_controlled_test_scope(
            site_name="development.localhost", test_batch_no="B1"
        )


def test_local_multisite_plan_is_preview_first_and_has_two_logical_sites() -> None:
    plan = local_writeback.build_controlled_multisite_plan(
        batch_no="B1",
        test_batch_no="ERPTEST-B1-20260907",
        stable_line_keys=["L1", "L2", "L3"],
    )

    assert plan["write_enabled"] is False
    assert [site["site_code"] for site in plan["sites"]] == ["ERPTEST-PROD", "ERPTEST-ECOM"]
    assert {key for site in plan["sites"] for key in site["stable_line_keys"]} == {"L1", "L2", "L3"}
    assert plan["required_confirmation"] is True


def test_deployment_check_mentions_new_erp_contract_without_real_write() -> None:
    script = (ROOT.parent / ".github/scripts/sync_and_verify_assets.sh").read_text(encoding="utf-8")

    for marker in (
        "Overseas Cost ERP Site",
        "Overseas Cost Project Route",
        "Overseas Cost ERP Document Link",
        "Overseas Cost ERP Sync Request",
        "renderErpSitePanel",
        "NO REAL ERP WRITE",
    ):
        assert marker in script
    assert "get_password(" not in script
