from __future__ import annotations

import hashlib
import json
import sqlite3
from types import SimpleNamespace

import pytest

from overseas_costing.services.logistics_settlement.store import Store


def _store() -> Store:
    store = Store.sqlite(sqlite3.connect(":memory:"))
    store.install()
    return store


def _row(content_hash: str = "a" * 64) -> dict:
    return {
        "corp_id": "C",
        "workbook_id": "WB-2026",
        "year": 2026,
        "workbook_label": "2026 装箱计划",
        "workbook_updated_at": "2026-09-16T07:00:00+08:00",
        "sheet_id": "S-1",
        "sheet_name": "指环扣-packing list2026.9.05",
        "visibility": "visible",
        "source_updated_at": "2026-09-16T07:10:00+08:00",
        "indexed_at": "2026-09-16T07:11:00+08:00",
        "snapshot_id": "SN-1",
        "snapshot_status": "ready",
        "snapshot_created_at": "2026-09-16T07:12:00+08:00",
        "capture_finished_at": "2026-09-16T07:12:00+08:00",
        "content_sha256": content_hash,
        "bucket": "packing",
        "object_key": "snapshots/WB-2026/S-1.json",
    }


def _payload(quantity: int = 4) -> dict:
    return {
        "schemaVersion": 1,
        "workbookId": "WB-2026",
        "sheetId": "S-1",
        "sheetName": "指环扣-packing list2026.9.05",
        "captureFinishedAt": "2026-09-16T07:12:00+08:00",
        "mergeRangesAvailable": True,
        "values": [
            ["物料编码", "数量", "单位", "毛重", "体积"],
            ["FL000427", quantity, "件", 8, 2],
        ],
    }


class FakeCatalog:
    def __init__(self, rows: list[dict]):
        self.rows = rows
        self.calls = 0

    def list_catalog_snapshot(self):
        self.calls += 1
        return list(self.rows)


class FakeArchive:
    def __init__(self, payload: dict):
        self.payload = payload
        self.downloads = 0
        self.error: Exception | None = None

    def download(self, _manifest):
        self.downloads += 1
        if str(_manifest.get("status") or "pending") != "ready":
            raise RuntimeError("snapshot is not ready")
        if self.error:
            raise self.error
        return self.payload


def _clients(row: dict | None = None, payload: dict | None = None):
    catalog = FakeCatalog([row or _row()])
    archive = FakeArchive(payload or _payload())
    return SimpleNamespace(catalog=catalog, archive=archive)


def test_first_sync_materializes_catalog_and_trusted_sheet() -> None:
    from overseas_costing.services import packing_sheet_cache_service as service

    store = _store()
    clients = _clients()

    result = service.refresh_catalog_cache(
        store=store,
        clients=clients,
        now="2026-09-16T00:00:00+00:00",
    )

    assert result == {"checked": 1, "updated": 1, "unchanged": 0, "failed": 0}
    assert clients.archive.downloads == 1
    catalog = service.get_cached_catalog(store=store, now="2026-09-16T00:01:00+00:00")
    sheet = catalog["wiki_workbooks"][0]["sheets"][0]
    assert sheet["source_id"] == "WB-2026:S-1"
    assert sheet["cache_status"] == "ready"
    assert sheet["content_hash"] == "a" * 64
    trusted = service.get_cached_sheet("WB-2026:S-1", store=store)
    assert trusted["source_hash"] == "a" * 64
    assert trusted["preview"]["material_rows"][0]["material_code"] == "FL000427"


def test_first_sync_satisfies_real_archive_status_and_hash_contract() -> None:
    from overseas_costing.integrations.dingtalk_packing_source import PackingSnapshotArchive
    from overseas_costing.services import packing_sheet_cache_service as service

    content = json.dumps(_payload(), ensure_ascii=False).encode("utf-8")
    row = {
        **_row(hashlib.sha256(content).hexdigest()),
        "actual_size": len(content),
    }

    class Response:
        def read(self):
            return content

        def close(self):
            return None

        def release_conn(self):
            return None

    class Minio:
        @staticmethod
        def get_object(bucket, object_key):
            assert (bucket, object_key) == ("packing", row["object_key"])
            return Response()

    clients = SimpleNamespace(
        catalog=FakeCatalog([row]),
        archive=PackingSnapshotArchive(bucket="packing", client=Minio()),
    )

    result = service.refresh_catalog_cache(
        store=_store(),
        clients=clients,
        now="2026-09-16T00:00:00+00:00",
    )

    assert result == {"checked": 1, "updated": 1, "unchanged": 0, "failed": 0}


