from copy import deepcopy
import json

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


def test_server_confirmation_revalidates_relation_without_freezing_candidate():
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

    relation = service.confirm_preview_candidate(
        store, ledger, batch["name"], reference, "user", freight_mode=True
    )
    assert relation == {
        "policy": service.POLICY,
        "candidate_id": candidate["id"],
        "candidate_revision": candidate["revision"],
        "version": version["name"],
        "logistics_id": candidate["logistics_id"],
        "expense_id": candidate["expense_id"],
        "logistics_snapshot": candidate["logistics_snapshot"],
        "expense_snapshot": candidate["expense_snapshot"],
        "confirmed_by": "user",
        "confirmed_at": relation["confirmed_at"],
    }
    assert relation["confirmed_at"]
    assert store.get("freight_candidate", candidate["id"])["status"] == "pending"
    assert not any(
        row["action"] == "material_ai_payment_match_confirmed"
        for row in store.find("audit", binding_id=batch["name"])
    )


def test_confirmation_locks_match_arbitration_before_candidate_context(monkeypatch):
    from overseas_costing.services import material_ai_payment_match as service

    store, ledger, batch, version, _logistics, _source, candidate = _strong_context()
    reference = service.select_preview_candidate(
        store, ledger, batch["name"], version["name"], freight_mode=True
    )
    original_get = store.get
    locked_reads = []

    def traced_get(table, row_id, lock=False):
        if lock:
            locked_reads.append((table, row_id))
        return original_get(table, row_id, lock=lock)

    monkeypatch.setattr(store, "get", traced_get)

    with store.atomic():
        service.confirm_preview_candidate(
            store, ledger, batch["name"], reference, "user", freight_mode=True
        )

    assert locked_reads[0] == ("state", "match_lock")
    assert locked_reads.index(("state", "match_lock")) < locked_reads.index(
        ("freight_candidate", candidate["id"])
    )


def test_version_relation_is_safe_audited_and_idempotent():
    from overseas_costing.services import material_ai_payment_match as service

    store, ledger, batch, version, _logistics, _source, candidate = _strong_context()
    reference = service.select_preview_candidate(
        store, ledger, batch["name"], version["name"], freight_mode=True
    )
    relation = service.confirm_preview_candidate(
        store, ledger, batch["name"], reference, "user", freight_mode=True
    )

    first = service.persist_relation(
        store, ledger, batch["name"], version["name"], relation, "user"
    )
    second = service.persist_relation(
        store, ledger, batch["name"], version["name"], relation, "user"
    )

    metadata = json.loads(ledger.get("version", version["name"])["extra_json"])
    assert metadata["material_ai_payment_match"] == first == second
    assert set(first) == {
        "policy", "candidate_id", "candidate_revision", "version",
        "logistics_id", "expense_id", "logistics_snapshot", "expense_snapshot",
        "confirmed_by", "confirmed_at",
    }
    assert "amount" not in json.dumps(first) and "text" not in json.dumps(first)
    audits = [
        row for row in store.find("audit", binding_id=batch["name"])
        if row["action"] == "material_ai_payment_match_confirmed"
    ]
    assert len(audits) == 1
    assert store.get("freight_candidate", candidate["id"])["status"] == "pending"


def test_version_relation_and_audit_roll_back_when_later_apply_fails():
    from overseas_costing.services import material_ai_payment_match as service

    store, ledger, batch, version, _logistics, _source, candidate = _strong_context()
    reference = service.select_preview_candidate(
        store, ledger, batch["name"], version["name"], freight_mode=True
    )
    relation = service.confirm_preview_candidate(
        store, ledger, batch["name"], reference, "user", freight_mode=True
    )

    with pytest.raises(RuntimeError, match="later write failed"):
        with store.atomic():
            service.persist_relation(
                store, ledger, batch["name"], version["name"], relation, "user"
            )
            raise RuntimeError("later write failed")

    metadata = json.loads(ledger.get("version", version["name"]).get("extra_json") or "{}")
    assert "material_ai_payment_match" not in metadata
    assert not any(
        row["action"] == "material_ai_payment_match_confirmed"
        for row in store.find("audit", binding_id=batch["name"])
    )
    assert store.get("freight_candidate", candidate["id"])["status"] == "pending"


def test_saved_ai_relation_does_not_freeze_candidate_rebuild_or_rejection():
    from overseas_costing.services import material_ai_payment_match as service
    from overseas_costing.services.logistics_settlement import freight_matching, freight_runtime
    from overseas_costing.services.logistics_settlement.model import parse_source
    from overseas_costing.tests.test_freight_lines import monthly, setup_cost

    store, ledger, batch, version, _item, logistics, expense = setup_cost()
    candidate = freight_matching.rule_pass(store, logistics["id"])[0]
    reference = service.select_preview_candidate(
        store, ledger, batch["name"], version["name"], freight_mode=True
    )
    relation = service.confirm_preview_candidate(
        store, ledger, batch["name"], reference, "user", freight_mode=True
    )
    service.persist_relation(
        store, ledger, batch["name"], version["name"], relation, "user"
    )

    changed = monthly()
    changed["raw_payload"]["comments"] = [{"text": "付款资料快照更新"}]
    changed["updated_at"] = "2026-09-16T10:00:00+00:00"
    refreshed_source = store.ingest(parse_source(changed, logistics_codes={"logistics"}))
    rebuilt = freight_matching.rule_pass(store, logistics["id"])[0]

    assert refreshed_source["snapshot"] != expense["snapshot"]
    assert rebuilt["revision"] != candidate["revision"]
    assert rebuilt["expense_snapshot"] == refreshed_source["snapshot"]
    assert rebuilt["status"] == "pending"

    rejected = freight_runtime.decide_payment_candidate(
        store, ledger, batch["name"], version["name"], rebuilt["id"], rebuilt["revision"],
        "reject", "新快照需重新核对", "user",
        lease_check=lambda *_args, **_kwargs: None,
        edit_token="token", expected_modified="modified",
    )
    assert rejected["candidate"]["status"] == "rejected"


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
