"""OA source refreshes may update estimates, never user fee decisions."""

from copy import deepcopy
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from overseas_costing.scripts import import_oa_logistics as importer
from overseas_costing.services import fee_service, import_service
from overseas_costing.tests.test_unified_transport_fees import MODES


class FeeDB:
    def __init__(self, rows=None, mode="AIR"):
        self.rows = deepcopy(rows or [])
        self.batch = dict(name="B", current_version="V", transport_mode=mode, status="Dirty", confirm_status="Draft", is_locked=0)
        self.version = dict(name="V", batch="B", status="Active")
        self.writes = []
        self.locks = []

    def sql(self, query, values, as_dict=False):
        assert "for update" in query.lower()
        self.locks.append(query)
        if "tabOverseas Cost Batch" in query:
            return [dict(self.batch)]
        if "tabOverseas Cost Version" in query:
            return [dict(self.version)]
        raise AssertionError(query)

    def get_value(self, doctype, key, fields, as_dict=False):
        if doctype == "Overseas Cost Batch":
            return dict(self.batch) if as_dict else self.batch.get(fields)
        if doctype == "Overseas Cost Version":
            return dict(self.version) if as_dict else self.version.get(fields)
        for row in self.rows:
            if key == row.get("name") or isinstance(key, dict) and all(row.get(field) == value for field, value in key.items()):
                return dict(row) if as_dict else row.get(fields)
        return None

    def set_value(self, doctype, name, values, value=None, **kwargs):
        values = values if isinstance(values, dict) else {values: value}
        self.writes.append((doctype, name, deepcopy(values)))
        if doctype == "Overseas Cost Allocation Rule":
            next(row for row in self.rows if row["name"] == name).update(values)
        elif doctype == "Overseas Cost Batch":
            self.batch.update(values, modified="2026-09-08 12:00:01")


def install(monkeypatch, rows=None, mode="AIR"):
    db = FeeDB(rows, mode)
    audits = []

    def get_all(doctype, **kwargs):
        assert doctype == "Overseas Cost Allocation Rule"
        assert kwargs["filters"] == {"batch": "B", "version": "V"}
        assert db.locks, "read fee rows only after locking their parent"
        return deepcopy(db.rows)

    def get_doc(values):
        def insert(**kwargs):
            row = {**values, "name": "NEW"}
            db.writes.append(("Overseas Cost Allocation Rule", "NEW", deepcopy(values)))
            db.rows.append(row)
            return SimpleNamespace(name="NEW")
        return SimpleNamespace(insert=insert)

    monkeypatch.setattr(importer, "frappe", SimpleNamespace(db=db, get_all=get_all, get_doc=get_doc,
                                                          session=SimpleNamespace(user="Administrator")))
    monkeypatch.setattr(import_service, "_invalid_batch_cost_write_response", lambda *args: None)
    monkeypatch.setattr(importer, "_insert_batch_audit_log", lambda **kwargs: audits.append(kwargs))
    return db, audits


def sync(amount=500, **extra):
    approval = {"logistics_fee": {"amount": amount, "currency": "RMB"}, **extra}
    return importer._sync_oa_logistics_allocation_rule(batch_name="B", version_name="V", approval_item=approval)


@pytest.mark.parametrize("mode,key,label,basis,count", MODES)
@pytest.mark.parametrize("amount", [0, 500])
def test_new_oa_fee_uses_saved_batch_transport_and_explicit_estimate(monkeypatch, mode, key, label, basis, count, amount):
    db, audits = install(monkeypatch, mode=mode)
    result = sync(amount, transport_mode="SEA")
    assert result["action"] == "created"
    row = db.rows[0]
    assert (row["logical_fee_key"], row["expense_category"], row["allocation_basis"]) == (key, label, basis)
    assert row["amount_status"] == "ESTIMATED" and row["amount"] == amount
    assert row["rule_code"] == "oa_logistics_freight" and row["amount_revision"].startswith("oa:")
    assert audits
    assert sync(amount)["action"] == "unchanged"
    assert len(db.rows) == 1


@pytest.mark.parametrize("amount", [None, "", "garbage"])
def test_absent_or_invalid_oa_money_does_not_create_a_zero_fee(monkeypatch, amount):
    db, _ = install(monkeypatch)
    assert sync(amount)["action"] == "skipped"
    assert not db.writes


@pytest.mark.parametrize("state,revision", [("ACTUAL", ""), ("NOT_INCURRED", ""), ("INCLUDED", ""),
                                          ("ESTIMATED", "user-saved-revision"), ("MISSING", "manual:revision")])
