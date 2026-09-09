"""DeepLinkERP 首页入口的迁移回归测试。"""

from __future__ import annotations

from overseas_costing import install


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
