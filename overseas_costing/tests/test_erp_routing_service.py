from decimal import Decimal

from overseas_costing.services.erp_routing_service import (
    build_erp_push_state,
    build_site_payload_preview,
    list_unambiguous_project_routes,
    preview_bulk_route,
    project_candidate_names,
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


def test_route_without_explicit_site_uses_shared_deeplinkerp_connection() -> None:
    result = resolve_item_routes(
        [{"stable_line_key": "P1", "project_collection": "YW MOLDES MX模具"}],
        [{"project_collection": "YW MOLDES MX模具", "subsidiary_code": "YW MOLDES MX模具", "erp_site": "", "enabled": 1}],
    )

    assert result["ready"] is True
    assert result["by_item"]["P1"]["site_code"] == "DEEPLINKERP"


def test_project_candidate_names_reuses_dingtalk_extra_json_structure() -> None:
    item = {
        "extra_json": '{"project_candidates":[{"id":"D1","name":"LatinGo拉丁购"},'
        '{"department_id":"D2","name":"YW MOLDES MX模具"},'
        '{"id":"D3","name":"LatinGo拉丁购"}]}'
    }

    assert project_candidate_names(item) == ["LatinGo拉丁购", "YW MOLDES MX模具"]


def test_unambiguous_route_options_preserve_ai_metadata() -> None:
    result = list_unambiguous_project_routes(
        [
            {
                "project_collection": "LatinGo拉丁购",
                "subsidiary_code": "LATIN COMPANY",
                "erp_site": "",
                "enabled": 1,
                "revision": 7,
                "ai_match_hint": "宠物用品",
            }
        ]
    )

    assert result["options"] == [
        {
            "project_collection": "LatinGo拉丁购",
            "subsidiary_code": "LATIN COMPANY",
            "site_code": "DEEPLINKERP",
            "revision": 7,
            "ai_match_hint": "宠物用品",
        }
    ]


def test_unambiguous_route_options_merge_aliases_and_use_highest_revision_display() -> None:
    result = list_unambiguous_project_routes(
        [
            {
                "project_collection": "YUEWEI MX核心制造",
                "subsidiary_code": "MX COMPANY",
                "enabled": 1,
                "revision": 2,
                "ai_match_hint": "旧提示",
            },
            {
                "project_collection": "YW Fabricación MX 核心制造",
                "subsidiary_code": "MX COMPANY",
                "enabled": 1,
                "revision": 5,
                "ai_match_hint": "新提示",
            },
        ]
    )

    assert result == {
        "options": [
            {
                "project_collection": "YW Fabricación MX 核心制造",
                "subsidiary_code": "MX COMPANY",
                "site_code": "DEEPLINKERP",
                "revision": 5,
                "ai_match_hint": "新提示",
            }
        ],
        "conflicts": [],
    }


def test_unambiguous_route_options_report_conflict_across_aliases() -> None:
    result = list_unambiguous_project_routes(
        [
            {
                "project_collection": "YUEWEI MX核心制造",
                "subsidiary_code": "LEGACY COMPANY",
                "enabled": 1,
                "revision": 2,
            },
            {
                "project_collection": "YW Fabricación MX 核心制造",
                "subsidiary_code": "CURRENT COMPANY",
                "enabled": 1,
                "revision": 5,
            },
        ]
    )

    assert result["options"] == []
    assert result["conflicts"] == ["YW Fabricación MX 核心制造"]


def test_historical_project_names_resolve_to_current_company_routes_without_rewriting_rows() -> None:
    result = resolve_item_routes(
        [
            {"stable_line_key": "GZ", "project_collection": "Guangzhou Lingxiang广州凌翔"},
            {"stable_line_key": "LATIN", "project_collection": "LatínGo拉丁购"},
            {"stable_line_key": "MX", "project_collection": "YUEWEI MX核心制造"},
        ],
        [
            {"project_collection": "Guangzhou Lingxiang 广州凌翔", "subsidiary_code": "GZ COMPANY", "enabled": 1},
            {"project_collection": "LatinGo拉丁购", "subsidiary_code": "LATIN COMPANY", "enabled": 1},
            {"project_collection": "YW Fabricación MX 核心制造", "subsidiary_code": "MX COMPANY", "enabled": 1},
        ],
    )

    assert result["ready"] is True
    assert {key: row["subsidiary_code"] for key, row in result["by_item"].items()} == {
        "GZ": "GZ COMPANY",
        "LATIN": "LATIN COMPANY",
        "MX": "MX COMPANY",
    }
    assert result["by_item"]["MX"]["project_collection"] == "YUEWEI MX核心制造"


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
                {"stable_line_key": "P1", "route_status": "RESOLVED", "erp_site_code": "ERP_PROD", "subsidiary_code": "COMPANY-P", "total_cost_rmb": "70", "allocated_fee_rmb": "20", "supplier": "S", "purchase_currency": "CNY", "erp_stock_uom": "kg"},
                {"stable_line_key": "E1", "route_status": "RESOLVED", "erp_site_code": "ERP_ECOM", "subsidiary_code": "COMPANY-E", "total_cost_rmb": "50", "allocated_fee_rmb": "10", "supplier": "S", "purchase_currency": "CNY", "erp_stock_uom": "件"},
            ],
        }
    )

    assert sum(Decimal(site["total_cost_rmb"]) for site in preview["sites"]) == Decimal("120")
    assert sum(Decimal(site["allocated_fee_rmb"]) for site in preview["sites"]) == Decimal("30")


