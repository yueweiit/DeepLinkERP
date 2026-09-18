from decimal import Decimal

from overseas_costing.services.erp_routing_service import (
    build_erp_push_state,
    build_site_payload_preview,
    preview_bulk_route,
    resolve_item_routes,
)


def test_mixed_container_routes_distinct_materials() -> None:
    result = resolve_item_routes(
        items=[
            {"stable_line_key": "P1", "project_collection": "生产项目"},
            {"stable_line_key": "E1", "project_collection": "电商项目"},
        ],
        routes=[
            {"project_collection": "生产项目", "subsidiary_code": "PROD_CO", "site_code": "ERP_PROD", "enabled": 1},
            {"project_collection": "电商项目", "subsidiary_code": "ECOM_CO", "site_code": "ERP_ECOM", "enabled": 1},
        ],
    )

    assert result["ok"] is True
    assert result["by_item"]["P1"]["site_code"] == "ERP_PROD"
    assert result["by_item"]["E1"]["site_code"] == "ERP_ECOM"


def test_ambiguous_project_mapping_never_chooses_first_route() -> None:
    result = resolve_item_routes(
        [{"stable_line_key": "P1", "project_collection": "项目A"}],
        [
            {"project_collection": "项目A", "subsidiary_code": "CO1", "site_code": "S1", "enabled": 1},
            {"project_collection": "项目A", "subsidiary_code": "CO2", "site_code": "S2", "enabled": 1},
        ],
    )

    assert result["ok"] is False
    assert result["by_item"]["P1"]["status"] == "CONFLICT"


def test_bulk_assignment_requires_preview_when_existing_routes_differ() -> None:
    preview = preview_bulk_route(
        [
            {"stable_line_key": "P1", "erp_site_code": "S1", "route_status": "RESOLVED"},
            {"stable_line_key": "E1", "erp_site_code": "S2", "route_status": "RESOLVED"},
        ],
        target_site="S1",
    )

    assert preview["requires_confirmation"] is True
    assert preview["changed_item_keys"] == ["E1"]


def test_common_fee_is_not_duplicated_across_sites() -> None:
    preview = build_site_payload_preview(
        result={
            "status": "CONFIRMED",
            "cost_result_hash": "H1",
            "fee_total_rmb": "30",
            "total_cost_rmb": "120",
            "items": [
                {"stable_line_key": "P1", "route_status": "RESOLVED", "erp_site_code": "ERP_PROD", "total_cost_rmb": "70", "allocated_fee_rmb": "20", "supplier": "S", "purchase_currency": "CNY", "erp_stock_uom": "kg"},
                {"stable_line_key": "E1", "route_status": "RESOLVED", "erp_site_code": "ERP_ECOM", "total_cost_rmb": "50", "allocated_fee_rmb": "10", "supplier": "S", "purchase_currency": "CNY", "erp_stock_uom": "件"},
            ],
        }
    )

    assert sum(Decimal(site["total_cost_rmb"]) for site in preview["sites"]) == Decimal("120")
    assert sum(Decimal(site["allocated_fee_rmb"]) for site in preview["sites"]) == Decimal("30")


def test_first_push_blocks_entire_batch_if_one_item_has_no_route() -> None:
    result = build_erp_push_state(
        {
            "status": "CONFIRMED",
            "total_cost_rmb": "70",
            "items": [{"stable_line_key": "P1", "route_status": "UNRESOLVED", "erp_site_code": "", "total_cost_rmb": "70", "erp_stock_uom": "kg"}],
        }
    )

    assert result["ready"] is False
    assert result["blocking"][0]["code"] == "ITEM_ROUTE_REQUIRED"
