"""物料表格 API 的权限、大小和薄层契约测试。"""

import importlib
import sys
from types import ModuleType

import pytest


def _load_api(monkeypatch):
    fake_frappe = ModuleType("frappe")
    fake_frappe.whitelist = lambda: (lambda function: function)
    monkeypatch.setitem(sys.modules, "frappe", fake_frappe)
    sys.modules.pop("overseas_costing.api.materials", None)
    return importlib.import_module("overseas_costing.api.materials")


def test_grid_checks_read_permission_before_query(monkeypatch) -> None:
    api = _load_api(monkeypatch)
    calls = []
    monkeypatch.setattr(
        api,
        "require_batch_permission",
        lambda batch, ptype: calls.append((batch, ptype)) or "BATCH-DOC",
    )
    monkeypatch.setattr(
        api.material_input_service,
        "get_material_grid",
        lambda **kwargs: {"batch": kwargs["batch_name"]},
    )

    assert api.get_material_grid("BATCH-NO") == {"batch": "BATCH-DOC"}
    assert calls == [("BATCH-NO", "read")]


def test_preview_checks_permission_and_rejects_paths_or_urls(monkeypatch) -> None:
    api = _load_api(monkeypatch)
    monkeypatch.setattr(api, "require_batch_permission", lambda _batch, _ptype: "BATCH-DOC")
    monkeypatch.setattr(
        api.material_import_service,
        "preview_material_import",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("must not inspect path")),
    )

    with pytest.raises(ValueError, match="受控 ID"):
        api.preview_material_import("BATCH", "manual_xlsx", "/tmp/packing.xlsx", "Sheet1")
    with pytest.raises(ValueError, match="受控 ID"):
        api.preview_material_import("BATCH", "manual_xlsx", "https://example.test/a.xlsx", "Sheet1")


def test_apply_limits_choices_payload_and_requires_write_permission(monkeypatch) -> None:
    api = _load_api(monkeypatch)
    calls = []
    monkeypatch.setattr(
        api,
        "require_batch_permission",
        lambda batch, ptype: calls.append((batch, ptype)) or "BATCH-DOC",
    )

    with pytest.raises(ValueError, match="过大"):
        api.apply_material_import("BATCH", "token", "x" * 200_000, "EDIT", "MOD")

    assert calls == [("BATCH", "write")]


def test_set_shipping_quantity_uses_write_permission_and_whitelisted_mode(monkeypatch) -> None:
    api = _load_api(monkeypatch)
    monkeypatch.setattr(api, "require_batch_permission", lambda _batch, _ptype: "BATCH-DOC")
    captured = {}
    monkeypatch.setattr(
        api.material_input_service,
        "set_shipping_quantity",
        lambda **kwargs: captured.update(kwargs) or {"ok": True},
    )

    result = api.set_shipping_quantity(
        "BATCH",
        "ITEM-1",
        "MANUAL_CONFIRMED",
        "32",
        "桶",
        "EDIT",
        "MOD",
    )

    assert result["ok"] is True
    assert captured["batch_name"] == "BATCH-DOC"
    assert captured["mode"] == "MANUAL_CONFIRMED"
    with pytest.raises(ValueError, match="来源状态"):
        api.set_shipping_quantity("BATCH", "ITEM-1", "CLIENT_FAKE", "32", "桶", "EDIT", "MOD")


def test_merge_review_preview_preserves_read_permission_and_payload_limit(monkeypatch):
    api = _load_api(monkeypatch)
    checks = []
    captured = {}
    monkeypatch.setattr(api, "require_batch_permission", lambda batch, ptype: checks.append(ptype) or batch)
    monkeypatch.setattr(api.material_import_service, "preview_material_import",
                        lambda *_args, **kwargs: captured.update(kwargs) or {"ok": True})
    payload = {"source_hash": "a" * 64, "ranges": []}
    assert api.preview_material_import("B1", "wiki_sheet", "WB:ST", merge_reviews_json=payload)["ok"]
    assert captured["merge_reviews_json"] == payload
    assert checks == ["read"]
    with pytest.raises(ValueError, match="过大"):
        api.preview_material_import("B1", "wiki_sheet", "WB:ST", merge_reviews_json="x" * 100_001)


def test_ai_fill_api_uses_read_for_status_and_write_for_mutations(monkeypatch) -> None:
    api = _load_api(monkeypatch)
    checks = []
    monkeypatch.setattr(
        api,
        "require_batch_permission",
        lambda batch, ptype: checks.append((batch, ptype)) or "BATCH-DOC",
    )
    monkeypatch.setattr(
        api.material_ai_fill_service,
        "start_material_ai_fill",
        lambda *args: {"ok": True, "args": args},
    )
    monkeypatch.setattr(
        api.material_ai_fill_service,
        "get_material_ai_fill_status",
        lambda *args: {"ok": True, "args": args},
    )
    monkeypatch.setattr(
        api.material_ai_fill_service,
        "apply_material_ai_fill",
        lambda *args: {"ok": True, "args": args},
    )
    monkeypatch.setattr(
        api.material_ai_fill_service,
        "discard_material_ai_fill",
        lambda *args: {"ok": True, "args": args},
    )

    api.start_material_ai_fill("B", "V", "T", "M")
    api.get_material_ai_fill_status("B", "R")
    api.apply_material_ai_fill("B", "R", '[{"item_name":"I"}]', "T", "M")
    api.discard_material_ai_fill("B", "R")
    assert checks == [
        ("B", "write"),
        ("B", "read"),
        ("B", "write"),
        ("B", "write"),
    ]


def test_ai_apply_rejects_oversized_or_non_array_updates_before_service(monkeypatch) -> None:
    api = _load_api(monkeypatch)
    monkeypatch.setattr(api, "require_batch_permission", lambda batch, _ptype: batch)
    with pytest.raises(ValueError, match="过大"):
        api.apply_material_ai_fill("B", "R", "x" * 1_100_000, "T", "M")
    with pytest.raises(ValueError, match="数组"):
        api.apply_material_ai_fill("B", "R", '{"item_name":"I"}', "T", "M")


def test_unified_source_review_api_uses_write_role_and_requires_edit_token_only_when_applying(monkeypatch) -> None:
    api = _load_api(monkeypatch)
    checks = []
    calls = []
    monkeypatch.setattr(api, "require_batch_permission", lambda batch, ptype: checks.append(ptype) or batch)
    monkeypatch.setattr(api.material_ai_fill_service, "start_source_ai_review", lambda *args, **kwargs: calls.append(("start", args, kwargs)) or {"ok": True})
    monkeypatch.setattr(api.material_ai_fill_service, "get_source_ai_review_status", lambda *args: calls.append(("get", args)) or {"ok": True})
    monkeypatch.setattr(api.material_ai_fill_service, "apply_source_ai_review", lambda *args: calls.append(("apply", args)) or {"ok": True})
    monkeypatch.setattr(api.material_ai_fill_service, "discard_source_ai_review", lambda *args: calls.append(("discard", args)) or {"ok": True})

    api.start_source_ai_review("B", "V", "两款是一套", 1)
    api.get_source_ai_review_status("B", "R")
    api.apply_source_ai_review("B", "R", '["P1"]', '{"P1":{}}', "TOKEN", "M1")
    api.discard_source_ai_review("B", "R")

    assert checks == ["write", "read", "write", "write"]
    assert calls[0][1] == ("B", "V", "两款是一套")
    assert calls[0][2] == {"force": True}
    assert calls[2][1][2:4] == (["P1"], {"P1": {}})
