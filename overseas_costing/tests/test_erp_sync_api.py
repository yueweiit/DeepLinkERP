"""Multi-site ERP API permission and server-authority tests."""

import importlib
import json
import sys
from inspect import signature
from types import ModuleType

import pytest


def _load_api(monkeypatch):
    fake_frappe = ModuleType("frappe")
    fake_frappe.whitelist = lambda: (lambda function: function)
    monkeypatch.setitem(sys.modules, "frappe", fake_frappe)
    sys.modules.pop("overseas_costing.api.erp_sync", None)
    return importlib.import_module("overseas_costing.api.erp_sync")


def test_preview_and_send_use_read_and_write_permissions(monkeypatch) -> None:
    api = _load_api(monkeypatch)
    permissions = []
    monkeypatch.setattr(
        api,
        "require_erp_sync_permission",
        lambda batch, operation: permissions.append((batch, operation)) or "BATCH-DOC",
    )
    monkeypatch.setattr(api.erp_sync_service, "preview_erp_sync", lambda batch, version: {"batch": batch})
    monkeypatch.setattr(
        api.erp_sync_service,
        "start_erp_create",
        lambda **kwargs: {"batch": kwargs["batch_name"], "hash": kwargs["cost_result_hash"]},
    )

    assert api.preview_erp_sync("BATCH-NO", "V1") == {"batch": "BATCH-DOC"}
    assert api.start_erp_create("BATCH-NO", "H1", "CLICK-1")["batch"] == "BATCH-DOC"
    assert permissions == [("BATCH-NO", "read"), ("BATCH-NO", "write")]


def test_send_api_never_accepts_client_built_payload_or_site_credentials(monkeypatch) -> None:
    api = _load_api(monkeypatch)

    parameters = set(signature(api.start_erp_create).parameters)

    assert parameters == {"batch_name", "cost_result_hash", "request_key"}
    assert not parameters.intersection({"payload", "base_url", "authorization", "site_config"})


def test_update_site_selection_is_bounded_json(monkeypatch) -> None:
    api = _load_api(monkeypatch)
    monkeypatch.setattr(api, "require_erp_sync_permission", lambda *_args: "BATCH-DOC")
    captured = {}
    monkeypatch.setattr(
        api.erp_sync_service,
        "start_erp_updates",
        lambda **kwargs: captured.update(kwargs) or {"ok": True},
    )

    api.start_erp_updates("BATCH", "H2", json.dumps(["PROD", "ECOM"]), "UPDATE-1")

    assert captured["accepted_site_codes"] == ["PROD", "ECOM"]
    with pytest.raises(ValueError, match="JSON 数组"):
        api.start_erp_updates("BATCH", "H2", '{"site":"PROD"}', "UPDATE-1")
    with pytest.raises(ValueError, match="过大"):
        api.start_erp_updates("BATCH", "H2", "x" * 100_000, "UPDATE-1")


def test_route_apply_and_retry_are_write_operations(monkeypatch) -> None:
    api = _load_api(monkeypatch)
    calls = []
    monkeypatch.setattr(
        api,
        "require_erp_sync_permission",
        lambda batch, operation: calls.append((batch, operation)) or "BATCH-DOC",
    )
    monkeypatch.setattr(api.erp_sync_service, "apply_bulk_route", lambda **kwargs: {"ok": True})
    monkeypatch.setattr(api.erp_sync_service, "retry_erp_request", lambda **kwargs: {"ok": True})

    api.apply_bulk_route("BATCH", "REV", "EDIT", "MOD")
    api.retry_erp_request("BATCH", "REQ-1")

    assert calls == [("BATCH", "write"), ("BATCH", "retry")]
