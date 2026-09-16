"""中文用途：装箱来源、刷新、确认与运费试算 API 的权限和输入边界测试。"""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest


def _load_api(monkeypatch):
    fake_frappe = ModuleType("frappe")
    fake_frappe.whitelist = lambda: (lambda function: function)
    fake_frappe.session = type("Session", (), {"user": "cost@example.com"})()
    fake_frappe.PermissionError = PermissionError
    fake_frappe.throw = lambda message, exc=ValueError: (_ for _ in ()).throw(exc(message))
    monkeypatch.setitem(sys.modules, "frappe", fake_frappe)
    sys.modules.pop("overseas_costing.api.packing_api", None)
    return importlib.import_module("overseas_costing.api.packing_api")


def test_read_and_write_endpoints_use_batch_level_permission(monkeypatch) -> None:
    api = _load_api(monkeypatch)
    calls = []
    monkeypatch.setattr(
        api,
        "require_packing_workflow_permission",
        lambda batch, operation: calls.append((batch, operation)) or "BATCH-DOC",
    )
    monkeypatch.setattr(api.packing_snapshot_service, "list_packing_sources", lambda batch: {"batch": batch})
    monkeypatch.setattr(
        api.packing_snapshot_service,
        "get_current_packing_snapshot",
        lambda batch: {"batch": batch},
    )
    monkeypatch.setattr(
        api.freight_comparison_service,
        "list_freight_comparisons",
        lambda batch: [{"batch": batch}],
    )

    assert api.list_packing_sources("BATCH-NO") == {"batch": "BATCH-DOC"}
    assert api.get_current_packing_snapshot("BATCH-NO") == {"batch": "BATCH-DOC"}
    assert api.list_freight_comparisons("BATCH-NO") == [{"batch": "BATCH-DOC"}]
    assert calls == [
        ("BATCH-NO", "read"),
        ("BATCH-NO", "read"),
        ("BATCH-NO", "read"),
    ]


def test_permission_failure_happens_before_any_source_lookup(monkeypatch) -> None:
    api = _load_api(monkeypatch)
    monkeypatch.setattr(
        api,
        "require_packing_workflow_permission",
        lambda *_args: (_ for _ in ()).throw(PermissionError("denied")),
    )
    monkeypatch.setattr(
        api.packing_snapshot_service,
        "list_packing_sources",
        lambda *_args: (_ for _ in ()).throw(AssertionError("must not reveal sources")),
    )

    with pytest.raises(PermissionError, match="denied"):
        api.list_packing_sources("SECRET-BATCH")


def test_list_packing_sheet_catalog_requires_read_permission_and_uses_local_cache(monkeypatch) -> None:
    api = _load_api(monkeypatch)
    calls = []
    monkeypatch.setattr(
        api,
        "require_packing_workflow_permission",
        lambda batch, permission: calls.append((batch, permission)) or "BATCH-DOC",
    )
    monkeypatch.setattr(
        api.packing_snapshot_service,
        "list_cached_packing_sheet_catalog",
        lambda batch: {"batch": batch, "catalog_status": "ready"},
    )

    result = api.list_packing_sheet_catalog("BATCH-NO")

    assert result == {"batch": "BATCH-DOC", "catalog_status": "ready"}
    assert calls == [("BATCH-NO", "read")]


def test_list_packing_attachment_sources_excludes_remote_wiki_lookup(monkeypatch) -> None:
    api = _load_api(monkeypatch)
    calls = []
    monkeypatch.setattr(
        api,
        "require_packing_workflow_permission",
        lambda batch, permission: calls.append((batch, permission)) or "BATCH-DOC",
    )
    source_calls = []
    monkeypatch.setattr(
        api.packing_snapshot_service,
        "list_packing_sources",
        lambda batch, **kwargs: source_calls.append((batch, kwargs)) or {"manual_attachments": []},
    )

    result = api.list_packing_attachment_sources("BATCH-NO")

    assert result == {"manual_attachments": []}
    assert calls == [("BATCH-NO", "read")]
    assert source_calls == [("BATCH-DOC", {"include_wiki": False})]


def test_refresh_uses_write_permission_and_only_server_runtime_submitter(monkeypatch) -> None:
    api = _load_api(monkeypatch)
    permissions = []
    monkeypatch.setattr(
        api,
        "require_packing_workflow_permission",
        lambda batch, operation: permissions.append((batch, operation)) or "BATCH-DOC",
    )

    class Submitter:
        def request_sheet_refresh(self, workbook_id, sheet_id, request_key, requested_by):
            assert (workbook_id, sheet_id, request_key, requested_by) == (
                "WB-2026",
                "st-1",
                "a" * 64,
                "cost@example.com",
            )
            return 88

    clients = type("Clients", (), {"submitter": Submitter()})()
    monkeypatch.setattr(api, "get_packing_runtime_clients", lambda: clients)
    remembered = []
    monkeypatch.setattr(
        api.packing_sheet_cache_service,
        "register_manual_refresh",
        lambda **kwargs: remembered.append(kwargs),
    )

    result = api.request_packing_sheet_refresh(
        "BATCH-NO", "WB-2026", "st-1", "a" * 64
    )

    assert permissions == [("BATCH-NO", "refresh")]
    assert result == {"ok": True, "request_id": 88, "request_key": "a" * 64}
    assert remembered == [{
        "batch_name": "BATCH-DOC",
        "workbook_id": "WB-2026",
        "sheet_id": "st-1",
        "request_key": "a" * 64,
    }]


