"""ERP 项目路由和整柜快捷归属纯规则测试。"""

from overseas_costing.services.erp_routing_service import (
    preview_bulk_route,
    resolve_item_routes,
    resolve_subsidiary_scope,
)


def test_mixed_container_routes_distinct_materials() -> None:
    result = resolve_item_routes(
        items=[
            {"stable_line_key": "P1", "project_collection": "生产项目"},
            {"stable_line_key": "E1", "project_collection": "电商项目"},
        ],
        routes=[
            {"project_collection": "生产项目", "subsidiary_code": "PROD_CO", "site_code": "ERP_PROD", "enabled": 1, "revision": "R1"},
            {"project_collection": "电商项目", "subsidiary_code": "ECOM_CO", "site_code": "ERP_ECOM", "enabled": 1, "revision": "R2"},
        ],
    )

    assert result["ready"] is True
    assert result["by_item"]["P1"]["site_code"] == "ERP_PROD"
    assert result["by_item"]["E1"]["site_code"] == "ERP_ECOM"


def test_ambiguous_project_mapping_never_chooses_first_route() -> None:
    result = resolve_item_routes(
        [{"stable_line_key": "P1", "project_collection": "项目A"}],
        [
            {"project_collection": "项目A", "subsidiary_code": "CO1", "site_code": "S1", "enabled": 1},
            {"project_collection": " 项目A ", "subsidiary_code": "CO2", "site_code": "S2", "enabled": 1},
        ],
    )

    assert result["ready"] is False
    assert result["by_item"]["P1"]["status"] == "CONFLICT"
    assert result["by_item"]["P1"]["code"] == "MULTIPLE_ACTIVE_ROUTES"


def test_missing_project_and_missing_mapping_are_distinct() -> None:
    result = resolve_item_routes(
        [
            {"stable_line_key": "P1", "project_collection": ""},
            {"stable_line_key": "P2", "project_collection": "未配置项目"},
        ],
        [],
    )

    assert result["by_item"]["P1"]["code"] == "PROJECT_REQUIRED"
    assert result["by_item"]["P2"]["code"] == "ROUTE_NOT_CONFIGURED"


def test_explicit_override_wins_without_changing_project_fact() -> None:
    item = {
        "stable_line_key": "P1",
        "project_collection": "原始项目",
        "route_status": "OVERRIDDEN",
        "subsidiary_code": "PROD_CO",
        "erp_site_code": "ERP_PROD",
        "route_revision": "OVERRIDE-1",
    }

    result = resolve_item_routes([item], [])

    assert result["by_item"]["P1"]["status"] == "OVERRIDDEN"
    assert result["by_item"]["P1"]["project_collection"] == "原始项目"
    assert result["by_item"]["P1"]["site_code"] == "ERP_PROD"


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
    assert preview["updates"]["E1"]["route_status"] == "OVERRIDDEN"


def test_subsidiary_fee_scope_freezes_explicit_item_keys_and_route_revision() -> None:
    result = resolve_subsidiary_scope(
        subsidiary_code="PROD_CO",
        item_routes={
            "P2": {"status": "RESOLVED", "subsidiary_code": "PROD_CO", "route_revision": "R2"},
            "P1": {"status": "OVERRIDDEN", "subsidiary_code": "PROD_CO", "route_revision": "R1"},
            "E1": {"status": "RESOLVED", "subsidiary_code": "ECOM_CO", "route_revision": "R3"},
            "X1": {"status": "UNRESOLVED", "subsidiary_code": "", "route_revision": ""},
        },
    )

    assert result["scope_type"] == "ITEMS"
    assert result["scope_item_keys"] == ["P1", "P2"]
    assert result["scope_revision"]
