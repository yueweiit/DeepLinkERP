"""费用修改、凭证关联和最终确认事务测试。"""

import pytest

from overseas_costing.services.fee_service import (
    deduplicate_evidence_candidates,
    invalidate_fee_completion_for_evidence,
    merge_logical_fee,
    normalize_fee_payload,
    validate_fee_completion,
)


def _estimated_fee_status() -> dict:
    return {
        "fee_key": "FREIGHT",
        "amount_state": "ESTIMATED",
        "todos": [
            {
                "code": "ACTUAL_AMOUNT_REQUIRED",
                "severity": "warning",
                "action": "enter_actual",
            }
        ],
    }


def test_confirm_complete_rejects_estimated_fee() -> None:
    result = validate_fee_completion([_estimated_fee_status()])

    assert result["ok"] is False
    assert result["blocking"][0]["code"] == "ACTUAL_AMOUNT_REQUIRED"


def test_estimate_to_actual_updates_one_logical_fee_instead_of_adding() -> None:
    existing = [
        {
            "name": "RULE-1",
            "logical_fee_key": "FREIGHT",
            "amount": "100",
            "amount_status": "ESTIMATED",
            "amount_revision": "A1",
            "scope_type": "ALL_ITEMS",
            "allocation_basis": "gross_weight",
        }
    ]

    result = merge_logical_fee(
        existing,
        normalize_fee_payload(
            {
                "logical_fee_key": "FREIGHT",
                "amount": "120",
                "amount_status": "ACTUAL",
                "currency": "RMB",
                "scope_type": "ALL_ITEMS",
                "allocation_basis": "gross_weight",
            }
        ),
        revision="A2",
    )

    assert len(result["fees"]) == 1
    assert result["action"] == "updated"
    assert result["fees"][0]["name"] == "RULE-1"
    assert result["fees"][0]["amount"] == "120"
    assert result["fees"][0]["amount_status"] == "ACTUAL"
    assert result["fees"][0]["amount_revision"] == "A2"
    assert result["cost_inputs_changed"] is True


def test_same_amount_nature_change_still_reopens_cost_result() -> None:
    result = merge_logical_fee(
        [
            {
                "logical_fee_key": "FREIGHT",
                "amount": "100",
                "amount_status": "ESTIMATED",
                "scope_type": "ALL_ITEMS",
                "allocation_basis": "gross_weight",
            }
        ],
        normalize_fee_payload(
            {
                "logical_fee_key": "FREIGHT",
                "amount": "100",
                "amount_status": "ACTUAL",
                "currency": "RMB",
                "scope_type": "ALL_ITEMS",
                "allocation_basis": "gross_weight",
            }
        ),
        revision="A2",
    )

    assert result["cost_inputs_changed"] is True


def test_not_incurred_and_included_require_auditable_reason() -> None:
    with pytest.raises(ValueError, match="原因"):
        normalize_fee_payload(
            {
                "logical_fee_key": "STORAGE",
                "amount_status": "NOT_INCURRED",
                "scope_type": "ALL_ITEMS",
                "allocation_basis": "goods_value",
            }
        )
    with pytest.raises(ValueError, match="已包含于"):
        normalize_fee_payload(
            {
                "logical_fee_key": "SURCHARGE",
                "amount_status": "INCLUDED",
                "remark": "已并入主费用",
                "scope_type": "ALL_ITEMS",
                "allocation_basis": "goods_value",
            }
        )


def test_attachment_candidates_are_deduplicated_but_not_turned_into_fees() -> None:
    result = deduplicate_evidence_candidates(
        [
            {"attachment": "ATT-1", "evidence_role": "invoice", "source_revision": "R1"},
            {"attachment": "ATT-1", "evidence_role": "invoice", "source_revision": "R1"},
            {"attachment": "ATT-2", "evidence_role": "payment", "source_revision": "R1"},
        ]
    )

    assert result == [
        {"attachment": "ATT-1", "evidence_role": "invoice", "source_revision": "R1"},
        {"attachment": "ATT-2", "evidence_role": "payment", "source_revision": "R1"},
    ]
    assert all("logical_fee_key" not in row for row in result)


def test_invalid_final_evidence_appends_invalidation_without_dirtying_batch(monkeypatch) -> None:
    from overseas_costing.services import fee_service

    writes = []
    inserted = []

    class FakeDB:
        @staticmethod
        def set_value(doctype, name, values, update_modified=True):
            writes.append((doctype, name, values, update_modified))

        @staticmethod
        def get_value(doctype, filters, fieldname):
            assert doctype == "Overseas Cost Fee Completion"
            assert fieldname == "name"
            return None

    class InsertedDoc:
        name = "INVALIDATION-1"

        def insert(self, **_kwargs):
            inserted.append(self)
            return self

    class FakeFrappe:
        db = FakeDB()
        session = type("Session", (), {"user": "finance@example.com"})()

        @staticmethod
        def get_all(doctype, **_kwargs):
            if doctype == "Overseas Cost Fee Evidence":
                return [
                    {
                        "name": "EVIDENCE-1",
                        "batch": "BATCH-1",
                        "version": "VERSION-1",
                        "validation_status": "VALID",
                    }
                ]
            assert doctype == "Overseas Cost Fee Completion"
            return [{"name": "CONFIRM-1", "input_hash": "H1", "creation": "2026-09-07"}]

        @staticmethod
        def get_doc(values):
            assert values["status"] == "INVALIDATED"
            return InsertedDoc()

    monkeypatch.setattr(fee_service, "frappe", FakeFrappe)

    result = invalidate_fee_completion_for_evidence("ATT-1", reason="凭证删除")

    assert result["affected_evidence_count"] == 1
    assert result["invalidated_count"] == 1
    assert writes[0][0] == "Overseas Cost Fee Evidence"
    assert writes[0][2]["validation_status"] == "UNLINKED"
    assert not any(doctype == "Overseas Cost Batch" for doctype, *_rest in writes)
    assert len(inserted) == 1

def test_completion_accepts_only_when_every_todo_is_closed() -> None:
    result = validate_fee_completion(
        [
            {
                "fee_key": "FREIGHT",
                "amount_state": "ACTUAL",
                "allocation_state": "ALLOCATED",
                "evidence_state": "VALID",
                "todos": [],
            }
        ]
    )

    assert result == {"ok": True, "blocking": []}