def test_successful_remote_refresh_is_not_reported_until_local_cache_is_materialized(monkeypatch) -> None:
    api = _load_api(monkeypatch)
    monkeypatch.setattr(api, "require_packing_workflow_permission", lambda *_args: "BATCH-DOC")
    monkeypatch.setattr(api.effective_source, "current_source_bundle", lambda *_args: None)

    class Catalog:
        @staticmethod
        def get_refresh_status(_request_key):
            return {"status": "success"}

    monkeypatch.setattr(
        api,
        "get_packing_runtime_clients",
        lambda: type("Clients", (), {"catalog": Catalog()})(),
    )
    completed = []
    monkeypatch.setattr(
        api.packing_sheet_cache_service,
        "complete_manual_refresh",
        lambda request_key: completed.append(request_key) or {"ok": True},
    )

    result = api.get_packing_refresh_status("BATCH-NO", "a" * 64)

    assert result["status"] == "success"
    assert completed == ["a" * 64]


def test_remote_success_without_registered_local_materialization_is_reported_failed(monkeypatch) -> None:
    api = _load_api(monkeypatch)
    monkeypatch.setattr(api, "require_packing_workflow_permission", lambda *_args: "BATCH-DOC")
    monkeypatch.setattr(api.effective_source, "current_source_bundle", lambda *_args: None)

    class Catalog:
        @staticmethod
        def get_refresh_status(_request_key):
            return {"status": "success"}

    monkeypatch.setattr(
        api,
        "get_packing_runtime_clients",
        lambda: type("Clients", (), {"catalog": Catalog()})(),
    )
    monkeypatch.setattr(
        api.packing_sheet_cache_service,
        "complete_manual_refresh",
        lambda _request_key: None,
    )

    result = api.get_packing_refresh_status("BATCH-NO", "a" * 64)

    assert result["status"] == "failed"
    assert "本地物化" in result["error_message"]


def test_remote_success_waits_when_another_cache_materialization_is_running(monkeypatch) -> None:
    api = _load_api(monkeypatch)
    monkeypatch.setattr(api, "require_packing_workflow_permission", lambda *_args: "BATCH-DOC")
    monkeypatch.setattr(api.effective_source, "current_source_bundle", lambda *_args: None)

    class Catalog:
        @staticmethod
        def get_refresh_status(_request_key):
            return {"status": "success"}

    monkeypatch.setattr(
        api,
        "get_packing_runtime_clients",
        lambda: type("Clients", (), {"catalog": Catalog()})(),
    )
    monkeypatch.setattr(
        api.packing_sheet_cache_service,
        "complete_manual_refresh",
        lambda _request_key: {"ok": False, "pending": True},
    )

    result = api.get_packing_refresh_status("BATCH-NO", "a" * 64)

    assert result["status"] == "running"


def test_confirm_and_save_validate_json_size_and_request_id(monkeypatch) -> None:
    api = _load_api(monkeypatch)
    monkeypatch.setattr(api, "require_packing_workflow_permission", lambda *_args: "BATCH-DOC")

    with pytest.raises(ValueError, match="过大"):
        api.confirm_packing_snapshot("BATCH", "token", "x" * 60000)
    with pytest.raises(ValueError, match="64 位"):
        api.save_freight_comparison("BATCH", "snapshot", "not-a-hash", "{}")
    with pytest.raises(ValueError, match="过大"):
        api.preview_freight_comparison("BATCH", "snapshot", "x" * 30000)


def test_bound_refresh_only_uses_explicit_sheets_and_polling_is_local(monkeypatch):
    import sqlite3
    from overseas_costing.services import effective_logistics_source,packing_source_service
    from overseas_costing.services.logistics_settlement.store import Store
    api=_load_api(monkeypatch)
    store=Store.sqlite(sqlite3.connect(':memory:'));store.install()
    context={'root_kind':'expense','available':True,'fingerprint':'current'}
    bundle={'context':context,'source':{'raw':{'workbookId':'WB','sheetId':'S'}}}
    monkeypatch.setattr(api,'require_packing_workflow_permission',lambda *a:'B')
    monkeypatch.setattr(effective_logistics_source,'current_source_bundle',lambda *a:bundle)
    monkeypatch.setattr(Store,'frappe',classmethod(lambda cls:store))
    calls=[]
    monkeypatch.setattr(packing_source_service,'refresh_bound_wiki_snapshot',lambda batch,source:calls.append((batch,source)))
    monkeypatch.setattr(api,'get_packing_runtime_clients',lambda:pytest.fail('ordinary poll must not query upstream'))
    result=api.request_packing_workbook_refresh('B','WB','a'*64)
    assert result['ok'] and calls==[('B','WB:S')]
    assert api.get_packing_refresh_status('B','a'*64)['status']=='success'
    api.request_packing_sheet_refresh('B','WB','S','a'*64)
    assert calls==[('B','WB:S')]
    with pytest.raises(ValueError,match='未被当前'):
        api.request_packing_sheet_refresh('B','WB','FOREIGN','b'*64)
    context['fingerprint']='new'
    assert api.get_packing_refresh_status('B','a'*64)['status']=='failed'


def test_api_source_contains_all_minimal_endpoints_and_no_credential_response() -> None:
    source = (
        Path(__file__).resolve().parents[1] / "api" / "packing_api.py"
    ).read_text(encoding="utf-8")
    endpoints = (
        "list_packing_sources",
        "list_packing_sheet_catalog",
        "list_packing_attachment_sources",
        "request_packing_workbook_refresh",
        "request_packing_sheet_refresh",
        "get_packing_refresh_status",
        "preview_packing_source_v2",
        "confirm_packing_snapshot",
        "get_current_packing_snapshot",
        "preview_freight_comparison",
        "save_freight_comparison",
        "list_freight_comparisons",
    )
    for endpoint in endpoints:
        assert f"def {endpoint}(" in source
    for forbidden in ("db_password", "secret_key", "access_key", "presigned_url", "raw_payload"):
        assert forbidden not in source
