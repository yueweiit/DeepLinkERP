"""AI 试算口径审核服务。"""

from decimal import Decimal

import pytest

from overseas_costing.services import cost_trial_ai_service


ITEMS = [
    {
        "name": "ITEM-1",
        "stable_line_key": "line-1",
        "goods_value": 100,
        "shipment_value_rmb": 100,
        "gross_weight_kg": 10,
        "volume_m3": 0,
        "chargeable_weight_kg": 12,
    },
    {
        "name": "ITEM-2",
        "stable_line_key": "line-2",
        "goods_value": 300,
        "shipment_value_rmb": 300,
        "gross_weight_kg": 30,
        "volume_m3": 0,
        "chargeable_weight_kg": 36,
    },
]


def _fee(key="international_air_freight", amount=100):
    return {
        "name": f"RULE-{key}",
        "logical_fee_key": key,
        "rule_code": key,
        "expense_category": key,
        "amount": amount,
        "currency": "RMB",
        "amount_status": "ACTUAL",
        "scope_type": "ALL_ITEMS",
        "allocation_basis": "goods_value",
    }


def test_build_review_exposes_complete_alternatives_when_ai_basis_is_missing():
    result = cost_trial_ai_service.build_cost_trial_review_draft(
        items=ITEMS,
        fees=[_fee()],
        fx_context={},
        context={"batch_name": "B1", "version_name": "V1", "transport_mode": "AIR"},
        ai_result={
            "ok": True,
            "model": "deepseek-test",
            "rules": [{
                **_fee(),
                "allocation_basis": "volume",
                "ai_confidence": 0.88,
                "remark": "AI 认为应按体积分摊",
            }],
        },
    )

    proposal = result["fee_suggestions"][0]
    assert proposal["recommended_basis"] == "volume"
    assert proposal["recommended_basis_available"] is False
    assert proposal["requires_temporary_basis"] is True
    assert [row["basis"] for row in proposal["available_alternatives"]] == [
        "goods_value",
        "gross_weight",
        "chargeable_weight",
    ]
    assert proposal["missing_fields"] == ["volume_m3"]
    assert result["trial_context"] == {
        "transport_mode": "AIR",
        "project": "",
        "supplier": "",
    }
    assert result["retrieval_context"] == []
    assert result["retrieval_version"] == ""


def test_review_exposes_scope_and_deterministic_alternative_differences():
    items = [
        {**ITEMS[0], "gross_weight_kg": 30},
        {**ITEMS[1], "gross_weight_kg": 10},
    ]
    result = cost_trial_ai_service.build_cost_trial_review_draft(
        items=items,
        fees=[_fee()],
        fx_context={},
        context={"batch_name": "B1", "version_name": "V1", "transport_mode": "AIR"},
        ai_result={"ok": True, "rules": [{**_fee(), "allocation_basis": "volume"}]},
    )

    proposal = result["fee_suggestions"][0]
    alternatives = {row["basis"]: row for row in proposal["available_alternatives"]}
    assert proposal["scope_type"] == "ALL_ITEMS"
    assert alternatives["goods_value"]["allocation_preview"] == [
        {"item_key": "line-1", "amount_rmb": "25.00"},
        {"item_key": "line-2", "amount_rmb": "75.00"},
    ]
    assert alternatives["gross_weight"]["allocation_preview"] == [
        {"item_key": "line-1", "amount_rmb": "75.00"},
        {"item_key": "line-2", "amount_rmb": "25.00"},
    ]


