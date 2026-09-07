"""中文用途：知识库装箱表只读目录、受限刷新和 MinIO 快照完整性测试。"""

from __future__ import annotations

import hashlib
import json

import pytest

from overseas_costing.integrations.dingtalk_approval_source import ApprovalSourceConfig
from overseas_costing.integrations.dingtalk_packing_source import (
    PackingRefreshSubmitter,
    PackingSheetCatalog,
    PackingSnapshotArchive,
    PackingSnapshotNotReady,
    build_refresh_request_key,
)


class FakeCursor:
    def __init__(self, rows=None, one=None):
        self.rows = rows or []
        self.one = one
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def execute(self, sql, params):
        self.calls.append((sql, params))

    def fetchall(self):
        return list(self.rows)

    def fetchone(self):
        return self.one


class FakeConnection:
    def __init__(self, cursor):
        self.fake_cursor = cursor

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def cursor(self, **_kwargs):
        return self.fake_cursor


def _config(user="costing_reader"):
    return ApprovalSourceConfig(
        host="10.203.0.1",
        port=5432,
        database="dingtalk_oa",
        user=user,
        password="secret",
    )


def test_reader_lists_only_enabled_workbooks_and_live_sheets() -> None:
    workbook_cursor = FakeCursor(
        rows=[{"workbook_id": "WB-2026", "year": 2026, "label": "2026 海运装箱", "enabled": True}]
    )
    sheet_cursor = FakeCursor(
        rows=[{"workbook_id": "WB-2026", "sheet_id": "st-1", "sheet_name": "油漆", "deleted_at": None}]
    )
    cursors = iter((workbook_cursor, sheet_cursor))
    connect_calls = []

    def connect(**kwargs):
        connect_calls.append(kwargs)
        return FakeConnection(next(cursors))

    catalog = PackingSheetCatalog(_config(), connect=connect)

    assert catalog.list_workbooks()[0]["workbook_id"] == "WB-2026"
    assert catalog.list_sheets("WB-2026")[0]["sheet_id"] == "st-1"
    assert "costing_read.packing_workbooks_v1" in workbook_cursor.calls[0][0]
    assert "allowed_packing_workbook" not in workbook_cursor.calls[0][0]
    assert "costing_read.packing_sheet_index_v1" in sheet_cursor.calls[0][0]
    assert "packing_sheet_index " not in sheet_cursor.calls[0][0]
    assert all("default_transaction_read_only=on" in call["options"] for call in connect_calls)


def test_refresh_submitter_uses_separate_non_reader_connection_and_only_named_function() -> None:
    cursor = FakeCursor(one={"request_id": 77})
    calls = []

    def connect(**kwargs):
        calls.append(kwargs)
        return FakeConnection(cursor)

    submitter = PackingRefreshSubmitter(_config("costing_job_submitter"), connect=connect)
    request_key = "a" * 64

    assert submitter.request_sheet_refresh("WB-2026", "st-1", request_key, "user@example.com") == 77
    sql, params = cursor.calls[0]
    assert "costing_read.request_packing_sheet_refresh" in sql
    assert params == ("WB-2026", "st-1", request_key, "user@example.com")
    assert calls[0]["user"] == "costing_job_submitter"
    assert "default_transaction_read_only" not in calls[0]["options"]
    assert not hasattr(submitter, "execute")


def test_refresh_request_key_is_sha256_and_idempotent() -> None:
    first = build_refresh_request_key("sheet_snapshot", "WB-2026", "st-1", "nonce-1")
    second = build_refresh_request_key("sheet_snapshot", "WB-2026", "st-1", "nonce-1")
    changed = build_refresh_request_key("sheet_snapshot", "WB-2026", "st-2", "nonce-1")

    assert len(first) == 64
    assert first == second
    assert first != changed
    assert all(character in "0123456789abcdef" for character in first)


class ObjectResponse:
    def __init__(self, content):
        self.content = content
        self.closed = False
        self.released = False

    def read(self):
        return self.content

    def close(self):
        self.closed = True

    def release_conn(self):
        self.released = True


class FakeMinio:
    def __init__(self, content):
        self.response = ObjectResponse(content)
        self.calls = []

    def get_object(self, bucket, object_key):
        self.calls.append((bucket, object_key))
        return self.response


def test_snapshot_download_verifies_size_sha256_and_schema() -> None:
    payload = {
        "schemaVersion": 1,
        "workbookId": "WB-2026",
        "sheetId": "st-1",
        "sheetName": "油漆",
        "mergeRangesAvailable": False,
        "chunks": [],
    }
    content = json.dumps(payload).encode()
    minio = FakeMinio(content)
    archive = PackingSnapshotArchive(bucket="dingtalk-packing-snapshots", client=minio)

    result = archive.download(
        {
            "status": "ready",
            "bucket": "dingtalk-packing-snapshots",
            "object_key": "corp/wb/st/hash.json",
            "actual_size": len(content),
            "content_sha256": hashlib.sha256(content).hexdigest(),
        }
    )

    assert result["sheetId"] == "st-1"
    assert minio.calls == [("dingtalk-packing-snapshots", "corp/wb/st/hash.json")]
    assert minio.response.closed and minio.response.released

    bad = dict(payload, schemaVersion=2)
    bad_content = json.dumps(bad).encode()
    with pytest.raises(ValueError, match="schema version 1"):
        PackingSnapshotArchive(bucket="dingtalk-packing-snapshots", client=FakeMinio(bad_content)).download(
            {
                "status": "ready",
                "object_key": "bad.json",
                "actual_size": len(bad_content),
                "content_sha256": hashlib.sha256(bad_content).hexdigest(),
            }
        )


def test_snapshot_status_must_be_ready() -> None:
    archive = PackingSnapshotArchive(bucket="dingtalk-packing-snapshots", client=FakeMinio(b"{}"))
    with pytest.raises(PackingSnapshotNotReady) as error:
        archive.download({"status": "failed", "error_message": "permission denied"})
    assert error.value.status == "failed"


@pytest.mark.parametrize(
    "value",
    ["https://alidocs.dingtalk.com/i/nodes/secret", "../WB", "", "a" * 201],
)
def test_browser_cannot_supply_an_arbitrary_workbook_url(value) -> None:
    catalog = PackingSheetCatalog(_config(), connect=lambda **_kwargs: None)
    with pytest.raises(ValueError):
        catalog.list_sheets(value)
