from __future__ import annotations

import hashlib
from datetime import datetime, timezone

import pytest

from overseas_costing.integrations.dingtalk_approval_source import (
    ApprovalSourceConfig,
    ArchiveIntegrityError,
    ArchiveNotReady,
    MinioArchiveClient,
    PostgresApprovalSource,
    parse_shanghai_window,
)


class FakeCursor:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def execute(self, sql, params):
        self.calls.append((sql, params))

    def fetchall(self):
        return list(self.rows)


class FakeConnection:
    def __init__(self, cursor):
        self.fake_cursor = cursor

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def cursor(self, **_kwargs):
        return self.fake_cursor


def _config() -> ApprovalSourceConfig:
    return ApprovalSourceConfig(
        host="10.203.0.1",
        port=5432,
        database="dingtalk_oa",
        user="costing_reader",
        password="secret",
    )


def test_parse_shanghai_window_uses_half_open_utc_boundaries() -> None:
    start, end = parse_shanghai_window("2026-09-01", "2026-09-03")

    assert start == datetime(2026, 8, 31, 16, tzinfo=timezone.utc)
    assert end == datetime(2026, 9, 3, 16, tzinfo=timezone.utc)


def test_postgres_source_lists_instances_with_one_parameterized_query() -> None:
    updated_at = datetime(2026, 9, 4, 3, 16, tzinfo=timezone.utc)
    cursor = FakeCursor(
        [
            {
                "process_instance_id": "PROC-001",
                "business_id": "OA-001",
                "process_code": "LOGISTICS",
                "status": "COMPLETED",
                "raw_payload": {"formComponentValues": []},
                "updated_at": updated_at,
            }
        ]
    )
    connect_calls = []

    def connect(**kwargs):
        connect_calls.append(kwargs)
        return FakeConnection(cursor)

    source = PostgresApprovalSource(_config(), connect=connect)
    result = source.list_instances(
        process_code="LOGISTICS",
        start="2026-09-01",
        end="2026-09-03",
        limit=20,
    )

    assert len(cursor.calls) == 1
    sql, params = cursor.calls[0]
    assert "process_code = %s" in sql
    assert "create_time >= %s" in sql
    assert "create_time < %s" in sql
    assert params[0] == "LOGISTICS"
    assert params[-1] == 20
    assert result["items"][0]["processInstanceId"] == "PROC-001"
    assert result["items"][0]["businessId"] == "OA-001"
    assert result["source_updated_at"] == updated_at
    assert connect_calls[0]["host"] == "10.203.0.1"
    assert connect_calls[0]["options"] == "-c default_transaction_read_only=on -c statement_timeout=10000"


def test_postgres_source_fetches_linked_instances_in_one_query() -> None:
    cursor = FakeCursor(
        [
            {"process_instance_id": "PROC-B", "raw_payload": {"title": "B"}},
            {"process_instance_id": "PROC-A", "raw_payload": {"title": "A"}},
        ]
    )
    source = PostgresApprovalSource(_config(), connect=lambda **_kwargs: FakeConnection(cursor))

    items = source.get_instances(["PROC-A", "PROC-B", "PROC-A"])

    assert len(cursor.calls) == 1
    sql, params = cursor.calls[0]
    assert "process_instance_id = ANY(%s)" in sql
    assert params == (["PROC-A", "PROC-B"],)
    assert list(items) == ["PROC-A", "PROC-B"]
    assert items["PROC-A"]["title"] == "A"


def test_postgres_source_loads_instance_bundle_without_per_record_queries() -> None:
    class SequenceCursor(FakeCursor):
        def __init__(self):
            super().__init__([])
            self.result_sets = [
                [
                    {
                        "process_instance_id": "PROC-MAIN",
                        "originator_user_name": "张三",
                        "originator_dept_name": "国际物流",
                        "raw_payload": {"title": "物流"},
                    },
                    {"process_instance_id": "PROC-BUY", "raw_payload": {"title": "采购"}},
                ],
                [
                    {
                        "process_instance_id": "PROC-MAIN",
                        "file_id": "FILE-1",
                        "archive_status": "archived",
                    }
                ],
                [{"source_updated_at": datetime(2026, 9, 4, tzinfo=timezone.utc), "source_lag_seconds": 8}],
            ]

        def fetchall(self):
            return self.result_sets[len(self.calls) - 1]

    cursor = SequenceCursor()
    source = PostgresApprovalSource(_config(), connect=lambda **_kwargs: FakeConnection(cursor))

    result = source.get_instance_bundle(["PROC-MAIN", "PROC-BUY", "PROC-MAIN"])

    assert len(cursor.calls) == 3
    assert all(call[1] == (["PROC-MAIN", "PROC-BUY"],) for call in cursor.calls[:2])
    assert result["instances"]["PROC-MAIN"]["title"] == "物流"
    assert result["instances"]["PROC-MAIN"]["originatorUserName"] == "张三"
    assert result["instances"]["PROC-MAIN"]["originatorDeptName"] == "国际物流"
    assert result["attachments"][0]["file_id"] == "FILE-1"
    assert result["health"]["source_lag_seconds"] == 8