def test_preview_uses_selected_temporary_basis_and_marks_non_complete():
    draft = cost_trial_ai_service.build_cost_trial_review_draft(
        items=ITEMS,
        fees=[_fee()],
        fx_context={},
        context={"batch_name": "B1", "version_name": "V1", "transport_mode": "AIR"},
        ai_result={
            "ok": True,
            "model": "deepseek-test",
            "rules": [{**_fee(), "allocation_basis": "volume", "ai_confidence": 0.8}],
        },
    )
    proposal = draft["fee_suggestions"][0]

    result = cost_trial_ai_service.preview_selected_cost_trial(
        items=ITEMS,
        fees=[_fee()],
        fx_context={},
        fee_components=[],
        draft=draft,
        selections=[{
            "suggestion_id": proposal["suggestion_id"],
            "basis": "gross_weight",
            "reason": "体积尚未补齐，本次暂按重量",
        }],
    )

    fee = result["included_fees"][0]
    assert fee["allocation_basis"] == "gross_weight"
    assert fee["allocations"] == {"line-1": "25.00", "line-2": "75.00"}
    assert result["summary"]["is_complete"] is False
    assert result["trial_review"]["is_temporary"] is True
    assert any(row["reason_code"] == "TEMPORARY_ALLOCATION_BASIS" for row in result["incomplete_reasons"])


def test_preview_rejects_client_basis_that_server_did_not_offer():
    draft = cost_trial_ai_service.build_cost_trial_review_draft(
        items=ITEMS,
        fees=[_fee()],
        fx_context={},
        context={"batch_name": "B1", "version_name": "V1"},
        ai_result={"ok": True, "rules": [{**_fee(), "allocation_basis": "volume"}]},
    )
    proposal = draft["fee_suggestions"][0]

    with pytest.raises(ValueError, match="不可用"):
        cost_trial_ai_service.preview_selected_cost_trial(
            items=ITEMS,
            fees=[_fee()],
            fx_context={},
            fee_components=[],
            draft=draft,
            selections=[{"suggestion_id": proposal["suggestion_id"], "basis": "not-a-basis"}],
        )


def test_complete_manual_override_is_formal_and_requires_a_reason():
    draft = cost_trial_ai_service.build_cost_trial_review_draft(
        items=ITEMS,
        fees=[_fee()],
        fx_context={},
        context={"batch_name": "B1", "version_name": "V1"},
        ai_result={"ok": True, "rules": [{**_fee(), "allocation_basis": "goods_value"}]},
    )
    proposal = draft["fee_suggestions"][0]

    with pytest.raises(ValueError, match="原因"):
        cost_trial_ai_service.preview_selected_cost_trial(
            items=ITEMS,
            fees=[_fee()],
            fx_context={},
            fee_components=[],
            draft=draft,
            selections=[{"suggestion_id": proposal["suggestion_id"], "basis": "gross_weight", "reason": ""}],
        )

    result = cost_trial_ai_service.preview_selected_cost_trial(
        items=ITEMS,
        fees=[_fee()],
        fx_context={},
        fee_components=[],
        draft=draft,
        selections=[{
            "suggestion_id": proposal["suggestion_id"],
            "basis": "gross_weight",
            "reason": "当前费用为按重量计价的操作费",
        }],
    )

    assert result["trial_review"]["is_temporary"] is False
    assert result["trial_review"]["fee_choices"][0]["modified_ai_suggestion"] is True


def test_saved_projection_hashes_formal_basis_but_keeps_temporary_basis_private():
    fee = _fee()
    formal = cost_trial_ai_service.project_fees_for_trial(
        [fee],
        {"international_air_freight": {"basis": "gross_weight", "temporary": False}},
        for_save=True,
    )[0]
    temporary = cost_trial_ai_service.project_fees_for_trial(
        [fee],
        {"international_air_freight": {"basis": "volume", "temporary": True}},
        for_save=True,
    )[0]

    assert formal["allocation_basis"] == "gross_weight"
    assert "trial_allocation_basis" not in formal
    assert temporary["allocation_basis"] == fee["allocation_basis"]
    assert temporary["trial_allocation_basis"] == "volume"


def test_temporary_saved_trial_is_marked_incomplete_and_blocks_formal_use():
    saved = cost_trial_ai_service.cost_preview_service.build_saved_cost_data(
        ITEMS,
        [{**_fee(), "trial_allocation_basis": "gross_weight"}],
        {},
        "AIR",
    )

    result = cost_trial_ai_service.annotate_saved_trial_result(
        saved,
        {"run_id": "RUN-1", "is_temporary": True, "fee_choices": []},
    )

    assert result["summary"]["is_complete"] is False
    assert result["summary"]["is_temporary"] is True
    assert result["summary_snapshot"]["formal_confirmation_blocked"] is True
    assert result["summary_snapshot"]["comprehensive_cost"]["summary"]["is_complete"] is False
    assert any(row["reason_code"] == "TEMPORARY_ALLOCATION_BASIS" for row in result["incomplete_reasons"])


