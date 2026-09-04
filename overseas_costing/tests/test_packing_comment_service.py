from __future__ import annotations

from overseas_costing.services.packing_comment_service import (
    build_comment_source_id,
    parse_packing_comment,
)


def test_comment_source_id_is_stable_and_sensitive_to_text() -> None:
    first = build_comment_source_id("PROC-1", "2026-09-01 10:00", "USER-1", "重量 21kg")
    second = build_comment_source_id("PROC-1", "2026-09-01 10:00", "USER-1", "重量 21kg")
    changed = build_comment_source_id("PROC-1", "2026-09-01 10:00", "USER-1", "重量 22kg")

    assert first == second
    assert first != changed
    assert len(first) == 64


def test_parses_mould_shipping_comment_into_reviewable_packing_candidate() -> None:
    result = parse_packing_comment("规格33*20*23，重量：42.05kg，1套模具+3个手机壳")

    assert result["is_candidate"] is True
    assert result["gross_weight_kg"] == 42.05
    assert result["dimensions_cm"] == [33.0, 20.0, 23.0]
    assert result["volume_m3"] == 0.01518
    assert result["rows"] == [
        {"product_name": "模具", "actual_shipped_qty": 1.0, "unit": "套", "gross_weight_kg": 42.05, "volume_m3": 0.01518},
        {"product_name": "手机壳", "actual_shipped_qty": 3.0, "unit": "个"},
    ]


def test_parses_material_quantity_and_aggregate_bag_comment() -> None:
    material = parse_packing_comment("DHL 发货明细: MBA101283 1PCS，重量 2.5kg")
    aggregate = parse_packing_comment("发5200个袋子过去，重量21kg")

    assert material["rows"][0]["material_code"] == "MBA101283"
    assert material["rows"][0]["actual_shipped_qty"] == 1.0
    assert material["rows"][0]["unit"] == "PCS"
    assert aggregate["rows"][0]["product_name"] == "袋子"
    assert aggregate["rows"][0]["actual_shipped_qty"] == 5200.0


def test_ordinary_approval_comment_is_not_treated_as_packing_data() -> None:
    assert parse_packing_comment("同意，请按计划安排发货")["is_candidate"] is False


def test_malformed_numbers_do_not_break_the_approval_detail() -> None:
    result = parse_packing_comment("模具发出，重量1..2kg，数量1,2,3个")

    assert result["is_candidate"] is False
    assert result["rows"] == []
    assert result["gross_weight_kg"] is None
