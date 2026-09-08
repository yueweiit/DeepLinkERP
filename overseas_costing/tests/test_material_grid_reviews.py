"""原始来源网格与坐标合并复核的回归测试。"""

import copy
import base64
import json

import pytest

from overseas_costing.services.material_import_service import (
    apply_material_import,
    build_wiki_material_projection,
    decode_material_preview_revision,
    preview_material_import,
)
from overseas_costing.services.packing_grid import build_grid_from_dingtalk_snapshot
from overseas_costing.services.packing_parse_service import parse_packing_grid
from overseas_costing.tests.test_material_import_service import FakeRepository


SOURCE_HASH = "b" * 64
HEADERS = ["物料编码", "采购订单号", "中文品名", "数量", "总净重", "总毛重", "总体积", "项目归属"]


def test_primary_bilingual_code_and_total_quantity_win_over_partial_export_helpers():
    grid = build_grid_from_dingtalk_snapshot({"schemaVersion":1,"sheetName":"packing",
        "values":[["品目编码Item code", "总个数 The total number of", "中文品名", "总净重", "总毛重", "总体积", "物料编码", "数量"],
                  ["M1", 96, "产品1", 8, 10, .3, "M1", 96],
                  ["M1", 4, "产品1", 2, 3, .1, "M1", 4],
                  ["OUT2", 5, "其他产品", 3, 4, .1, None, None]],
        "mergeRangesAvailable":False})
    parsed = parse_packing_grid(grid)
    mapping = {c['field']:c['column'] for c in parsed['columns']}
    assert mapping['material_code'] == 1
    assert mapping['quantity'] == 2
    assert [(r['material_code'], r['quantity']) for r in parsed['material_rows']] == [('M1','96'),('M1','4'),('OUT2','5')]


def test_known_complete_merge_metadata_does_not_infer_unmerged_blanks():
    parsed = parse_packing_grid(_grid(available=True))
    assert parsed['candidate_regions'] == []


def test_conflicting_cross_sku_source_ranges_cannot_be_bypassed_with_legacy_confirmation():
    from overseas_costing.services.material_import_service import apply_wiki_group_allocations
    grid = _grid(rows=[['M1','PO1','物料1',10,8,10,.3,''],
                       ['M2','PO2','物料2',20,None,None,None,''],
                       ['M3','PO3','物料3',30,4,None,.2,'']],
                 merges=[_range(5,action=None),_range(6,action=None,end=4),_range(7,action=None)],available=True)
    result = _preview(grid)
    group = result['confirmation_groups'][0]
    assert group['source_correction_required'] is True
    blockers = result['source_validation']['blocking']
    assert any(b['code']=='source_merge_conflict' and b['ranges'] for b in blockers)
    projection = build_wiki_material_projection(FakeRepository().items, parse_packing_grid(grid))
    rows, error = apply_wiki_group_allocations(projection, {'group_confirmations':{group['group_id']:True}})
    assert rows == [] and error['code'] == 'SOURCE_MERGE_CONFLICT'


def _grid(rows=None, merges=(), available=False):
    return build_grid_from_dingtalk_snapshot({
        "schemaVersion": 1,
        "sheetName": "装箱计划",
        "rangeAddress": "A1:H3",
        "values": [HEADERS, *(rows or [
            ["M1", "PO1", "油漆", 10, 8, 10, 0.3, "A项目"],
            [None, None, "第二行", None, None, None, None, None],
        ])],
        "mergeRangesAvailable": available,
        "mergeRanges": list(merges),
    })


def _range(column, *, action="confirm", start=2, end=3, end_column=None):
    result = {"start_row": start, "end_row": end, "start_column": column,
              "end_column": end_column or column}
    if action:
        result["action"] = action
    return result


def _resolver(grid, source_hash=SOURCE_HASH):
    def resolve(**_kwargs):
        return {"source_hash": source_hash,
                "source": {"source_kind": "wiki_sheet", "source_id": "WB:ST", "sheet_name": "装箱计划"},
                "grid": copy.deepcopy(grid), "preview": parse_packing_grid(grid)}
    return resolve


