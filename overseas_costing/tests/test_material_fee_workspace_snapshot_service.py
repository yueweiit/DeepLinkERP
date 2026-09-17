from __future__ import annotations

import sqlite3
from types import SimpleNamespace

import pytest

from overseas_costing.services.logistics_settlement.store import Store


def _store() -> Store:
    store = Store.sqlite(sqlite3.connect(":memory:"))
    store.install()
    return store


def _builder(calls: list[str], *, total: str = "100.00"):
    def build(batch_name: str, version_name: str, page: int, page_length: int) -> dict:
        calls.append(f"{batch_name}:{version_name}:{page}:{page_length}")
        return {
            "detail": {"header": {"name": batch_name}, "edit_token": "must-not-cache"},
            "materials": {
                "items": [{"name": "ITEM-1", "content": "已落库的 OA 正文"}],
                "missing_cell_count": 0,
            },
            "fees": {"fees": [], "summary": {}},
            "preview": {"summary": {"total_cost_rmb": total}, "preview_token": "must-not-cache"},
            "settlement": {
                "logistics": {"approval_no": "OA-1", "image_url": "data:image/png;base64,AAAA"},
                "raw_attachment": b"not-cacheable",
            },
        }

    return build


def test_first_read_builds_persistent_snapshot_and_second_read_hits_cache() -> None:
    from overseas_costing.services import material_fee_workspace_snapshot_service as service

    store = _store()
    calls: list[str] = []
    fingerprint_calls: list[str] = []

    def fingerprint(batch_name: str, version_name: str) -> str:
        fingerprint_calls.append(f"{batch_name}:{version_name}")
        return "fingerprint-1"

    first = service.get_snapshot(
        "B1",
        "V1",
        page=1,
        page_length=200,
        store=store,
        fingerprint_loader=fingerprint,
        snapshot_builder=_builder(calls),
        now="2026-09-17T01:00:00+00:00",
    )
    second = service.get_snapshot(
        "B1",
        "V1",
        page=1,
        page_length=200,
        store=store,
        fingerprint_loader=fingerprint,
        snapshot_builder=_builder(calls, total="999.00"),
        now="2026-09-17T01:01:00+00:00",
    )

    assert calls == ["B1:V1:1:200"]
    assert fingerprint_calls == ["B1:V1"]
    assert first["data"] == second["data"]
    assert first["cache"]["served_from_cache"] is False
    assert second["cache"]["served_from_cache"] is True
    assert second["cache"]["status"] == "ready"
    assert second["cache"]["input_fingerprint"] == "fingerprint-1"
    assert second["cache"]["generated_at"] == "2026-09-17T01:00:00+00:00"
    assert "raw_attachment" not in second["data"]["settlement"]
    assert "image_url" not in second["data"]["settlement"]["logistics"]
    assert second["data"]["materials"]["items"][0]["content"] == "已落库的 OA 正文"
    assert "edit_token" not in second["data"]["detail"]
    assert "preview_token" not in second["data"]["preview"]


def test_freshness_check_marks_changed_snapshot_stale_without_rebuilding() -> None:
    from overseas_costing.services import material_fee_workspace_snapshot_service as service

    store = _store()
    calls: list[str] = []
    service.get_snapshot(
        "B1",
        "V1",
        store=store,
        fingerprint_loader=lambda *_: "fingerprint-1",
        snapshot_builder=_builder(calls),
        now="2026-09-17T01:00:00+00:00",
    )

    unchanged = service.check_freshness(
        "B1",
        "V1",
        snapshot_fingerprint="fingerprint-1",
        store=store,
        fingerprint_loader=lambda *_: "fingerprint-1",
        now="2026-09-17T01:02:00+00:00",
    )
    changed = service.check_freshness(
        "B1",
        "V1",
        snapshot_fingerprint="fingerprint-1",
        store=store,
        fingerprint_loader=lambda *_: "fingerprint-2",
        now="2026-09-17T01:03:00+00:00",
    )
    cached = service.get_snapshot(
        "B1",
        "V1",
        store=store,
        fingerprint_loader=lambda *_: "fingerprint-2",
        snapshot_builder=_builder(calls, total="999.00"),
        now="2026-09-17T01:04:00+00:00",
    )

    assert unchanged == {
        "ok": True,
        "batch_name": "B1",
        "version_name": "V1",
        "unchanged": True,
        "snapshot_fingerprint": "fingerprint-1",
        "current_fingerprint": "fingerprint-1",
        "checked_at": "2026-09-17T01:02:00+00:00",
    }
    assert changed["unchanged"] is False
    assert changed["current_fingerprint"] == "fingerprint-2"
    assert cached["cache"]["status"] == "stale"
    assert cached["cache"]["served_from_cache"] is True
    assert calls == ["B1:V1:1:200"]


