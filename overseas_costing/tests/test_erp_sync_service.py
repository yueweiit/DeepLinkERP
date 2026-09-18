from overseas_costing.services.erp_sync_service import (
    build_site_sync_plan,
    build_sync_request_specs,
    can_transition,
    classify_existing_request,
    is_stale_cost_result,
    purchase_business_key,
)


def test_cost_version_is_not_part_of_purchase_business_identity() -> None:
    assert purchase_business_key(batch="B1", site="S1", group="G1", version="V1") == purchase_business_key(
        batch="B1", site="S1", group="G1", version="V2"
    )


def test_same_request_is_reused_and_different_payload_supersedes() -> None:
    preview = {
        "ready": True,
        "sites": [
            {
                "site_code": "S1",
                "groups": [{"supplier": "SUP", "purchase_currency": "CNY", "erp_stock_uom": "kg", "total_cost_rmb": "10", "allocated_fee_rmb": "2", "items": [{"stable_line_key": "L1"}]}],
            }
        ],
    }
    first = build_sync_request_specs(batch="B1", cost_result_hash="H1", preview=preview, client_intent_id="I1")["requests"][0]
    same = build_sync_request_specs(batch="B1", cost_result_hash="H1", preview=preview, client_intent_id="I1")["requests"][0]
    changed = build_sync_request_specs(batch="B1", cost_result_hash="H2", preview=preview, client_intent_id="I2")["requests"][0]

    assert classify_existing_request(first, same) == "REUSE"
    assert classify_existing_request(first, changed) == "SUPERSEDE"


def test_old_cost_result_is_stale() -> None:
    assert is_stale_cost_result("H2", "H1") is True
    assert is_stale_cost_result("H1", "H1") is False


def test_request_state_transitions_reject_terminal_rewrite() -> None:
    assert can_transition("PENDING", "RUNNING") is True
    assert can_transition("SUCCESS", "RUNNING") is False
    assert can_transition("UNCERTAIN", "MANUAL_REQUIRED") is True


def test_site_sync_plan_routes_mixed_container_without_duplicate_fee() -> None:
    result = build_site_sync_plan(
        batch={"name": "B1", "confirm_status": "Confirmed"},
        version={"name": "V1"},
        items=[
            {"name": "I1", "project_collection": "生产", "total_cost_rmb": "70", "allocated_fee_rmb": "20", "supplier": "S", "purchase_currency": "CNY", "stock_uom": "kg"},
            {"name": "I2", "project_collection": "电商", "total_cost_rmb": "50", "allocated_fee_rmb": "10", "supplier": "S", "purchase_currency": "CNY", "stock_uom": "Nos"},
        ],
        routes=[
            {"project_collection": "生产", "subsidiary_code": "PROD", "erp_site": "S1", "enabled": 1},
            {"project_collection": "电商", "subsidiary_code": "ECOM", "erp_site": "S2", "enabled": 1},
        ],
        site_configs=[{"site_code": "S1", "enabled": 1}, {"site_code": "S2", "enabled": 1}],
    )

    assert result["ready"] is True
    assert len(result["request_specs"]["requests"]) == 2
    assert result["push_state"]["preview"]["preview_total_cost_rmb"] == "120"
    assert result["push_state"]["preview"]["preview_allocated_fee_rmb"] == "30"


def test_site_sync_plan_blocks_unrouted_item_before_creating_requests() -> None:
    result = build_site_sync_plan(
        batch={"name": "B1", "confirm_status": "Confirmed"},
        version={"name": "V1"},
        items=[{"name": "I1", "project_collection": "未配置", "total_cost_rmb": "70", "allocated_fee_rmb": "20"}],
        routes=[],
        site_configs=[],
    )

    assert result["ready"] is False
    assert result["request_specs"]["requests"] == []
    assert result["blocking"][0]["code"] == "ITEM_ROUTE_REQUIRED"
