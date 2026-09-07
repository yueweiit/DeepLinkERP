"""中文用途：装箱计划 Sheet 日期、摘要、推荐评分和稳定排序测试。"""

from __future__ import annotations

from datetime import date

import pytest

from overseas_costing.services.packing_sheet_recommendation import (
    parse_sheet_business_date,
    recommend_packing_sheets,
    sort_packing_sheets,
    summarize_packing_preview,
)


@pytest.mark.parametrize(
    ("sheet_name", "workbook_year", "expected"),
    [
        ("指环扣-packing list2026.9.05", 2026, date(2026, 9, 5)),
        ("2026-08-28 海运", 2026, date(2026, 8, 28)),
        ("8.15日货柜", 2026, date(2026, 8, 15)),
        ("5月9日模具", "2026", date(2026, 5, 9)),
        ("劳保鞋", 2026, None),
        ("13.40 无效日期", 2026, None),
    ],
)
def test_parse_sheet_business_date(sheet_name, workbook_year, expected) -> None:
    assert parse_sheet_business_date(sheet_name, workbook_year) == expected


def test_sort_packing_sheets_pins_recommendation_then_uses_latest_business_date() -> None:
    sheets = [
        {"source_id": "WB:unknown-b", "source_label": "未知 B", "business_date": None},
        {"source_id": "WB:aug", "source_label": "8.28 海运", "business_date": "2026-08-28"},
        {"source_id": "WB:recommended", "source_label": "8.15 推荐", "business_date": "2026-08-15", "is_recommended": True},
        {"source_id": "WB:sep", "source_label": "9.05 油漆", "business_date": "2026-09-05"},
        {"source_id": "WB:unknown-a", "source_label": "未知 A", "business_date": None},
    ]

    result = sort_packing_sheets(sheets)

    assert [item["source_id"] for item in result] == [
        "WB:recommended",
        "WB:sep",
        "WB:aug",
        "WB:unknown-a",
        "WB:unknown-b",
    ]
    assert sheets[0].get("business_date") is None


def test_summarize_packing_preview_deduplicates_material_codes_and_references() -> None:
    preview = {
        "material_rows": [
            {"material_code": " fl000427 ", "raw_fields": {"对应钉钉采购订单号": {"raw_value": "202607150204000137997"}}},
            {"material_code": "FL000427", "raw_fields": {}},
            {"material_code": "CW000224", "raw_fields": {"采购审批号": {"display_value": "PROC-88"}}},
        ]
    }

    assert summarize_packing_preview(preview) == {
        "item_codes": ["CW000224", "FL000427"],
        "references": ["202607150204000137997", "PROC-88"],
    }


def test_recommendation_prefers_full_sku_match_but_exposes_extra_material() -> None:
    sheets = [
        {
            "source_id": "WB:st-ring",
            "source_label": "指环扣-packing list2026.9.05",
            "workbook_year": 2026,
            "snapshot_updated_at": "2026-09-07T10:00:00+08:00",
        },
        {
            "source_id": "WB:st-paint",
            "source_label": "油漆-packing list2026.9.05",
            "workbook_year": 2026,
            "snapshot_updated_at": "2026-09-07T10:00:00+08:00",
        },
    ]
    batch = {
        "item_codes": ["FL000427", "FL000428", "FL000429", "FL000430", "FL003377"],
        "references": ["202609032107000062462"],
        "keywords": ["指环扣"],
        "reference_date": "2026-09-03",
    }
    summaries = {
        "WB:st-ring": {
            "item_codes": ["FL000427", "FL000428", "FL000429", "FL000430", "FL003377", "CW000224"],
            "references": [],
        },
        "WB:st-paint": {"item_codes": ["PC001", "PC002"], "references": []},
    }

    result = recommend_packing_sheets(sheets, batch_context=batch, snapshot_summaries=summaries)

    recommended = result[0]
    assert recommended["source_id"] == "WB:st-ring"
    assert recommended["is_recommended"] is True
    assert recommended["auto_select_recommended"] is True
    assert recommended["recommendation_confidence"] == "high"
    assert recommended["matched_item_codes"] == ["FL000427", "FL000428", "FL000429", "FL000430", "FL003377"]
    assert recommended["missing_item_codes"] == []
    assert recommended["extra_item_codes"] == ["CW000224"]
    assert "匹配当前批次 5/5 个 SKU" in recommended["recommendation_reasons"]
    assert "含 1 个批次外物料，预览时确认" in recommended["recommendation_reasons"]
    assert sum(1 for item in result if item["is_recommended"]) == 1


def test_date_only_candidate_is_low_confidence_and_unknown_candidate_is_not_forced() -> None:
    dated = recommend_packing_sheets(
        [{"source_id": "WB:dated", "source_label": "2026.9.05", "workbook_year": 2026}],
        batch_context={"item_codes": ["SKU-1"], "references": [], "keywords": [], "reference_date": "2026-09-04"},
        snapshot_summaries={},
    )
    unknown = recommend_packing_sheets(
        [{"source_id": "WB:unknown", "source_label": "劳保鞋", "workbook_year": 2026}],
        batch_context={"item_codes": ["SKU-1"], "references": [], "keywords": [], "reference_date": "2026-09-04"},
        snapshot_summaries={},
    )

    assert dated[0]["is_recommended"] is True
    assert dated[0]["auto_select_recommended"] is False
    assert dated[0]["recommendation_confidence"] == "low"
    assert dated[0]["snapshot_status"] == "not_cached"
    assert unknown[0]["is_recommended"] is False
    assert unknown[0]["auto_select_recommended"] is False
    assert unknown[0]["recommendation_confidence"] == "none"


def test_uncached_sheet_name_can_match_approval_number_without_being_auto_selected() -> None:
    result = recommend_packing_sheets(
        [
            {
                "source_id": "WB:po-123",
                "source_label": "PO-123 装箱计划",
                "workbook_year": 2026,
                "snapshot_status": "not_cached",
            }
        ],
        batch_context={
            "item_codes": ["SKU-1"],
            "references": ["PO-123"],
            "keywords": [],
            "reference_date": None,
        },
        snapshot_summaries={},
    )

    assert result[0]["is_recommended"] is True
    assert result[0]["recommendation_confidence"] == "low"
    assert result[0]["auto_select_recommended"] is False
    assert "匹配 1 个审批或订单编号" in result[0]["recommendation_reasons"]


def test_unreadable_snapshot_is_never_auto_selected() -> None:
    result = recommend_packing_sheets(
        [
            {
                "source_id": "WB:broken",
                "source_label": "指环扣-packing list2026.9.05",
                "workbook_year": 2026,
                "snapshot_status": "unreadable",
            }
        ],
        batch_context={
            "item_codes": ["SKU-1"],
            "references": [],
            "keywords": ["指环扣"],
            "reference_date": "2026-09-03",
        },
        snapshot_summaries={},
    )

    assert result[0]["is_recommended"] is True
    assert result[0]["auto_select_recommended"] is False