def test_oa_refresh_preserves_user_amount_decisions_and_retains_quote_audit(monkeypatch, state, revision):
    original = dict(name="OA", rule_code="oa_logistics_freight", expense_category="国际物流费用",
                    amount=20360, amount_status=state, currency="USD", amount_revision=revision)
    db, audits = install(monkeypatch, [original])
    result = sync()
    assert result["action"] == "protected" and result["ok"]
    assert not db.writes and db.rows == [original]
    assert audits[-1]["new_value"]["candidate_fee"]["amount"] == 500


@pytest.mark.parametrize("manual", [dict(logical_fee_key="international_air_freight"), dict(expense_category="国际空运费")])
def test_existing_manual_primary_prevents_creating_oa_duplicate(monkeypatch, manual):
    original = dict(name="MANUAL", rule_code="manual-1", amount=123, amount_status="ESTIMATED", **manual)
    db, _ = install(monkeypatch, [original])
    assert sync()["action"] == "protected"
    assert db.rows == [original] and not db.writes


@pytest.mark.parametrize("flag", ["is_enabled", "is_active"])
def test_retired_oa_fee_is_not_resurrected(monkeypatch, flag):
    original = dict(name="RETIRED", rule_code="oa_logistics_freight", amount=200, **{flag: 0})
    db, _ = install(monkeypatch, [original])
    assert sync()["action"] == "retired"
    assert db.rows == [original] and not db.writes


def test_legacy_source_estimate_refresh_gets_identity_and_source_revision(monkeypatch):
    db, _ = install(monkeypatch, [dict(name="OA", rule_code="oa_logistics_freight", amount=200, amount_status="MISSING")])
    assert sync()["action"] == "updated"
    assert db.rows[0]["logical_fee_key"] == "international_air_freight"
    assert db.rows[0]["amount_status"] == "ESTIMATED" and db.rows[0]["amount"] == 500
    assert db.rows[0]["amount_revision"].startswith("oa:")


def test_duplicate_primary_oa_sync_is_blocked_without_writing_either_fee(monkeypatch):
    rows = [dict(name="OA", rule_code="oa_logistics_freight", amount=200),
            dict(name="MANUAL", logical_fee_key="international_air_freight", amount=300)]
    db, _ = install(monkeypatch, rows)
    result = sync()
    assert result["action"] == "conflict" and not result["ok"]
    assert set(result["duplicate_rule_names"]) == {"OA", "MANUAL"}
    assert db.rows == rows and not db.writes


@pytest.mark.parametrize("target,changes", [
    ("batch", dict(current_version="OTHER")), ("batch", dict(is_locked=1)),
    ("batch", dict(confirm_status="Confirmed")), ("version", dict(status="Confirmed")),
    ("version", dict(status="Archived")), ("version", dict(batch="OTHER")),
    ("batch", dict(confirm_status="Partially Confirmed")), ("batch", dict(status="Confirmed")),
    ("batch", dict(status="Written Back")), ("version", dict(status="")), ("version", dict(status="Draft")),
    ("batch", dict(edit_lock_owner="Administrator", edit_lock_expires_at=datetime.now() + timedelta(minutes=4))),
    ("batch", dict(transport_mode="")),
])
def test_oa_sync_respects_frozen_version_live_lease_and_unknown_transport(monkeypatch, target, changes):
    db, _ = install(monkeypatch)
    getattr(db, target).update(changes)
    result = sync(transport_mode="SEA")
    assert not result["ok"] and result["action"] == "blocked"
    assert not db.writes


@pytest.mark.parametrize("token,modified,allowed", [("OWNED", "2026-09-08 12:00:00", True),
    ("WRONG", "2026-09-08 12:00:00", False), ("OWNED", None, False), (None, "2026-09-08 12:00:00", False),
    ("OWNED", "2026-09-08 11:00:00", False)])
def test_manual_quote_sync_only_accepts_matching_live_edit_context(monkeypatch, token, modified, allowed):
    db, _ = install(monkeypatch)
    db.batch.update(edit_lock_owner="Administrator", edit_lock_token="OWNED", modified="2026-09-08 12:00:00",
                    edit_lock_expires_at=datetime.now() + timedelta(minutes=4))
    result = importer._sync_oa_logistics_allocation_rule(batch_name="B", version_name="V",
        approval_item={"logistics_fee": {"amount": 100}}, edit_token=token, expected_modified=modified, manual_entry=True)
    assert result["ok"] is allowed
    if allowed:
        assert db.rows[0]["amount_revision"].startswith("manual:")
    else:
        assert not db.writes


