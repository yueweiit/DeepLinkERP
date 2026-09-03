"""批次编辑租约服务测试。"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from overseas_costing.services.edit_session_service import assert_batch_write, assert_editable, lock_is_active


def test_lock_is_active_only_before_expiry() -> None:
    now = datetime(2026, 9, 2, 10, 0, 0)
    assert lock_is_active({"edit_lock_expires_at": now + timedelta(minutes=1)}, now=now) is True
    assert lock_is_active({"edit_lock_expires_at": now - timedelta(seconds=1)}, now=now) is False


def test_assert_editable_rejects_other_users_token() -> None:
    with pytest.raises(PermissionError, match="正在被财务甲编辑"):
        assert_editable(
            {
                "edit_lock_owner": "财务甲",
                "edit_lock_token": "token-a",
                "edit_lock_expires_at": datetime(2026, 9, 2, 10, 5),
            },
            user="管理员乙",
            token="token-b",
            expected_modified=None,
            now=datetime(2026, 9, 2, 10, 0),
        )


def test_assert_editable_rejects_expired_token() -> None:
    with pytest.raises(PermissionError, match="已过期"):
        assert_editable(
            {
                "edit_lock_owner": "管理员乙",
                "edit_lock_token": "token-b",
                "edit_lock_expires_at": datetime(2026, 9, 2, 9, 59),
            },
            user="管理员乙",
            token="token-b",
            expected_modified=None,
            now=datetime(2026, 9, 2, 10, 0),
        )


def test_assert_editable_rejects_stale_modified_value() -> None:
    with pytest.raises(RuntimeError, match="已被更新"):
        assert_editable(
            {
                "edit_lock_owner": "管理员乙",
                "edit_lock_token": "token-b",
                "edit_lock_expires_at": datetime(2026, 9, 2, 10, 5),
                "modified": datetime(2026, 9, 2, 10, 1),
            },
            user="管理员乙",
            token="token-b",
            expected_modified="2026-09-02 10:00:00",
            now=datetime(2026, 9, 2, 10, 0),
        )


def test_assert_batch_write_requires_expected_modified(monkeypatch) -> None:
    from overseas_costing.services import edit_session_service

    class FakeFrappe:
        class session:
            user = "管理员乙"

    monkeypatch.setattr(edit_session_service, "frappe", FakeFrappe())
    monkeypatch.setattr(
        edit_session_service,
        "_lock_row",
        lambda _batch_name: {
            "edit_lock_owner": "管理员乙",
            "edit_lock_token": "token-b",
            "edit_lock_expires_at": datetime(2099, 9, 2, 10, 5),
            "modified": datetime(2026, 9, 2, 10, 0),
        },
    )

    with pytest.raises(RuntimeError, match="缺少数据版本"):
        assert_batch_write(
            "BATCH-1",
            edit_token="token-b",
            expected_modified=None,
        )
