"""ERP synchronization ledger, identity and reconciliation tests."""

from overseas_costing.services.erp_sync_service import (
    InMemorySyncStore,
    apply_sync_response,
    execute_site_pushes,
    filter_retry_preview,
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


def test_site_pushes_keep_partial_success_and_retry_only_failed_group() -> None:
    preview = {
        "sites": [
            {
                "site_code": "PROD",
                "groups": [{
                    "group_key": "G-PROD",
                    "supplier": "S",
                    "currency": "CNY",
                    "stock_uom": "kg",
                    "allocated_fee_rmb": "20.00",
                    "total_cost_rmb": "70.00",
                    "estimated_fee_keys": ["FREIGHT"],
                    "items": [{
                        "stable_line_key": "P1",
                        "material_code": "M-P",
                        "effective_shipped_qty": 2,
                        "goods_value": 50,
                        "total_cost_rmb": 70,
                        "total_unit_rmb": 35,
                    }],
                }],
            },
            {
                "site_code": "ECOM",
                "groups": [{
                    "group_key": "G-ECOM",
                    "supplier": "S",
                    "currency": "CNY",
                    "stock_uom": "件",
                    "allocated_fee_rmb": "10.00",
                    "total_cost_rmb": "50.00",
                    "estimated_fee_keys": ["FREIGHT"],
                    "items": [{
                        "stable_line_key": "E1",
                        "material_code": "M-E",
                        "effective_shipped_qty": 1,
                        "goods_value": 40,
                        "total_cost_rmb": 50,
                        "total_unit_rmb": 50,
                    }],
                }],
            },
        ]
    }

    class FakeClient:
        def __init__(self):
            self.calls = []
            self.payloads = {}
            self.fail_ecom = True

        def create_purchase(self, payload, config):
            self.calls.append((config["site_code"], payload))
            if config["site_code"] == "ECOM" and self.fail_ecom:
                return {"ok": False, "status": "FAILED", "code": "OFFLINE"}
            name = f"PO-{config['site_code']}"
            self.payloads[name] = payload
            return {"ok": True, "status": "CREATED", "erp_target_doc": name}

        def read_purchase_state(self, link, _config):
            payload = self.payloads[link["remote_document"]]
            return {
                "data": {
                    "name": link["remote_document"],
                    "docstatus": 0,
                    "custom_overseas_business_key": payload["business_key"],
                    "items": [
                        {
                            "name": f"ROW-{row['stable_line_key']}",
                            "custom_overseas_stable_line_key": row["stable_line_key"],
                            "qty": row["source_quantity"],
                            "custom_overseas_comprehensive_amount": row["cost_formula"]["total_cost"],
                        }
                        for row in payload["items"]
                    ],
                }
            }

    store = InMemorySyncStore()
    client = FakeClient()
    configs = {
        "PROD": {"site_code": "PROD", "company": "PROD CO"},
        "ECOM": {"site_code": "ECOM", "company": "ECOM CO"},
    }

    first = execute_site_pushes(
        batch="B1",
        version="V1",
        cost_result_hash="H1",
        preview=preview,
        site_configs=configs,
        intent_key="CLICK-1",
        client=client,
        store=store,
    )

    assert first["status"] == "PARTIAL"
    assert {(row["site_code"], row["status"]) for row in first["groups"]} == {
        ("PROD", "SUCCESS"),
        ("ECOM", "FAILED"),
    }
    assert {row["stable_line_key"] for row in store.links} == {"P1"}
    assert {site: payload["fee_total_rmb"] for site, payload in client.calls} == {
        "PROD": "20.00",
        "ECOM": "10.00",
    }

    client.fail_ecom = False
    client.calls.clear()
    retried = execute_site_pushes(
        batch="B1", version="V1", cost_result_hash="H1", preview=preview,
        site_configs=configs, intent_key="CLICK-2", client=client, store=store,
    )
    assert retried["status"] == "SUCCESS"
    assert [site for site, _ in client.calls] == ["ECOM"]
    assert {row["stable_line_key"] for row in store.links} == {"P1", "E1"}

    client.calls.clear()
    repeated = execute_site_pushes(
        batch="B1", version="V1", cost_result_hash="H1", preview=preview,
        site_configs=configs, intent_key="CLICK-3", client=client, store=store,
    )
    assert repeated["status"] == "SUCCESS"
    assert client.calls == []


def test_retry_preview_contains_only_the_requested_failed_site_group() -> None:
    preview = {
        "sites": [
            {"site_code": "PROD", "groups": [{"group_key": "G-PROD"}]},
            {"site_code": "ECOM", "groups": [{"group_key": "G-ECOM"}, {"group_key": "G-OTHER"}]},
        ]
    }
    request = {
        "site_code": "ECOM",
        "business_key": purchase_business_key(batch="B1", site="ECOM", group="G-ECOM", version="V1"),
    }

    result = filter_retry_preview(preview, batch="B1", version="V2", request=request)

    assert [site["site_code"] for site in result["sites"]] == ["ECOM"]
    assert [group["group_key"] for group in result["sites"][0]["groups"]] == ["G-ECOM"]
