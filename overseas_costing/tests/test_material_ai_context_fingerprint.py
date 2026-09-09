"""Drafts must bind the calculation context as well as item/source data."""

from copy import deepcopy

import pytest

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
        return self.run if self.run and self.run["status"] in {"QUEUED", "RUNNING", "READY"} and self.run["input_fingerprint"] == fingerprint else None

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

    result = service.apply_source_ai_review(
        "B1", repo.run["name"], ["L1"], {}, "TOKEN", "M1", repository=repo,
    )

    assert result["status"] == "STALE"
    assert repo.writes == []


def test_apply_rejects_updated_material_specification():
    repo = ContextRepository()
    start(repo)
    repo.run.update(status="READY", candidates_json=[])
    repo.items[0]["spec_model"] = "New"

    result = service.apply_source_ai_review(
        "B1", repo.run["name"], [], {}, "TOKEN", "M1", repository=repo,
    )

    assert result["status"] == "STALE"
    assert repo.writes == []


def test_unchanged_context_can_still_generate_and_confirm(monkeypatch):
    repo = ContextRepository()
    start(repo)
    monkeypatch.setattr(service, "_call_source_review_ai", lambda *_args, **_kwargs: {"ok": True, "proposals": []})
    ready = service.execute_material_ai_fill(repo.run["name"], repository=repo)
    assert ready["status"] == "READY", repo.run.get("error_message")

    applied = service.apply_source_ai_review(
        "B1", repo.run["name"], [], {}, "TOKEN", "M1", repository=repo,
    )

    assert applied["status"] == "APPLIED"
    assert len(repo.writes) == 1
