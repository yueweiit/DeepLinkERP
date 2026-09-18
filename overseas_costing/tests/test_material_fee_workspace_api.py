from __future__ import annotations

import importlib
import sys
from types import ModuleType

import pytest


def _load_api(monkeypatch):
    fake_frappe = ModuleType("frappe")
    fake_frappe.whitelist = lambda *args, **kwargs: (lambda function: function)
    fake_frappe.PermissionError = PermissionError
    monkeypatch.setitem(sys.modules, "frappe", fake_frappe)
    sys.modules.pop("overseas_costing.api.material_fee_workspace", None)
    return importlib.import_module("overseas_costing.api.material_fee_workspace")


def test_snapshot_endpoints_check_batch_read_permission_before_cache_access(monkeypatch) -> None:
    api = _load_api(monkeypatch)
    permission_calls = []
    service_calls = []
    monkeypatch.setattr(
        api,
        "require_batch_permission",
        lambda batch, permission: permission_calls.append((batch, permission)) or "BATCH-DOC",
    )
    monkeypatch.setattr(
        api.snapshot_service,
        "get_snapshot",
        lambda *args, **kwargs: service_calls.append(("get", args, kwargs)) or {"ok": True},
    )
    monkeypatch.setattr(
        api.snapshot_service,
        "check_freshness",
        lambda *args, **kwargs: service_calls.append(("check", args, kwargs)) or {"ok": True},
    )
    monkeypatch.setattr(
        api.snapshot_service,
        "refresh_snapshot",
        lambda *args, **kwargs: service_calls.append(("refresh", args, kwargs)) or {"ok": True},
    )

    api.get_snapshot("BATCH-NO", "V1", page="2", page_length="50")
    api.check_freshness("BATCH-NO", "V1", "HASH")
    api.refresh_snapshot("BATCH-NO", "V1", page="2", page_length="50")

    assert permission_calls == [
        ("BATCH-NO", "read"),
        ("BATCH-NO", "read"),
        ("BATCH-NO", "read"),
    ]
    assert service_calls[0] == (
        "get",
        ("BATCH-DOC", "V1"),
        {"page": 2, "page_length": 50},
    )
    assert service_calls[1] == (
        "check",
        ("BATCH-DOC", "V1"),
        {"snapshot_fingerprint": "HASH", "page": 1, "page_length": 200},
    )
    assert service_calls[2] == (
        "refresh",
        ("BATCH-DOC", "V1"),
        {"page": 2, "page_length": 50},
    )


def test_permission_failure_prevents_snapshot_lookup(monkeypatch) -> None:
    api = _load_api(monkeypatch)
    monkeypatch.setattr(
        api,
        "require_batch_permission",
        lambda *_: (_ for _ in ()).throw(PermissionError("denied")),
    )
    monkeypatch.setattr(
        api.snapshot_service,
        "get_snapshot",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("must not read cache")),
    )

    with pytest.raises(PermissionError, match="denied"):
        api.get_snapshot("SECRET", "V1")
