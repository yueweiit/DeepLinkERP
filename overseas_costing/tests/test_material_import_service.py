"""物料 Excel 字段级预览与安全采用测试。"""

import pytest

from overseas_costing.services.material_import_service import (
    FrappeMaterialImportRepository,
    apply_material_import,
    apply_wiki_group_allocations,
    build_field_changes,
    build_material_import_preview,
    build_wiki_material_projection,
    decode_material_preview_revision,
    encode_material_preview_revision,
    preview_material_import,
    validate_material_workbook_metadata,
)


class FakeRepository:
    def __init__(self):
        self.context = {
            "batch": "B1",
            "version": "V1",
            "batch_modified": "BM1",
            "version_modified": "VM1",
        }
        self.items = [
            {
                "name": "I1",
                "stable_line_key": "L1",
                "material_code": "M1",
                "source_doc_no": "PO1",
                "excel_row_no": 9,
                "actual_shipped_qty": 17,
                "actual_shipped_qty_mode": "MANUAL_CONFIRMED",
                "shipped_uom": "桶",
            }
        ]
        self.writes = []
        self.commits = 0
        self.rollbacks = 0
        self.write_checks = []
        self.import_audits = []

    def get_context(self, batch_name):
        assert batch_name == "B1"
        return dict(self.context)

    def get_items(self, batch_name, version_name):
        assert (batch_name, version_name) == ("B1", "V1")
        return [dict(item) for item in self.items]

    def assert_write(self, batch_name, edit_token, expected_modified):
        self.write_checks.append((batch_name, edit_token, expected_modified))

    def lock(self, batch_name, version_name):
        assert (batch_name, version_name) == ("B1", "V1")

    def update_item(self, item_name, updates, audit_context):
        self.writes.append((item_name, dict(updates), dict(audit_context)))

    def mark_dirty(self, batch_name):
        assert batch_name == "B1"

    def record_import_audit(self, payload):
        self.import_audits.append(dict(payload))

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


def _packing_group(
    group_id,
    rows,
    *,
    net,
    gross,
    volume,
    needs_confirmation=False,
    count_once=True,
    count_once_by_field=None,
):
    def metric(value, fieldname):
        return {
            "value": value,
            "count_once": (count_once_by_field or {}).get(fieldname, count_once),
            "source_row": rows[0] if value is not None else None,
            "evidence": "direct_value" if value is not None else "missing",
        }

    return {
        "group_id": group_id,
        "row_numbers": rows,
        "net_weight_kg": metric(net, "net_weight_kg"),
        "gross_weight_kg": metric(gross, "gross_weight_kg"),
        "volume_m3": metric(volume, "volume_m3"),
        "needs_confirmation": needs_confirmation,
    }


def test_material_excel_accepts_only_bounded_xlsx_files() -> None:
    assert validate_material_workbook_metadata("packing.xlsx", 1024) is None
    with pytest.raises(ValueError, match="xlsx"):
        validate_material_workbook_metadata("packing.xlsm", 1024)
    with pytest.raises(ValueError, match="20 MB"):
        validate_material_workbook_metadata("packing.xlsx", 20 * 1024 * 1024 + 1)


def test_frappe_repository_treats_source_audit_failure_as_transaction_failure(monkeypatch) -> None:
    from overseas_costing.services import usage_service

    monkeypatch.setattr(
        usage_service,
        "record_usage",
        lambda **_kwargs: {"ok": False, "message": "audit unavailable"},
    )

    with pytest.raises(RuntimeError, match="audit unavailable"):
        FrappeMaterialImportRepository().record_import_audit(
            {"batch": "B1", "version": "V1", "source_kind": "wiki_sheet", "sheet": "装箱计划"}
        )


def _resolver_with_quantity(quantity=15, source_hash="a" * 64):
    def resolve(**_kwargs):
        return {
            "source_hash": source_hash,
            "source": {
                "source_kind": "manual_attachment",
                "source_id": "FILE-1",
                "source_label": "装箱计划.xlsx",
                "sheet_name": "油漆",
            },
            "preview": {
                "material_rows": [
                    {
                        "source_row": 9,
                        "source_line_no": 9,
                        "source_doc_no": "PO1",
                        "material_code": "M1",
                        "quantity": quantity,
                        "unit": "桶",
                    }
                ],
                "totals": {
                    "gross_weight_kg": {"value": "4197.4"},
                    "volume_m3": {"value": "8.74"},
                },
            },
        }

    return resolve


def _wiki_resolver(source_hash="d" * 64):
    def resolve(**_kwargs):
        return {
            "source_hash": source_hash,
            "source": {
                "source_kind": "wiki_sheet",
                "source_id": "WB-1:ST-1",
                "source_label": "2026装箱计划 / 油漆",
                "sheet_name": "油漆",
                "source_updated_at": "2026-09-08 09:00:00",
            },
            "preview": {
                "material_rows": [
                    {"source_row": 2, "material_code": "M1", "quantity": "6", "unit": "桶"},
                    {"source_row": 3, "material_code": "M1", "quantity": "4", "unit": "桶"},
                    {"source_row": 4, "material_code": "OUTSIDE", "quantity": "2", "unit": "件"},
                ],
                "groups": [
                    _packing_group("package-1", [2], net="5", gross="6", volume="0.02"),
                    _packing_group("package-2", [3], net="3", gross="4", volume="0.01"),
                    _packing_group("package-3", [4], net="1", gross="2", volume="0.01"),
                ],
                "totals": {"gross_weight_kg": {"value": "12"}, "volume_m3": {"value": "0.04"}},
            },
        }

    return resolve


def _shared_wiki_resolver(source_hash="e" * 64):
    def resolve(**_kwargs):
        return {
            "source_hash": source_hash,
            "source": {
                "source_kind": "wiki_sheet",
                "source_id": "WB-1:ST-SHARED",
                "source_label": "2026装箱计划 / 合箱",
                "sheet_name": "合箱",
            },
            "preview": {
                "material_rows": [
                    {"source_row": 2, "material_code": "M1", "quantity": "10", "unit": "件"},
                    {"source_row": 3, "material_code": "M2", "quantity": "20", "unit": "件"},
                ],
                "groups": [_packing_group("package-1", [2, 3], net="25", gross="30", volume="0.12")],
                "totals": {"gross_weight_kg": {"value": "30"}, "volume_m3": {"value": "0.12"}},
            },
        }

    return resolve


def _unit_conflict_wiki_resolver(source_hash="f" * 64):
    def resolve(**_kwargs):
        return {
            "source_hash": source_hash,
            "source": {
                "source_kind": "wiki_sheet",
                "source_id": "WB-1:ST-UNIT",
                "source_label": "2026装箱计划 / 单位冲突",
                "sheet_name": "单位冲突",
            },
            "preview": {
                "material_rows": [
                    {"source_row": 2, "material_code": "M1", "quantity": "6", "unit": "件"},
                    {"source_row": 3, "material_code": "M1", "quantity": "4", "unit": "箱"},
                ],
                "groups": [
                    _packing_group("package-1", [2], net="5", gross="6", volume="0.02"),
                    _packing_group("package-2", [3], net="3", gross="4", volume="0.01"),
                ],
            },
        }

    return resolve


