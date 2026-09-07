"""只读试算 API 权限契约测试。"""

import importlib
import sys
from types import ModuleType


def test_preview_uses_batch_read_permission_and_read_only_service(monkeypatch) -> None:
    fake_frappe = ModuleType("frappe")
    fake_frappe.whitelist = lambda: (lambda function: function)
    monkeypatch.setitem(sys.modules, "frappe", fake_frappe)
    sys.modules.pop("overseas_costing.api.calculate", None)
    api = importlib.import_module("overseas_costing.api.calculate")
    calls = []
    monkeypatch.setattr(
        api,
        "require_batch_permission",
        lambda batch, ptype: calls.append((batch, ptype)) or "BATCH-DOC",
    )
    monkeypatch.setattr(
        api.cost_preview_service,
        "preview_comprehensive_cost",
        lambda batch, version: {"batch": batch, "version": version, "read_only": True},
    )

    result = api.preview_comprehensive_cost("BATCH-NO", "VER-1")

    assert result == {"batch": "BATCH-DOC", "version": "VER-1", "read_only": True}
    assert calls == [("BATCH-NO", "read")]
