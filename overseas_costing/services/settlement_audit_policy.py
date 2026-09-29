"""统一维护「资料能否参与核算」的审计口径。

历史问题：多处代码把两类完全不同的情况写成同一个 ``audit_only`` 布尔——

* **真排除（A 类）**：审批被拒绝 / 撤销 / 终止 / 作废，或附件被撤销、被新版本替代。
  这类资料确实只能留档备查。
* **审批未完成（B 类）**：审批还在走流程（钉钉 ``RUNNING``），或附件尚未归档。
  这是**业务常态**，不是"仅供审计"。把它显示成"仅审计"会让人误解，
  还会让本可使用的装箱单在候选列表里被直接丢弃。

本模块是这条判定的**唯一 owner**：上游任何链路需要"能不能用 / 该显示什么提示"，
都从这里取，不要再各自维护一份 ``approval_reasons`` 白名单。

判定依据（按可靠性排序）：

1. ``exclusion_reason`` —— 钉钉归档链路在审批结束时写入的三个精确值，
   见 ``dingtalk_approval_service._approval``。非空即真排除。
2. ``source.invalid`` / ``settlement_document.retired`` —— 状态或结果命中拒绝词表，
   或附件被撤销、被新版本替代。真排除。
3. 其余 ``approval_excluded`` / ``cost_source_allowed is False`` / ``approved is False``
   —— 都只说明"当前还不能参与核算"，归入待审批。
"""

from __future__ import annotations

#: 与 ``dingtalk_approval_service._approval`` 写入 ``exclusion_reason`` 的三个值保持一致。
#: 这是真排除的唯一文本白名单，不要在别处复制。
REJECTION_EXCLUSION_REASONS = frozenset(
    {
        "审批结果为拒绝",
        "审批状态为拒绝",
        "审批已撤销、终止或作废",
    }
)

#: 判定结论。
MODE_AVAILABLE = "available"  #: 可参与核算
MODE_PENDING = "pending"  #: 审批未完成 / 附件待归档，暂不可核算
MODE_EXCLUDED = "excluded"  #: 已排除，仅供审计留档


def _as_dict(value) -> dict:
    return value if isinstance(value, dict) else {}


def _settlement_document(parsed: dict) -> dict:
    return _as_dict(parsed.get("settlement_document"))


def is_excluded_from_settlement(parsed: dict) -> bool:
    """仅当资料属于**真排除**（审批拒绝/撤销/终止/作废，或附件已撤销、被替代）时为真。"""

    parsed = _as_dict(parsed)
    descriptor = _settlement_document(parsed)
    reason = str(parsed.get("exclusion_reason") or "").strip()
    if reason in REJECTION_EXCLUSION_REASONS:
        return True
    if reason:
        # 未知原因也算排除：拿不到明确业务含义时不能当作可用。
        return True
    for record in (parsed, descriptor):
        if (
            record.get("retired")
            or record.get("retired_at")
            or record.get("disabled")
            or record.get("invalid")
            or record.get("excluded")
        ):
            return True
    return False


def is_blocked_from_settlement(parsed: dict) -> bool:
    """资料当前是否不能参与核算（真排除或审批未完成都算）。"""

    parsed = _as_dict(parsed)
    descriptor = _settlement_document(parsed)
    if is_excluded_from_settlement(parsed):
        return True
    return bool(
        parsed.get("approval_excluded")
        or parsed.get("cost_source_allowed") is False
        or descriptor.get("audit_only")
    )


def settlement_audit_state(parsed: dict) -> dict:
    """返回统一判定：``mode`` / ``audit_only`` / ``pending_approval`` / ``reason``。

    ``audit_only`` 刻意只对真排除为真——这正是"不要显示仅审计"的落点。
    审批未完成走 ``pending_approval``，文案说明"审批未完成"，不再说"仅审计"。
    """

    parsed = _as_dict(parsed)
    if is_excluded_from_settlement(parsed):
        reason = str(parsed.get("exclusion_reason") or "").strip()
        return {
            "mode": MODE_EXCLUDED,
            "audit_only": True,
            "pending_approval": False,
            "reason": reason or "资料已撤销或被替代，仅留档备查。",
        }

    if is_blocked_from_settlement(parsed):
        descriptor = _settlement_document(parsed)
        pending = bool(
            parsed.get("approval_excluded")
            or parsed.get("cost_source_allowed") is False
            or descriptor.get("audit_only")
        )
        return {
            "mode": MODE_PENDING,
            "audit_only": False,
            "pending_approval": pending,
            "reason": "审批尚未完成，暂不参与核算；审批通过后自动生效。" if pending else "",
        }

    return {"mode": MODE_AVAILABLE, "audit_only": False, "pending_approval": False, "reason": ""}