def _suggested_group_wiki_resolver(source_hash="1" * 64):
    def resolve(**_kwargs):
        return {
            "source_hash": source_hash,
            "source": {
                "source_kind": "wiki_sheet",
                "source_id": "WB-1:ST-GROUP",
                "source_label": "2026装箱计划 / 候选合并组",
                "sheet_name": "候选合并组",
            },
            "preview": {
                "material_rows": [
                    {"source_row": 2, "material_code": "M1", "quantity": "6", "unit": "件"},
                    {"source_row": 3, "material_code": "M1", "quantity": "4", "unit": "件"},
                ],
                "groups": [
                    _packing_group(
                        "package-1",
                        [2, 3],
                        net="8",
                        gross="10",
                        volume="0.03",
                        needs_confirmation=True,
                        count_once=False,
                    )
                ],
            },
        }

    return resolve


def _mismatch_wiki_resolver(source_hash="2" * 64):
    def resolve(**_kwargs):
        payload = _wiki_resolver(source_hash=source_hash)(**_kwargs)
        payload["preview"]["ok"] = False
        payload["preview"]["validation"] = {
            "blocking": [
                {
                    "code": "total_mismatch",
                    "field": "gross_weight_kg",
                    "message": "表内毛重合计与明细加总不一致。",
                }
            ],
            "warnings": [{"code": "test_warning", "message": "测试警告。"}],
        }
        return payload

    return resolve


def test_preview_keeps_duplicate_sku_rows_and_requires_line_choice() -> None:
    result = build_material_import_preview(
        existing=[
            {
                "name": "I1",
                "stable_line_key": "L1",
                "material_code": "FL000103",
                "source_doc_no": "PO1",
                "excel_row_no": 9,
            },
            {
                "name": "I2",
                "stable_line_key": "L2",
                "material_code": "FL000103",
                "source_doc_no": "PO1",
                "excel_row_no": 9,
            },
        ],
        incoming=[
            {
                "source_row": 9,
                "source_line_no": 9,
                "source_doc_no": "PO1",
                "material_code": "FL000103",
                "actual_shipped_qty": 15,
            }
        ],
        source={"kind": "manual_xlsx", "revision": "R1"},
    )

    assert result["rows"][0]["match_status"] == "choice_required"
    assert {candidate["stable_line_key"] for candidate in result["rows"][0]["candidates"]} == {
        "L1",
        "L2",
    }


def test_source_document_disambiguates_duplicate_sku_rows() -> None:
    result = build_material_import_preview(
        existing=[
            {"name": "I1", "stable_line_key": "L1", "material_code": "M1", "source_doc_no": "PO1", "excel_row_no": 2},
            {"name": "I2", "stable_line_key": "L2", "material_code": "M1", "source_doc_no": "PO2", "excel_row_no": 3},
        ],
        incoming=[
            {"source_row": 3, "source_line_no": 3, "material_code": "M1", "source_doc_no": "PO2", "actual_shipped_qty": 9}
        ],
        source={"kind": "manual_xlsx", "revision": "R1"},
    )

    assert result["rows"][0]["match_status"] == "matched"
    assert result["rows"][0]["target_stable_line_key"] == "L2"


def test_wiki_sheet_matches_unique_sku_without_purchase_line_identity() -> None:
    result = build_material_import_preview(
        existing=[
            {
                "name": "I1",
                "stable_line_key": "L1",
                "material_code": "M1",
                "source_doc_no": "PO1",
                "excel_row_no": 4,
            }
        ],
        incoming=[
            {
                "source_row": "2,3",
                "source_rows": [2, 3],
                "material_code": "M1",
                "actual_shipped_qty": "100000",
            }
        ],
        source={"kind": "wiki_sheet"},
    )

    assert result["rows"][0]["match_status"] == "matched"
    assert result["rows"][0]["target_stable_line_key"] == "L1"


def test_wiki_sheet_requires_choice_when_sku_has_multiple_purchase_targets() -> None:
    result = build_material_import_preview(
        existing=[
            {"name": "I1", "stable_line_key": "L1", "material_code": "M1", "source_doc_no": "PO1"},
            {"name": "I2", "stable_line_key": "L2", "material_code": "M1", "source_doc_no": "PO2"},
        ],
        incoming=[{"source_row": 2, "material_code": "M1", "actual_shipped_qty": 10}],
        source={"kind": "wiki_sheet"},
    )

    assert result["rows"][0]["match_status"] == "choice_required"
    assert {row["stable_line_key"] for row in result["rows"][0]["candidates"]} == {"L1", "L2"}


def test_wiki_sheet_purchase_approval_disambiguates_sku_and_never_falls_back() -> None:
    existing = [
        {"name": "I1", "stable_line_key": "L1", "material_code": "M1", "source_doc_no": "PO1"},
        {"name": "I2", "stable_line_key": "L2", "material_code": "M1", "source_doc_no": "PO2"},
    ]

    matched = build_material_import_preview(
        existing,
        [{"source_row": 2, "material_code": "M1", "source_doc_no": "PO2", "actual_shipped_qty": 10}],
        {"kind": "wiki_sheet"},
    )
    wrong_approval = build_material_import_preview(
        existing,
        [{"source_row": 2, "material_code": "M1", "source_doc_no": "PO-X", "actual_shipped_qty": 10}],
        {"kind": "wiki_sheet"},
    )

    assert matched["rows"][0]["match_status"] == "matched"
    assert matched["rows"][0]["target_stable_line_key"] == "L2"
    assert wrong_approval["rows"][0]["match_status"] == "unmatched"


def test_wiki_projection_aggregates_repeated_sku_once_and_filters_other_materials() -> None:
    projection = build_wiki_material_projection(
        existing=[{"name": "I1", "stable_line_key": "L1", "material_code": "M1"}],
        parsed_preview={
            "material_rows": [
                {"source_row": 2, "material_code": "M1", "quantity": "96", "unit": "件"},
                {"source_row": 3, "material_code": "M1", "quantity": "4", "unit": "件"},
                {"source_row": 4, "material_code": "OUTSIDE", "quantity": "8", "unit": "件"},
            ],
            "groups": [
                _packing_group("package-1", [2], net="90", gross="100", volume="0.4"),
                _packing_group("package-2", [3], net="4", gross="5", volume="0.02"),
                _packing_group("package-3", [4], net="7", gross="8", volume="0.03"),
            ],
        },
    )

    assert projection["incoming"] == [
        {
            "source_row": "2,3",
            "source_rows": [2, 3],
            "source_group_ids": ["package-1", "package-2"],
            "source_doc_no": "",
            "material_code": "M1",
            "actual_shipped_qty": "100",
            "shipped_uom": "件",
            "net_weight_kg": "94",
            "gross_weight_kg": "105",
            "volume_m3": "0.42",
            "physical_status": "complete",
            "physical_missing_rows": [],
        }
    ]
    assert projection["out_of_batch"] == [
        {"source_row": 4, "material_code": "OUTSIDE", "source_doc_no": "", "quantity": "8"}
    ]


