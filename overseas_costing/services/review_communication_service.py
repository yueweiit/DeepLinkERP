"""成本复核整改沟通的纯规则和事务入口。"""

from __future__ import annotations


ALLOWED_TARGET_TABS = {"overview", "dingtalk", "documents", "items", "vouchers"}


def _clean(value) -> str:
    return str(value or "").strip()


def normalize_issue_draft(value: dict, *, order_no: int) -> dict:
    """只接受用户已确认的最小问题结构，丢弃分类和责任方等扩展字段。"""

    draft = dict(value or {})
    description = _clean(draft.get("description"))
    if not description:
        raise ValueError("整改问题不能为空。")
    target_tab = _clean(draft.get("target_tab"))
    if target_tab and target_tab not in ALLOWED_TARGET_TABS:
        raise ValueError("整改问题关联页签无效。")
    attachments = []
    for name in draft.get("attachments") or []:
        normalized = _clean(name)
        if normalized and normalized not in attachments:
            attachments.append(normalized)
    return {
        "order_no": int(order_no),
        "description": description,
        "target_tab": target_tab,
        "target_field": _clean(draft.get("target_field")),
        "target_row": _clean(draft.get("target_row")),
        "target_item": _clean(draft.get("target_item")),
        "attachments": attachments,
    }


def project_review_state(review_round: dict | None, issues: list[dict] | None = None) -> dict:
    """把活动轮次投影为列表与 ERP 门禁共同使用的稳定字段。"""

    if not review_round:
        return {
            "remediation_state": "none",
            "round_name": "",
            "round_no": 0,
            "issue_count": 0,
            "unresolved_count": 0,
            "addressed_count": 0,
            "erp_blocked": False,
        }
    rows = list(issues or [])
    unresolved = sum(_clean(row.get("status")).lower() == "open" for row in rows)
    addressed = sum(_clean(row.get("status")).lower() == "addressed" for row in rows)
    state = _clean(review_round.get("status")).lower() or "returned"
    return {
        "remediation_state": state,
        "round_name": _clean(review_round.get("name")),
        "round_no": int(review_round.get("round_no") or 0),
        "issue_count": len(rows),
        "unresolved_count": unresolved,
        "addressed_count": addressed,
        "erp_blocked": state != "resolved" or unresolved > 0 or addressed > 0,
    }