def test_manual_confirmation_of_unchanged_oa_estimate_marks_it_as_manually_saved(monkeypatch):
    db, _ = install(monkeypatch)
    sync()
    db.batch.update(edit_lock_owner="Administrator", edit_lock_token="OWNED",
                    edit_lock_expires_at=datetime.now() + timedelta(minutes=4))
    result = importer._sync_oa_logistics_allocation_rule(batch_name="B", version_name="V",
        approval_item={"logistics_fee": {"amount": 500, "currency": "RMB"}}, manual_entry=True,
        edit_token="OWNED", expected_modified=db.batch["modified"])
    assert result["action"] == "updated"
    assert db.rows[0]["amount_revision"].startswith("manual:")
    db.batch["edit_lock_expires_at"] = None
    assert sync(700)["action"] == "protected" and db.rows[0]["amount"] == 500


@pytest.mark.parametrize("value", [0, "0", "0.00 RMB"])
def test_explicit_zero_in_oa_form_field_survives_extraction(value):
    fee = importer.extract_logistics_fee_from_approval({"form_fields": {"物流费用": value}})
    assert fee["amount"] == 0


@pytest.mark.parametrize("operation", ["confirm_logistics_quote_candidate", "save_manual_logistics_quote"])
def test_existing_quote_api_forwards_lease_context(monkeypatch, operation):
    import importlib
    import sys
    from types import ModuleType
    stub = ModuleType("frappe")
    stub.whitelist = lambda: (lambda fn: fn)
    monkeypatch.setitem(sys.modules, "frappe", stub)
    sys.modules.pop("overseas_costing.api.import_api", None)
    api = importlib.import_module("overseas_costing.api.import_api")
    monkeypatch.setattr(api, "require_batch_permission", lambda name, permission: "B")
    monkeypatch.setattr(api.import_service, operation, lambda **kwargs: kwargs)
    kwargs = {"candidate_index": 0} if operation.startswith("confirm") else {"amount": 100}
    result = getattr(api, operation)(batch_name="B", edit_token="OWNED", expected_modified="M", **kwargs)
    assert result["edit_token"] == "OWNED" and result["expected_modified"] == "M"


@pytest.mark.parametrize("operation", ["confirm_logistics_quote_candidate", "save_manual_logistics_quote"])
def test_quote_services_forward_owned_context_and_do_not_claim_protected_fee_was_changed(monkeypatch, operation):
    monkeypatch.setattr(import_service, "frappe", SimpleNamespace(db=SimpleNamespace(commit=lambda: None)))
    monkeypatch.setattr(import_service, "_resolve_batch_name", lambda name: "B")
    monkeypatch.setattr(import_service, "_resolve_version_name", lambda *args: "V")
    monkeypatch.setattr(import_service, "_invalid_batch_cost_write_response", lambda *args: None)
    monkeypatch.setattr(import_service, "_get_batch_trace_row", lambda name: {"extra_json": {
        "logistics_quote_candidates": [{"amount": 100, "currency": "RMB"}]}})
    captured = []
    def protected(**kwargs):
        captured.append(kwargs)
        return {"ok": True, "action": "protected", "message": "已保留报价供复核"}
    monkeypatch.setattr(importer, "_sync_oa_logistics_allocation_rule", protected)
    kwargs = {"candidate_index": 0} if operation.startswith("confirm") else {"amount": 100}
    result = getattr(import_service, operation)(batch_name="B", edit_token="OWNED", expected_modified="M", **kwargs)
    assert result["ok"] and result["rule_result"]["action"] == "protected"
    assert captured[0]["edit_token"] == "OWNED" and captured[0]["expected_modified"] == "M"
    assert captured[0]["manual_entry"] is True
    assert "生成" not in result["message"]


def test_oa_sync_rechecks_invalid_source_after_taking_parent_lock(monkeypatch):
    db, _ = install(monkeypatch)
    def check(*args):
        return {"ok": False, "invalid_business": True, "message": "审批刚刚撤销"} if db.locks else None
    monkeypatch.setattr(import_service, "_invalid_batch_cost_write_response", check)
    result = sync()
    assert not result["ok"] and result["invalid_business"]
    assert not db.writes


def test_blocked_fee_sync_prevents_background_recalculation_from_bypassing_lease(monkeypatch):
    install(monkeypatch)
    monkeypatch.setattr("overseas_costing.services.calculate_service.recalculate_batch",
                        lambda **kwargs: pytest.fail("blocked fee sync must not trigger trusted calculation"))
    result = importer._recalculate_after_purchase_sync(batch_name="B", version_name="V",
        purchase_sync={"ok": True, "updated_count": 1}, logistics_fee_sync={"ok": False, "action": "blocked", "message": "租约占用"})
    assert not result["ok"] and result["action"] == "blocked"