def test_wiki_projection_merges_blank_approval_row_into_its_unique_batch_target() -> None:
    projection = build_wiki_material_projection(
        existing=[
            {
                "name": "I1",
                "stable_line_key": "L1",
                "material_code": "M1",
                "source_doc_no": "PO1",
            }
        ],
        parsed_preview={
            "material_rows": [
                {"source_row": 2, "source_doc_no": "PO1", "material_code": "M1", "quantity": "6", "unit": "件"},
                {"source_row": 3, "source_doc_no": "", "material_code": "M1", "quantity": "4", "unit": "件"},
            ],
            "groups": [
                _packing_group("package-1", [2], net="5", gross="6", volume="0.02"),
                _packing_group("package-2", [3], net="3", gross="4", volume="0.01"),
            ],
        },
    )

    assert len(projection["incoming"]) == 1
    assert projection["incoming"][0]["source_doc_no"] == "PO1"
    assert projection["incoming"][0]["actual_shipped_qty"] == "10"


def test_wiki_projection_rejects_physical_metric_without_count_once_evidence() -> None:
    projection = build_wiki_material_projection(
        existing=[{"name": "I1", "stable_line_key": "L1", "material_code": "M1"}],
        parsed_preview={
            "material_rows": [
                {"source_row": 2, "material_code": "M1", "quantity": "6", "unit": "件"},
                {"source_row": 3, "material_code": "M1", "quantity": "4", "unit": "件"},
            ],
            "groups": [
                _packing_group(
                    "package-1",
                    [2, 3],
                    net="8",
                    gross="10",
                    volume="0.1",
                    count_once_by_field={
                        "net_weight_kg": True,
                        "gross_weight_kg": True,
                        "volume_m3": False,
                    },
                )
            ],
        },
    )

    row = projection["incoming"][0]
    assert row["physical_status"] == "incomplete"
    assert row["physical_missing_rows"] == [2, 3]
    assert "net_weight_kg" not in row
    assert "gross_weight_kg" not in row
    assert "volume_m3" not in row


def test_wiki_projection_withholds_all_physical_values_when_one_sku_row_is_incomplete() -> None:
    projection = build_wiki_material_projection(
        existing=[{"name": "I1", "stable_line_key": "L1", "material_code": "M1"}],
        parsed_preview={
            "material_rows": [
                {"source_row": 2, "material_code": "M1", "quantity": "96", "unit": "件"},
                {"source_row": 3, "material_code": "M1", "quantity": "4", "unit": "件"},
            ],
            "groups": [
                _packing_group("package-1", [2], net="90", gross="100", volume="0.4"),
                _packing_group("package-2", [3], net=None, gross="0", volume=None),
            ],
        },
    )

    incoming = projection["incoming"][0]
    assert incoming["actual_shipped_qty"] == "100"
    assert incoming["physical_status"] == "incomplete"
    assert incoming["physical_missing_rows"] == [3]
    assert "net_weight_kg" not in incoming
    assert "gross_weight_kg" not in incoming
    assert "volume_m3" not in incoming


def test_wiki_projection_keeps_consistent_project_and_sums_only_explicit_chargeable_weight() -> None:
    projection = build_wiki_material_projection(
        existing=[{"name": "I1", "stable_line_key": "L1", "material_code": "M1"}],
        parsed_preview={
            "material_rows": [
                {
                    "source_row": 2,
                    "material_code": "M1",
                    "quantity": "6",
                    "unit": "件",
                    "chargeable_weight_kg": "7",
                    "project_collection": "指环扣",
                },
                {
                    "source_row": 3,
                    "material_code": "M1",
                    "quantity": "4",
                    "unit": "件",
                    "chargeable_weight_kg": "5",
                    "project_collection": "指环扣",
                },
            ],
            "groups": [
                _packing_group("package-1", [2], net="5", gross="6", volume="0.02"),
                _packing_group("package-2", [3], net="3", gross="4", volume="0.01"),
            ],
        },
    )

    incoming = projection["incoming"][0]
    assert incoming["project_collection"] == "指环扣"
    assert incoming["chargeable_weight_kg"] == "12"

    missing_explicit = build_wiki_material_projection(
        existing=[{"name": "I1", "stable_line_key": "L1", "material_code": "M1"}],
        parsed_preview={
            "material_rows": [
                {"source_row": 2, "material_code": "M1", "quantity": "6", "chargeable_weight_kg": "7"},
                {"source_row": 3, "material_code": "M1", "quantity": "4", "chargeable_weight_kg": None},
            ],
            "groups": [
                _packing_group("package-1", [2], net="5", gross="6", volume="0.02"),
                _packing_group("package-2", [3], net="3", gross="4", volume="0.01"),
            ],
        },
    )["incoming"][0]
    assert "chargeable_weight_kg" not in missing_explicit


def test_wiki_projection_requires_manual_values_for_cross_sku_package_group() -> None:
    projection = build_wiki_material_projection(
        existing=[
            {"name": "I1", "stable_line_key": "L1", "material_code": "M1"},
            {"name": "I2", "stable_line_key": "L2", "material_code": "M2"},
        ],
        parsed_preview={
            "material_rows": [
                {"source_row": 2, "material_code": "M1", "quantity": "10", "unit": "件"},
                {"source_row": 3, "material_code": "M2", "quantity": "20", "unit": "件"},
            ],
            "groups": [_packing_group("package-1", [2, 3], net="25", gross="30", volume="0.12")],
        },
    )

    assert len(projection["shared_groups"]) == 1
    shared = projection["shared_groups"][0]
    assert shared["group_id"] == "package-1"
    assert [row["material_code"] for row in shared["participants"]] == ["M1", "M2"]
    assert shared["metrics"] == {
        "net_weight_kg": {"value": "25", "precision": 0},
        "gross_weight_kg": {"value": "30", "precision": 0},
        "volume_m3": {"value": "0.12", "precision": 2},
    }
    assert all(row["physical_status"] == "allocation_required" for row in projection["incoming"])
    assert all("gross_weight_kg" not in row for row in projection["incoming"])


def test_incomplete_cross_sku_group_does_not_block_quantity_only_import() -> None:
    projection = build_wiki_material_projection(
        existing=[
            {"name": "I1", "stable_line_key": "L1", "material_code": "M1"},
            {"name": "I2", "stable_line_key": "L2", "material_code": "M2"},
        ],
        parsed_preview={
            "material_rows": [
                {"source_row": 2, "material_code": "M1", "quantity": "10", "unit": "件"},
                {"source_row": 3, "material_code": "M2", "quantity": "20", "unit": "件"},
            ],
            "groups": [_packing_group("package-1", [2, 3], net="25", gross=None, volume="0.12")],
        },
    )

    assert projection["shared_groups"][0]["allocation_required"] is False
    assert all(row["physical_status"] == "incomplete" for row in projection["incoming"])

    resolved, error = apply_wiki_group_allocations(projection, {})

    assert error is None
    assert [row["actual_shipped_qty"] for row in resolved] == ["10", "20"]
    assert all("net_weight_kg" not in row for row in resolved)


