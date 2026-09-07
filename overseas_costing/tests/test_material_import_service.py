"""物料 Excel 字段级预览与安全采用测试。"""

import pytest

from overseas_costing.services.material_import_service import (
    apply_material_import,
    build_field_changes,
    build_material_import_preview,
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
                "actual_shipped_qty": 17,
                "actual_shipped_qty_mode": "MANUAL_CONFIRMED",
                "shipped_uom": "桶",
            }
        ]
        self.writes = []
        self.commits = 0
        self.rollbacks = 0
        self.write_checks = []

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

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


def test_material_excel_accepts_only_bounded_xlsx_files() -> None:
    assert validate_material_workbook_metadata("packing.xlsx", 1024) is None
    with pytest.raises(ValueError, match="xlsx"):
        validate_material_workbook_metadata("packing.xlsm", 1024)
    with pytest.raises(ValueError, match="20 MB"):
        validate_material_workbook_metadata("packing.xlsx", 20 * 1024 * 1024 + 1)


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


def test_preview_keeps_duplicate_sku_rows_and_requires_line_choice() -> None:
    result = build_material_import_preview(
        existing=[
            {
                "name": "I1",
                "stable_line_key": "L1",
                "material_code": "FL000103",
                "source_doc_no": "PO1",
            },
            {
                "name": "I2",
                "stable_line_key": "L2",
                "material_code": "FL000103",
                "source_doc_no": "PO2",
            },
        ],
        incoming=[
            {
                "source_row": 9,
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
            {"name": "I1", "stable_line_key": "L1", "material_code": "M1", "source_doc_no": "PO1"},
            {"name": "I2", "stable_line_key": "L2", "material_code": "M1", "source_doc_no": "PO2"},
        ],
        incoming=[
            {"source_row": 2, "material_code": "M1", "source_doc_no": "PO2", "actual_shipped_qty": 9}
        ],
        source={"kind": "manual_xlsx", "revision": "R1"},
    )

    assert result["rows"][0]["match_status"] == "matched"
    assert result["rows"][0]["target_stable_line_key"] == "L2"


def test_legacy_target_without_stored_key_uses_database_row_identity() -> None:
    result = build_material_import_preview(
        existing=[{"name": "I1", "stable_line_key": "", "material_code": "M1"}],
        incoming=[{"source_row": 2, "material_code": "M1", "actual_shipped_qty": 9}],
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


def test_preview_classifies_supplements_conflicts_and_unmatched_rows() -> None:
    result = build_material_import_preview(
        existing=[
            {"name": "I1", "stable_line_key": "L1", "material_code": "M1", "gross_weight_kg": ""},
            {"name": "I2", "stable_line_key": "L2", "material_code": "M2", "gross_weight_kg": 10},
        ],
        incoming=[
            {"source_row": 2, "material_code": "M1", "gross_weight_kg": 8},
            {"source_row": 3, "material_code": "M2", "gross_weight_kg": 12},
            {"source_row": 4, "material_code": "UNKNOWN", "gross_weight_kg": 5},
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
