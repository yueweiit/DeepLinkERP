from __future__ import annotations

import importlib
import sys
from types import ModuleType, SimpleNamespace


def _load_api(monkeypatch):
    fake_frappe = ModuleType("frappe")
    fake_frappe.whitelist = lambda *args, **kwargs: (lambda function: function)
    fake_frappe.session = SimpleNamespace(user="operator@example.com")
    monkeypatch.setitem(sys.modules, "frappe", fake_frappe)
    sys.modules.pop("overseas_costing.api.review", None)
    return importlib.import_module("overseas_costing.api.review")


def test_review_api_enforces_read_and_write_permissions_and_delegates(monkeypatch) -> None:
    api = _load_api(monkeypatch)
    permissions = []
    calls = []
    monkeypatch.setattr(api, "require_batch_permission", lambda batch, ptype: permissions.append((batch, ptype)) or "B-1")
    monkeypatch.setattr(api.service, "get_review_communication", lambda batch: calls.append(("get", batch)) or {"ok": True})
    monkeypatch.setattr(api.service, "return_for_remediation", lambda *args: calls.append(("return", args)) or {"ok": True})
    monkeypatch.setattr(api.service, "address_review_issue", lambda *args: calls.append(("address", args)) or {"ok": True})
    monkeypatch.setattr(api.service, "resubmit_review_round", lambda *args: calls.append(("resubmit", args)) or {"ok": True})
    monkeypatch.setattr(api.service, "resolve_review_issue", lambda *args: calls.append(("resolve", args)) or {"ok": True})

    api.get_review_communication("OTHER")
    api.return_for_remediation("OTHER", "V-1", "HASH", '[{"description":"问题"}]')
    api.address_review_issue("OTHER", "I-1", "回复", "M-1")
    api.resubmit_review_round("OTHER", "R-1", "M-2")
    api.resolve_review_issue("OTHER", "I-1", "M-3")

    assert permissions == [
        ("OTHER", "read"),
        ("OTHER", "write"),
        ("OTHER", "write"),
        ("OTHER", "write"),
        ("OTHER", "write"),
    ]
    assert [name for name, _payload in calls] == ["get", "return", "address", "resubmit", "resolve"]
    assert calls[1][1][-1] == [{"description": "问题"}]
