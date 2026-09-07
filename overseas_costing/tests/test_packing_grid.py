"""中文用途：统一装箱网格、合并单元格证据和整票汇总测试。"""

from decimal import Decimal

import pytest

openpyxl = pytest.importorskip("openpyxl")

from overseas_costing.services.packing_grid import (
    PackingSheetNotFound,
    build_grid_from_dingtalk_snapshot,
)
from overseas_costing.services.packing_parse_service import parse_packing_grid
from overseas_costing.utils.excel_workbook import read_packing_grid


def _build_grouped_workbook(path):
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "油漆-packing list2026.9.05"
    sheet.append(
        [
            "对应钉钉采购订单号",
            "品目编码Item code",
            "中文品名",
            "数量",
            "单位",
            "长m",
            "宽m",
            "高m",
            "总净重NW kg",
            "总毛重Gross weight kg",
            "总体积CBM",
            "件数",
        ]
    )
    groups = [
        ([2], "FL000101", Decimal("500"), Decimal("600"), Decimal("1.2")),
        ([3], "FL000102", Decimal("400"), Decimal("500"), Decimal("1.0")),
        ([4, 5], "FL000103", Decimal("600"), Decimal("700"), Decimal("1.5")),
        ([6], "FL000104", Decimal("300"), Decimal("400"), Decimal("0.8")),
        ([7, 8], "FL000105", Decimal("800"), Decimal("900"), Decimal("2")),
        ([9, 10], "FL000106", Decimal("892"), Decimal("1097.4"), Decimal("2.2403305")),
    ]
    code_index = 0
    for rows, code_prefix, net, gross, volume in groups:
        for row_no in rows:
            code_index += 1
            sheet.cell(row_no, 1, "202609050001")
            sheet.cell(row_no, 2, f"{code_prefix}-{code_index}")
            sheet.cell(row_no, 3, f"物料 {code_index}")
            sheet.cell(row_no, 4, code_index * 10)
            sheet.cell(row_no, 5, "桶")
            if row_no == rows[0]:
                sheet.cell(row_no, 6, Decimal("1.27"))
                sheet.cell(row_no, 7, Decimal("0.97"))
                sheet.cell(row_no, 8, Decimal("1.245"))
                sheet.cell(row_no, 9, net)
                sheet.cell(row_no, 10, gross)
                sheet.cell(row_no, 11, volume)
                sheet.cell(row_no, 12, 1)
        if len(rows) > 1:
            for column in (6, 7, 8, 9, 10, 11, 12):
                sheet.merge_cells(
                    start_row=rows[0],
                    end_row=rows[-1],
                    start_column=column,
                    end_column=column,
                )

    sheet.cell(11, 3, "合计")
    sheet.cell(11, 9, Decimal("3492"))
    sheet.cell(11, 10, Decimal("4197.4"))
    sheet.cell(11, 11, Decimal("8.7403305"))

    other = workbook.create_sheet("其他表")
    other["A1"] = "不是装箱单"
    workbook.save(path)
    workbook.close()


def test_xlsx_merges_create_six_package_groups_without_double_counting(tmp_path) -> None:
    path = tmp_path / "packing.xlsx"
    _build_grouped_workbook(path)

    grid = read_packing_grid(
        str(path),
        sheet_name="油漆-packing list2026.9.05",
        require_exact_sheet=True,
    )
    preview = parse_packing_grid(grid)

    assert preview["material_row_count"] == 9
    assert preview["package_count"] == 6
    assert preview["totals"]["gross_weight_kg"]["value"] == "4197.4"
    assert preview["totals"]["volume_m3"]["value"] == "8.7403305"
    assert preview["totals"]["net_weight_kg"]["kind"] == "calculated_detail_sum"
    assert preview["totals"]["net_weight_kg"]["value"] == "3492"
    assert preview["groups"][2]["row_numbers"] == [4, 5]
    assert preview["groups"][2]["gross_weight_kg"]["count_once"] is True
    assert preview["groups"][2]["needs_confirmation"] is False


def test_exact_sheet_selection_never_silently_falls_back(tmp_path) -> None:
    path = tmp_path / "packing.xlsx"
    _build_grouped_workbook(path)

    with pytest.raises(PackingSheetNotFound, match="不存在工作表"):
        read_packing_grid(str(path), sheet_name="错误页签", require_exact_sheet=True)


def test_material_import_grid_limits_rows_and_columns_before_iteration(tmp_path) -> None:
    path = tmp_path / "wide.xlsx"
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.cell(2, 121, "too wide")
    workbook.save(path)
    workbook.close()

    with pytest.raises(ValueError, match="120"):
        read_packing_grid(
            str(path),
            sheet_name=sheet.title,
            require_exact_sheet=True,
            max_rows=1000,
            max_columns=120,
        )