def _preview(grid, ranges=None, repo=None, **kwargs):
    return preview_material_import("B1", "wiki_sheet", "WB:ST",
        repository=repo or FakeRepository(), resolver=_resolver(grid), signing_key=b"key",
        **({"merge_reviews_json": {"source_hash": SOURCE_HASH, "ranges": ranges}} if ranges is not None else {}),
        **kwargs)


def test_preview_exposes_unchanged_cells_candidates_and_row_mapping_without_writes():
    grid = _grid()
    before = copy.deepcopy(grid)
    repo = FakeRepository()
    result = _preview(grid, repo=repo)
    source = result["source_grid"]
    assert source["cells"] == before["cells"]
    assert source["header_row"] == 1
    assert source["source_hash"] == SOURCE_HASH
    assert source["row_count"] == 3 and source["column_count"] == 8
    assert any(r["field"] == "material_code" and r["start_row"] == 2 and r["end_row"] == 3
               for r in source["candidate_regions"])
    states = {row["source_row"]: row for row in source["row_states"]}
    assert states[2]["state"] == "matched"
    assert states[2]["target_stable_line_keys"] == ["L1"]
    assert states[3]["state"] == "unmatched"
    assert grid == before
    assert repo.writes == [] and repo.commits == 0 and repo.import_audits == []


