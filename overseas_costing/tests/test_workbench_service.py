"""工作台查询、异常分类和分页规则测试。"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from overseas_costing.services import batch_service, workbench_service
from overseas_costing.services.workbench_service import (
    classify_batch,
    filter_batches_for_task,
    normalize_item_query,
    normalize_page,
    operation_error,
    select_item_columns,
)
from overseas_costing.services.batch_service import EXCEL_COLUMNS


def test_operation_error_exposes_stage_scope_reason_and_action() -> None:
    assert operation_error(
        "单批次补充",
        "BATCH-001",
        "文件含其他批次",
        "删除其他批次数据后重新上传",
    ) == {
        "ok": False,
        "error": {
            "stage": "单批次补充",
            "scope": "BATCH-001",
            "reason": "文件含其他批次",
            "next_action": "删除其他批次数据后重新上传",
        },
    }


def test_classify_batch_prioritizes_missing_purchase_data() -> None:
    result = classify_batch(
        {
            "status": "Dirty",
            "writeback_status": "Failed",
            "actual_total_cost_rmb": 0,
            "subsidiary_code": "MX",
            "source_status": {"purchase_approval_sync_state": "missing"},
        },
        {"item_count": 20, "missing_purchase_count": 3, "missing_logistics_count": 2},
    )
    assert result["issue_codes"] == ["purchase", "logistics", "calculation", "erp_failed"]
    assert result["primary_issue"] == "purchase"
    assert result["primary_action"] == "supplement"


def test_classify_batch_marks_calculated_batch_ready_for_cost_review() -> None:
    result = classify_batch(
        {
            "status": "Calculated",
            "writeback_status": "Not Started",
            "actual_total_cost_rmb": 52802.95,
            "subsidiary_code": "MX",
            "source_status": {"purchase_approval_sync_state": "valid"},
        },
        {"item_count": 3, "missing_purchase_count": 0, "missing_logistics_count": 0},
    )
    assert result["issue_codes"] == []
    assert result["primary_issue"] == "ready"
    assert result["primary_action"] == "view"


def test_normalize_page_caps_page_length_and_handles_invalid_values() -> None:
    assert normalize_page("0", "999") == (1, 100)
    assert normalize_page("3", "30") == (3, 30)
    assert normalize_page("bad", "bad") == (1, 30)


def test_erp_task_only_keeps_pending_or_failed_writeback() -> None:
    rows = [
        {"name": "PENDING", "writeback_status": "Pending", "confirm_status": "Pending"},
        {"name": "FAILED", "writeback_status": "Failed", "confirm_status": "Pending"},
        {"name": "READY", "writeback_status": "Not Started", "confirm_status": "Confirmed"},
        {"name": "DONE", "writeback_status": "Success", "confirm_status": "Confirmed"},
    ]
    assert [row["name"] for row in filter_batches_for_task(rows, "erp")] == ["PENDING", "FAILED", "READY"]


def test_logistics_group_keeps_two_fixed_columns() -> None:
    fields = [column["fieldname"] for column in select_item_columns(EXCEL_COLUMNS, "logistics")]
    assert fields[:2] == ["material_code", "product_name"]
    assert "igi_amount" in fields
    assert "unit_price" not in fields


def test_item_query_defaults_to_fifty_rows() -> None:
    assert normalize_item_query(
        page=None,
        page_length=None,
        group=None,
        sort_by=None,
        sort_order=None,
    ) == {
        "page": 1,
        "page_length": 50,
        "group": "basic",
        "sort_by": "row_no",
        "sort_order": "asc",
    }


def test_item_page_queries_only_requested_slice(monkeypatch) -> None:
    calls = []

    class FakeFrappe:
        @staticmethod
        def get_all(doctype, **kwargs):
            calls.append((doctype, kwargs))
            if kwargs["fields"] == [{"COUNT": "name", "as": "total"}]:
                return [{"total": 120}]
            return [{"name": "ITEM-51", "row_no": 51, "material_code": "SKU-51"}]

    monkeypatch.setattr(workbench_service, "frappe", FakeFrappe())
    monkeypatch.setattr(batch_service, "_resolve_batch_name", lambda value: "BATCH-DOC")
    monkeypatch.setattr(batch_service, "_resolve_version_name", lambda batch, version: "VER-1")
    monkeypatch.setattr(batch_service, "_build_item_query_args", lambda *args, **kwargs: (["batch-filter"], ["keyword-filter"]))

    result = workbench_service.get_batch_items_page(
        "BATCH-001", page=2, page_length=50, field_group="basic"
    )

    assert result["total"] == 120
    assert result["page_count"] == 3
    assert result["items"][0]["row_no"] == 51
    assert calls[0][1]["fields"] == [{"COUNT": "name", "as": "total"}]
    assert calls[0][1]["filters"] == ["batch-filter"]
    assert calls[0][1]["or_filters"] == ["keyword-filter"]
    assert calls[1][1]["filters"] == calls[0][1]["filters"]
    assert calls[1][1]["or_filters"] == calls[0][1]["or_filters"]
    assert calls[1][1]["limit_start"] == 50
    assert calls[1][1]["limit_page_length"] == 50


@pytest.mark.parametrize(
    ("frappe_version", "expected_count_fields"),
    [
        ("16.23.0", [{"COUNT": "name", "as": "total"}]),
        ("15.88.1", ["count(name) as total"]),
    ],
)
def test_item_page_selects_count_fields_for_frappe_major_version(
    monkeypatch, frappe_version, expected_count_fields
) -> None:
    calls = []

    class FakeFrappe:
        __version__ = frappe_version

        @staticmethod
        def get_all(doctype, **kwargs):
            calls.append((doctype, kwargs))
            if kwargs["fields"] == expected_count_fields:
                return [{"total": 1}]
            return [{"name": "ITEM-1", "row_no": 1}]

    monkeypatch.setattr(workbench_service, "frappe", FakeFrappe())
    monkeypatch.setattr(batch_service, "_resolve_batch_name", lambda value: "BATCH-DOC")
    monkeypatch.setattr(batch_service, "_resolve_version_name", lambda batch, version: "VER-1")
    monkeypatch.setattr(
        batch_service,
        "_build_item_query_args",
        lambda *args, **kwargs: (["batch-filter"], ["keyword-filter"]),
    )

    result = workbench_service.get_batch_items_page("BATCH-001")

    assert result["ok"] is True
    assert result["total"] == 1
    assert calls[0][1]["fields"] == expected_count_fields
    assert calls[0][1]["filters"] == calls[1][1]["filters"]
    assert calls[0][1]["or_filters"] == calls[1][1]["or_filters"]


def test_item_page_returns_empty_result_without_changing_response_shape(monkeypatch) -> None:
    calls = []

    class FakeFrappe:
        @staticmethod
        def get_all(doctype, **kwargs):
            calls.append((doctype, kwargs))
            if kwargs["fields"] == [{"COUNT": "name", "as": "total"}]:
                return []
            return []

    monkeypatch.setattr(workbench_service, "frappe", FakeFrappe())
    monkeypatch.setattr(batch_service, "_resolve_batch_name", lambda value: "BATCH-DOC")
    monkeypatch.setattr(batch_service, "_resolve_version_name", lambda batch, version: "VER-1")
    monkeypatch.setattr(batch_service, "_build_item_query_args", lambda *args, **kwargs: (["batch-filter"], []))

    result = workbench_service.get_batch_items_page(
        "BATCH-001", keyword="missing", page=1, page_length=50, field_group="basic"
    )

    assert result["ok"] is True
    assert result["items"] == []
    assert result["total"] == 0
    assert result["page"] == 1
    assert result["page_length"] == 50
    assert result["page_count"] == 0
    assert result["field_group"] == "basic"
    assert calls[0][1]["filters"] == calls[1][1]["filters"]
    assert calls[0][1]["or_filters"] == calls[1][1]["or_filters"]


def test_item_page_calculates_last_page_for_partial_page(monkeypatch) -> None:
    class FakeFrappe:
        @staticmethod
        def get_all(doctype, **kwargs):
            if kwargs["fields"] == [{"COUNT": "name", "as": "total"}]:
                return [{"total": 101}]
            return [{"name": "ITEM-101", "row_no": 101}]

    monkeypatch.setattr(workbench_service, "frappe", FakeFrappe())
    monkeypatch.setattr(batch_service, "_resolve_batch_name", lambda value: "BATCH-DOC")
    monkeypatch.setattr(batch_service, "_resolve_version_name", lambda batch, version: "VER-1")
    monkeypatch.setattr(batch_service, "_build_item_query_args", lambda *args, **kwargs: (["batch-filter"], ["keyword-filter"]))

    result = workbench_service.get_batch_items_page(
        "BATCH-001", keyword="SKU", page=3, page_length=50, field_group="all"
    )

    assert result["total"] == 101
    assert result["page"] == 3
    assert result["page_count"] == 3
    assert result["items"] == [{"name": "ITEM-101", "row_no": 101}]


def test_locate_batch_item_uses_unfiltered_server_order(monkeypatch) -> None:
    calls = []

    class FakeFrappe:
        @staticmethod
        def get_all(doctype, **kwargs):
            calls.append((doctype, kwargs))
            return [
                {"name": f"ITEM-{index:03d}", "row_no": index, "material_code": f"SKU-{index:03d}"}
                for index in range(1, 121)
            ]

    monkeypatch.setattr(workbench_service, "frappe", FakeFrappe())
    monkeypatch.setattr(batch_service, "_resolve_batch_name", lambda value: "BATCH-DOC")
    monkeypatch.setattr(batch_service, "_resolve_version_name", lambda batch, version: "VER-1")

    result = workbench_service.locate_batch_item(
        batch_name="BATCH-1",
        item_name="ITEM-076",
        page_length=50,
    )

    assert result["ok"] is True
    assert result["page"] == 2
    assert result["item"]["material_code"] == "SKU-076"
    assert calls[0][1]["limit_page_length"] == 0


def test_result_preview_item_keeps_other_cost_out_of_clearance() -> None:
    item = {
        "name": "ITEM-1",
        "row_no": 1,
        "material_code": "SKU-1",
        "product_name": "Industrial pump",
        "spec_model": "A-200",
        "unit_price": 8,
        "purchase_currency": "RMB",
        "quantity": 2,
        "goods_value": 16,
        "freight_alloc_rmb": 6,
        "import_tax_total": 3,
        "total_cost_rmb": 29,
        "total_unit_rmb": 14.5,
        "derived_json": json.dumps(
            {
                "fx_rmb_to_mxn": 3,
                "direct_customs": {"amount_rmb": 4, "tax_mxn": 3, "service_mxn": 9},
                "allocated_rules": [
                    {
                        "rule_code": "china_to_mexico_freight_rmb",
                        "expense_category": "国际运费",
                        "allocated_rmb": 6,
                    },
                    {
                        "rule_code": "china_misc_rmb",
                        "expense_category": "中国段杂费",
                        "remark": "来自清关资料，但业务口径仍是普通杂费",
                        "allocated_rmb": 2,
                    },
                    {
                        "rule_code": "forwarder_misc_rmb",
                        "expense_category": "货代杂费",
                        "allocated_rmb": 1,
                    },
                ],
            },
            ensure_ascii=False,
        ),
    }

    result = workbench_service.build_batch_result_preview_item(item, calculated=True)

    assert result["freight_alloc_rmb"] == 6
    assert result["tax_alloc_rmb"] == 1
    assert result["clearance_alloc_rmb"] == 3
    assert result["unlisted_other_cost_rmb"] == 3
    assert result["total_unit_rmb"] == 14.5


def test_result_preview_groups_goods_value_by_currency_and_weights_unit_cost() -> None:
    batch = {"name": "BATCH-DOC", "batch_no": "BATCH-001", "waybill_no": "WB-001"}
    version = {"name": "VER-1", "calculated_at": "2026-09-03 10:00:00"}
    items = [
        {
            "name": "ITEM-1",
            "row_no": 1,
            "material_code": "SKU-1",
            "purchase_currency": "RMB",
            "quantity": 2,
            "goods_value": 20,
            "freight_alloc_rmb": 2,
            "total_cost_rmb": 30,
            "total_unit_rmb": 15,
            "derived_json": json.dumps({"fx_rmb_to_mxn": 3, "direct_customs": {"amount_rmb": 8}}),
        },
        {
            "name": "ITEM-2",
            "row_no": 2,
            "material_code": "SKU-2",
            "purchase_currency": "USD",
            "quantity": 3,
            "goods_value": 12,
            "freight_alloc_rmb": 3,
            "total_cost_rmb": 45,
            "total_unit_rmb": 15,
            "derived_json": json.dumps({"fx_rmb_to_mxn": 3, "direct_customs": {"amount_rmb": 30}}),
        },
    ]

    result = workbench_service.build_batch_result_preview_payload(
        batch=batch,
        version=version,
        items=items,
        page=1,
        page_length=20,
    )

    assert result["summary"]["purchase_totals"] == [
        {"currency": "RMB", "amount": 20},
        {"currency": "USD", "amount": 12},
    ]
    assert result["summary"]["total_quantity"] == 5
    assert result["summary"]["weighted_total_unit_rmb"] == 15
    assert result["total"] == 2
    assert result["page_count"] == 1


def test_result_preview_does_not_guess_split_for_customs_total() -> None:
    item = {
        "name": "ITEM-1",
        "row_no": 1,
        "material_code": "SKU-1",
        "purchase_currency": "RMB",
        "quantity": 1,
        "goods_value": 100,
        "freight_alloc_rmb": 0,
        "mexico_customs_rmb": 20,
        "total_cost_rmb": 120,
        "total_unit_rmb": 120,
        "derived_json": json.dumps(
            {
                "fx_rmb_to_mxn": 3,
                "direct_customs": {
                    "source_type": "customs_total",
                    "amount_rmb": 20,
                    "tax_mxn": 0,
                    "service_mxn": 0,
                },
            }
        ),
    }

    result = workbench_service.build_batch_result_preview_item(item, calculated=True)

    assert result["tax_alloc_rmb"] is None
    assert result["clearance_alloc_rmb"] is None
    assert result["unlisted_other_cost_rmb"] == 20


def test_result_preview_returns_null_calculation_values_before_recalculation() -> None:
    result = workbench_service.build_batch_result_preview_payload(
        batch={"name": "BATCH-DOC", "batch_no": "BATCH-001", "waybill_no": ""},
        version={"name": "VER-1", "calculated_at": None},
        items=[
            {
                "name": "ITEM-1",
                "row_no": 1,
                "material_code": "SKU-1",
                "purchase_currency": "RMB",
                "quantity": 2,
                "goods_value": 20,
                "freight_alloc_rmb": 0,
                "total_cost_rmb": 0,
                "total_unit_rmb": 0,
            }
        ],
        page=1,
        page_length=20,
    )

    assert result["summary"]["calculation_status"] == "pending"
    assert result["summary"]["total_freight_rmb"] is None
    assert result["summary"]["total_tax_rmb"] is None
    assert result["summary"]["total_clearance_rmb"] is None
    assert result["summary"]["weighted_total_unit_rmb"] is None
    assert result["items"][0]["freight_alloc_rmb"] is None
    assert result["items"][0]["total_unit_rmb"] is None


def test_result_preview_keeps_missing_calculated_fields_distinct_from_zero() -> None:
    result = workbench_service.build_batch_result_preview_payload(
        batch={"name": "BATCH-DOC", "batch_no": "BATCH-PARTIAL"},
        version={"name": "VER-1", "calculated_at": "2026-09-03 10:00:00"},
        items=[
            {
                "name": "ITEM-1",
                "row_no": 1,
                "material_code": "SKU-1",
                "purchase_currency": "RMB",
                "quantity": 1,
                "goods_value": 100,
                "freight_alloc_rmb": None,
                "total_cost_rmb": None,
                "total_unit_rmb": None,
                "derived_json": json.dumps(
                    {
                        "fx_rmb_to_mxn": 3,
                        "direct_customs": {
                            "source_type": "customs_components",
                            "amount_rmb": 0,
                            "tax_mxn": 0,
                            "service_mxn": 0,
                        },
                    }
                ),
            }
        ],
        page=1,
        page_length=20,
    )

    assert result["summary"]["calculation_status"] == "partial"
    assert result["summary"]["total_freight_rmb"] is None
    assert result["summary"]["total_tax_rmb"] == 0
    assert result["summary"]["total_clearance_rmb"] == 0
    assert result["summary"]["weighted_total_unit_rmb"] is None
    assert result["items"][0]["freight_alloc_rmb"] is None
    assert result["items"][0]["tax_alloc_rmb"] == 0
    assert result["items"][0]["clearance_alloc_rmb"] == 0
    assert result["items"][0]["total_unit_rmb"] is None


def test_result_preview_paginates_184_items_by_twenty() -> None:
    items = [
        {
            "name": f"ITEM-{index:03d}",
            "row_no": index,
            "material_code": f"SKU-{index:03d}",
            "purchase_currency": "RMB",
            "quantity": 1,
            "goods_value": 1,
            "freight_alloc_rmb": 0,
            "total_cost_rmb": 1,
            "total_unit_rmb": 1,
            "derived_json": "{}",
        }
        for index in range(1, 185)
    ]

    result = workbench_service.build_batch_result_preview_payload(
        batch={"name": "BATCH-DOC", "batch_no": "BATCH-184", "waybill_no": "WB-184"},
        version={"name": "VER-1", "calculated_at": "2026-09-03 10:00:00"},
        items=items,
        page=10,
        page_length=20,
    )

    assert result["total"] == 184
    assert result["page"] == 10
    assert result["page_length"] == 20
    assert result["page_count"] == 10
    assert [item["material_code"] for item in result["items"]] == [
        "SKU-181",
        "SKU-182",
        "SKU-183",
        "SKU-184",
    ]


def test_result_preview_queries_only_current_version_and_lightweight_fields(monkeypatch) -> None:
    calls = []

    class FakeFrappe:
        @staticmethod
        def get_all(doctype, **kwargs):
            calls.append((doctype, kwargs))
            if doctype == "Overseas Cost Batch":
                return [{"name": "BATCH-DOC", "batch_no": "BATCH-001", "waybill_no": "WB-001"}]
            if doctype == "Overseas Cost Version":
                return [{"name": "VER-1", "calculated_at": "2026-09-03 10:00:00"}]
            return [
                {
                    "name": f"ITEM-{index:02d}",
                    "row_no": index,
                    "material_code": f"SKU-{index:02d}",
                    "purchase_currency": "RMB",
                    "quantity": 1,
                    "goods_value": 1,
                    "freight_alloc_rmb": 0,
                    "total_cost_rmb": 1,
                    "total_unit_rmb": 1,
                    "derived_json": "{}",
                }
                for index in range(1, 26)
            ]

    monkeypatch.setattr(workbench_service, "frappe", FakeFrappe())
    monkeypatch.setattr(batch_service, "_resolve_batch_name", lambda value: "BATCH-DOC")
    monkeypatch.setattr(batch_service, "_resolve_version_name", lambda batch, version: "VER-1")

    result = workbench_service.get_batch_result_preview("BATCH-001", page=2, page_length=20)

    assert result["version_name"] == "VER-1"
    assert result["page"] == 2
    assert len(result["items"]) == 5
    assert set(result["items"][0]) == {
        "material_code",
        "product_name",
        "spec_model",
        "unit_price",
        "purchase_currency",
        "quantity",
        "freight_alloc_rmb",
        "tax_alloc_rmb",
        "clearance_alloc_rmb",
        "total_unit_rmb",
    }
    item_call = next(call for call in calls if call[0] == "Overseas Cost Item")
    assert item_call[1]["filters"] == {"batch": "BATCH-DOC", "version": "VER-1"}
    assert item_call[1]["fields"] == workbench_service.RESULT_PREVIEW_ITEM_FIELDS
    assert item_call[1]["limit_page_length"] == 0
    assert "raw_excel_json" not in item_call[1]["fields"]


def test_result_preview_api_checks_batch_permission_before_loading() -> None:
    source = Path(workbench_service.__file__).parents[1] / "api" / "workbench.py"
    api_source = source.read_text(encoding="utf-8")
    module = ast.parse(api_source)
    function = next(
        node for node in module.body if isinstance(node, ast.FunctionDef) and node.name == "get_batch_result_preview"
    )
    body = ast.unparse(function)

    permission_check = "batch_name = require_batch_permission(batch_name, 'read')"
    service_call = "return workbench_service.get_batch_result_preview("
    assert permission_check in body
    assert service_call in body
    assert body.index(permission_check) < body.index(service_call)
