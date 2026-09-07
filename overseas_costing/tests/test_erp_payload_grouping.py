"""ERP 按站点和单据约束分组的金额守恒与门槛测试。"""

from decimal import Decimal

from overseas_costing.services.erp_routing_service import (
    build_erp_push_state,
    build_site_payload_preview,
)


def _confirmed_result(**overrides) -> dict:
    result = {
        "status": "CONFIRMED",
        "cost_result_hash": "H1",
        "fee_total_rmb": "30",
        "items": [
            {
                "stable_line_key": "P1", "route_status": "RESOLVED", "erp_site_code": "ERP_PROD",
                "subsidiary_code": "PROD_CO", "total_cost_rmb": "70", "allocated_fee_rmb": "20",
                "goods_value": "50", "supplier": "S", "purchase_currency": "CNY", "erp_stock_uom": "kg",
                "effective_shipped_qty": "10", "estimated_fee_keys": ["FREIGHT"],
            },
            {
                "stable_line_key": "E1", "route_status": "RESOLVED", "erp_site_code": "ERP_ECOM",
                "subsidiary_code": "ECOM_CO", "total_cost_rmb": "50", "allocated_fee_rmb": "10",
                "goods_value": "40", "supplier": "S", "purchase_currency": "CNY", "erp_stock_uom": "件",
                "effective_shipped_qty": "5", "estimated_fee_keys": ["FREIGHT"],
            },
        ],
        "site_configs": {
            "ERP_PROD": {"site_code": "ERP_PROD", "capability_status": "VERIFIED", "enabled": 1},
            "ERP_ECOM": {"site_code": "ERP_ECOM", "capability_status": "VERIFIED", "enabled": 1},
        },
        "fee_statuses": [],
    }
    result.update(overrides)
    return result


def test_common_fee_is_not_duplicated_across_sites() -> None:
    preview = build_site_payload_preview(_confirmed_result())

    assert sum(Decimal(site["total_cost_rmb"]) for site in preview["sites"]) == Decimal("120.00")
    assert sum(Decimal(site["allocated_fee_rmb"]) for site in preview["sites"]) == Decimal("30.00")
    assert preview["conservation"]["fee_matches"] is True


def test_payload_groups_by_site_supplier_currency_and_stock_uom() -> None:
    result = _confirmed_result()
    result["items"].append({
        **result["items"][0],
        "stable_line_key": "P2",
        "supplier": "OTHER",
        "total_cost_rmb": "10",
        "allocated_fee_rmb": "2",
        "goods_value": "8",
        "estimated_fee_keys": [],
    })

    preview = build_site_payload_preview(result)
    production = next(site for site in preview["sites"] if site["site_code"] == "ERP_PROD")

    assert production["group_count"] == 2
    assert production["estimated_fee_keys"] == ["FREIGHT"]
    assert {group["supplier"] for group in production["groups"]} == {"S", "OTHER"}


def test_first_push_blocks_entire_batch_if_one_item_has_no_route() -> None:
    result = build_erp_push_state({
        "status": "CONFIRMED",
        "cost_result_hash": "H1",
        "items": [{
            "stable_line_key": "P1", "route_status": "UNRESOLVED", "erp_site_code": "",
            "total_cost_rmb": "70", "erp_stock_uom": "kg",
        }],
    })

    assert result["ready"] is False
    assert result["blocking"][0]["code"] == "ITEM_ROUTE_REQUIRED"


def test_missing_erp_uom_and_unverified_site_are_explicit_blockers() -> None:
    result = _confirmed_result()
    result["items"][0]["erp_stock_uom"] = ""
    result["site_configs"]["ERP_ECOM"]["capability_status"] = "UNVERIFIED"

    state = build_erp_push_state(result)

    assert {row["code"] for row in state["blocking"]} >= {"ERP_UOM_REQUIRED", "ERP_SITE_UNVERIFIED"}


def test_estimated_fee_is_allowed_but_missing_or_unallocated_fee_blocks() -> None:
    estimated = _confirmed_result(fee_statuses=[{
        "fee_key": "FREIGHT", "amount_state": "ESTIMATED", "allocation_state": "ALLOCATED",
        "todos": [{"code": "ACTUAL_AMOUNT_REQUIRED"}, {"code": "EVIDENCE_REQUIRED"}],
    }])
    invalid = _confirmed_result(fee_statuses=[{
        "fee_key": "PORT", "amount_state": "MISSING", "allocation_state": "NOT_ALLOCATED",
        "todos": [{"code": "AMOUNT_REQUIRED"}, {"code": "ALLOCATION_REQUIRED"}],
    }])

    assert build_erp_push_state(estimated)["ready"] is True
    assert {row["code"] for row in build_erp_push_state(invalid)["blocking"]} == {"FEE_AMOUNT_REQUIRED", "FEE_ALLOCATION_REQUIRED"}


def test_rejected_approval_and_invalidated_cost_snapshot_block_every_site() -> None:
    invalid = _confirmed_result(invalid_business=True, invalid_business_reason="审批已撤销")
    stale = _confirmed_result(status="INVALIDATED")

    assert build_erp_push_state(invalid)["blocking"][0]["code"] == "INVALID_BUSINESS_STATE"
    assert build_erp_push_state(stale)["blocking"][0]["code"] == "COST_RESULT_NOT_CONFIRMED"
