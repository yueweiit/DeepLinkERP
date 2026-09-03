"""工作台使用记录 API 权限边界测试。"""

from __future__ import annotations

import importlib
import sys
from types import ModuleType


def test_record_usage_does_not_require_usage_log_create_permission(monkeypatch) -> None:
    """普通业务用户的遥测写入不应因日志 DocType 权限弹错。"""

    fake_frappe = ModuleType("frappe")
    fake_frappe.whitelist = lambda: (lambda function: function)
    monkeypatch.setitem(sys.modules, "frappe", fake_frappe)
    sys.modules.pop("overseas_costing.api.usage", None)
    usage_api = importlib.import_module("overseas_costing.api.usage")

    def reject_permission_check(*_args, **_kwargs):
        raise AssertionError("record_usage must not require create permission on the internal usage log")

    monkeypatch.setattr(usage_api, "require_doctype_permission", reject_permission_check)
    monkeypatch.setattr(
        usage_api.usage_service,
        "record_usage",
        lambda **kwargs: {"ok": True, "action_type": kwargs["action_type"]},
    )

    try:
        assert usage_api.record_usage("PAGE_VIEW") == {"ok": True, "action_type": "PAGE_VIEW"}
    finally:
        sys.modules.pop("overseas_costing.api.usage", None)