def test_unchanged_sync_does_not_download_or_reparse_snapshot(monkeypatch) -> None:
    from overseas_costing.services import packing_sheet_cache_service as service

    store = _store()
    clients = _clients()
    service.refresh_catalog_cache(store=store, clients=clients, now="2026-09-16T00:00:00+00:00")
    clients.archive.downloads = 0
    parses = []
    monkeypatch.setattr(service, "_build_trusted_sheet", lambda *_args, **_kwargs: parses.append(True))

    result = service.refresh_catalog_cache(
        store=store,
        clients=clients,
        now="2026-09-16T10:00:00+00:00",
    )

    assert result == {"checked": 1, "updated": 0, "unchanged": 1, "failed": 0}
    assert clients.archive.downloads == 0
    assert parses == []


def test_failed_changed_snapshot_keeps_last_good_payload() -> None:
    from overseas_costing.services import packing_sheet_cache_service as service

    store = _store()
    clients = _clients()
    service.refresh_catalog_cache(store=store, clients=clients, now="2026-09-16T00:00:00+00:00")
    clients.catalog.rows = [_row("b" * 64)]
    clients.archive.error = RuntimeError("temporary MinIO failure")

    result = service.refresh_catalog_cache(
        store=store,
        clients=clients,
        now="2026-09-16T10:00:00+00:00",
    )

    assert result["failed"] == 1
    trusted = service.get_cached_sheet("WB-2026:S-1", store=store)
    assert trusted["source_hash"] == "a" * 64
    catalog = service.get_cached_catalog(store=store, now="2026-09-18T10:01:00+00:00")
    sheet = catalog["wiki_workbooks"][0]["sheets"][0]
    assert sheet["cache_status"] == "stale"
    assert "temporary MinIO failure" in sheet["sync_error"]


def test_catalog_marks_successful_cache_stale_after_24_hours() -> None:
    from overseas_costing.services import packing_sheet_cache_service as service

    store = _store()
    service.refresh_catalog_cache(
        store=store,
        clients=_clients(),
        now="2026-09-16T00:00:00+00:00",
    )

    catalog = service.get_cached_catalog(store=store, now="2026-09-17T00:00:01+00:00")

    assert catalog["catalog_status"] == "stale"
    assert catalog["wiki_workbooks"][0]["sheets"][0]["cache_status"] == "stale"


def test_removed_sheet_is_retained_as_unavailable_without_deleting_cached_payload() -> None:
    from overseas_costing.services import packing_sheet_cache_service as service

    store = _store()
    clients = _clients()
    service.refresh_catalog_cache(
        store=store,
        clients=clients,
        now="2026-09-16T00:00:00+00:00",
    )
    clients.catalog.rows = []

    result = service.refresh_catalog_cache(
        store=store,
        clients=clients,
        now="2026-09-16T10:00:00+00:00",
    )

    assert result == {"checked": 0, "updated": 0, "unchanged": 0, "failed": 0}
    catalog = service.get_cached_catalog(store=store, now="2026-09-18T10:01:00+00:00")
    sheet = catalog["wiki_workbooks"][0]["sheets"][0]
    assert sheet["source_id"] == "WB-2026:S-1"
    assert sheet["cache_status"] == "unavailable"
    with pytest.raises(service.PackingSheetCacheError, match="已停用或移除"):
        service.get_cached_sheet("WB-2026:S-1", store=store)


def test_expired_worker_cannot_overwrite_newer_run() -> None:
    from overseas_costing.services import packing_sheet_cache_service as service

    store = _store()
    first = service._begin_run(store, "2026-09-16T00:00:00+00:00")
    assert first is not None
    first_token, _ = first
    second = service._begin_run(store, "2026-09-16T03:00:01+00:00")
    assert second is not None

    with pytest.raises(service.PackingSheetCacheError, match="更新的任务取代"):
        service._save_sheet_state(
            store,
            first_token,
            "WB-2026:S-1",
            {"source_id": "WB-2026:S-1"},
            "2026-09-16T03:00:02+00:00",
        )


def test_scheduler_runs_twice_daily_at_eight_and_eighteen() -> None:
    from overseas_costing import hooks

    events = hooks.scheduler_events["cron"]

    assert "0 8,18 * * *" in events
    assert (
        "overseas_costing.services.packing_sheet_cache_service.scheduled_refresh_catalog_cache"
        in events["0 8,18 * * *"]
    )