def test_dingtalk_raw_number_wins_over_formatted_display_value() -> None:
    grid = build_grid_from_dingtalk_snapshot(
        {
            "schemaVersion": 1,
            "sheetName": "2026.9.05",
            "rangeAddress": "A1:D3",
            "values": [
                ["物料编码", "数量", "总毛重", "总体积"],
                ["FL001", 1, 4197.4, 8.7403305],
                ["合计", None, 4197.4, 8.7403305],
            ],
            "displayValues": [
                ["物料编码", "数量", "总毛重", "总体积"],
                ["FL001", "1", "¥4,197.40", "¥8.74"],
                ["合计", "", "¥4,197.40", "¥8.74"],
            ],
            "formulas": [["", "", "", ""], ["", "", "", ""], ["", "", "", ""]],
            "mergeRangesAvailable": False,
        }
    )

    preview = parse_packing_grid(grid)

    assert preview["totals"]["gross_weight_kg"]["value"] == "4197.4"
    assert preview["totals"]["volume_m3"]["value"] == "8.7403305"


def test_dingtalk_chunked_snapshot_is_reassembled_in_row_order() -> None:
    grid = build_grid_from_dingtalk_snapshot(
        {
            "schemaVersion": 1,
            "sheetName": "分块",
            "rangeAddress": "A1:D3",
            "mergeRangesAvailable": False,
            "chunks": [
                {
                    "rangeAddress": "A3:D3",
                    "values": [["合计", None, 30, 0.2]],
                    "displayValues": [["合计", "", "30", "0.2"]],
                    "formulas": [["", "", "", ""]],
                },
                {
                    "rangeAddress": "A1:D2",
                    "values": [["物料编码", "数量", "总毛重", "总体积"], ["FL001", 1, 30, 0.2]],
                    "displayValues": [["物料编码", "数量", "总毛重", "总体积"], ["FL001", "1", "30", "0.2"]],
                    "formulas": [["", "", "", ""], ["", "", "", ""]],
                },
            ],
        }
    )

    preview = parse_packing_grid(grid)

    assert preview["material_row_count"] == 1
    assert preview["totals"]["gross_weight_kg"]["value"] == "30"


def test_snapshot_blanks_can_only_suggest_groups_until_user_confirms() -> None:
    grid = build_grid_from_dingtalk_snapshot(
        {
            "schemaVersion": 1,
            "sheetName": "8.15装箱计划",
            "rangeAddress": "A1:E4",
            "values": [
                ["物料编码", "数量", "总毛重", "总体积", "计划日期"],
                ["10001", 1, 30, 0.2, 46249],
                ["10002", 2, None, None, None],
                ["合计", None, 30, 0.2, None],
            ],
            "displayValues": [
                ["物料编码", "数量", "总毛重", "总体积", "计划日期"],
                ["10001", "1", "30", "0.2", "2026/8/15"],
                ["10002", "2", "", "", ""],
                ["合计", "", "30", "0.2", ""],
            ],
            "formulas": [["", "", "", "", ""]] * 4,
            "mergeRangesAvailable": False,
        }
    )

    preview = parse_packing_grid(grid)

    assert preview["material_row_count"] == 2
    assert preview["groups"][0]["row_numbers"] == [2, 3]
    assert preview["groups"][0]["needs_confirmation"] is True
    assert preview["validation"]["needs_group_confirmation"] is True
    assert preview["material_rows"][0]["raw_fields"]["计划日期"]["raw_value"] == 46249
    assert preview["source"]["sheet_name"] == "8.15装箱计划"


def test_conflicting_physical_merge_spans_are_blocking(tmp_path) -> None:
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "冲突"
    sheet.append(["物料编码", "数量", "总毛重", "总体积"])
    for row_no in (2, 3, 4):
        sheet.cell(row_no, 1, f"FL{row_no}")
        sheet.cell(row_no, 2, 1)
    sheet["C2"] = 50
    sheet["D2"] = 0.4
    sheet.merge_cells("C2:C3")
    sheet.merge_cells("D2:D4")
    path = tmp_path / "conflict.xlsx"
    workbook.save(path)
    workbook.close()

    preview = parse_packing_grid(
        read_packing_grid(str(path), sheet_name="冲突", require_exact_sheet=True)
    )

    assert preview["groups"][0]["row_numbers"] == [2, 3, 4]
    assert preview["groups"][0]["needs_confirmation"] is True
    assert any(item["code"] == "conflicting_merge_ranges" for item in preview["validation"]["blocking"])


def test_formula_without_cached_value_is_unresolved(tmp_path) -> None:
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "公式"
    sheet.append(["物料编码", "数量", "总毛重", "总体积"])
    sheet.append(["FL001", 2, "=B2*5", "=B2*0.1"])
    path = tmp_path / "formula.xlsx"
    workbook.save(path)
    workbook.close()

    preview = parse_packing_grid(
        read_packing_grid(str(path), sheet_name="公式", require_exact_sheet=True)
    )

    assert any(item["code"] == "unresolved_formula" for item in preview["validation"]["blocking"])
    assert preview["groups"][0]["gross_weight_kg"]["value"] is None