def test_refresh_failure_keeps_last_known_good_snapshot() -> None:
    from overseas_costing.services import material_fee_workspace_snapshot_service as service

    store = _store()
    service.get_snapshot(
        "B1",
        "V1",
        store=store,
        fingerprint_loader=lambda *_: "fingerprint-1",
        snapshot_builder=_builder([]),
        now="2026-09-17T01:00:00+00:00",
    )

    def fail(*_args):
        raise RuntimeError("database busy")

    stale = service.refresh_snapshot(
        "B1",
        "V1",
        store=store,
        fingerprint_loader=lambda *_: "fingerprint-2",
        snapshot_builder=fail,
        now="2026-09-17T01:05:00+00:00",
    )

    assert stale["ok"] is True
    assert stale["data"]["preview"]["summary"]["total_cost_rmb"] == "100.00"
    assert stale["cache"]["status"] == "stale"
    assert stale["cache"]["served_from_cache"] is True
    assert stale["cache"]["refresh_error"] == "database busy"
    assert stale["cache"]["last_success_at"] == "2026-09-17T01:00:00+00:00"


def test_first_build_failure_has_no_stale_payload_to_serve() -> None:
    from overseas_costing.services import material_fee_workspace_snapshot_service as service

    with pytest.raises(RuntimeError, match="database busy"):
        service.get_snapshot(
            "B1",
            "V1",
            store=_store(),
            fingerprint_loader=lambda *_: "fingerprint-1",
            snapshot_builder=lambda *_: (_ for _ in ()).throw(RuntimeError("database busy")),
            now="2026-09-17T01:00:00+00:00",
        )


def test_concurrent_refresh_reuses_last_good_snapshot_without_duplicate_build() -> None:
    from overseas_costing.services import material_fee_workspace_snapshot_service as service

    store = _store()
    calls: list[str] = []
    service.get_snapshot(
        "B1",
        "V1",
        store=store,
        fingerprint_loader=lambda *_: "fingerprint-1",
        snapshot_builder=_builder(calls),
        now="2026-09-17T01:00:00+00:00",
    )
    state_id = service._state_id("B1", "V1", 1, 200)
    started = service._begin_refresh(
        store,
        state_id,
        {"batch_name": "B1", "version_name": "V1", "page": 1, "page_length": 200},
        "2026-09-17T01:01:00+00:00",
    )
    assert started is not None

    concurrent = service.refresh_snapshot(
        "B1",
        "V1",
        store=store,
        fingerprint_loader=lambda *_: "fingerprint-2",
        snapshot_builder=_builder(calls, total="999.00"),
        now="2026-09-17T01:02:00+00:00",
    )

    assert calls == ["B1:V1:1:200"]
    assert concurrent["data"]["preview"]["summary"]["total_cost_rmb"] == "100.00"
    assert concurrent["cache"]["served_from_cache"] is True
    assert concurrent["cache"]["status"] == "refreshing"


def test_context_rejects_a_version_owned_by_another_batch(monkeypatch) -> None:
    from overseas_costing.services import batch_service
    from overseas_costing.services import material_fee_workspace_snapshot_service as service

    fake_db = SimpleNamespace(
        get_value=lambda doctype, name, field: "OTHER-BATCH"
        if doctype == "Overseas Cost Version" and name == "V-SECRET" and field == "batch"
        else None
    )
    monkeypatch.setattr(batch_service, "frappe", SimpleNamespace(db=fake_db))
    monkeypatch.setattr(batch_service, "_resolve_batch_name", lambda value: "B-ALLOWED")

    with pytest.raises(ValueError, match="版本不属于当前批次"):
        service._context("B-ALLOWED", "V-SECRET")


def test_incomplete_rebuild_never_replaces_last_good_snapshot() -> None:
    from overseas_costing.services import material_fee_workspace_snapshot_service as service

    store = _store()
    service.get_snapshot(
        "B1",
        "V1",
        store=store,
        fingerprint_loader=lambda *_: "fingerprint-1",
        snapshot_builder=_builder([]),
        now="2026-09-17T01:00:00+00:00",
    )

    stale = service.refresh_snapshot(
        "B1",
        "V1",
        store=store,
        fingerprint_loader=lambda *_: "fingerprint-2",
        snapshot_builder=lambda *_: {"detail": {}, "materials": {}, "fees": {}},
        now="2026-09-17T01:05:00+00:00",
    )

    assert stale["cache"]["status"] == "stale"
    assert "preview" in stale["cache"]["refresh_error"]
    assert stale["data"]["preview"]["summary"]["total_cost_rmb"] == "100.00"
