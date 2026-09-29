# -*- coding: utf-8 -*-
"""统一审计口径的守卫测试。

「仅审计」曾经把两类完全不同的情况混成一个布尔，导致审批进行中（业务常态）
的资料在页面上被显示成"仅审计"，并让装箱单在候选列表里被直接丢弃。
本测试锁住新口径：只有真排除才算 audit_only。
"""

import pytest

from overseas_costing.services.settlement_audit_policy import (
    REJECTION_EXCLUSION_REASONS,
    settlement_audit_state,
)


@pytest.mark.parametrize(
    "reason",
    [
        "审批结果为拒绝",
        "审批状态为拒绝",
        "审批已撤销、终止或作废",
    ],
)
def test_rejection_reasons_are_real_exclusions(reason) -> None:
    """钉钉归档写入的三个精确原因就是真排除。"""

    state = settlement_audit_state({"exclusion_reason": reason})

    assert state["mode"] == "excluded"
    assert state["audit_only"] is True
    assert state["pending_approval"] is False
    assert state["reason"] == reason


def test_rejection_reason_whitelist_matches_the_approval_writer_values() -> None:
    """白名单必须与 dingtalk_approval_service 写入的三个值逐字一致。"""

    assert REJECTION_EXCLUSION_REASONS == {
        "审批结果为拒绝",
        "审批状态为拒绝",
        "审批已撤销、终止或作废",
    }


@pytest.mark.parametrize(
    "parsed",
    [
        pytest.param({"approval_excluded": True}, id="approval_excluded"),
        pytest.param({"cost_source_allowed": False}, id="cost_source_allowed_false"),
        pytest.param({"settlement_document": {"audit_only": True}}, id="descriptor_audit_only"),
        pytest.param(
            {"approval_excluded": True, "cost_source_allowed": False, "settlement_document": {"audit_only": True}},
            id="all_pending_flags",
        ),
    ],
)
def test_pending_approval_is_not_an_audit_only_exclusion(parsed) -> None:
    """审批未完成只算"待审批"，不算仅审计——这是本次修复的核心结论。"""

    state = settlement_audit_state(parsed)

    assert state["mode"] == "pending"
    assert state["audit_only"] is False
    assert state["pending_approval"] is True
    assert "审批尚未完成" in state["reason"]


def test_retired_attachment_is_excluded_even_without_approval_reason() -> None:
    """附件被撤销/替代属于真排除，与审批是否完成无关。"""

    for parsed in (
        {"settlement_document": {"retired": True}},
        {"retired": True},
        {"settlement_document": {"retired_at": "2026-09-09"}},
    ):
        state = settlement_audit_state(parsed)
        assert state["mode"] == "excluded", parsed
        assert state["audit_only"] is True


def test_unknown_exclusion_reason_stays_excluded() -> None:
    """拿不到明确业务含义的原因时按排除处理，不能当作可用。"""

    state = settlement_audit_state({"exclusion_reason": "某个还没归类的历史原因"})

    assert state["mode"] == "excluded"
    assert state["audit_only"] is True


def test_clean_attachment_is_available() -> None:
    """没有任何标记的资料就是可用，不产生任何提示文案。"""

    state = settlement_audit_state({})

    assert state["mode"] == "available"
    assert state["audit_only"] is False
    assert state["pending_approval"] is False
    assert state["reason"] == ""