def test_real_xlsx_identity_quantity_and_physical_merges_count_once(tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    from overseas_costing.utils.excel_workbook import read_packing_grid
    book = openpyxl.Workbook()
    sheet = book.active
    sheet.append(HEADERS)
    sheet.append(["M1", "PO1", "油漆", 10, 8, 10, 0.3, "A项目"])
    sheet.append([None, None, "第二行", None, None, None, None, None])
    for col in (1, 2, 4, 5, 6, 7):
        sheet.merge_cells(start_row=2, end_row=3, start_column=col, end_column=col)
    path = tmp_path / "identity.xlsx"
    book.save(path)
    book.close()
    grid = read_packing_grid(str(path), sheet_name=sheet.title, require_exact_sheet=True)
    parsed = parse_packing_grid(grid)
    assert [r["material_code"] for r in parsed["material_rows"]] == ["M1", "M1"]
    assert parsed["material_rows"][1]["source_doc_no"] == "PO1"
    projection = build_wiki_material_projection(FakeRepository().items, parsed)
    assert projection["incoming"][0]["actual_shipped_qty"] == "10"
    assert projection["incoming"][0]["gross_weight_kg"] == "10"
    assert grid["cells"][2][0]["raw_value"] is None


def test_manual_reviews_are_signed_reapplied_and_audited_without_changing_raw_grid():
    grid = _grid()
    repo = FakeRepository()
    ranges = [_range(c) for c in (1, 2, 4, 5, 6, 7)]
    preview = _preview(grid, ranges, repo)
    assert preview["source_grid"]["cells"][2][0]["raw_value"] is None
    assert preview["rows"][0]["source_rows"] == [2, 3]
    assert preview["rows"][0]["incoming"]["actual_shipped_qty"] == "10"
    assert preview["rows"][0]["incoming"]["gross_weight_kg"] == "10"
    assert preview["confirmation_groups"] == []
    claims = decode_material_preview_revision(preview["preview_revision"], signing_key=b"key")
    assert claims["merge_reviews"] == preview["merge_reviews"]
    assert repo.writes == []
    result = apply_material_import("B1", preview["preview_revision"],
        {"fields": {"2,3": {"actual_shipped_qty": "use_source"}}}, "edit", "BM1",
        repository=repo, resolver=_resolver(grid), signing_key=b"key")
    assert result["ok"] is True
    assert repo.writes[0][1]["actual_shipped_qty"] == "10"
    assert repo.writes[0][1]["gross_weight_kg"] == "10"
    assert repo.import_audits[0]["merge_reviews"] == preview["merge_reviews"]
    assert "actor" in repo.import_audits[0]


@pytest.mark.parametrize("ranges", [
    [_range(1, start=0)], [_range(1, end=4)], [_range(9)],
    [_range(1, end=2)], [_range(1, action="other")],
    [_range(1), _range(1, action="separate")],
    [_range(3)],
])
def test_invalid_overlapping_or_conflicting_reviews_are_rejected(ranges):
    with pytest.raises(ValueError):
        _preview(_grid(), ranges)


def test_stale_review_hash_and_known_source_merge_override_are_rejected():
    with pytest.raises(ValueError, match="来源.*变|哈希|hash|SHA"):
        preview_material_import("B1", "wiki_sheet", "WB:ST", repository=FakeRepository(),
            resolver=_resolver(_grid()), signing_key=b"key",
            merge_reviews_json={"source_hash": "c" * 64, "ranges": [_range(1)]})
    with pytest.raises(ValueError, match="来源.*合并|真实.*合并"):
        _preview(_grid(merges=[_range(1, action=None)], available=True), [_range(1, action="separate")])


def test_description_confirmation_does_not_inherit_identity_or_resolve_physical_blanks():
    grid = _grid(rows=[["M1", "PO1", "油漆", 6, 8, 10, 0.3, "A项目"],
                       [None, None, None, 4, None, None, None, None]])
    preview = _preview(grid, [_range(3), _range(8)])
    assert preview["source_grid"]["row_states"][2]["state"] == "unmatched"
    assert preview["confirmation_groups"]
    assert preview["rows"][0]["incoming"].get("gross_weight_kg") is None


def test_separate_disables_inferred_packaging_but_keeps_true_blank_incomplete():
    grid = _grid(rows=[["M1", "PO1", "油漆", 6, 8, 10, 0.3],
                       ["M1", "PO1", "油漆2", 4, None, None, None]])
    preview = _preview(grid, [_range(c, action="separate") for c in (5, 6, 7)])
    assert preview["confirmation_groups"] == []
    assert preview["rows"][0]["physical_status"] == "incomplete"
    assert preview["rows"][0]["incoming"].get("gross_weight_kg") is None


def test_grid_inference_cannot_be_bypassed_with_legacy_group_checkbox():
    grid = _grid(rows=[["M1", "PO1", "油漆", 6, 8, 10, 0.3],
                       ["M1", "PO1", "油漆2", 4, None, None, None]])
    repo = FakeRepository()
    preview = _preview(grid, repo=repo)
    result = apply_material_import("B1", preview["preview_revision"],
        {"group_confirmations": {"package-1": True}}, "edit", "BM1",
        repository=repo, resolver=_resolver(grid), signing_key=b"key")
    assert result["code"] == "MERGE_REVIEW_REQUIRED"
    assert repo.writes == []


def test_same_sku_different_field_ranges_count_each_source_field_once():
    grid = _grid(rows=[["M1", "PO1", "油漆", 2, 8, 10, 0.1],
                       ["M1", "PO1", "油漆", 3, None, None, 0.2],
                       ["M1", "PO1", "油漆", 5, 4, 5, 0.3]],
                 merges=[_range(5, action=None), _range(6, action=None)], available=True)
    parsed = parse_packing_grid(grid)
    projection = build_wiki_material_projection(FakeRepository().items, parsed)
    incoming = projection["incoming"][0]
    assert incoming["physical_status"] == "complete"
    assert incoming["net_weight_kg"] == "12"
    assert incoming["gross_weight_kg"] == "15"
    assert incoming["volume_m3"] == "0.6"


def test_source_change_after_review_prevents_apply_and_all_writes():
    grid = _grid()
    repo = FakeRepository()
    preview = _preview(grid, [_range(1)], repo)
    result = apply_material_import("B1", preview["preview_revision"], {}, "edit", "BM1",
        repository=repo, resolver=_resolver(grid, "f" * 64), signing_key=b"key")
    assert result["code"] == "SOURCE_CHANGED"
    assert repo.writes == [] and repo.commits == 0


def test_rectangular_review_normalizes_per_column_and_preserves_formatted_formula_cells():
    grid = _grid()
    grid["cells"][1][5].update({"display_value": "10.00 kg", "formula": "=8+2"})
    preview = _preview(grid, [_range(5, end_column=7)])
    assert preview["merge_reviews"]["ranges"] == [_range(c) for c in (5, 6, 7)]
    assert preview["source_grid"]["cells"][1][5] == grid["cells"][1][5]
    assert [r["evidence_kind"] for r in preview["source_grid"]["merge_ranges"]] == ["manual_confirmed"] * 3


def test_review_rejects_unresolved_formula_even_when_display_value_looks_numeric():
    grid = _grid()
    grid["cells"][2][5].update({"display_value": "10", "formula": "=5+5"})
    with pytest.raises(ValueError, match="公式"):
        _preview(grid, [_range(6)])


def test_same_sku_repeated_values_count_once_only_after_confirming_exact_ranges():
    grid = _grid(rows=[["M1", "PO1", "A", 6, 8, 10, 0.3],
                       ["M1", "PO1", "B", 4, 8, 10, 0.3]])
    direct = _preview(grid)
    assert direct["rows"][0]["incoming"]["gross_weight_kg"] == "20"
    confirmed = _preview(grid, [_range(5, end_column=7)])
    assert confirmed["rows"][0]["incoming"]["gross_weight_kg"] == "10"
    assert confirmed["rows"][0]["incoming"]["actual_shipped_qty"] == "10"


def test_cross_sku_confirmed_group_requires_actual_allocations_and_exact_totals():
    grid = _grid(rows=[["M1", "PO1", "A", 6, 8, 10, 0.3],
                       ["M2", "PO1", "B", 4, None, None, None]])
    repo = FakeRepository()
    repo.items = [{"name": "I1", "stable_line_key": "L1", "material_code": "M1", "source_doc_no": "PO1"},
                  {"name": "I2", "stable_line_key": "L2", "material_code": "M2", "source_doc_no": "PO1"}]
    preview = _preview(grid, [_range(5, end_column=7)], repo)
    assert preview["confirmation_groups"] == []
    assert preview["shared_groups"][0]["allocation_required"] is True
    def apply(choices):
        return apply_material_import("B1", preview["preview_revision"], choices, "edit", "BM1",
            repository=repo, resolver=_resolver(grid), signing_key=b"key")
    assert apply({})["code"] == "ALLOCATION_REQUIRED"
    allocations = {"package-1": {"po1|m1": {"net_weight_kg": "3", "gross_weight_kg": "4", "volume_m3": "0.1"},
                                  "po1|m2": {"net_weight_kg": "5", "gross_weight_kg": "7", "volume_m3": "0.2"}}}
    assert apply({"allocations": allocations})["code"] == "ALLOCATION_TOTAL_MISMATCH"
    assert repo.writes == []
    allocations["package-1"]["po1|m2"]["gross_weight_kg"] = "6"
    assert apply({"allocations": allocations})["ok"] is True
    assert sum(float(write[1]["gross_weight_kg"]) for write in repo.writes) == 10


def test_cross_sku_shared_quantity_is_not_repeated_for_each_material():
    grid = _grid(rows=[["M1", "PO1", "A", 10, 3, 4, 0.1],
                       ["M2", "PO1", "B", None, 5, 6, 0.2]],
                 merges=[_range(4, action=None)], available=True)
    repo = FakeRepository()
    repo.items.append({"name": "I2", "stable_line_key": "L2", "material_code": "M2", "source_doc_no": "PO1"})
    preview = _preview(grid, repo=repo)
    assert all("actual_shipped_qty" not in row["incoming"] for row in preview["rows"])


def test_outside_only_candidate_ranges_never_block_in_batch_apply():
    grid = _grid(rows=[["M1", "PO1", "A", 6, 8, 10, 0.3],
                       ["OUTSIDE", "PO2", "B", 4, 5, 6, 0.2],
                       ["OUTSIDE", "PO2", "C", 4, None, None, None]])
    repo = FakeRepository()
    preview = _preview(grid, repo=repo)
    assert preview["confirmation_groups"] == []
    assert preview["source_grid"]["candidate_regions"]
    assert all(region["outside_only"] for region in preview["source_grid"]["candidate_regions"])
    result = apply_material_import("B1", preview["preview_revision"],
        {"fields": {"2": {"actual_shipped_qty": "use_source"}}}, "edit", "BM1",
        repository=repo, resolver=_resolver(grid), signing_key=b"key")
    assert result["ok"] is True and len(repo.writes) == 1


def test_forged_reviews_in_signed_revision_are_rejected_before_any_write():
    repo = FakeRepository()
    preview = _preview(_grid(), [_range(1)], repo)
    encoded, signature = preview["preview_revision"].split(".")
    claims = json.loads(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))
    claims["merge_reviews"]["ranges"].append(_range(5))
    forged = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=") + "." + signature
    result = apply_material_import("B1", forged, {}, "edit", "BM1",
        repository=repo, resolver=_resolver(_grid()), signing_key=b"key")
    assert result["code"] == "INVALID_PREVIEW_REVISION"
    assert repo.write_checks == [] and repo.writes == []