def test_wiki_projection_requires_confirmation_for_suggested_same_sku_group() -> None:
    projection = build_wiki_material_projection(
        existing=[{"name": "I1", "stable_line_key": "L1", "material_code": "M1"}],
        parsed_preview={
            "material_rows": [
                {"source_row": 2, "material_code": "M1", "quantity": "6", "unit": "件"},
                {"source_row": 3, "material_code": "M1", "quantity": "4", "unit": "件"},
            ],
            "groups": [
                _packing_group(
                    "package-1",
                    [2, 3],
                    net="8",
                    gross="10",
                    volume="0.03",
                    needs_confirmation=True,
                    count_once=False,
                )
            ],
        },
    )

    assert projection["incoming"][0]["physical_status"] == "group_confirmation_required"
    assert projection["confirmation_groups"] == [
        {
            "group_id": "package-1",
            "row_numbers": [2, 3],
            "material_codes": ["M1"],
            "metrics": {
                "net_weight_kg": {"value": "8", "precision": 0},
                "gross_weight_kg": {"value": "10", "precision": 0},
                "volume_m3": {"value": "0.03", "precision": 2},
            },
        }
    ]


def test_wiki_projection_exposes_conflicting_source_units_for_confirmation() -> None:
    projection = build_wiki_material_projection(
        existing=[{"name": "I1", "stable_line_key": "L1", "material_code": "M1"}],
        parsed_preview={
            "material_rows": [
                {"source_row": 2, "material_code": "M1", "quantity": "6", "unit": "件"},
                {"source_row": 3, "material_code": "M1", "quantity": "4", "unit": "箱"},
            ],
            "groups": [
                _packing_group("package-1", [2], net="5", gross="6", volume="0.02"),
                _packing_group("package-2", [3], net="3", gross="4", volume="0.01"),
            ],
        },
    )

    assert projection["incoming"][0]["source_conflicts"] == [
        {"field": "shipped_uom", "options": ["件", "箱"]}
    ]


def test_legacy_target_without_stored_key_uses_database_row_identity() -> None:
    result = build_material_import_preview(
        existing=[{"name": "I1", "stable_line_key": "", "material_code": "M1", "source_doc_no": "PO1", "excel_row_no": 2}],
        incoming=[{"source_row": 2, "source_line_no": 2, "source_doc_no": "PO1", "material_code": "M1", "actual_shipped_qty": 9}],
        source={"kind": "manual_xlsx"},
    )

    assert result["rows"][0]["target_stable_line_key"] == "legacy:I1"
    assert result["rows"][0]["candidates"][0]["stable_line_key"] == "legacy:I1"


def test_source_line_disambiguates_duplicate_sku_in_same_approval() -> None:
    result = build_material_import_preview(
        existing=[
            {
                "name": "I1",
                "stable_line_key": "L1",
                "material_code": "M1",
                "source_doc_no": "PO1",
                "excel_row_no": 4,
            },
            {
                "name": "I2",
                "stable_line_key": "L2",
                "material_code": "M1",
                "source_doc_no": "PO1",
                "excel_row_no": 5,
            },
        ],
        incoming=[
            {
                "source_row": 9,
                "source_line_no": 5,
                "material_code": "M1",
                "source_doc_no": "PO1",
                "actual_shipped_qty": 9,
            }
        ],
        source={"kind": "manual_xlsx", "revision": "R1"},
    )

    assert result["rows"][0]["match_status"] == "matched"
    assert result["rows"][0]["target_stable_line_key"] == "L2"


def test_provided_approval_and_source_line_never_fall_back_to_sku_only() -> None:
    existing = [
        {
            "name": "I1",
            "stable_line_key": "L1",
            "material_code": "M1",
            "source_doc_no": "PO1",
            "excel_row_no": 4,
        }
    ]
    wrong_approval = build_material_import_preview(
        existing,
        [{"source_row": 9, "source_line_no": 4, "material_code": "M1", "source_doc_no": "PO-X"}],
        {"kind": "manual_xlsx"},
    )
    wrong_line = build_material_import_preview(
        existing,
        [
            {
                "source_row": 9,
                "source_line_no": 99,
                "material_code": "M1",
                "source_doc_no": "PO1",
            }
        ],
        {"kind": "manual_xlsx"},
    )

    assert wrong_approval["rows"][0]["match_status"] == "unmatched"
    assert wrong_line["rows"][0]["match_status"] == "unmatched"

    missing_identity = build_material_import_preview(
        existing,
        [{"source_row": 4, "source_line_no": 4, "material_code": "M1"}],
        {"kind": "manual_xlsx"},
    )
    assert missing_identity["rows"][0]["match_status"] == "unmatched"


def test_preview_classifies_supplements_conflicts_and_unmatched_rows() -> None:
    result = build_material_import_preview(
        existing=[
            {"name": "I1", "stable_line_key": "L1", "material_code": "M1", "source_doc_no": "PO1", "excel_row_no": 2, "gross_weight_kg": ""},
            {"name": "I2", "stable_line_key": "L2", "material_code": "M2", "source_doc_no": "PO2", "excel_row_no": 3, "gross_weight_kg": 10},
        ],
        incoming=[
            {"source_row": 2, "source_line_no": 2, "source_doc_no": "PO1", "material_code": "M1", "gross_weight_kg": 8},
            {"source_row": 3, "source_line_no": 3, "source_doc_no": "PO2", "material_code": "M2", "gross_weight_kg": 12},
            {"source_row": 4, "source_line_no": 4, "source_doc_no": "PO-X", "material_code": "UNKNOWN", "gross_weight_kg": 5},
        ],
        source={"kind": "manual_xlsx"},
    )

    assert [row["classification"] for row in result["rows"]] == [
        "supplement",
        "conflict",
        "unmatched",
    ]
    assert result["summary"]["supplement"] == 1
    assert result["summary"]["conflict"] == 1
    assert result["summary"]["unmatched"] == 1


def test_blank_excel_shipping_quantity_never_clears_current_value() -> None:
    changes = build_field_changes(
        existing={"actual_shipped_qty": 17, "actual_shipped_qty_mode": "MANUAL_CONFIRMED"},
        incoming={"actual_shipped_qty": ""},
    )

    assert changes == []


def test_field_changes_never_offer_stable_identity_updates() -> None:
    changes = build_field_changes(
        existing={"stable_line_key": "L1", "gross_weight_kg": 10},
        incoming={"stable_line_key": "EVIL", "gross_weight_kg": 12},
    )

    assert changes == [
        {"field": "gross_weight_kg", "old": 10, "new": 12, "conflict": True}
    ]


def test_excel_supplement_never_overwrites_oa_purchase_facts() -> None:
    changes = build_field_changes(
        existing={
            "material_code": "OA-SKU",
            "product_name": "OA 物料",
            "quantity": 34,
            "unit_price": 25,
            "goods_value": 850,
            "gross_weight_kg": "",
        },
        incoming={
            "material_code": "OA-SKU",
            "product_name": "Excel 名称",
            "quantity": 99,
            "unit_price": 1,
            "goods_value": 99,
            "gross_weight_kg": 735.6,
        },
    )

    assert changes == [
        {"field": "gross_weight_kg", "old": "", "new": 735.6, "conflict": False}
    ]


