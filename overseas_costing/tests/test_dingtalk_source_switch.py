from __future__ import annotations

from datetime import datetime, timezone

import pytest


def _logistics_payload(instance_id: str = "PROC-LOGISTICS-001") -> dict:
    return {
        "processInstanceId": instance_id,
        "businessId": "OA-LOGISTICS-001",
        "title": "国际物流审批",
        "status": "COMPLETED",
        "formComponentValues": [
            {"name": "物流方式", "value": "海运"},
            {"name": "柜号", "value": "FSCU8486789"},
        ],
    }


class FakePostgresSource:
    def __init__(self, items=None):
        self.items = list(items or [])
        self.list_calls = []
        self.get_calls = []

    def list_instances(self, **kwargs):
        self.list_calls.append(kwargs)
        return {
            "items": self.items,
            "source_updated_at": datetime(2026, 9, 4, 3, 16, tzinfo=timezone.utc),
            "source_lag_seconds": 12,
            "data_source": "postgres",
            "fallback_used": False,
        }

    def get_instances(self, instance_ids):
        ids = list(instance_ids)
        self.get_calls.append(ids)
        return {
            instance_id: {
                "processInstanceId": instance_id,
                "businessId": f"OA-{instance_id}",
                "title": "采购支出",
                "status": "COMPLETED",
                "formComponentValues": [],
            }
            for instance_id in ids
        }


def test_postgres_mode_lists_full_approvals_without_any_dingtalk_api(monkeypatch) -> None:
    from overseas_costing.scripts import import_oa_logistics

    source = FakePostgresSource([_logistics_payload()])
    monkeypatch.setenv("OVERSEAS_COSTING_OA_SOURCE", "postgres")
    monkeypatch.setattr(import_oa_logistics, "_get_postgres_approval_source", lambda: source)
    monkeypatch.setattr(
        import_oa_logistics,
        "get_access_token",
        lambda **_kwargs: pytest.fail("数据库模式不应请求钉钉 token"),
    )
    monkeypatch.setattr(
        import_oa_logistics,
        "list_process_instance_ids",
        lambda **_kwargs: pytest.fail("数据库模式不应调用钉钉列表接口"),
    )
    monkeypatch.setattr(
        import_oa_logistics,
        "get_process_instance_detail",
        lambda **_kwargs: pytest.fail("数据库模式不应逐张请求钉钉详情"),
    )

    result = import_oa_logistics.pull_logistics_approvals(
        process_code="PROC-LOGISTICS",
        start="2026-09-01",
        end="2026-09-03",
        include_all=True,
    )

    assert source.list_calls == [
        {
            "process_code": "PROC-LOGISTICS",
            "start": "2026-09-01",
            "end": "2026-09-03",
            "limit": 400,
        }
    ]
    assert result["data_source"] == "postgres"
    assert result["fallback_used"] is False
    assert result["source_lag_seconds"] == 12
    assert result["filtered_count"] == 1
    assert result["items"][0]["source_instance_id"] == "PROC-LOGISTICS-001"


def test_postgres_mode_fetches_linked_purchase_approvals_in_one_batch(monkeypatch) -> None:
    from overseas_costing.scripts import import_oa_logistics

    source = FakePostgresSource()
    monkeypatch.setenv("OVERSEAS_COSTING_OA_SOURCE", "postgres")
    monkeypatch.setattr(import_oa_logistics, "_get_postgres_approval_source", lambda: source)

    result = import_oa_logistics.pull_linked_purchase_approval_details(
        token="",
        linked_approvals=[
            {"source_instance_id": "PROC-PURCHASE-A"},
            {"source_instance_id": "PROC-PURCHASE-B"},
            {"source_instance_id": "PROC-PURCHASE-A"},
        ],
    )

    assert source.get_calls == [["PROC-PURCHASE-A", "PROC-PURCHASE-B"]]
    assert len(result) == 3
    assert all(item["data_source"] == "postgres" for item in result)


def test_postgres_failure_never_falls_back_to_dingtalk_implicitly(monkeypatch) -> None:
    from overseas_costing.scripts import import_oa_logistics

    class BrokenSource:
        def list_instances(self, **_kwargs):
            raise ConnectionError("database unavailable")

    monkeypatch.setenv("OVERSEAS_COSTING_OA_SOURCE", "postgres")
    monkeypatch.setenv("OVERSEAS_COSTING_OA_EMERGENCY_API_ENABLED", "false")
    monkeypatch.setattr(import_oa_logistics, "_get_postgres_approval_source", lambda: BrokenSource())
    monkeypatch.setattr(
        import_oa_logistics,
        "get_access_token",
        lambda **_kwargs: pytest.fail("数据库故障时禁止自动消耗钉钉 API 额度"),
    )

    with pytest.raises(ConnectionError, match="database unavailable"):
        import_oa_logistics.pull_logistics_approvals(
            process_code="PROC-LOGISTICS",
            start="2026-09-01",
            end="2026-09-03",
        )


def test_single_instance_entrypoint_uses_postgres_source_without_token(monkeypatch) -> None:
    from overseas_costing.scripts import import_oa_logistics

    source = FakePostgresSource()
    monkeypatch.setenv("OVERSEAS_COSTING_OA_SOURCE", "postgres")
    monkeypatch.setattr(import_oa_logistics, "_get_postgres_approval_source", lambda: source)
    monkeypatch.setattr(
        import_oa_logistics,
        "_get_process_instance_detail_by_new_api",
        lambda **_kwargs: pytest.fail("单张重拉不应调用钉钉 API"),
    )

    assert import_oa_logistics.get_access_token() == ""
    detail = import_oa_logistics.get_process_instance_detail(token="", process_instance_id="PROC-PURCHASE-A")

    assert detail["processInstanceId"] == "PROC-PURCHASE-A"
    assert source.get_calls == [["PROC-PURCHASE-A"]]


def test_explicit_api_mode_requires_emergency_switch_when_it_is_configured(monkeypatch) -> None:
    from overseas_costing.scripts import import_oa_logistics

    monkeypatch.setenv("OVERSEAS_COSTING_OA_SOURCE", "api")
    monkeypatch.setenv("OVERSEAS_COSTING_OA_EMERGENCY_API_ENABLED", "false")

    with pytest.raises(PermissionError, match="应急开关"):
        import_oa_logistics.get_access_token(access_token="existing-token")