def test_confirmed_customs_components_are_evidence_locked_and_conserve_amount():
    components = [
        {
            "name": "COMP-1",
            "fee_rule": "RULE-import_tax",
            "logical_fee_key": "import_tax",
            "evidence": "EVIDENCE-1",
            "attachment": "ATTACHMENT-1",
            "stable_line_key": "line-1",
            "amount_rmb": "20",
            "status": "CONFIRMED",
            "is_active": 1,
            "cost_effect": "COST",
            "tax_code": "IGI",
            "hs_code": "3926.90",
            "source_evidence_json": '{"page":2,"line":18}',
        },
        {
            "name": "COMP-2",
            "fee_rule": "RULE-import_tax",
            "logical_fee_key": "import_tax",
            "evidence": "EVIDENCE-1",
            "attachment": "ATTACHMENT-1",
            "stable_line_key": "line-2",
            "amount_rmb": "80",
            "status": "CONFIRMED",
            "is_active": 1,
            "cost_effect": "COST",
            "tax_code": "IGI",
            "hs_code": "3926.90",
            "source_evidence_json": '{"page":2,"line":19}',
        },
    ]
    result = cost_trial_ai_service.build_cost_trial_review_draft(
        items=ITEMS,
        fees=[_fee("import_tax")],
        fx_context={},
        fee_components=components,
        context={"batch_name": "B1", "version_name": "V1"},
        ai_result={"ok": True, "rules": [{**_fee("import_tax"), "allocation_basis": "volume"}]},
    )

    proposal = result["fee_suggestions"][0]
    assert proposal["evidence_locked"] is True
    assert proposal["evidence_component_count"] == 2
    assert Decimal(proposal["evidence_amount_rmb"]) == Decimal("100.00")
    assert proposal["requires_user_choice"] is False
    assert {row["tax_code"] for row in proposal["evidence_summary"]} == {"IGI"}

    preview = cost_trial_ai_service.preview_selected_cost_trial(
        items=ITEMS,
        fees=[_fee("import_tax")],
        fx_context={},
        fee_components=components,
        draft=result,
        selections=[],
    )
    evidence_lock = preview["trial_review"]["evidence_locks"][0]
    assert evidence_lock["fee_key"] == "import_tax"
    assert evidence_lock["component_count"] == 2
    assert evidence_lock["components"][0]["evidence"] == "EVIDENCE-1"
    assert evidence_lock["components"][0]["attachment"] == "ATTACHMENT-1"
    assert evidence_lock["components"][0]["source_evidence"]["page"] == 2


def test_component_with_unmatched_sku_cannot_be_evidence_locked():
    result = cost_trial_ai_service.build_cost_trial_review_draft(
        items=ITEMS,
        fees=[_fee("import_tax")],
        fx_context={},
        fee_components=[{
            "fee_rule": "RULE-import_tax",
            "logical_fee_key": "import_tax",
            "stable_line_key": "missing-line",
            "amount_rmb": "100",
            "status": "CONFIRMED",
            "is_active": 1,
            "cost_effect": "COST",
        }],
        context={"batch_name": "B1", "version_name": "V1"},
        ai_result={"ok": True, "rules": [_fee("import_tax")]},
    )

    proposal = result["fee_suggestions"][0]
    assert proposal["evidence_locked"] is False
    assert proposal["evidence_issue"] == "SKU_MATCH_INVALID"
    assert proposal["blocked"] is True
    with pytest.raises(ValueError, match="凭证.*SKU"):
        cost_trial_ai_service.preview_selected_cost_trial(
            items=ITEMS,
            fees=[_fee("import_tax")],
            fx_context={},
            fee_components=[],
            draft=result,
            selections=[],
        )