def test_frappe_default_zero_is_empty_for_positive_supplement_fields() -> None:
    assert build_field_changes(
        existing={"gross_weight_kg": 0.0, "volume_m3": 0},
        incoming={"gross_weight_kg": 735.6, "volume_m3": 1.5337},
    ) == [
        {"field": "gross_weight_kg", "old": 0.0, "new": 735.6, "conflict": False},
        {"field": "volume_m3", "old": 0, "new": 1.5337, "conflict": False},
    ]


def test_nonpositive_net_weight_is_not_offered_for_import() -> None:
    assert build_field_changes(
        existing={"net_weight_kg": 0},
        incoming={"net_weight_kg": -1},
    ) == []


def test_preview_revision_is_signed_and_bound_to_preview_hash() -> None:
    claims = {
        "batch": "B1",
        "version": "V1",
        "kind": "manual_attachment",
        "id": "FILE-1",
        "source_hash": "a" * 64,
        "sheet": "油漆",
        "preview_hash": "b" * 64,
    }
    token = encode_material_preview_revision(claims, signing_key=b"secret")

    assert decode_material_preview_revision(token, signing_key=b"secret") == claims
    assert decode_material_preview_revision(token + "x", signing_key=b"secret") == {}


def test_trusted_preview_binds_batch_version_sheet_and_source_hash() -> None:
    result = preview_material_import(
        "B1",
        "manual_xlsx",
        "FILE-1",
        sheet_name="油漆",
        repository=FakeRepository(),
        resolver=_resolver_with_quantity(),
        signing_key=b"secret",
    )

    claims = decode_material_preview_revision(result["preview_revision"], signing_key=b"secret")
    assert result["rows"][0]["changes"][0]["field"] == "actual_shipped_qty"
    assert result["source_totals"] == {"gross_weight_kg": "4197.4", "volume_m3": "8.74"}
    assert claims["batch"] == "B1"
    assert claims["version"] == "V1"
    assert claims["sheet"] == "油漆"
    assert claims["source_hash"] == "a" * 64


def test_wiki_preview_uses_batch_projection_and_exposes_source_diagnostics() -> None:
    repository = FakeRepository()
    repository.items[0].update({"material_code": "M1", "source_doc_no": ""})

    result = preview_material_import(
        "B1",
        "wiki_sheet",
        "WB-1:ST-1",
        repository=repository,
        resolver=_wiki_resolver(),
        signing_key=b"secret",
    )

    assert result["rows"][0]["match_status"] == "matched"
    assert result["rows"][0]["incoming"]["actual_shipped_qty"] == "10"
    assert result["rows"][0]["incoming"]["net_weight_kg"] == "8"
    assert result["rows"][0]["source_rows"] == [2, 3]
    assert result["rows"][0]["physical_status"] == "complete"
    assert result["out_of_batch"] == [
        {"source_row": 4, "material_code": "OUTSIDE", "source_doc_no": "", "quantity": "2"}
    ]
    assert result["summary"]["out_of_batch"] == 1
    assert result["source"]["source_updated_at"] == "2026-09-08 09:00:00"


def test_wiki_preview_exposes_parser_blockers_and_requires_acknowledgement() -> None:
    repository = FakeRepository()
    repository.items[0].update({"material_code": "M1", "source_doc_no": "", "actual_shipped_qty": 0})

    preview = preview_material_import(
        "B1",
        "wiki_sheet",
        "WB-1:ST-1",
        repository=repository,
        resolver=_mismatch_wiki_resolver(),
        signing_key=b"secret",
    )

    assert preview["source_validation"]["blocking"][0]["code"] == "total_mismatch"
    assert preview["source_validation"]["warnings"][0]["code"] == "test_warning"
    blocked = apply_material_import(
        "B1",
        preview["preview_revision"],
        {},
        "EDIT-1",
        "BM1",
        repository=repository,
        resolver=_mismatch_wiki_resolver(),
        signing_key=b"secret",
    )
    assert blocked["ok"] is False
    assert blocked["code"] == "SOURCE_VALIDATION_CONFIRMATION_REQUIRED"
    assert repository.writes == []

    applied = apply_material_import(
        "B1",
        preview["preview_revision"],
        {"source_validation": {"total_mismatch:gross_weight_kg": True}},
        "EDIT-1",
        "BM1",
        repository=repository,
        resolver=_mismatch_wiki_resolver(),
        signing_key=b"secret",
    )
    assert applied["ok"] is True


def test_apply_requires_explicit_conflict_choice_and_sets_quantity_provenance() -> None:
    repository = FakeRepository()
    preview = preview_material_import(
        "B1",
        "manual_xlsx",
        "FILE-1",
        sheet_name="油漆",
        repository=repository,
        resolver=_resolver_with_quantity(),
        signing_key=b"secret",
    )

    blocked = apply_material_import(
        "B1",
        preview["preview_revision"],
        {},
        "EDIT-1",
        "BM1",
        repository=repository,
        resolver=_resolver_with_quantity(),
        signing_key=b"secret",
    )
    assert blocked["ok"] is False
    assert blocked["code"] == "CONFLICT_DECISION_REQUIRED"
    assert repository.writes == []

    applied = apply_material_import(
        "B1",
        preview["preview_revision"],
        {"fields": {"9": {"actual_shipped_qty": "use_source"}}},
        "EDIT-1",
        "BM1",
        repository=repository,
        resolver=_resolver_with_quantity(),
        signing_key=b"secret",
    )
    assert applied["ok"] is True
    assert repository.writes[0][0] == "I1"
    assert repository.writes[0][1]["actual_shipped_qty"] == 15
    assert repository.writes[0][1]["actual_shipped_qty_mode"] == "EXPLICIT_SOURCE"
    assert repository.writes[0][1]["actual_shipped_qty_source_revision"] == "a" * 64
    assert repository.commits == 1


def test_apply_rejects_changed_source_before_writing() -> None:
    repository = FakeRepository()
    preview = preview_material_import(
        "B1",
        "manual_xlsx",
        "FILE-1",
        sheet_name="油漆",
        repository=repository,
        resolver=_resolver_with_quantity(),
        signing_key=b"secret",
    )

    result = apply_material_import(
        "B1",
        preview["preview_revision"],
        {"fields": {"9": {"actual_shipped_qty": "use_source"}}},
        "EDIT-1",
        "BM1",
        repository=repository,
        resolver=_resolver_with_quantity(source_hash="c" * 64),
        signing_key=b"secret",
    )

    assert result["ok"] is False
    assert result["source_changed"] is True
    assert repository.writes == []
    assert repository.rollbacks == 1


def test_apply_rejects_batch_changed_after_preview_before_writing() -> None:
    repository = FakeRepository()
    preview = preview_material_import(
        "B1",
        "manual_xlsx",
        "FILE-1",
        repository=repository,
        resolver=_resolver_with_quantity(),
        signing_key=b"secret",
    )
    repository.context["batch_modified"] = "BM2"

    result = apply_material_import(
        "B1",
        preview["preview_revision"],
        {"fields": {"9": {"actual_shipped_qty": "use_source"}}},
        "EDIT-1",
        "BM1",
        repository=repository,
        resolver=_resolver_with_quantity(),
        signing_key=b"secret",
    )

    assert result["code"] == "BATCH_VERSION_CHANGED"
    assert repository.writes == []
    assert repository.commits == 0
    assert repository.rollbacks == 1