def test_changed_batch_and_changed_grid_under_same_hash_both_prevent_review_apply():
    grid = _grid()
    repo = FakeRepository()
    preview = _preview(grid, [_range(1)], repo)
    repo.context["version_modified"] = "VM2"
    result = apply_material_import("B1", preview["preview_revision"], {}, "edit", "BM1",
        repository=repo, resolver=_resolver(grid), signing_key=b"key")
    assert result["code"] == "BATCH_VERSION_CHANGED"
    repo.context["version_modified"] = "VM1"
    grid["cells"][1][3]["raw_value"] = 11
    result = apply_material_import("B1", preview["preview_revision"], {}, "edit", "BM1",
        repository=repo, resolver=_resolver(grid), signing_key=b"key")
    assert result["code"] == "PREVIEW_CHANGED"
    assert repo.writes == [] and repo.commits == 0


def test_merged_confirmation_response_retains_original_source_grid():
    grid = _grid(rows=[["M1", "PO1", "A", 6, 8, 10, 0.3]])
    repo = FakeRepository()
    repo.items.append({"name": "I2", "stable_line_key": "L2", "material_code": "M1", "source_doc_no": "PO1"})
    preview = _preview(grid, repo=repo)
    result = apply_material_import("B1", preview["preview_revision"], {"matches": {"2": "L1"}}, "edit", "BM1",
        repository=repo, resolver=_resolver(grid), signing_key=b"key")
    assert result["code"] == "MERGED_PREVIEW_CONFIRMATION_REQUIRED"
    assert result["merged_preview"]["source_grid"] == preview["source_grid"]
    assert repo.writes == []


