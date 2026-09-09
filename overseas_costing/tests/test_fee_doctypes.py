"""费用生命周期与凭证关联 DocType 契约测试。"""

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _doctype(relative: str) -> dict:
    return json.loads((ROOT / relative).read_text(encoding="utf-8"))


def _fields(meta: dict) -> dict[str, dict]:
    return {row["fieldname"]: row for row in meta["fields"]}


def test_allocation_rule_has_explicit_fee_state_fields() -> None:
    doc = _doctype("doctype/overseas_cost_allocation_rule/overseas_cost_allocation_rule.json")
    fields = _fields(doc)

    assert {
        "logical_fee_key",
        "amount_status",
        "scope_type",
        "scope_value_json",
        "scope_revision",
        "amount_revision",
        "required_evidence_role",
        "included_in_fee_key",
    } <= fields.keys()
    assert fields["logical_fee_key"]["reqd"] == 1
    assert fields["amount_status"]["options"].splitlines() == [
        "MISSING",
        "ESTIMATED",
        "ACTUAL",
        "NOT_INCURRED",
        "INCLUDED",
    ]
    assert fields["scope_type"]["options"].splitlines() == [
        "ALL_ITEMS",
        "ITEMS",
        "DIRECT_ITEM",
    ]


def test_fee_doctype_mirrors_are_identical() -> None:
    for name in (
        "overseas_cost_fee_evidence",
        "overseas_cost_fee_evidence_ai_run",
        "overseas_cost_fee_sku_component",
    ):
        for filename in ("__init__.py", f"{name}.json", f"{name}.py"):
            assert (ROOT / "doctype" / name / filename).read_bytes() == (
                ROOT / "overseas_costing" / "doctype" / name / filename
            ).read_bytes()


def test_fee_evidence_tracks_attachment_validation() -> None:
    doc = _doctype("doctype/overseas_cost_fee_evidence/overseas_cost_fee_evidence.json")
    fields = _fields(doc)

    assert {
        "batch",
        "version",
        "fee_rule",
        "attachment",
        "evidence_role",
        "validation_status",
        "source_revision",
        "validated_by",
        "validated_at",
        "remark",
    } <= fields.keys()
    assert fields["validation_status"]["options"].splitlines() == [
        "PENDING",
        "VALID",
        "INVALID",
        "UNLINKED",
    ]


def test_fee_evidence_and_component_support_refund_linkage_and_cost_effect() -> None:
    evidence = _fields(
        _doctype("doctype/overseas_cost_fee_evidence/overseas_cost_fee_evidence.json")
    )
    component = _fields(
        _doctype("doctype/overseas_cost_fee_sku_component/overseas_cost_fee_sku_component.json")
    )

    assert evidence["related_evidence"]["options"] == "Overseas Cost Fee Evidence"
    assert component["accounting_role"]["options"].splitlines() == [
        "ESTIMATE",
        "FINAL_BILL",
        "SETTLEMENT",
    ]
    assert component["cost_effect"]["options"].splitlines() == ["COST", "LEDGER_ONLY"]
    assert component["reverses_component"]["options"] == "Overseas Cost Fee SKU Component"
    assert "REFUND_REVERSAL" in component["component_type"]["options"].splitlines()