def test_apply_wiki_sheet_writes_only_current_batch_materials() -> None:
    repository = FakeRepository()
    repository.items[0].update(
        {"material_code": "M1", "source_doc_no": "", "actual_shipped_qty": 0, "shipped_uom": ""}
    )
    preview = preview_material_import(
        "B1",
        "wiki_sheet",
        "WB-1:ST-1",
        repository=repository,
        resolver=_wiki_resolver(),
        signing_key=b"secret",
    )

    result = apply_material_import(
        "B1",
        preview["preview_revision"],
        {},
        "EDIT-1",
        "BM1",
        repository=repository,
        resolver=_wiki_resolver(),
        signing_key=b"secret",
    )

    assert result["ok"] is True
    assert [item_name for item_name, _updates, _audit in repository.writes] == ["I1"]
    assert all("OUTSIDE" not in str(entry) for entry in repository.writes)


def test_apply_merges_two_projected_rows_selected_for_the_same_target() -> None:
    repository = FakeRepository()
    repository.items = [
        {"name": "I1", "stable_line_key": "L1", "material_code": "M1", "source_doc_no": "PO1"},
        {"name": "I2", "stable_line_key": "L2", "material_code": "M1", "source_doc_no": "PO2"},
    ]

    def resolver(**_kwargs):
        return {
            "source_hash": "3" * 64,
            "source": {
                "source_kind": "wiki_sheet",
                "source_id": "WB-1:ST-DUPLICATE",
                "source_label": "重复目标",
                "sheet_name": "重复目标",
            },
            "preview": {
                "material_rows": [
                    {"source_row": 2, "source_doc_no": "PO1", "material_code": "M1", "quantity": "6"},
                    {"source_row": 3, "source_doc_no": "", "material_code": "M1", "quantity": "4"},
                ],
                "groups": [
                    _packing_group("package-1", [2], net="5", gross="6", volume="0.02"),
                    _packing_group("package-2", [3], net="3", gross="4", volume="0.01"),
                ],
            },
        }

    preview = preview_material_import(
        "B1",
        "wiki_sheet",
        "WB-1:ST-DUPLICATE",
        repository=repository,
        resolver=resolver,
        signing_key=b"secret",
    )
    blank_row = next(row for row in preview["rows"] if row["match_status"] == "choice_required")

    merged_preview = apply_material_import(
        "B1",
        preview["preview_revision"],
        {"matches": {str(blank_row["source_row"]): "L1"}},
        "EDIT-1",
        "BM1",
        repository=repository,
        resolver=resolver,
        signing_key=b"secret",
    )

    assert merged_preview["ok"] is False
    assert merged_preview["code"] == "MERGED_PREVIEW_CONFIRMATION_REQUIRED"
    assert merged_preview["merged_preview"]["rows"][0]["incoming"]["actual_shipped_qty"] == "10"
    assert repository.writes == []

    result = apply_material_import(
        "B1",
        preview["preview_revision"],
        {
            "matches": {str(blank_row["source_row"]): "L1"},
            "merged_preview_hash": merged_preview["merged_preview_hash"],
        },
        "EDIT-1",
        "BM1",
        repository=repository,
        resolver=resolver,
        signing_key=b"secret",
    )

    assert result["ok"] is True
    assert len(repository.writes) == 1
    assert repository.writes[0][0] == "I1"
    assert repository.writes[0][1]["actual_shipped_qty"] == "10"
    assert repository.writes[0][1]["net_weight_kg"] == "8"
    assert repository.writes[0][1]["gross_weight_kg"] == "10"
    assert repository.writes[0][1]["volume_m3"] == "0.03"


def test_apply_withholds_all_physical_values_when_a_merged_source_row_is_incomplete() -> None:
    repository = FakeRepository()
    repository.items = [
        {"name": "I1", "stable_line_key": "L1", "material_code": "M1", "source_doc_no": "PO1"},
        {"name": "I2", "stable_line_key": "L2", "material_code": "M1", "source_doc_no": "PO2"},
    ]

    def resolver(**_kwargs):
        return {
            "source_hash": "4" * 64,
            "source": {
                "source_kind": "wiki_sheet",
                "source_id": "WB-1:ST-INCOMPLETE-MERGE",
                "source_label": "不完整合并",
                "sheet_name": "不完整合并",
            },
            "preview": {
                "material_rows": [
                    {"source_row": 2, "source_doc_no": "PO1", "material_code": "M1", "quantity": "6"},
                    {"source_row": 3, "source_doc_no": "", "material_code": "M1", "quantity": "4"},
                ],
                "groups": [_packing_group("package-1", [2], net="5", gross="6", volume="0.02")],
            },
        }

    preview = preview_material_import(
        "B1", "wiki_sheet", "WB-1:ST-INCOMPLETE-MERGE",
        repository=repository, resolver=resolver, signing_key=b"secret",
    )
    choice_row = next(row for row in preview["rows"] if row["match_status"] == "choice_required")
    merged_preview = apply_material_import(
        "B1",
        preview["preview_revision"],
        {"matches": {str(choice_row["source_row"]): "L1"}},
        "EDIT-1",
        "BM1",
        repository=repository,
        resolver=resolver,
        signing_key=b"secret",
    )
    result = apply_material_import(
        "B1",
        preview["preview_revision"],
        {
            "matches": {str(choice_row["source_row"]): "L1"},
            "merged_preview_hash": merged_preview["merged_preview_hash"],
        },
        "EDIT-1",
        "BM1",
        repository=repository,
        resolver=resolver,
        signing_key=b"secret",
    )

    assert result["ok"] is True
    updates = repository.writes[0][1]
    assert updates["actual_shipped_qty"] == "10"
    assert not {"net_weight_kg", "gross_weight_kg", "volume_m3"}.intersection(updates)


