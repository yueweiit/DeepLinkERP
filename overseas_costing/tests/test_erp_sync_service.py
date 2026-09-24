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
                "groups": [{"subsidiary_code": "COMPANY-A", "supplier": "SUP", "purchase_currency": "CNY", "erp_stock_uom": "kg", "total_cost_rmb": "10", "allocated_fee_rmb": "2", "items": [{"stable_line_key": "L1"}]}],
            }
        ],
    }
    first = build_sync_request_specs(batch="B1", cost_result_hash="H1", preview=preview, client_intent_id="I1")["requests"][0]
    same = build_sync_request_specs(batch="B1", cost_result_hash="H1", preview=preview, client_intent_id="I1")["requests"][0]
    changed = build_sync_request_specs(batch="B1", cost_result_hash="H2", preview=preview, client_intent_id="I2")["requests"][0]

    assert classify_existing_request(first, same) == "REUSE"
    assert classify_existing_request(first, changed) == "SUPERSEDE"
    assert first["payload"]["subsidiary_code"] == "COMPANY-A"


def test_same_request_id_with_different_payload_is_never_reused() -> None:
    existing = {"request_id": "R1", "business_key": "BK1", "payload_hash": "OLD"}
    candidate = {"request_id": "R1", "business_key": "BK1", "payload_hash": "NEW"}

    assert classify_existing_request(existing, candidate) == "SUPERSEDE"


def test_company_is_part_of_request_identity_on_one_shared_site() -> None:
    preview = {
        "ready": True,
        "sites": [{
            "site_code": "DEEPLINKERP",
            "groups": [
                {"subsidiary_code": "COMPANY-A", "supplier": "SUP", "purchase_currency": "CNY", "erp_stock_uom": "kg", "total_cost_rmb": "10", "allocated_fee_rmb": "2", "items": [{"stable_line_key": "L1"}]},
                {"subsidiary_code": "COMPANY-B", "supplier": "SUP", "purchase_currency": "CNY", "erp_stock_uom": "kg", "total_cost_rmb": "20", "allocated_fee_rmb": "3", "items": [{"stable_line_key": "L2"}]},
            ],
        }],
    }

    requests = build_sync_request_specs(batch="B1", cost_result_hash="H1", preview=preview)["requests"]

    assert len(requests) == 2
    assert len({row["business_key"] for row in requests}) == 2
    assert {row["payload"]["subsidiary_code"] for row in requests} == {"COMPANY-A", "COMPANY-B"}


def test_safe_groups_still_create_requests_when_other_material_groups_are_blocked() -> None:
    preview = {
        "ready": False,
        "blocking": [{"code": "ITEM_SUPPLIER_REQUIRED", "stable_line_key": "L2"}],
        "sites": [{
            "site_code": "DEEPLINKERP",
            "groups": [
                {
                    "subsidiary_code": "COMPANY-A",
                    "supplier": "SUP",
                    "purchase_currency": "CNY",
                    "erp_stock_uom": "件",
                    "total_cost_rmb": "10",
                    "allocated_fee_rmb": "2",
                    "warnings": [],
                    "items": [{"stable_line_key": "L1"}],
                }
            ],
        }],
    }

    specs = build_sync_request_specs(batch="B1", cost_result_hash="H1", preview=preview)

    assert specs["ready"] is True
    assert specs["complete"] is False
    assert specs["blocking"] == preview["blocking"]
    assert [row["payload"]["items"][0]["stable_line_key"] for row in specs["requests"]] == ["L1"]


def test_legacy_default_supplier_warning_is_carried_into_request_payload() -> None:
    preview = {
        "ready": True,
        "blocking": [],
        "sites": [{
            "site_code": "DEEPLINKERP",
            "groups": [{
                "subsidiary_code": "COMPANY-A",
                "supplier": "",
                "purchase_currency": "CNY",
                "erp_stock_uom": "件",
                "total_cost_rmb": "10",
                "allocated_fee_rmb": "2",
                "warnings": [{"code": "LEGACY_DEFAULT_SUPPLIER", "message": "历史兼容默认供应商"}],
                "items": [{"stable_line_key": "L1"}],
            }],
        }],
    }

    request = build_sync_request_specs(batch="B1", cost_result_hash="H1", preview=preview)["requests"][0]

    assert request["payload"]["warnings"] == preview["sites"][0]["groups"][0]["warnings"]


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
            {"project_collection": "生产", "subsidiary_code": "PROD", "erp_site": "S1", "warehouse": "仓库 - 生产", "enabled": 1},
            {"project_collection": "电商", "subsidiary_code": "ECOM", "erp_site": "S2", "warehouse": "仓库 - 电商", "enabled": 1},
        ],
        site_configs=[{"site_code": "S1", "enabled": 1}, {"site_code": "S2", "enabled": 1}],
    )

    assert result["ready"] is True
    assert len(result["request_specs"]["requests"]) == 2
    assert result["push_state"]["preview"]["preview_total_cost_rmb"] == "120"
    assert result["push_state"]["preview"]["preview_allocated_fee_rmb"] == "30"


