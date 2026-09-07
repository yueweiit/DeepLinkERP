"""中文用途：四类装箱来源预览、版本校验和不可变确认快照测试。"""

from __future__ import annotations

import copy

from openpyxl import Workbook

import pytest

from overseas_costing.services import packing_snapshot_service as service


def _preview(*, needs_confirmation=False):
    group = {
        "group_id": "package-1",
        "row_numbers": [2, 3],
        "needs_confirmation": needs_confirmation,
        "gross_weight_kg": {"value": "4197.4", "count_once": not needs_confirmation},
        "volume_m3": {"value": "8.7403305", "count_once": not needs_confirmation},
        "net_weight_kg": {"value": "3492", "count_once": not needs_confirmation},
        "package_count": {"value": "6", "count_once": not needs_confirmation},
        "dimensions": {},
        "evidence": [],
    }
    return {
        "ok": not needs_confirmation,
        "source": {"source_kind": "wiki_sheet", "sheet_name": "油漆"},
        "material_row_count": 9,
        "package_count": 6,
        "material_rows": [{"source_row": 2, "material_code": "FL001"}],
        "groups": [group],
        "totals": {
            "net_weight_kg": {"value": "3492", "kind": "calculated_detail_sum"},
            "gross_weight_kg": {"value": "4197.4", "kind": "source_total"},
            "volume_m3": {"value": "8.7403305", "kind": "source_total"},
        },
        "validation": {
            "blocking": ([{"code": "group_confirmation_required", "message": "待确认"}] if needs_confirmation else []),
            "warnings": [],
            "needs_group_confirmation": needs_confirmation,
        },
    }


class FakeRepository:
    def __init__(self):
        self.current = None
        self.saved = []
        self.audits = []
        self.locked = []
        self.commits = 0
        self.rollbacks = 0
        self.domain_state = {
            "items": [{"name": "ITEM-1", "amount": "100"}],
            "expense_pool": [{"amount": "200"}],
            "batch_status": "Calculated",
            "erp_state": "Not Started",
        }

    def lock_batch(self, batch_name):
        self.locked.append(batch_name)

    def current_version(self, _batch_name):
        return "VERSION-1"

    def get_by_idempotency_key(self, key):
        return next((item for item in self.saved if item["idempotency_key"] == key), None)

    def get_current(self, _batch_name):
        return self.current

    def supersede(self, snapshot):
        snapshot["status"] = "Superseded"
        snapshot["is_current"] = 0

    def insert_snapshot(self, values):
        row = {"name": f"SNAP-{len(self.saved) + 1}", **values}
        self.saved.append(row)
        self.current = row
        return row

    def write_audit(self, values):
        self.audits.append(values)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


def test_preview_signs_trusted_source_and_never_uses_browser_totals(monkeypatch) -> None:
    monkeypatch.setattr(service.packing_source_service, "_revision_signing_key", lambda: b"secret")
    captured = {}

    def resolver(**kwargs):
        captured.update(kwargs)
        return {
            "source_hash": "a" * 64,
            "source": {"source_kind": "wiki_sheet", "source_id": "WB:st-1", "source_label": "油漆"},
            "preview": _preview(),
        }

    result = service.preview_packing_source_v2(
        "BATCH-1",
        "wiki_sheet",
        "WB:st-1",
        sheet_name="油漆",
        browser_payload={"total_gross_weight_kg": "1", "workbook_url": "https://evil"},
        resolver=resolver,
    )

    assert result["ok"] is True
    assert result["totals"]["gross_weight_kg"]["value"] == "4197.4"
    assert result["source_revision"]
    assert "browser_payload" not in captured
    assert "workbook_url" not in result["source"]


def test_confirmation_blocks_unresolved_groups(monkeypatch) -> None:
    monkeypatch.setattr(service.packing_source_service, "_revision_signing_key", lambda: b"secret")
    resolver = lambda **_kwargs: {
        "source_hash": "b" * 64,
        "source": {"source_kind": "wiki_sheet", "source_id": "WB:st-1", "source_label": "油漆"},
        "preview": _preview(needs_confirmation=True),
    }
    preview = service.preview_packing_source_v2("BATCH-1", "wiki_sheet", "WB:st-1", resolver=resolver)

    result = service.confirm_packing_snapshot(
        "BATCH-1", preview["source_revision"], {}, repository=FakeRepository(), resolver=resolver
    )

    assert result["ok"] is False
    assert result["needs_group_confirmation"] is True


