from copy import deepcopy

import pytest

from overseas_costing.services.logistics_settlement.model import dumps
from overseas_costing.tests.test_payment_adoption import payment_setup


def _candidate_values(candidate, **changes):
    value = {**candidate, "method": "identifier", "issues": [], **changes}
    return {
        "id": value["id"],
        "logistics_id": value["logistics_id"],
        "expense_id": value["expense_id"],
        "status": value["status"],
        "data": dumps(value),
    }


def _strong_context():
    context = payment_setup()
    store, _ledger, _batch, _version, _logistics, _source, candidate = context
    store.put("freight_candidate", _candidate_values(candidate))
    return context


def test_unique_strong_current_freight_candidate_is_selected_by_server():
    from overseas_costing.services import material_ai_payment_match as service

    store, ledger, batch, version, _logistics, _source, candidate = _strong_context()

    selected = service.select_preview_candidate(
        store, ledger, batch["name"], version["name"], freight_mode=True
    )

    assert selected == {
        "candidate_id": candidate["id"],
        "revision": candidate["revision"],
        "version": version["name"],
    }


@pytest.mark.parametrize(
    "changes",
    [
        {"status": "rejected"},
        {"status": "conflict"},
        {"method": "deepseek", "confidence": "0.89"},
        {"method": "deepseek", "confidence": None},
    ],
)
def test_rejected_conflicting_or_low_confidence_match_is_not_selected(changes):
    from overseas_costing.services import material_ai_payment_match as service

    store, ledger, batch, version, _logistics, _source, candidate = _strong_context()
    store.put("freight_candidate", _candidate_values(candidate, **changes))

    assert service.select_preview_candidate(
        store, ledger, batch["name"], version["name"], freight_mode=True
    ) is None


def test_multiple_strong_payment_matches_are_not_selected_arbitrarily():
    from overseas_costing.services import material_ai_payment_match as service

    store, ledger, batch, version, _logistics, source, candidate = _strong_context()
    second_source = {
        **source,
        "id": "payment-2",
        "instance": "PAY-2",
        "snapshot": "payment-snapshot-2",
        "match_hash": "pm2",
    }
    store.insert(
        "source",
        {
            "id": second_source["id"],
            "corp": second_source["corp"],
            "instance": second_source["instance"],
            "kind": second_source["kind"],
            "snapshot": second_source["snapshot"],
            "match_hash": second_source["match_hash"],
            "updated_at": second_source["updated_at"],
            "data": dumps(second_source),
        },
    )
    second_candidate = {
        **candidate,
        "id": "candidate-2",
        "expense_id": second_source["id"],
        "expense_snapshot": second_source["snapshot"],
        "revision": "candidate-revision-2",
        "method": "explicit",
        "issues": [],
    }
    store.insert("freight_candidate", _candidate_values(second_candidate))

    assert service.select_preview_candidate(
        store, ledger, batch["name"], version["name"], freight_mode=True
    ) is None


def test_server_confirmation_is_revision_fenced_and_atomic():
    from overseas_costing.services import material_ai_payment_match as service

    store, ledger, batch, version, _logistics, _source, candidate = _strong_context()
    reference = service.select_preview_candidate(
        store, ledger, batch["name"], version["name"], freight_mode=True
    )

    with pytest.raises(RuntimeError, match="downstream failed"):
        with store.atomic():
            service.confirm_preview_candidate(
                store, ledger, batch["name"], reference, "user", freight_mode=True
            )
            raise RuntimeError("downstream failed")
    assert store.get("freight_candidate", candidate["id"])["status"] == "pending"

    stale = {**reference, "revision": "stale"}
    with pytest.raises(ValueError, match="变化"):
        service.confirm_preview_candidate(
            store, ledger, batch["name"], stale, "user", freight_mode=True
        )
    assert store.get("freight_candidate", candidate["id"])["status"] == "pending"

    confirmed = service.confirm_preview_candidate(
        store, ledger, batch["name"], reference, "user", freight_mode=True
    )
    assert confirmed == reference
    assert store.get("freight_candidate", candidate["id"])["status"] == "confirmed"


def test_cross_ticket_candidate_cannot_be_confirmed():
    from overseas_costing.services import material_ai_payment_match as service

    store, ledger, _batch, version, _logistics, _source, candidate = _strong_context()
    other_batch = ledger.create("batch", {"status": "Dirty", "confirm_status": "Pending"})
    other_version = ledger.create(
        "version", {"batch": other_batch["name"], "status": "Active", "is_current": 1}
    )
    ledger.put("batch", other_batch["name"], {"current_version": other_version["name"]})

    with pytest.raises(ValueError, match="不属于当前批次"):
        service.confirm_preview_candidate(
            store,
            ledger,
            other_batch["name"],
            {
                "candidate_id": candidate["id"],
                "revision": candidate["revision"],
                "version": other_version["name"],
            },
            "user",
            freight_mode=True,
        )


def test_payment_match_sources_are_server_scoped_and_contain_stable_reference_only():
    from overseas_costing.services import material_ai_payment_match as service
    from overseas_costing.services.logistics_settlement import freight_matching
    from overseas_costing.tests.test_freight_lines import setup_cost

    store, ledger, batch, version, _item, logistics, source = setup_cost()
    candidate = freight_matching.rule_pass(store, logistics["id"])[0]
    reference = service.select_preview_candidate(
        store, ledger, batch["name"], version["name"], freight_mode=True
    )

    sources = service.preview_sources(
        store, ledger, batch["name"], version["name"], reference, freight_mode=True
    )

    assert sources
    assert {row["workflow_stage"] for row in sources} == {"payment"}
    assert {row["workflow_rank"] for row in sources} == {0}
    assert {row["payment_match_candidate_id"] for row in sources} == {candidate["id"]}
    assert {row["process_instance_id"] for row in sources} == {source["instance"]}
    assert all(row["scoped_packing"] for row in sources)
    assert all("payment_match_status" not in row for row in sources)
    assert all("amount" not in row and "currency" not in row for row in sources)