def test_site_sync_plan_keeps_valid_supplier_group_executable_when_another_row_is_blocked() -> None:
    common = {
        "project_collection": "项目A",
        "purchase_currency": "CNY",
        "purchase_uom": "件",
        "extra_json": '{"supplier_field_present":true}',
    }
    result = build_site_sync_plan(
        batch={"name": "B1", "confirm_status": "CONFIRMED"},
        version={"name": "V1"},
        items=[
            {**common, "name": "I1", "supplier": "Supplier A", "total_cost_rmb": "10"},
            {**common, "name": "I2", "supplier": "", "total_cost_rmb": "20"},
        ],
        routes=[{"project_collection": "项目A", "subsidiary_code": "COMPANY-A", "warehouse": "仓库 - A", "enabled": 1}],
        site_configs=[],
        active_supplier_names={"Supplier A"},
    )

    assert result["ok"] is False
    assert result["ready"] is True
    assert result["complete"] is False
    assert result["blocking"][0]["code"] == "ITEM_SUPPLIER_REQUIRED"
    assert [row["payload"]["items"][0]["name"] for row in result["request_specs"]["requests"]] == ["I1"]


def test_global_confirmation_gate_still_blocks_all_generated_groups() -> None:
    result = build_site_sync_plan(
        batch={"name": "B1", "confirm_status": "DRAFT"},
        version={"name": "V1"},
        items=[
            {
                "name": "I1",
                "project_collection": "项目A",
                "supplier": "Supplier A",
                "purchase_currency": "CNY",
                "purchase_uom": "件",
                "total_cost_rmb": "10",
                "extra_json": '{"supplier_field_present":true}',
            }
        ],
        routes=[{"project_collection": "项目A", "subsidiary_code": "COMPANY-A", "warehouse": "仓库 - A", "enabled": 1}],
        site_configs=[],
        active_supplier_names={"Supplier A"},
    )

    assert result["request_specs"]["requests"]
    assert result["ready"] is False
    assert any(row["code"] == "CALCULATION_CONFIRMATION_REQUIRED" for row in result["blocking"])


def test_material_change_with_same_totals_changes_cost_result_identity() -> None:
    common = {
        "batch": {"name": "B1", "confirm_status": "Confirmed"},
        "version": {"name": "V1"},
        "routes": [{"project_collection": "项目A", "subsidiary_code": "COMPANY-A", "warehouse": "仓库 - A", "enabled": 1}],
        "site_configs": [],
    }
    first = build_site_sync_plan(
        **common,
        items=[
            {
                "name": "I1",
                "stable_line_key": "L1",
                "material_code": "OLD-SKU",
                "project_collection": "项目A",
                "supplier": "SUP",
                "purchase_currency": "CNY",
                "purchase_uom": "件",
                "source_quantity": 2,
                "total_cost_rmb": "100",
                "allocated_fee_rmb": "10",
            }
        ],
    )
    changed = build_site_sync_plan(
        **common,
        items=[
            {
                "name": "I1",
                "stable_line_key": "L1",
                "material_code": "NEW-SKU",
                "project_collection": "项目A",
                "supplier": "SUP",
                "purchase_currency": "CNY",
                "purchase_uom": "件",
                "source_quantity": 2,
                "total_cost_rmb": "100",
                "allocated_fee_rmb": "10",
            }
        ],
    )

    assert first["cost_result_hash"] != changed["cost_result_hash"]
    assert first["request_specs"]["requests"][0]["request_id"] != changed["request_specs"]["requests"][0]["request_id"]


def test_shared_default_site_needs_no_duplicate_site_configuration() -> None:
    result = build_site_sync_plan(
        batch={"name": "B1", "confirm_status": "Confirmed"},
        version={"name": "V1"},
        items=[{"name": "I1", "project_collection": "YW MOLDES MX模具", "total_cost_rmb": "70", "allocated_fee_rmb": "20", "supplier": "S", "purchase_currency": "CNY", "stock_uom": "kg"}],
        routes=[{"project_collection": "YW MOLDES MX模具", "subsidiary_code": "YW MOLDES MX模具", "erp_site": "", "warehouse": "Stores - MOLD", "enabled": 1}],
        site_configs=[],
    )

    assert result["ready"] is True
    request = result["request_specs"]["requests"][0]
    assert request["site_code"] == "DEEPLINKERP"
    assert request["payload"]["subsidiary_code"] == "YW MOLDES MX模具"
    assert request["payload"]["warehouse"] == "Stores - MOLD"


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
