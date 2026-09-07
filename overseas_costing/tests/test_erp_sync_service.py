"""ERP synchronization ledger, identity and reconciliation tests."""

from overseas_costing.services.erp_sync_service import (
    apply_sync_response,
    plan_uncertain_retry,
    prepare_sync_request,
    purchase_business_key,
    transition_request,
    verify_legacy_document_candidates,
)


def _request(**overrides) -> dict:
    value = {
        "operation": "CREATE",
        "batch": "B1",
        "version": "V1",
        "cost_result_hash": "C1",
        "site_code": "S1",
        "business_key": "BK1",
        "payload": {"business_key": "BK1", "items": [{"stable_line_key": "L1", "quantity": 2}]},
        "intent_key": "CLICK-1",
    }
    value.update(overrides)
    return value


def test_cost_version_is_not_part_of_purchase_business_identity() -> None:
    assert purchase_business_key(batch="B1", site="S1", group="G1", version="V1") == purchase_business_key(
        batch="B1", site="S1", group="G1", version="V2"
    )


def test_same_request_id_replays_the_saved_result() -> None:
    first = prepare_sync_request([], **_request())
    saved = {**first["request"], "status": "SUCCESS", "safe_response": {"remote_document": "PO-1"}}

    replay = prepare_sync_request([saved], **_request())

    assert replay["action"] == "REPLAY"
    assert replay["request"] == saved


def test_same_payload_with_a_new_intent_does_not_create_again() -> None:
    first = prepare_sync_request([], **_request())
    saved = {**first["request"], "status": "SUCCESS", "remote_document": "PO-1"}

    repeated = prepare_sync_request([saved], **_request(intent_key="CLICK-2"))

    assert repeated["action"] == "NOOP"
    assert repeated["request"]["request_id"] == saved["request_id"]


def test_old_response_cannot_overwrite_the_latest_cost_version() -> None:
    request = prepare_sync_request([], **_request())["request"]
    running = transition_request(request, "RUNNING")

    result = apply_sync_response(running, {"status": "SUCCESS"}, latest_cost_result_hash="C2")

    assert result["applied"] is False
    assert result["request"]["status"] == "SUPERSEDED"


def test_uncertain_request_is_looked_up_before_retrying() -> None:
    uncertain = {**prepare_sync_request([], **_request())["request"], "status": "UNCERTAIN"}

    found = plan_uncertain_retry(uncertain, {"found": True, "name": "PO-1"})
    missing = plan_uncertain_retry(uncertain, {"found": False})

    assert found == {"action": "RECONCILE_SUCCESS", "remote_document": "PO-1"}
    assert missing["action"] == "RETRY"


def test_ambiguous_or_mismatched_legacy_documents_require_manual_review() -> None:
    expected = [{"stable_line_key": "L1", "quantity": 2}]

    ambiguous = verify_legacy_document_candidates(
        [{"name": "PO-1", "items": expected}, {"name": "PO-2", "items": expected}],
        expected,
    )
    mismatch = verify_legacy_document_candidates(
        [{"name": "PO-1", "items": [{"stable_line_key": "L1", "quantity": 3}]}],
        expected,
    )
    verified = verify_legacy_document_candidates([{"name": "PO-1", "items": expected}], expected)

    assert ambiguous["status"] == "MANUAL_REQUIRED"
    assert mismatch["status"] == "MANUAL_REQUIRED"
    assert verified == {"status": "VERIFIED", "remote_document": "PO-1"}