def test_source_column_coordinates_do_not_shift_when_snapshot_range_starts_below_a1():
    grid = build_grid_from_dingtalk_snapshot({"schemaVersion": 1, "sheetName": "局部范围",
        "rangeAddress": "C5:F7", "values": [["物料编码", "数量", "总毛重", "总体积"],
            ["M1", 10, 20, 0.1], ["M2", 5, 10, 0.05]], "mergeRangesAvailable": False})
    parsed = parse_packing_grid(grid)
    assert parsed["header_row"] == 5
    assert parsed["material_rows"][0]["source_row"] == 6
    assert grid["cells"][5][2]["raw_value"] == "M1"
    assert parsed["columns"][0]["column"] == 3


def test_numeric_looking_identity_values_cannot_be_replaced_by_another_code():
    grid = _grid(rows=[["001", "PO1", "A", 6, 8, 10, 0.3],
                       [1, "PO1", "B", 4, 8, 10, 0.3]])
    with pytest.raises(ValueError, match="冲突"):
        _preview(grid, [_range(1)])


def test_missing_identity_under_outside_anchor_is_outside_only_review_scope():
    grid = _grid(rows=[["M1", "PO1", "A", 6, 8, 10, 0.3],
                       ["OUTSIDE", "PO2", "B", 4, 5, 6, 0.2],
                       [None, None, "C", 4, None, None, None]])
    preview = _preview(grid)
    assert preview["source_grid"]["row_states"][3]["state"] == "unmatched"
    assert all(region["outside_only"] for region in preview["source_grid"]["candidate_regions"])


def test_real_source_ranges_and_actor_are_written_to_existing_audit(monkeypatch):
    from types import SimpleNamespace
    from overseas_costing.services import material_import_service
    monkeypatch.setattr(material_import_service, "frappe", SimpleNamespace(session=SimpleNamespace(user="operator@example.test")))
    grid = _grid(merges=[_range(c, action=None) for c in (1, 2, 4, 5, 6, 7)], available=True)
    repo = FakeRepository()
    preview = _preview(grid, repo=repo)
    result = apply_material_import("B1", preview["preview_revision"],
        {"fields": {"2,3": {"actual_shipped_qty": "use_source"}}}, "edit", "BM1",
        repository=repo, resolver=_resolver(grid), signing_key=b"key")
    assert result["ok"]
    assert repo.import_audits[0]["source_merge_ranges"] == grid["merge_ranges"]
    assert repo.import_audits[0]["actor"] == "operator@example.test"