def test_confirmation_is_idempotent_supersedes_old_and_does_not_touch_formal_cost(monkeypatch) -> None:
    monkeypatch.setattr(service.packing_source_service, "_revision_signing_key", lambda: b"secret")
    repository = FakeRepository()
    old = {"name": "SNAP-OLD", "status": "Confirmed", "is_current": 1}
    repository.current = old
    resolver = lambda **_kwargs: {
        "source_hash": "c" * 64,
        "source": {
            "source_kind": "wiki_sheet",
            "source_id": "WB:st-1",
            "source_label": "油漆",
            "source_updated_at": "2026-09-05T14:41:00+08:00",
        },
        "preview": _preview(needs_confirmation=True),
    }
    preview = service.preview_packing_source_v2("BATCH-1", "wiki_sheet", "WB:st-1", resolver=resolver)
    before = copy.deepcopy(repository.domain_state)
    resolutions = {"groups": {"package-1": {"action": "confirm_shared"}}}

    first = service.confirm_packing_snapshot(
        "BATCH-1", preview["source_revision"], resolutions, repository=repository, resolver=resolver
    )
    second = service.confirm_packing_snapshot(
        "BATCH-1", preview["source_revision"], resolutions, repository=repository, resolver=resolver
    )

    assert first["ok"] is True
    assert first["snapshot"]["name"] == "SNAP-1"
    assert second["snapshot"]["name"] == "SNAP-1"
    assert second["idempotent"] is True
    assert len(repository.saved) == 1
    assert old == {"name": "SNAP-OLD", "status": "Superseded", "is_current": 0}
    assert repository.audits[0]["action_type"] == "PACKING_CONFIRM"
    assert repository.domain_state == before
    assert repository.commits == 1


def test_confirmation_rechecks_source_hash_and_rejects_stale_preview(monkeypatch) -> None:
    monkeypatch.setattr(service.packing_source_service, "_revision_signing_key", lambda: b"secret")
    hashes = iter(("d" * 64, "e" * 64))

    def resolver(**_kwargs):
        return {
            "source_hash": next(hashes),
            "source": {"source_kind": "manual_attachment", "source_id": "ATT-1", "source_label": "装箱单.xlsx"},
            "preview": _preview(),
        }

    preview = service.preview_packing_source_v2("BATCH-1", "manual_attachment", "ATT-1", resolver=resolver)
    result = service.confirm_packing_snapshot(
        "BATCH-1", preview["source_revision"], {}, repository=FakeRepository(), resolver=resolver
    )

    assert result["ok"] is False
    assert result["source_changed"] is True


def test_attachment_sheet_names_are_read_server_side_without_exposing_path(tmp_path) -> None:
    path = tmp_path / "packing.xlsx"
    workbook = Workbook()
    workbook.active.title = "民打印-packing list2026.9.05"
    workbook.create_sheet("油漆-packing list2026.9.05")
    workbook.save(path)

    result = service._attachment_sheet_names({"file_url": str(path)})

    assert result == ["民打印-packing list2026.9.05", "油漆-packing list2026.9.05"]
    assert str(path) not in repr(result)


def test_user_can_split_a_suggested_shared_group_without_double_counting() -> None:
    resolved = service._apply_resolutions(
        _preview(needs_confirmation=True),
        {"groups": {"package-1": {"action": "split"}}},
    )

    assert resolved["validation"]["blocking"] == []
    assert resolved["validation"]["needs_group_confirmation"] is False
    assert resolved["package_count"] == 2
    assert [group["row_numbers"] for group in resolved["groups"]] == [[2], [3]]
    assert resolved["groups"][0]["gross_weight_kg"]["value"] == "4197.4"
    assert resolved["groups"][1]["gross_weight_kg"]["value"] is None