def test_apply_rejects_conflicting_units_when_selected_rows_merge_to_one_target() -> None:
    repository = FakeRepository()
    repository.items = [
        {"name": "I1", "stable_line_key": "L1", "material_code": "M1", "source_doc_no": "PO1"},
        {"name": "I2", "stable_line_key": "L2", "material_code": "M1", "source_doc_no": "PO2"},
    ]

    def resolver(**_kwargs):
        return {
            "source_hash": "5" * 64,
            "source": {
                "source_kind": "wiki_sheet",
                "source_id": "WB-1:ST-UNIT-CONFLICT",
                "source_label": "单位冲突",
                "sheet_name": "单位冲突",
            },
            "preview": {
                "material_rows": [
                    {"source_row": 2, "source_doc_no": "PO1", "material_code": "M1", "quantity": "6", "unit": "桶"},
                    {"source_row": 3, "source_doc_no": "", "material_code": "M1", "quantity": "4", "unit": "件"},
                ],
                "groups": [
                    _packing_group("package-1", [2], net="5", gross="6", volume="0.02"),
                    _packing_group("package-2", [3], net="3", gross="4", volume="0.01"),
                ],
            },
        }

    preview = preview_material_import(
        "B1", "wiki_sheet", "WB-1:ST-UNIT-CONFLICT",
        repository=repository, resolver=resolver, signing_key=b"secret",
    )
    choice_row = next(row for row in preview["rows"] if row["match_status"] == "choice_required")
    merged_preview = apply_material_import(
        "B1",
        preview["preview_revision"],
        {"matches": {str(choice_row["source_row"]): "L1"}},
        "EDIT-1",
        "BM1",
        repository=repository,
        resolver=resolver,
        signing_key=b"secret",
    )

    assert merged_preview["code"] == "MERGED_PREVIEW_CONFIRMATION_REQUIRED"
    merged_row = merged_preview["merged_preview"]["rows"][0]
    assert merged_row["source_conflicts"] == [
        {"field": "shipped_uom", "options": ["件", "桶"], "current": None}
    ]

    result = apply_material_import(
        "B1",
        preview["preview_revision"],
        {
            "matches": {str(choice_row["source_row"]): "L1"},
            "merged_preview_hash": merged_preview["merged_preview_hash"],
            "merged_source_fields": {str(merged_row["source_row"]): {"shipped_uom": "桶"}},
        },
        "EDIT-1",
        "BM1",
        repository=repository,
        resolver=resolver,
        signing_key=b"secret",
    )
    assert result["ok"] is True
    assert repository.writes[0][1]["shipped_uom"] == "桶"


def test_apply_rejects_premerge_conflict_choice_for_a_new_merged_value() -> None:
    repository = FakeRepository()
    repository.items = [
        {
            "name": "I1",
            "stable_line_key": "L1",
            "material_code": "M1",
            "source_doc_no": "PO1",
            "actual_shipped_qty": 5,
        },
        {"name": "I2", "stable_line_key": "L2", "material_code": "M1", "source_doc_no": "PO2"},
    ]

    def resolver(**_kwargs):
        return {
            "source_hash": "6" * 64,
            "source": {
                "source_kind": "wiki_sheet",
                "source_id": "WB-1:ST-MERGED-CONFLICT",
                "source_label": "合并冲突",
                "sheet_name": "合并冲突",
            },
            "preview": {
                "material_rows": [
                    {"source_row": 2, "source_doc_no": "PO1", "material_code": "M1", "quantity": "6"},
                    {"source_row": 3, "source_doc_no": "", "material_code": "M1", "quantity": "4"},
                ],
                "groups": [
                    _packing_group("package-1", [2], net="5", gross="6", volume="0.02"),
                    _packing_group("package-2", [3], net="3", gross="4", volume="0.01"),
                ],
            },
        }

    preview = preview_material_import(
        "B1", "wiki_sheet", "WB-1:ST-MERGED-CONFLICT",
        repository=repository, resolver=resolver, signing_key=b"secret",
    )
    matched_row = next(row for row in preview["rows"] if row["match_status"] == "matched")
    choice_row = next(row for row in preview["rows"] if row["match_status"] == "choice_required")
    merged_preview = apply_material_import(
        "B1",
        preview["preview_revision"],
        {
            "matches": {str(choice_row["source_row"]): "L1"},
            "fields": {str(matched_row["source_row"]): {"actual_shipped_qty": "use_source"}},
        },
        "EDIT-1",
        "BM1",
        repository=repository,
        resolver=resolver,
        signing_key=b"secret",
    )
    merged_row = merged_preview["merged_preview"]["rows"][0]

    blocked = apply_material_import(
        "B1",
        preview["preview_revision"],
        {
            "matches": {str(choice_row["source_row"]): "L1"},
            "fields": {str(matched_row["source_row"]): {"actual_shipped_qty": "use_source"}},
            "merged_preview_hash": merged_preview["merged_preview_hash"],
        },
        "EDIT-1",
        "BM1",
        repository=repository,
        resolver=resolver,
        signing_key=b"secret",
    )
    assert blocked["code"] == "CONFLICT_DECISION_REQUIRED"
    assert blocked["source_row"] == merged_row["source_row"]
    assert repository.writes == []

    result = apply_material_import(
        "B1",
        preview["preview_revision"],
        {
            "matches": {str(choice_row["source_row"]): "L1"},
            "fields": {str(merged_row["source_row"]): {"actual_shipped_qty": "use_source"}},
            "merged_preview_hash": merged_preview["merged_preview_hash"],
        },
        "EDIT-1",
        "BM1",
        repository=repository,
        resolver=resolver,
        signing_key=b"secret",
    )

    assert result["ok"] is True
    assert repository.writes[0][1]["actual_shipped_qty"] == "10"


def test_apply_repreviews_a_single_row_after_the_user_selects_its_target() -> None:
    repository = FakeRepository()
    repository.items = [
        {
            "name": "I1",
            "stable_line_key": "L1",
            "material_code": "M1",
            "source_doc_no": "PO1",
            "actual_shipped_qty": 5,
        },
        {
            "name": "I2",
            "stable_line_key": "L2",
            "material_code": "M1",
            "source_doc_no": "PO2",
            "actual_shipped_qty": 7,
        },
    ]

    def resolver(**_kwargs):
        return {
            "source_hash": "7" * 64,
            "source": {
                "source_kind": "wiki_sheet",
                "source_id": "WB-1:ST-SINGLE-CHOICE",
                "source_label": "单行选择",
                "sheet_name": "单行选择",
            },
            "preview": {
                "material_rows": [
                    {"source_row": 2, "source_doc_no": "", "material_code": "M1", "quantity": "10"},
                ],
                "groups": [
                    _packing_group("package-1", [2], net="5", gross="6", volume="0.02"),
                ],
            },
        }

    preview = preview_material_import(
        "B1", "wiki_sheet", "WB-1:ST-SINGLE-CHOICE",
        repository=repository, resolver=resolver, signing_key=b"secret",
    )
    row = preview["rows"][0]
    assert row["match_status"] == "choice_required"

    selected_preview = apply_material_import(
        "B1",
        preview["preview_revision"],
        {"matches": {str(row["source_row"]): "L1"}},
        "EDIT-1",
        "BM1",
        repository=repository,
        resolver=resolver,
        signing_key=b"secret",
    )

    assert selected_preview["code"] == "MERGED_PREVIEW_CONFIRMATION_REQUIRED"
    selected_row = selected_preview["merged_preview"]["rows"][0]
    assert selected_row["changes"][0] == {
        "field": "actual_shipped_qty",
        "old": 5,
        "new": "10",
        "conflict": True,
    }
    assert repository.writes == []

    result = apply_material_import(
        "B1",
        preview["preview_revision"],
        {
            "matches": {str(row["source_row"]): "L1"},
            "merged_preview_hash": selected_preview["merged_preview_hash"],
            "fields": {str(selected_row["source_row"]): {"actual_shipped_qty": "use_source"}},
        },
        "EDIT-1",
        "BM1",
        repository=repository,
        resolver=resolver,
        signing_key=b"secret",
    )
    assert result["ok"] is True
    assert repository.writes[0][1]["actual_shipped_qty"] == "10"