def test_postgres_source_loads_all_approval_actors_with_one_scoped_query() -> None:
    class SequenceCursor(FakeCursor):
        def __init__(self):
            super().__init__([])
            self.result_sets = [
                [{
                    "corp_id": "CORP-1",
                    "process_instance_id": "PROC-MAIN",
                    "originator_user_id": "USER-1",
                    "raw_payload": {
                        "operationRecords": [{"userId": "USER-2"}],
                    },
                }],
                [{
                    "corp_id": "CORP-1",
                    "process_instance_id": "PROC-MAIN",
                    "file_id": "FILE-1",
                    "comment_user_id": "USER-3",
                }],
                [
                    {"corp_id": "CORP-1", "user_id": "USER-1", "name": "李仲华", "title": ""},
                    {"corp_id": "CORP-1", "user_id": "USER-2", "name": "周汉琴", "title": ""},
                    {"corp_id": "CORP-1", "user_id": "USER-3", "name": "陈一", "title": ""},
                ],
                [{"source_lag_seconds": 3}],
            ]

        def fetchall(self):
            return self.result_sets[len(self.calls) - 1]

    cursor = SequenceCursor()
    source = PostgresApprovalSource(_config(), connect=lambda **_kwargs: FakeConnection(cursor))

    result = source.get_instance_bundle(["PROC-MAIN"])

    assert len(cursor.calls) == 4
    actor_sql, actor_params = cursor.calls[2]
    assert "costing_read.approval_actor_names_v1" in actor_sql
    assert "unnest(%s::text[], %s::text[])" in actor_sql
    assert set(zip(*actor_params)) == {
        ("CORP-1", "USER-1"),
        ("CORP-1", "USER-2"),
        ("CORP-1", "USER-3"),
    }
    assert result["instances"]["PROC-MAIN"]["corpId"] == "CORP-1"
    assert result["actors"]["CORP-1"]["USER-1"]["name"] == "李仲华"
    assert result["actors"]["CORP-1"]["USER-2"]["name"] == "周汉琴"
    assert result["actors"]["CORP-1"]["USER-3"]["name"] == "陈一"


def test_postgres_source_tolerates_missing_optional_actor_view() -> None:
    class MissingActorCursor(FakeCursor):
        def __init__(self):
            super().__init__([])
            self.result_sets = [
                [{
                    "corp_id": "CORP-1",
                    "process_instance_id": "PROC-MAIN",
                    "originator_user_id": "USER-1",
                    "raw_payload": {},
                }],
                [],
                [{"source_lag_seconds": 3}],
            ]
            self.result_index = 0

        def execute(self, sql, params):
            self.calls.append((sql, params))
            if "approval_actor_names_v1" in sql:
                raise RuntimeError('relation "costing_read.approval_actor_names_v1" does not exist')

        def fetchall(self):
            value = self.result_sets[self.result_index]
            self.result_index += 1
            return value

    class RecoverableConnection(FakeConnection):
        def __init__(self, cursor):
            super().__init__(cursor)
            self.rollback_count = 0

        def rollback(self):
            self.rollback_count += 1

    cursor = MissingActorCursor()
    connection = RecoverableConnection(cursor)
    source = PostgresApprovalSource(_config(), connect=lambda **_kwargs: connection)

    result = source.get_instance_bundle(["PROC-MAIN"])

    assert connection.rollback_count == 1
    assert result["instances"]["PROC-MAIN"]["originatorUserId"] == "USER-1"
    assert result["actors"] == {}
    assert result["health"]["source_lag_seconds"] == 3


class FakeObjectResponse:
    def __init__(self, content: bytes):
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
    def __init__(self, response):
        self.response = response
        self.calls = []

    def get_object(self, bucket, object_key):
        self.calls.append((bucket, object_key))
        return self.response


def test_minio_archive_client_downloads_and_verifies_content() -> None:
    content = b"archived-attachment"
    response = FakeObjectResponse(content)
    minio = FakeMinio(response)
    client = MinioArchiveClient(bucket="dingtalk-approval-archive", client=minio)

    downloaded, metadata = client.download(
        {
            "archive_status": "archived",
            "object_key": "corp/proc/file",
            "actual_size": len(content),
            "sha256": hashlib.sha256(content).hexdigest(),
            "content_type": "application/pdf",
        }
    )

    assert downloaded == content
    assert metadata["content_length"] == len(content)
    assert minio.calls == [("dingtalk-approval-archive", "corp/proc/file")]
    assert response.closed is True
    assert response.released is True


def test_minio_archive_client_rejects_not_ready_and_bad_hash() -> None:
    client = MinioArchiveClient(bucket="dingtalk-approval-archive", client=FakeMinio(FakeObjectResponse(b"bad")))

    with pytest.raises(ArchiveNotReady) as pending:
        client.download({"archive_status": "retry", "last_error": "temporary"})
    assert pending.value.status == "retry"

    with pytest.raises(ArchiveIntegrityError):
        client.download(
            {
                "archive_status": "archived",
                "object_key": "corp/proc/file",
                "actual_size": 3,
                "sha256": hashlib.sha256(b"expected").hexdigest(),
            }
        )
