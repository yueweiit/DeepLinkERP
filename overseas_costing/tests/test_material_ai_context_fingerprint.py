"""Drafts must bind the calculation context as well as item/source data."""

from copy import deepcopy
import json

import pytest
from types import SimpleNamespace

from overseas_costing.services import material_ai_fill_service as service


class ContextRepository:
    def __init__(self):
        self.context = {
            "batch": "B1", "version": "V1", "batch_modified": "M1",
            "version_modified": "VM1", "transport_mode": "SEA",
            "fx_rates": {"USD": "7", "MXN": "0.4", "RMB": "1"},
        }
        self.items = [{"name": "I1", "material_code": "SKU1", "spec_model": "Old"}]
        self.run = None
        self.created = []
        self.writes = []

    def get_context(self, *_args):
        return deepcopy(self.context)

    def get_items(self, *_args):
        return deepcopy(self.items)

    def list_sources(self, *_args):
        return []

    def find_running_run(self, *_args):
        return self.run if self.run and self.run["status"] in {"QUEUED", "RUNNING"} else None

    def find_reusable_run(self, _batch, _version, fingerprint):
        return self.run if self.run and self.run["status"] in service.ACTIVE_STATES and self.run["input_fingerprint"] == fingerprint else None

    def supersede_active_runs(self, *_args):
        if self.run:
            self.run["status"] = "STALE"

    def create_run(self, payload):
        self.run = {**deepcopy(payload), "name": f"RUN-{len(self.created) + 1}"}
        self.created.append(self.run)
        return self.run

    def get_run(self, run_id):
        return next(run for run in self.created if run["name"] == run_id)

    lock_run = get_run

    def save_run(self, run, **updates):
        run.update(deepcopy(updates))
        return run

    def assert_write(self, *_args):
        pass

    def apply_source_review(self, run, proposals, manual_updates, audit):
        self.writes.append(deepcopy(proposals))
        return {"changed_count": 1, "batch_modified": "M2"}


def start(repo):
    return service.start_source_ai_review("B1", "V1", repository=repo, enqueue=lambda _run: None)


def test_explicit_source_reanalysis_uses_original_sources_instead_of_adopted_row_scope():
    repo = ContextRepository()
    repo.context['effective_source'] = {
        'root_kind': 'logistics',
        'packing': {'selected_source': {'id': 'ONE-ROW'}},
        'fingerprint': 'SCOPED',
    }
    repo.list_sources = lambda *_args: [{'source_id': 'ONE-ROW', 'source_kind': 'approval_form'}]
    repo.get_original_context = lambda *_args: {
        **deepcopy(repo.context),
        'effective_source': {'root_kind': 'logistics', 'fingerprint': 'ORIGINAL'},
    }
    repo.list_original_sources = lambda *_args: [
        {'source_id': 'PACKING-LIST', 'source_kind': 'approval_attachment'},
        {'source_id': 'LOGISTICS-OA', 'source_kind': 'approval_form'},
    ]

    started = service.start_source_ai_review(
        'B1', 'V1', repository=repo, enqueue=lambda _run: None,
        force=True, reanalyze_original_sources=True,
    )

    assert started['ok'] and not started['reused']
    assert repo.run['trigger_mode'] == 'SOURCE_REANALYSIS'
    assert [row['source_id'] for row in json.loads(repo.run['source_manifest_json'])] == [
        'PACKING-LIST', 'LOGISTICS-OA',
    ]
    assert service._reload_review_manifest(repo, 'B1', 'V1', repo.run)[0]['source_id'] == 'PACKING-LIST'


CHANGES = [
    {"fx_rates": {"USD": "8", "MXN": "0.4", "RMB": "1"}},
    {"fx_rates": {"USD": "7", "MXN": "0.5", "RMB": "1"}},
    {"transport_mode": "AIR"},
    {"version_modified": "VM2"},
]


@pytest.mark.parametrize("change", CHANGES)
@pytest.mark.parametrize("status", ["READY", "RUNNING"])
def test_start_does_not_reuse_a_different_calculation_context(change, status):
    repo = ContextRepository()
    first = start(repo)
    repo.run["status"] = status
    repo.context.update(change)

    second = start(repo)

    assert second["reused"] is False
    assert second["run_id"] != first["run_id"]


def test_start_fingerprints_context_read_after_batch_lock():
    repo = ContextRepository()
    repo.lock_review_scope = lambda *_args: repo.context.update(transport_mode="AIR")
    start(repo)
    expected = ContextRepository()
    expected.context["transport_mode"] = "AIR"
    start(expected)
    before_lock = ContextRepository()
    start(before_lock)

    assert repo.run["input_fingerprint"] == expected.run["input_fingerprint"]
    assert repo.run["input_fingerprint"] != before_lock.run["input_fingerprint"]


