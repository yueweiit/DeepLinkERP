from __future__ import annotations

import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
MIRROR_ROOT = ROOT / "overseas_costing"


def _doctype(name: str) -> dict:
    path = ROOT / "doctype" / name / f"{name}.json"
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    "name",
    ("overseas_cost_review_round", "overseas_cost_review_issue"),
)
def test_review_communication_doctypes_are_mirrored(name: str) -> None:
    source = _doctype(name)
    mirror = json.loads(
        (MIRROR_ROOT / "doctype" / name / f"{name}.json").read_text(encoding="utf-8")
    )

    assert source["doctype"] == "DocType"
    assert mirror == source


def test_review_round_schema_captures_versioned_workflow_without_assignment() -> None:
    fields = {row["fieldname"]: row for row in _doctype("overseas_cost_review_round")["fields"]}

    assert fields["batch"]["options"] == "Overseas Cost Batch"
    assert fields["version"]["options"] == "Overseas Cost Version"
    assert fields["status"]["options"] == "Returned\nResubmitted\nResolved"
    assert fields["trial_signature"]["read_only"] == 1
    assert {"returned_by", "returned_at", "resubmitted_by", "resubmitted_at", "resolved_by", "resolved_at"} <= fields.keys()
    assert "responsible_party" not in fields
    assert "assignee" not in fields


def test_review_issue_schema_keeps_optional_anchor_reply_and_audit_fields() -> None:
    fields = {row["fieldname"]: row for row in _doctype("overseas_cost_review_issue")["fields"]}

    assert fields["review_round"]["options"] == "Overseas Cost Review Round"
    assert fields["status"]["options"] == "Open\nAddressed\nResolved"
    assert fields["description"]["reqd"] == 1
    assert fields["target_tab"]["reqd"] == 0
    assert fields["attachment_manifest_json"]["fieldtype"] == "Long Text"
    assert {"reply", "addressed_by", "addressed_at", "resolved_by", "resolved_at"} <= fields.keys()
    assert "issue_type" not in fields
    assert "responsible_party" not in fields


def test_project_review_state_handles_none_returned_resubmitted_and_resolved() -> None:
    from overseas_costing.services.review_communication_service import project_review_state

    assert project_review_state(None) == {
        "remediation_state": "none",
        "round_name": "",
        "round_no": 0,
        "issue_count": 0,
        "unresolved_count": 0,
        "addressed_count": 0,
        "erp_blocked": False,
    }
    returned = project_review_state(
        {"name": "ROUND-1", "round_no": 1, "status": "Returned"},
        [
            {"name": "I-1", "status": "Open"},
            {"name": "I-2", "status": "Addressed"},
        ],
    )
    assert returned == {
        "remediation_state": "returned",
        "round_name": "ROUND-1",
        "round_no": 1,
        "issue_count": 2,
        "unresolved_count": 1,
        "addressed_count": 1,
        "erp_blocked": True,
    }
    assert project_review_state(
        {"name": "ROUND-1", "round_no": 1, "status": "Resubmitted"},
        [{"status": "Addressed"}],
    )["remediation_state"] == "resubmitted"
    resolved = project_review_state(
        {"name": "ROUND-1", "round_no": 1, "status": "Resolved"},
        [{"status": "Resolved"}],
    )
    assert resolved["remediation_state"] == "resolved"
    assert resolved["erp_blocked"] is False


def test_normalize_issue_draft_requires_text_and_preserves_only_supported_anchor() -> None:
    from overseas_costing.services.review_communication_service import normalize_issue_draft

    with pytest.raises(ValueError, match="整改问题不能为空"):
        normalize_issue_draft({"description": "  "}, order_no=1)

    assert normalize_issue_draft(
        {
            "description": "  清关费金额与凭证不一致  ",
            "target_tab": "documents",
            "target_field": "clearance_fee",
            "target_row": "RULE-1",
            "target_item": "",
            "attachments": ["FILE-1", "FILE-1", "FILE-2"],
            "issue_type": "must-drop",
            "responsible_party": "must-drop",
        },
        order_no=2,
    ) == {
        "order_no": 2,
        "description": "清关费金额与凭证不一致",
        "target_tab": "documents",
        "target_field": "clearance_fee",
        "target_row": "RULE-1",
        "target_item": "",
        "attachments": ["FILE-1", "FILE-2"],
    }
