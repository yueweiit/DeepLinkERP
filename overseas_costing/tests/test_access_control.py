"""海外成本 API 访问控制测试。"""

from __future__ import annotations

import pytest


def test_require_overseas_cost_access_allows_configured_role(monkeypatch) -> None:
    from overseas_costing.services import access_control

    calls = []

    class FakeFrappe:
        @staticmethod
        def only_for(roles):
            calls.append(tuple(roles))

    monkeypatch.setattr(access_control, "frappe", FakeFrappe())

    access_control.require_overseas_cost_access()

    assert calls == [("System Manager", "海外成本核算用户")]


def test_require_batch_permission_rejects_missing_doctype_permission(monkeypatch) -> None:
    from overseas_costing.services import access_control

    class FakeFrappe:
        class PermissionError(Exception):
            pass

        @staticmethod
        def only_for(_roles):
            return None

        @staticmethod
        def has_permission(*_args, **_kwargs):
            return False

        @staticmethod
        def throw(message, exc):
            raise exc(message)

    monkeypatch.setattr(access_control, "frappe", FakeFrappe())

    with pytest.raises(FakeFrappe.PermissionError, match="没有修改权限"):
        access_control.require_doctype_permission("Overseas Cost Batch", "write", doc="BATCH-1")


def test_validate_api_access_guards_all_cost_api_commands(monkeypatch) -> None:
    from overseas_costing.services import access_control

    calls = []

    class FakeFrappe:
        class Local:
            form_dict = {"cmd": "overseas_costing.api.import_api.delete_manual_document_attachment"}

        local = Local()

    monkeypatch.setattr(access_control, "frappe", FakeFrappe())
    monkeypatch.setattr(access_control, "require_overseas_cost_access", lambda: calls.append("checked"))

    access_control.validate_api_access()

    assert calls == ["checked"]


def test_require_batch_permission_resolves_reference_and_checks_document(monkeypatch) -> None:
    from overseas_costing.services import access_control, batch_service

    calls = []
    monkeypatch.setattr(batch_service, "_resolve_batch_name", lambda value: "BATCH-DOC" if value == "BATCH-NO" else None)
    monkeypatch.setattr(access_control, "require_overseas_cost_access", lambda: calls.append("role"))
    monkeypatch.setattr(
        access_control,
        "require_doctype_permission",
        lambda doctype, ptype, doc=None: calls.append((doctype, ptype, doc)),
    )

    assert access_control.require_batch_permission("BATCH-NO", "write") == "BATCH-DOC"
    assert calls == ["role", ("Overseas Cost Batch", "write", "BATCH-DOC")]