@pytest.mark.parametrize("operation", ["confirm_logistics_quote_candidate", "save_manual_logistics_quote"])
def test_quote_service_saves_through_shared_sync_and_returns_new_modified(monkeypatch, operation):
    db, _ = install(monkeypatch)
    db.batch.update(modified="2026-09-08 12:00:00", edit_lock_owner="Administrator", edit_lock_token="OWNED",
                    edit_lock_expires_at=datetime.now() + timedelta(minutes=4))
    db.commit = lambda: None
    importer.frappe.utils = SimpleNamespace(now_datetime=datetime.now)
    monkeypatch.setattr(import_service, "frappe", importer.frappe)
    monkeypatch.setattr(import_service, "_resolve_batch_name", lambda name: "B")
    monkeypatch.setattr(import_service, "_resolve_version_name", lambda *args: "V")
    monkeypatch.setattr(import_service, "_get_batch_trace_row", lambda name: {"extra_json": {
        "logistics_quote_candidates": [{"amount": 100, "currency": "RMB"}]}})
    monkeypatch.setattr(import_service, "_create_audit_log", lambda **kwargs: None)
    monkeypatch.setattr(import_service, "_mark_batch_dirty", lambda *args: None)
    monkeypatch.setattr(import_service, "_recalculate_after_writeback", lambda **kwargs: {"ok": True})
    kwargs = {"candidate_index": 0} if operation.startswith("confirm") else {"amount": 100}
    result = getattr(import_service, operation)(batch_name="B", edit_token="OWNED", expected_modified="2026-09-08 12:00:00", **kwargs)
    assert result["ok"] and db.rows[0]["logical_fee_key"] == "international_air_freight"
    assert db.rows[0]["amount_status"] == "ESTIMATED" and db.rows[0]["amount_revision"].startswith("manual:")
    assert result["batch_modified"] == db.batch["modified"] == "2026-09-08 12:00:01"


@pytest.mark.parametrize("amount", [0, "0", "0.00", 200])
def test_quote_confirmation_cannot_replace_explicit_oa_fee_including_real_zero(monkeypatch, amount):
    monkeypatch.setattr(import_service, "frappe", SimpleNamespace())
    monkeypatch.setattr(import_service, "_resolve_batch_name", lambda name: "B")
    monkeypatch.setattr(import_service, "_resolve_version_name", lambda *args: "V")
    monkeypatch.setattr(import_service, "_invalid_batch_cost_write_response", lambda *args: None)
    monkeypatch.setattr(import_service, "_get_batch_trace_row", lambda name: {"extra_json": {
        "logistics_fee": {"amount": amount, "currency": "RMB"},
        "logistics_quote_candidates": [{"amount": 100, "currency": "RMB"}]}})
    calls = []
    monkeypatch.setattr(importer, "_sync_oa_logistics_allocation_rule", lambda **kwargs:
                        calls.append(kwargs) or {"ok": False, "message": "must not sync an alternative quote"})
    result = import_service.confirm_logistics_quote_candidate(batch_name="B", candidate_index=0)
    assert not result["ok"] and "明确物流费用" in result["message"]
    assert not calls


@pytest.mark.parametrize("operation", ["confirm_logistics_quote_candidate", "save_manual_logistics_quote"])
def test_manual_quote_service_without_tokens_cannot_write_even_without_an_active_lease(monkeypatch, operation):
    db, _ = install(monkeypatch)
    monkeypatch.setattr(import_service, "frappe", importer.frappe)
    monkeypatch.setattr(import_service, "_resolve_batch_name", lambda name: "B")
    monkeypatch.setattr(import_service, "_resolve_version_name", lambda *args: "V")
    monkeypatch.setattr(import_service, "_get_batch_trace_row", lambda name: {"extra_json": {
        "logistics_quote_candidates": [{"amount": 100, "currency": "RMB"}]}})
    # Stop immediately after the real sync in the old implementation, so the
    # regression reports its unauthorized fee write without unrelated mocks.
    writes_after_sync = []
    original_sync = importer._sync_oa_logistics_allocation_rule
    def sync_then_stop(**kwargs):
        result = original_sync(**kwargs)
        writes_after_sync.extend(db.writes)
        return result if not result.get("ok") else {"ok": False, "message": "unexpected fee write"}
    monkeypatch.setattr(importer, "_sync_oa_logistics_allocation_rule", sync_then_stop)
    kwargs = {"candidate_index": 0} if operation.startswith("confirm") else {"amount": 100}
    result = getattr(import_service, operation)(batch_name="B", **kwargs)
    assert not writes_after_sync
    assert not result["ok"] and "编辑会话" in result["message"]
