"""费用修改、默认清单和凭证关联事务测试。"""

import pytest

from overseas_costing.services import fee_service
from overseas_costing.services.fee_service import (
    build_default_fee_templates,
    build_evidence_candidates,
    compose_fee_worklist_rows,
    deduplicate_evidence_candidates,
    map_historical_fee_key,
    merge_logical_fee,
    normalize_fee_payload,
)


def test_default_fee_templates_change_only_the_transport_specific_pair() -> None:
    sea = build_default_fee_templates("SEA")
    air = build_default_fee_templates("AIR")
    express = build_default_fee_templates("EXPRESS")

    assert [row["expense_category"] for row in sea] == [
        "国际海运费",
        "港杂/货代附加费",
        "清关费",
        "进口税费",
        "目的地配送费",
    ]
    assert [row["allocation_basis"] for row in sea] == [
        "volume",
        "volume",
        "goods_value",
        "goods_value",
        "gross_weight",
    ]
    assert air[0]["expense_category"] == "国际空运费"
    assert air[0]["allocation_basis"] == "chargeable_weight"
    assert express[0]["expense_category"] == "国际快递费"
    assert all(row["virtual"] for row in sea + air + express)


def test_historical_fee_names_map_in_memory_without_guessing_unknown_names() -> None:
    assert map_historical_fee_key({"expense_category": "国际海运费"}, "SEA") == "international_sea_freight"
    assert map_historical_fee_key({"rule_code": "清关费"}, "SEA") == "customs_clearance_fee"
    assert map_historical_fee_key({"expense_category": "历史特殊费用"}, "SEA") == ""


def test_saved_historical_fee_replaces_virtual_template_without_writing_defaults() -> None:
    rows = compose_fee_worklist_rows(
        [
            {
                "name": "RULE-1",
                "expense_category": "国际海运费",
                "amount": "123.45",
                "currency": "USD",
            },
            {
                "name": "RULE-LEGACY",
                "expense_category": "历史特殊费用",
                "amount": "20",
                "currency": "RMB",
            },
        ],
        "SEA",
    )

    assert len([row for row in rows if row["logical_fee_key"] == "international_sea_freight"]) == 1
    freight = next(row for row in rows if row["logical_fee_key"] == "international_sea_freight")
    assert freight["name"] == "RULE-1"
    assert freight["amount"] == "123.45"
    assert freight["amount_status"] == "ESTIMATED"
    assert freight["required_evidence_role"] == "freight_invoice"
    assert freight["virtual"] is False
    legacy = next(row for row in rows if row["name"] == "RULE-LEGACY")
    assert legacy["legacy_unmapped"] is True
    assert legacy["logical_fee_key"] == "legacy:RULE-LEGACY"


def test_parsed_amounts_are_candidates_only_and_never_become_fee_rows() -> None:
    attachments = [
        {
            "name": "ATT-1",
            "file_name": "freight.pdf",
            "source_type": "Voucher",
            "parse_status": "Parsed",
            "parse_result_json": '{"classification":{"code":"logistics_quote"},"field_candidates":{"amount_candidate":321.50,"currency":"USD"}}',
            "mapped_result_json": "{}",
        }
    ]

    candidates = build_evidence_candidates(attachments)

    assert candidates[0]["attachment"] == "ATT-1"
    assert candidates[0]["amount_candidates"] == [
        {"amount": "321.5", "currency": "USD", "path": "field_candidates.amount_candidate"}
    ]
    assert "logical_fee_key" not in candidates[0]


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


@pytest.mark.parametrize("currency", [None, "", "US", "USDT", "U1D"])
def test_normalize_fee_payload_rejects_invalid_currency(currency) -> None:
    with pytest.raises(ValueError, match="币种"):
        normalize_fee_payload(
            {
                "logical_fee_key": "FREIGHT",
                "amount": "100",
                "amount_status": "ACTUAL",
                "currency": currency,
                "scope_type": "ALL_ITEMS",
                "allocation_basis": "gross_weight",
            }
        )


def test_normalize_fee_payload_defaults_missing_currency_to_rmb() -> None:
    result = normalize_fee_payload(
        {
            "logical_fee_key": "FREIGHT",
            "amount": "100",
            "amount_status": "ACTUAL",
            "scope_type": "ALL_ITEMS",
            "allocation_basis": "gross_weight",
        }
    )

    assert result["currency"] == "RMB"


def test_normalize_fee_payload_uppercases_any_three_letter_currency() -> None:
    result = normalize_fee_payload(
        {
            "logical_fee_key": "FREIGHT",
            "amount": "100",
            "amount_status": "ACTUAL",
            "currency": "eur",
            "scope_type": "ALL_ITEMS",
            "allocation_basis": "gross_weight",
        }
    )

    assert result["currency"] == "EUR"


@pytest.mark.parametrize("amount", ["NaN", "Infinity", "-Infinity"])
def test_normalize_fee_payload_rejects_non_finite_amount(amount: str) -> None:
    with pytest.raises(ValueError, match="金额"):
        normalize_fee_payload(
            {
                "logical_fee_key": "FREIGHT",
                "amount": amount,
                "amount_status": "ACTUAL",
                "currency": "RMB",
                "scope_type": "ALL_ITEMS",
                "allocation_basis": "gross_weight",
            }
        )


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


def test_deleted_attachment_unlinks_evidence_without_creating_completion_state(monkeypatch) -> None:
    writes = []

    class FakeDb:
        @staticmethod
        def set_value(doctype, name, values, update_modified=False):
            writes.append((doctype, name, values, update_modified))

    class FakeFrappe:
        db = FakeDb()

        @staticmethod
        def get_all(*_args, **_kwargs):
            return [{"name": "EVID-1"}, {"name": "EVID-2"}]

    monkeypatch.setattr(fee_service, "frappe", FakeFrappe())

    result = fee_service.unlink_fee_evidence_for_attachment("ATT-1", reason="附件已删除")

    assert result["affected_count"] == 2
    assert all(row[2]["validation_status"] == "UNLINKED" for row in writes)
    assert all(row[2]["attachment"] == "" for row in writes)


def test_fee_worklist_rejects_a_version_from_another_batch(monkeypatch) -> None:
    class FakeDb:
        @staticmethod
        def get_value(doctype, name, fieldname, **_kwargs):
            if doctype == "Overseas Cost Version" and fieldname == "batch":
                return "OTHER-BATCH"
            return None

    class FakeFrappe:
        db = FakeDb()

    monkeypatch.setattr(fee_service, "frappe", FakeFrappe())

    with pytest.raises(ValueError, match="不属于当前批次"):
        fee_service.get_fee_worklist("BATCH-1", "VERSION-OTHER")
