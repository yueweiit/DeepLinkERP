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

    result = api.request_packing_sheet_refresh(
        "BATCH-NO", "WB-2026", "st-1", "a" * 64
    )

    assert permissions == [("BATCH-NO", "refresh")]
    assert result == {"ok": True, "request_id": 88, "request_key": "a" * 64}


def test_confirm_and_save_validate_json_size_and_request_id(monkeypatch) -> None:
    api = _load_api(monkeypatch)
    monkeypatch.setattr(api, "require_packing_workflow_permission", lambda *_args: "BATCH-DOC")

    with pytest.raises(ValueError, match="过大"):
        api.confirm_packing_snapshot("BATCH", "token", "x" * 60000)
    with pytest.raises(ValueError, match="64 位"):
        api.save_freight_comparison("BATCH", "snapshot", "not-a-hash", "{}")
    with pytest.raises(ValueError, match="过大"):
        api.preview_freight_comparison("BATCH", "snapshot", "x" * 30000)


def test_api_source_contains_all_minimal_endpoints_and_no_credential_response() -> None:
    source = (
        Path(__file__).resolve().parents[1] / "api" / "packing_api.py"
    ).read_text(encoding="utf-8")
    endpoints = (
        "list_packing_sources",
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