def test_batch_catalog_recommendation_reads_only_local_cache(monkeypatch) -> None:
    from overseas_costing.services import packing_sheet_cache_service as cache
    from overseas_costing.services import packing_snapshot_service as service

    store = _store()
    cache.refresh_catalog_cache(
        store=store,
        clients=_clients(),
        now="2026-09-16T00:00:00+00:00",
    )

    class FakeDB:
        @staticmethod
        def get_value(_doctype, _name, _fields, as_dict=False):
            assert as_dict is True
            return {
                "name": "B1",
                "batch_no": "BATCH-1",
                "waybill_no": "",
                "source_approval_no": "",
                "source_instance_id": "",
                "project_collection": "指环扣",
                "creation": "2026-09-05 08:00:00",
            }

    class FakeFrappe:
        db = FakeDB()

        @staticmethod
        def get_list(doctype, **_kwargs):
            assert doctype == "Overseas Cost Item"
            return [{"material_code": "FL000427", "product_name": "指环扣", "source_doc_no": ""}]

    monkeypatch.setattr(service, "frappe", FakeFrappe())
    monkeypatch.setattr(service.effective_source, "current_source_bundle", lambda *_args: None)
    local_catalog = cache.get_cached_catalog(store=store, now="2026-09-16T00:01:00+00:00")
    monkeypatch.setattr(
        cache,
        "get_cached_catalog",
        lambda **_kwargs: local_catalog,
    )
    monkeypatch.setattr(
        service.packing_source_service.dingtalk_approval_service,
        "get_batch_dingtalk_approval_detail",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("must stay local")),
    )

    result = service.list_cached_packing_sheet_catalog("B1")

    sheet = result["wiki_workbooks"][0]["sheets"][0]
    assert result["catalog_status"] == "ready"
    assert sheet["is_recommended"] is True
    assert sheet["matched_item_codes"] == ["FL000427"]


def test_manual_refresh_materializes_only_selected_sheet() -> None:
    from overseas_costing.services import packing_sheet_cache_service as service

    store = _store()
    first = _row()
    second = {
        **_row("b" * 64),
        "sheet_id": "S-2",
        "sheet_name": "油漆-packing list2026.9.06",
        "snapshot_id": "SN-2",
        "object_key": "snapshots/WB-2026/S-2.json",
    }
    catalog = FakeCatalog([first, second])

    class SelectedArchive(FakeArchive):
        def download(self, manifest):
            self.downloads += 1
            assert manifest["sheet_id"] == "S-2"
            return {**_payload(9), "sheetId": "S-2", "sheetName": second["sheet_name"]}

    clients = SimpleNamespace(catalog=catalog, archive=SelectedArchive(_payload()))

    result = service.refresh_sheet_cache(
        "WB-2026",
        "S-2",
        store=store,
        clients=clients,
        now="2026-09-16T10:00:00+00:00",
    )

    assert result == {"checked": 1, "updated": 1, "unchanged": 0, "failed": 0}
    assert clients.archive.downloads == 1
    assert service.get_cached_sheet("WB-2026:S-2", store=store)["source_hash"] == "b" * 64
    with pytest.raises(service.PackingSheetCacheError, match="尚无可用"):
        service.get_cached_sheet("WB-2026:S-1", store=store)


def test_manual_refresh_request_key_is_idempotently_bound_to_one_target() -> None:
    from overseas_costing.services import packing_sheet_cache_service as service

    store = _store()
    request_key = "a" * 64
    service.register_manual_refresh(
        batch_name="B-1",
        workbook_id="WB-2026",
        sheet_id="S-1",
        request_key=request_key,
        store=store,
    )
    service.register_manual_refresh(
        batch_name="B-1",
        workbook_id="WB-2026",
        sheet_id="S-1",
        request_key=request_key,
        store=store,
    )

    with pytest.raises(service.PackingSheetCacheError, match="已绑定其他"):
        service.register_manual_refresh(
            batch_name="B-1",
            workbook_id="WB-2026",
            sheet_id="S-2",
            request_key=request_key,
            store=store,
        )


def test_manual_refresh_stays_pending_while_another_cache_run_holds_the_lease(monkeypatch) -> None:
    from overseas_costing.services import packing_sheet_cache_service as service

    store = _store()
    request_key = "a" * 64
    service.register_manual_refresh(
        batch_name="B-1",
        workbook_id="WB-2026",
        sheet_id="S-1",
        request_key=request_key,
        store=store,
    )
    monkeypatch.setattr(
        service,
        "refresh_sheet_cache",
        lambda *_args, **_kwargs: {
            "checked": 0,
            "updated": 0,
            "unchanged": 0,
            "failed": 0,
            "skipped": True,
        },
    )

    result = service.complete_manual_refresh(request_key, store=store)

    assert result == {"ok": False, "pending": True}
    request = store.get("state", service._manual_refresh_state_id(request_key))
    assert request["status"] == "pending"
