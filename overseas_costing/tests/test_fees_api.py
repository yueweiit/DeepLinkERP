"""费用与凭证 API 的权限、输入上限和薄层契约测试。"""

import importlib
import sys
from types import ModuleType

import pytest


def _load_api(monkeypatch):
    fake_frappe = ModuleType("frappe")
    fake_frappe.whitelist = lambda: (lambda function: function)
    monkeypatch.setitem(sys.modules, "frappe", fake_frappe)
    sys.modules.pop("overseas_costing.api.fees", None)
    return importlib.import_module("overseas_costing.api.fees")


def test_worklist_requires_batch_read_permission(monkeypatch) -> None:
    api = _load_api(monkeypatch)
    calls = []
    monkeypatch.setattr(
        api,
        "require_batch_permission",
        lambda batch, ptype: calls.append((batch, ptype)) or "BATCH-DOC",
    )
    monkeypatch.setattr(api.fee_service, "get_fee_worklist", lambda batch, version: {"batch": batch})

    assert api.get_fee_worklist("BATCH-NO") == {"batch": "BATCH-DOC"}
    assert calls == [("BATCH-NO", "read")]


def test_save_fee_requires_write_permission_and_bounded_json(monkeypatch) -> None:
    api = _load_api(monkeypatch)
    calls = []
    monkeypatch.setattr(
        api,
        "require_batch_permission",
        lambda batch, ptype: calls.append((batch, ptype)) or "BATCH-DOC",
    )
    captured = {}
    monkeypatch.setattr(
        api.fee_service,
        "save_fee",
        lambda **kwargs: captured.update(kwargs) or {"ok": True},
    )

    result = api.save_fee(
        "BATCH-NO",
        "VER-1",
        '{"logical_fee_key":"import_tax"}',
        "EDIT",
        "MOD",
    )

    assert result["ok"] is True
    assert calls == [("BATCH-NO", "write")]
    assert captured["batch_name"] == "BATCH-DOC"
    assert captured["fee_payload"] == {"logical_fee_key": "import_tax"}
    with pytest.raises(ValueError, match="过大"):
        api.save_fee("BATCH", "VER", "x" * 200_000, "EDIT", "MOD")


def test_link_and_validate_evidence_require_batch_write_permission(monkeypatch) -> None:
    api = _load_api(monkeypatch)
    calls = []
    monkeypatch.setattr(
        api,
        "require_batch_permission",
        lambda batch, ptype: calls.append((batch, ptype)) or "BATCH-DOC",
    )
    monkeypatch.setattr(api.fee_service, "link_fee_evidence", lambda **kwargs: kwargs)
    monkeypatch.setattr(api.fee_service, "set_fee_evidence_status", lambda **kwargs: kwargs)

    linked = api.link_fee_evidence("BATCH", "RULE", "ATT", "invoice", "EDIT", "MOD")
    validated = api.set_fee_evidence_status("BATCH", "EVID", "VALID", "ok", "EDIT", "MOD")

    assert calls == [("BATCH", "write"), ("BATCH", "write")]
    assert linked["batch_name"] == "BATCH-DOC"
    assert validated["batch_name"] == "BATCH-DOC"