def test_source_review_fingerprint_changes_with_project_candidates_revision_and_hint() -> None:
    items = [{
        "name": "I1",
        "extra_json": json.dumps({"project_candidates": [{"id": "D1", "name": "LatinGo拉丁购"}]}, ensure_ascii=False),
    }]
    context = {
        "project_routing": {
            "route_revision": "R1",
            "options": [{
                "project_collection": "LatinGo拉丁购",
                "subsidiary_code": "LATIN",
                "site_code": "DEEPLINKERP",
                "revision": 1,
                "ai_match_hint": "宠物用品",
            }],
        }
    }
    baseline = service._source_review_fingerprint("B1", "V1", items, [], "", context=context)
    changed_hint = deepcopy(context)
    changed_hint["project_routing"]["options"][0]["ai_match_hint"] = "宠物用品、户外用品"
    changed_revision = deepcopy(context)
    changed_revision["project_routing"]["route_revision"] = "R2"
    changed_candidates = deepcopy(items)
    changed_candidates[0]["extra_json"] = json.dumps(
        {"project_candidates": [{"id": "D2", "name": "YW MOLDES MX模具"}]}, ensure_ascii=False
    )

    assert baseline != service._source_review_fingerprint("B1", "V1", items, [], "", context=changed_hint)
    assert baseline != service._source_review_fingerprint("B1", "V1", items, [], "", context=changed_revision)
    assert baseline != service._source_review_fingerprint("B1", "V1", changed_candidates, [], "", context=context)


def test_frappe_repository_context_includes_current_project_routing(monkeypatch) -> None:
    class DB:
        def get_value(self, doctype, name, fields=None, as_dict=False):
            if doctype == "Overseas Cost Batch":
                if fields == "extra_json":
                    return "{}"
                return {
                    "name": "B1", "current_version": "V1", "modified": "BM1",
                    "transport_mode": "SEA", "confirm_status": "", "writeback_status": "",
                }
            return {
                "name": "V1", "batch": "B1", "status": "Active", "modified": "VM1",
                "fx_usd_to_rmb": "7", "fx_rmb_to_mxn": "2.5",
            }

    monkeypatch.setattr(service, "frappe", SimpleNamespace(db=DB()))
    from overseas_costing.services import batch_service, erp_sync_plan_service
    monkeypatch.setattr(batch_service, "_resolve_batch_name", lambda name: name)
    monkeypatch.setattr(
        service.effective_source,
        "current_source_bundle",
        lambda *_args, **_kwargs: {"context": {}},
    )
    expected = {"ok": True, "route_revision": "ROUTES-1", "options": []}
    monkeypatch.setattr(erp_sync_plan_service, "list_project_route_options", lambda batch: expected)

    context = service.FrappeMaterialAIFillRepository().get_context("B1", "V1")

    assert context["project_routing"] == expected


@pytest.mark.parametrize("change", CHANGES)
@pytest.mark.parametrize("timing", ["before_worker", "during_worker"])
def test_worker_rejects_context_changes_before_or_during_read(change, timing, monkeypatch):
    repo = ContextRepository()
    start(repo)
    original_run = repo.run
    reads = []

    def ai_read(*_args, **_kwargs):
        reads.append(True)
        if timing == "during_worker":
            repo.context.update(change)
        return {"ok": True, "proposals": []}

    monkeypatch.setattr(service, "_call_source_review_ai", ai_read)
    monkeypatch.setattr(service, "_default_enqueue", lambda _run: None)
    if timing == "before_worker":
        repo.context.update(change)

    result = service.execute_material_ai_fill(original_run["name"], repository=repo)

    assert result["status"] == "STALE"
    assert original_run["status"] == "STALE"
    assert reads == ([] if timing == "before_worker" else [True])
    assert repo.writes == []


@pytest.mark.parametrize("change", CHANGES)
@pytest.mark.parametrize("timing", ["before_apply", "after_inputs_lock"])
def test_apply_rejects_context_changes_including_after_input_lock(change, timing):
    repo = ContextRepository()
    start(repo)
    repo.run.update(status="READY", candidates_json=[{
        "proposal_id": "L1", "proposal_type": "logistics_reconcile",
        "payload": {"rows": [{"goods_value": "700"}]},
    }])
    if timing == "before_apply":
        repo.context.update(change)
    else:
        repo.lock_review_inputs = lambda *_args: repo.context.update(change)

    with pytest.raises(ValueError, match="重新分析"):
        service.apply_source_ai_review(
            "B1", repo.run["name"], ["L1"], {}, "TOKEN", "M1", repository=repo,
        )
    assert repo.writes == []


def test_apply_rejects_updated_material_specification():
    repo = ContextRepository()
    start(repo)
    repo.run.update(status="READY", candidates_json=[])
    repo.items[0]["spec_model"] = "New"

    with pytest.raises(ValueError, match="重新分析"):
        service.apply_source_ai_review(
            "B1", repo.run["name"], [], {}, "TOKEN", "M1", repository=repo,
        )
    assert repo.writes == []


def test_raw_source_apply_cannot_confirm_warning_draft_without_selection_receipt(monkeypatch):
    repo = ContextRepository()
    start(repo)
    monkeypatch.setattr(service, "_call_source_review_ai", lambda *_args, **_kwargs: {"ok": True, "proposals": []})
    ready = service.execute_material_ai_fill(repo.run["name"], repository=repo)
    assert ready["status"] == "READY_WITH_WARNINGS", repo.run.get("error_message")

    with pytest.raises(ValueError, match="重新分析"):
        service.apply_source_ai_review(
            "B1", repo.run["name"], [], {}, "TOKEN", "M1", repository=repo,
        )

    assert repo.writes == []