class TrialRepository:
    def __init__(self):
        self.context = {"batch_name": "B1", "version_name": "V1", "transport_mode": "AIR", "batch_modified": "m1"}
        self.items = ITEMS
        self.fees = [_fee()]
        self.fx = {}
        self.components = []
        self.runs = {}
        self.created = 0
        self.saved_calculation = None
        self.commits = 0
        self.rollbacks = 0

    def load_trial_inputs(self, batch_name, version_name, *, edit_token="", expected_modified="", write=False, trusted=False):
        assert batch_name == "B1"
        if write and not trusted:
            assert edit_token == "T" and expected_modified == "m1"
        return {
            "context": dict(self.context),
            "items": [dict(row) for row in self.items],
            "fees": [dict(row) for row in self.fees],
            "fx_context": dict(self.fx),
            "fee_components": [dict(row) for row in self.components],
        }

    def find_active(self, batch_name, version_name, fingerprint):
        return next((row for row in self.runs.values() if row["input_fingerprint"] == fingerprint and row["status"] in {"QUEUED", "RUNNING"}), None)

    def find_reusable(self, batch_name, version_name, fingerprint):
        return next((row for row in self.runs.values() if row["input_fingerprint"] == fingerprint and row["status"] == "READY"), None)

    def create_run(self, values):
        self.created += 1
        row = {"name": f"RUN-{self.created}", **values}
        self.runs[row["name"]] = row
        return row

    def get_run(self, run_id):
        return self.runs[run_id]

    def save_run(self, run_id, **values):
        self.runs[run_id].update(values)
        self.runs[run_id]["progress_revision"] = int(self.runs[run_id].get("progress_revision") or 0) + 1
        return self.runs[run_id]

    def save_calculation(self, inputs, preview, trial_review):
        self.saved_calculation = {"preview": preview, "trial_review": trial_review}
        return {**preview, "ok": True, "saved": True, "batch_modified": "m2"}

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


def _ai_volume(**_kwargs):
    return {
        "ok": True,
        "action": "suggested",
        "model": "deepseek-test",
        "rules": [{**_fee(), "allocation_basis": "volume", "ai_confidence": 0.91}],
    }


def test_lifecycle_reuses_same_ready_input_unless_force_is_requested():
    repo = TrialRepository()
    queued = []
    first = cost_trial_ai_service.start_cost_trial_ai_review(
        "B1", "V1", edit_token="T", expected_modified="m1", repository=repo, enqueue=queued.append
    )
    assert first == {"ok": True, "run_id": "RUN-1", "status": "QUEUED", "reused": False, "progress_revision": 0}
    assert queued == ["RUN-1"]

    cost_trial_ai_service.execute_cost_trial_ai_review("RUN-1", repository=repo, ai_suggester=_ai_volume)
    reused = cost_trial_ai_service.start_cost_trial_ai_review(
        "B1", "V1", edit_token="T", expected_modified="m1", repository=repo, enqueue=queued.append
    )
    forced = cost_trial_ai_service.start_cost_trial_ai_review(
        "B1", "V1", edit_token="T", expected_modified="m1", force=True, repository=repo, enqueue=queued.append
    )

    assert reused["run_id"] == "RUN-1" and reused["reused"] is True
    assert forced["run_id"] == "RUN-2" and forced["reused"] is False
    assert queued == ["RUN-1", "RUN-2"]


def test_feature_switch_can_disable_new_ai_trial_entry(monkeypatch):
    repo = TrialRepository()
    monkeypatch.setattr(cost_trial_ai_service, "cost_trial_ai_enabled", lambda: False)

    with pytest.raises(RuntimeError, match="未启用"):
        cost_trial_ai_service.start_cost_trial_ai_review(
            "B1", "V1", edit_token="T", expected_modified="m1", repository=repo, enqueue=lambda _run: None
        )

    assert repo.created == 0


def test_preview_marks_run_stale_when_any_trial_input_changes():
    repo = TrialRepository()
    started = cost_trial_ai_service.start_cost_trial_ai_review(
        "B1", "V1", edit_token="T", expected_modified="m1", repository=repo, enqueue=lambda _run: None
    )
    cost_trial_ai_service.execute_cost_trial_ai_review(started["run_id"], repository=repo, ai_suggester=_ai_volume)
    repo.items[0]["gross_weight_kg"] = 11

    with pytest.raises(ValueError, match="输入已变化"):
        cost_trial_ai_service.preview_cost_trial(
            "B1", started["run_id"], [], repository=repo
        )
    assert repo.runs["RUN-1"]["status"] == "STALE"