def test_apply_wiki_sheet_requires_allocations_that_match_shared_group_totals() -> None:
    repository = FakeRepository()
    repository.items = [
        {"name": "I1", "stable_line_key": "L1", "material_code": "M1", "actual_shipped_qty": 0},
        {"name": "I2", "stable_line_key": "L2", "material_code": "M2", "actual_shipped_qty": 0},
    ]
    preview = preview_material_import(
        "B1",
        "wiki_sheet",
        "WB-1:ST-SHARED",
        repository=repository,
        resolver=_shared_wiki_resolver(),
        signing_key=b"secret",
    )

    result = apply_material_import(
        "B1",
        preview["preview_revision"],
        {
            "allocations": {
                "package-1": {
                    "|m1": {"net_weight_kg": "10", "gross_weight_kg": "12", "volume_m3": "0.05"},
                    "|m2": {"net_weight_kg": "15", "gross_weight_kg": "18", "volume_m3": "0.07"},
                }
            }
        },
        "EDIT-1",
        "BM1",
        repository=repository,
        resolver=_shared_wiki_resolver(),
        signing_key=b"secret",
    )

    assert result["ok"] is True
    writes = {item_name: updates for item_name, updates, _audit in repository.writes}
    assert writes["I1"]["actual_shipped_qty"] == "10"
    assert writes["I1"]["net_weight_kg"] == "10"
    assert writes["I1"]["gross_weight_kg"] == "12"
    assert writes["I1"]["volume_m3"] == "0.05"
    assert writes["I2"]["net_weight_kg"] == "15"
    assert writes["I2"]["gross_weight_kg"] == "18"
    assert writes["I2"]["volume_m3"] == "0.07"
    assert all("package-1" in audit["remark"] for _name, _updates, audit in repository.writes)
    assert repository.import_audits == [
        {
            "batch": "B1",
            "version": "V1",
            "source_kind": "wiki_sheet",
            "source_id": "WB-1:ST-SHARED",
            "workbook_id": "WB-1",
            "sheet_id": "ST-SHARED",
            "sheet": "合箱",
            "source_hash": "e" * 64,
            "source_rows": [2, 3],
            "source_groups": ["package-1"],
            "manual_choices": {
                    "matches": {},
                    "fields": {},
                    "source_fields": {},
                    "merged_source_fields": {},
                    "group_confirmations": {},
                "source_validation": {},
                "allocations": {
                    "package-1": {
                        "|m1": {"net_weight_kg": "10", "gross_weight_kg": "12", "volume_m3": "0.05"},
                        "|m2": {"net_weight_kg": "15", "gross_weight_kg": "18", "volume_m3": "0.07"},
                    }
                },
            },
            "writes": [
                {"item_name": "I1", "fields": ["actual_shipped_qty", "actual_shipped_qty_mode", "actual_shipped_qty_source_revision", "gross_weight_kg", "net_weight_kg", "shipped_uom", "volume_m3"]},
                {"item_name": "I2", "fields": ["actual_shipped_qty", "actual_shipped_qty_mode", "actual_shipped_qty_source_revision", "gross_weight_kg", "net_weight_kg", "shipped_uom", "volume_m3"]},
            ],
        }
    ]


def test_apply_wiki_sheet_rejects_incorrect_shared_group_allocation_without_writes() -> None:
    repository = FakeRepository()
    repository.items = [
        {"name": "I1", "stable_line_key": "L1", "material_code": "M1", "actual_shipped_qty": 0},
        {"name": "I2", "stable_line_key": "L2", "material_code": "M2", "actual_shipped_qty": 0},
    ]
    preview = preview_material_import(
        "B1",
        "wiki_sheet",
        "WB-1:ST-SHARED",
        repository=repository,
        resolver=_shared_wiki_resolver(),
        signing_key=b"secret",
    )

    result = apply_material_import(
        "B1",
        preview["preview_revision"],
        {
            "allocations": {
                "package-1": {
                    "|m1": {"net_weight_kg": "10", "gross_weight_kg": "12", "volume_m3": "0.05"},
                    "|m2": {"net_weight_kg": "15", "gross_weight_kg": "17", "volume_m3": "0.07"},
                }
            }
        },
        "EDIT-1",
        "BM1",
        repository=repository,
        resolver=_shared_wiki_resolver(),
        signing_key=b"secret",
    )

    assert result["ok"] is False
    assert result["code"] == "ALLOCATION_TOTAL_MISMATCH"
    assert result["group_id"] == "package-1"
    assert result["field"] == "gross_weight_kg"
    assert repository.writes == []
    assert repository.commits == 0


def test_apply_wiki_sheet_requires_and_validates_conflicting_source_unit_choice() -> None:
    repository = FakeRepository()
    repository.items[0].update(
        {"material_code": "M1", "source_doc_no": "", "actual_shipped_qty": 0, "shipped_uom": ""}
    )
    preview = preview_material_import(
        "B1",
        "wiki_sheet",
        "WB-1:ST-UNIT",
        repository=repository,
        resolver=_unit_conflict_wiki_resolver(),
        signing_key=b"secret",
    )

    blocked = apply_material_import(
        "B1",
        preview["preview_revision"],
        {},
        "EDIT-1",
        "BM1",
        repository=repository,
        resolver=_unit_conflict_wiki_resolver(),
        signing_key=b"secret",
    )
    assert blocked["ok"] is False
    assert blocked["code"] == "SOURCE_FIELD_CHOICE_REQUIRED"
    assert blocked["field"] == "shipped_uom"
    assert repository.writes == []

    applied = apply_material_import(
        "B1",
        preview["preview_revision"],
        {"source_fields": {"2,3": {"shipped_uom": "件"}}},
        "EDIT-1",
        "BM1",
        repository=repository,
        resolver=_unit_conflict_wiki_resolver(),
        signing_key=b"secret",
    )
    assert applied["ok"] is True
    assert repository.writes[0][1]["shipped_uom"] == "件"


def test_apply_wiki_sheet_requires_confirmation_for_suggested_group() -> None:
    repository = FakeRepository()
    repository.items[0].update(
        {"material_code": "M1", "source_doc_no": "", "actual_shipped_qty": 0, "shipped_uom": ""}
    )
    preview = preview_material_import(
        "B1",
        "wiki_sheet",
        "WB-1:ST-GROUP",
        repository=repository,
        resolver=_suggested_group_wiki_resolver(),
        signing_key=b"secret",
    )

    blocked = apply_material_import(
        "B1",
        preview["preview_revision"],
        {},
        "EDIT-1",
        "BM1",
        repository=repository,
        resolver=_suggested_group_wiki_resolver(),
        signing_key=b"secret",
    )
    assert blocked["ok"] is False
    assert blocked["code"] == "GROUP_CONFIRMATION_REQUIRED"
    assert repository.writes == []

    applied = apply_material_import(
        "B1",
        preview["preview_revision"],
        {"group_confirmations": {"package-1": True}},
        "EDIT-1",
        "BM1",
        repository=repository,
        resolver=_suggested_group_wiki_resolver(),
        signing_key=b"secret",
    )
    assert applied["ok"] is True
    assert repository.writes[0][1]["net_weight_kg"] == "8"
    assert repository.writes[0][1]["gross_weight_kg"] == "10"
    assert repository.writes[0][1]["volume_m3"] == "0.03"
