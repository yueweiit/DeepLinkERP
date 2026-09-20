"""DeepLinkERP 首页入口的迁移回归测试。"""

from __future__ import annotations

import sys
from types import SimpleNamespace

from overseas_costing import install
from overseas_costing.services.erp_capability_service import build_erpnext_standard_field_spec


def test_erpnext_standard_field_spec_has_unique_fields_per_doctype() -> None:
    for fields in build_erpnext_standard_field_spec().values():
        names = [field["fieldname"] for field in fields]
        assert len(names) == len(set(names))


def test_after_migrate_restores_deeplink_desktop_entry(monkeypatch) -> None:
    calls: list[str] = []

    for function_name in (
        "ensure_language_defaults",
        "ensure_access_role",
        "ensure_erpnext_standard_fields",
        "ensure_workspace",
        "ensure_workspace_sidebar",
        "ensure_desktop_icon",
        "clear_permission_cache",
    ):
        monkeypatch.setattr(
            install,
            function_name,
            lambda name=function_name: calls.append(name),
            raising=False,
        )

    from overseas_costing.services.logistics_settlement import policy_migration
    monkeypatch.setattr(policy_migration,"register_after_migrate",lambda:calls.append("policy_upgrade"))
    install.after_migrate()

    assert calls[-3:] == [
        "ensure_workspace_sidebar",
        "ensure_desktop_icon",
        "clear_permission_cache",
    ]


def test_before_migrate_normalizes_legacy_route_revision_values(monkeypatch) -> None:
    queries: list[str] = []

    class FakeDB:
        def table_exists(self, doctype: str) -> bool:
            assert doctype == "Overseas Cost Item"
            return True

        def sql(self, query: str):
            queries.append(query)
            return [("route_revision",)]

    monkeypatch.setitem(sys.modules, "frappe", SimpleNamespace(db=FakeDB()))

    install.before_migrate()

    assert len(queries) == 2
    assert "show columns" in queries[0].lower()
    assert "update `taboverseas cost item`" in queries[1].lower()
    assert "not regexp '^[0-9]+$'" in queries[1].lower()
