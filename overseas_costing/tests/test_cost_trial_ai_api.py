"""AI 试算 API 权限与参数契约。"""

import importlib
import sys
from types import ModuleType


def _load_api(monkeypatch):
    fake_frappe = ModuleType("frappe")
    fake_frappe.whitelist = lambda: (lambda function: function)
    monkeypatch.setitem(sys.modules, "frappe", fake_frappe)
    sys.modules.pop("overseas_costing.api.calculate", None)
    return importlib.import_module("overseas_costing.api.calculate")


def test_start_status_preview_confirm_and_discard_delegate_with_permissions(monkeypatch):
    api = _load_api(monkeypatch)
    permissions = []
    calls = []
    monkeypatch.setattr(api, "require_batch_permission", lambda batch, ptype: permissions.append((batch, ptype)) or "B1")
    service = api.cost_trial_ai_service
    monkeypatch.setattr(service, "start_cost_trial_ai_review", lambda **kwargs: calls.append(("start", kwargs)) or {"ok": True})
    monkeypatch.setattr(service, "get_cost_trial_ai_review_status", lambda **kwargs: calls.append(("status", kwargs)) or {"ok": True})
    monkeypatch.setattr(service, "preview_cost_trial", lambda **kwargs: calls.append(("preview", kwargs)) or {"ok": True})
    monkeypatch.setattr(service, "confirm_cost_trial", lambda **kwargs: calls.append(("confirm", kwargs)) or {"ok": True})
    monkeypatch.setattr(service, "discard_cost_trial_ai_review", lambda **kwargs: calls.append(("discard", kwargs)) or {"ok": True})

    api.start_cost_trial_ai_review("NO", "V1", "T", "M", "1", "1")
    api.get_cost_trial_ai_review_status("NO", "RUN", "2")
    api.preview_cost_trial("NO", "RUN", '[{"suggestion_id":"S","basis":"goods_value"}]')
    api.confirm_cost_trial("NO", "RUN", "TOKEN", '[{"suggestion_id":"S","basis":"goods_value"}]', "T", "M")
    api.discard_cost_trial_ai_review("NO", "RUN")

    assert permissions == [("NO", "write"), ("NO", "read"), ("NO", "read"), ("NO", "write"), ("NO", "write")]
    assert [name for name, _kwargs in calls] == ["start", "status", "preview", "confirm", "discard"]
    assert calls[0][1]["force"] is True
    assert calls[0][1]["reuse_only"] is True
    assert calls[3][1]["preview_token"] == "TOKEN"