def test_name_merge_and_unmerged_physical_blank_do_not_prove_shared_package(tmp_path) -> None:
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "品名合并"
    sheet.append(["物料编码", "中文品名", "数量", "总毛重", "总体积"])
    sheet.append(["FL001", "同一品名", 1, 10, 0.1])
    sheet.append(["FL002", None, 1, None, None])
    sheet.merge_cells("B2:B3")
    path = tmp_path / "name-merge.xlsx"
    workbook.save(path)
    workbook.close()

    preview = parse_packing_grid(
        read_packing_grid(str(path), sheet_name="品名合并", require_exact_sheet=True)
    )

    assert preview["package_count"] == 2
    assert preview["groups"][1]["gross_weight_kg"]["value"] is None
    assert preview["groups"][1]["volume_m3"]["value"] is None


def test_second_horizontal_header_does_not_duplicate_material_rows(tmp_path) -> None:
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "左右两区"
    sheet.append(["物料编码", "数量", "总毛重", "总体积"])
    sheet.append(["FL001", 2, 20, 0.2])
    sheet["AZ1"] = "物料编码"
    sheet["BA1"] = "数量"
    sheet["AZ2"] = "不应重复读取"
    sheet["BA2"] = 999
    path = tmp_path / "wide.xlsx"
    workbook.save(path)
    workbook.close()

    preview = parse_packing_grid(
        read_packing_grid(str(path), sheet_name="左右两区", require_exact_sheet=True)
    )

    assert preview["material_row_count"] == 1
    assert preview["material_rows"][0]["material_code"] == "FL001"


def test_package_piece_total_is_distinct_from_package_group_count() -> None:
    rows = [["物料编码", "数量", "总毛重", "总体积", "件数"]]
    for index in range(1, 25):
        rows.append(
            [
                f"ITEM-{index:02d}",
                1,
                1000 if index < 24 else 2360.08,
                2 if index < 24 else 9.33429,
                15 if index < 24 else 23,
            ]
        )
    rows.append(["合计", None, 25360.08, 55.33429, 368])
    snapshot = {
        "schemaVersion": 1,
        "sheetName": "8.15日货柜",
        "rangeAddress": "A1:E26",
        "values": rows,
        "displayValues": [["" if value is None else str(value) for value in row] for row in rows],
        "formulas": [["", "", "", "", ""] for _row in rows],
        "mergeRangesAvailable": False,
    }

    preview = parse_packing_grid(build_grid_from_dingtalk_snapshot(snapshot))

    assert preview["material_row_count"] == 24
    assert preview["package_group_count"] == 24
    assert preview["package_count"] == 368
    assert preview["totals"]["gross_weight_kg"]["value"] == "25360.08"
    assert preview["totals"]["volume_m3"]["value"] == "55.33429"


def test_total_physical_columns_win_over_earlier_per_piece_columns() -> None:
    snapshot = {
        "schemaVersion": 1,
        "sheetName": "总量列优先",
        "rangeAddress": "A1:G3",
        "values": [
            ["物料编码", "数量", "每件净重", "每件毛重", "每件CBM", "总净重", "总毛重", "总体积"],
            ["ITEM-1", 10, 4, 6, 0.3, 40, 60, 3],
            ["合计", None, None, None, None, 40, 60, 3],
        ],
        "displayValues": [],
        "formulas": [],
        "mergeRangesAvailable": False,
    }
    snapshot["rangeAddress"] = "A1:H3"
    preview = parse_packing_grid(build_grid_from_dingtalk_snapshot(snapshot))

    assert preview["totals"]["net_weight_kg"]["value"] == "40"
    assert preview["totals"]["gross_weight_kg"]["value"] == "60"
    assert preview["totals"]["volume_m3"]["value"] == "3"


def test_declared_total_mismatch_is_blocking_until_user_chooses_basis() -> None:
    snapshot = {
        "schemaVersion": 1,
        "sheetName": "合计差异",
        "rangeAddress": "A1:D4",
        "values": [
            ["物料编码", "数量", "总毛重", "总体积"],
            ["ITEM-1", 1, 10, 1],
            ["ITEM-2", 1, 20, 2],
            ["合计", None, 999, 99],
        ],
        "displayValues": [],
        "formulas": [],
        "mergeRangesAvailable": False,
    }

    preview = parse_packing_grid(build_grid_from_dingtalk_snapshot(snapshot))

    assert preview["ok"] is False
    assert {item["field"] for item in preview["validation"]["blocking"] if item["code"] == "total_mismatch"} == {
        "gross_weight_kg",
        "volume_m3",
    }
