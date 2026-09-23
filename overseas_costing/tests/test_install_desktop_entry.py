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
    from overseas_costing.services import company_route_provision_service
    monkeypatch.setattr(
        company_route_provision_service,
        "ensure_default_route_hints",
        lambda: calls.append("route_hints"),
    )
    install.after_migrate()

    assert "route_hints" in calls
    assert calls[-3:] == [
        "ensure_workspace_sidebar",
        "ensure_desktop_icon",
        "clear_permission_cache",
    ]


def test_before_migrate_normalizes_legacy_route_revision_values(monkeypatch) -> None:
    queries: list[str] = []

    class FakeDB:
        def sql(self, query: str):
            queries.append(query)
            lowered = query.lower()
            if "show tables" in lowered:
                return [("tabOverseas Cost Item",)]
            if "@@sql_safe_updates" in lowered:
                return [(1,)]
            return [("route_revision",)]

        def commit(self) -> None:
            queries.append("commit")

    monkeypatch.setitem(sys.modules, "frappe", SimpleNamespace(db=FakeDB()))

    install.before_migrate()

    assert len(queries) == 8
    assert "show tables" in queries[0].lower()
    assert "show columns" in queries[1].lower()
    assert "alter table `taboverseas cost item`" in queries[2].lower()
    assert "alter column `route_revision` set default 0" in queries[2].lower()
    assert "@@sql_safe_updates" in queries[3].lower()
    assert queries[4].lower() == "set sql_safe_updates = 0"
    assert "update `taboverseas cost item`" in queries[5].lower()
    assert "route_revision is null" in queries[5].lower()
    assert "not regexp '^[0-9]+$'" in queries[5].lower()
    assert queries[6].lower() == "set sql_safe_updates = 1"
    assert queries[7] == "commit"