def test_same_site_different_companies_never_share_one_purchase_group() -> None:
    preview = build_site_payload_preview(
        {
            "status": "CONFIRMED",
            "fee_total_rmb": "30",
            "total_cost_rmb": "120",
            "items": [
                {"stable_line_key": "P1", "route_status": "RESOLVED", "erp_site_code": "DEEPLINKERP", "subsidiary_code": "YW MOLDES MX模具", "total_cost_rmb": "70", "allocated_fee_rmb": "20", "supplier": "S", "purchase_currency": "CNY", "erp_stock_uom": "kg"},
                {"stable_line_key": "E1", "route_status": "RESOLVED", "erp_site_code": "DEEPLINKERP", "subsidiary_code": "AmigoMart", "total_cost_rmb": "50", "allocated_fee_rmb": "10", "supplier": "S", "purchase_currency": "CNY", "erp_stock_uom": "kg"},
            ],
        }
    )

    assert len(preview["sites"]) == 1
    assert {group["subsidiary_code"] for group in preview["sites"][0]["groups"]} == {"YW MOLDES MX模具", "AmigoMart"}


def test_real_material_purchase_uom_splits_purchase_groups() -> None:
    preview = build_site_payload_preview(
        {
            "status": "CONFIRMED",
            "total_cost_rmb": "30",
            "items": [
                {
                    "stable_line_key": "L1",
                    "route_status": "RESOLVED",
                    "erp_site_code": "DEEPLINKERP",
                    "subsidiary_code": "Company A",
                    "supplier": "SUP",
                    "purchase_currency": "CNY",
                    "purchase_uom": "kg",
                    "total_cost_rmb": "10",
                },
                {
                    "stable_line_key": "L2",
                    "route_status": "RESOLVED",
                    "erp_site_code": "DEEPLINKERP",
                    "subsidiary_code": "Company A",
                    "supplier": "SUP",
                    "purchase_currency": "CNY",
                    "purchase_uom": "件",
                    "total_cost_rmb": "20",
                },
            ],
        }
    )

    assert {group["erp_stock_uom"] for group in preview["sites"][0]["groups"]} == {"kg", "件"}


def test_new_template_missing_supplier_blocks_only_that_material_group() -> None:
    preview = build_site_payload_preview(
        {
            "items": [
                {
                    "stable_line_key": "VALID",
                    "route_status": "RESOLVED",
                    "erp_site_code": "DEEPLINKERP",
                    "subsidiary_code": "Company A",
                    "supplier": "Supplier A",
                    "purchase_currency": "CNY",
                    "purchase_uom": "件",
                    "total_cost_rmb": "10",
                    "extra_json": '{"supplier_field_present":true,"supplier_match_status":"EXACT"}',
                },
                {
                    "stable_line_key": "MISSING",
                    "route_status": "RESOLVED",
                    "erp_site_code": "DEEPLINKERP",
                    "subsidiary_code": "Company A",
                    "supplier": "",
                    "purchase_currency": "CNY",
                    "purchase_uom": "件",
                    "total_cost_rmb": "20",
                    "extra_json": '{"supplier_field_present":true,"supplier_raw_value":"未匹配供应商","supplier_match_status":"UNMATCHED"}',
                },
            ]
        },
        active_supplier_names={"Supplier A"},
    )

    assert preview["ready"] is False
    assert preview["blocking"] == [
        {
            "code": "ITEM_SUPPLIER_REQUIRED",
            "stable_line_key": "MISSING",
            "raw_value": "未匹配供应商",
            "match_status": "UNMATCHED",
            "message": "物料行 MISSING：供应商尚未匹配并确认。",
        }
    ]
    assert [row["stable_line_key"] for row in preview["sites"][0]["groups"][0]["items"]] == ["VALID"]


def test_new_template_inactive_supplier_is_not_sent_to_erp() -> None:
    preview = build_site_payload_preview(
        {
            "items": [
                {
                    "stable_line_key": "INACTIVE",
                    "route_status": "RESOLVED",
                    "erp_site_code": "DEEPLINKERP",
                    "subsidiary_code": "Company A",
                    "supplier": "Disabled Supplier",
                    "purchase_currency": "CNY",
                    "purchase_uom": "件",
                    "extra_json": '{"supplier_field_present":true,"supplier_match_status":"EXACT"}',
                }
            ]
        },
        active_supplier_names={"Supplier A"},
    )

    assert preview["sites"] == []
    assert preview["blocking"][0]["code"] == "ITEM_SUPPLIER_INACTIVE"


def test_legacy_item_without_supplier_column_keeps_default_supplier_fallback_warning() -> None:
    preview = build_site_payload_preview(
        {
            "items": [
                {
                    "stable_line_key": "LEGACY",
                    "route_status": "RESOLVED",
                    "erp_site_code": "DEEPLINKERP",
                    "subsidiary_code": "Company A",
                    "supplier": "",
                    "purchase_currency": "CNY",
                    "purchase_uom": "件",
                    "extra_json": "{}",
                }
            ]
        },
        active_supplier_names={"Supplier A"},
    )

    group = preview["sites"][0]["groups"][0]
    assert preview["ready"] is True
    assert group["supplier"] == ""
    assert group["warnings"] == [
        {"code": "LEGACY_DEFAULT_SUPPLIER", "message": "历史兼容默认供应商"}
    ]


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