def test_confirm_validates_server_preview_token_and_saves_trial_audit():
    repo = TrialRepository()
    started = cost_trial_ai_service.start_cost_trial_ai_review(
        "B1", "V1", edit_token="T", expected_modified="m1", repository=repo, enqueue=lambda _run: None
    )
    cost_trial_ai_service.execute_cost_trial_ai_review(started["run_id"], repository=repo, ai_suggester=_ai_volume)
    draft = repo.runs["RUN-1"]["draft_json"]
    selection = [{
        "suggestion_id": draft["fee_suggestions"][0]["suggestion_id"],
        "basis": "gross_weight",
        "reason": "暂按毛重",
    }]
    preview = cost_trial_ai_service.preview_cost_trial("B1", "RUN-1", selection, repository=repo)

    with pytest.raises(ValueError, match="预览已失效"):
        cost_trial_ai_service.confirm_cost_trial(
            "B1", "RUN-1", "wrong", selection, edit_token="T", expected_modified="m1", repository=repo
        )
    saved = cost_trial_ai_service.confirm_cost_trial(
        "B1", "RUN-1", preview["preview_token"], selection,
        edit_token="T", expected_modified="m1", repository=repo,
    )

    assert saved["saved"] is True
    assert saved["trial_review"]["run_id"] == "RUN-1"
    assert saved["trial_review"]["is_temporary"] is True
    assert repo.runs["RUN-1"]["status"] == "CONFIRMED"
    assert repo.saved_calculation["trial_review"]["fee_choices"][0]["basis"] == "gross_weight"


def test_preview_token_is_server_signed(monkeypatch):
    draft = cost_trial_ai_service.build_cost_trial_review_draft(
        items=ITEMS,
        fees=[_fee()],
        fx_context={},
        context={"batch_name": "B1", "version_name": "V1"},
        ai_result={"ok": True, "rules": [_fee()]},
    )
    proposal = draft["fee_suggestions"][0]
    selections = [{"suggestion_id": proposal["suggestion_id"], "basis": "goods_value"}]

    monkeypatch.setattr(cost_trial_ai_service, "_preview_token_secret", lambda: b"first-secret")
    first = cost_trial_ai_service.preview_selected_cost_trial(
        items=ITEMS, fees=[_fee()], fx_context={}, fee_components=[], draft=draft, selections=selections,
    )
    monkeypatch.setattr(cost_trial_ai_service, "_preview_token_secret", lambda: b"second-secret")
    second = cost_trial_ai_service.preview_selected_cost_trial(
        items=ITEMS, fees=[_fee()], fx_context={}, fee_components=[], draft=draft, selections=selections,
    )

    assert first["preview_token"] != second["preview_token"]


def test_discard_does_not_change_a_confirmed_run():
    repo = TrialRepository()
    repo.runs["RUN-1"] = {
        "name": "RUN-1",
        "batch": "B1",
        "version": "V1",
        "status": "CONFIRMED",
        "progress_revision": 4,
    }

    result = cost_trial_ai_service.discard_cost_trial_ai_review("B1", "RUN-1", repository=repo)

    assert result["status"] == "CONFIRMED"
    assert repo.runs["RUN-1"]["status"] == "CONFIRMED"
    assert repo.commits == 0


def test_status_does_not_expose_private_input_snapshots():
    repo = TrialRepository()
    cost_trial_ai_service.start_cost_trial_ai_review(
        "B1", "V1", edit_token="T", expected_modified="m1", repository=repo, enqueue=lambda _run: None
    )
    cost_trial_ai_service.execute_cost_trial_ai_review("RUN-1", repository=repo, ai_suggester=_ai_volume)

    result = cost_trial_ai_service.get_cost_trial_ai_review_status("B1", "RUN-1", repository=repo)

    assert result["status"] == "READY"
    assert result["draft"]["model"] == "deepseek-test"
    assert "items_json" not in result and "fees_json" not in result
