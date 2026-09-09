"""统一资料审核的来源清单和确定性提取测试。"""

from decimal import Decimal

import pytest

from overseas_costing.services.source_review_extract_service import (
    allocate_gross_weight,
    build_system_approval_proposals,
)
from overseas_costing.services.source_review_manifest_service import (
    prepare_source_manifest,
    source_progress_manifest,
)


def test_source_manifest_uses_stable_public_ids_and_keeps_approval_bodies_locked() -> None:
    raw = [
        {
            "source_kind": "approval_form",
            "source_id": "approval:PROC-1:form",
            "logical_source_id": "approval:PROC-1:form",
            "source_label": "国际物流审批正文",
            "approval_no": "LOG-001",
            "form_fields": {"重量": "4200"},
        },
        {
            "source_kind": "approval_attachment",
            "source_id": "ATT-LOCAL-NAME",
            "logical_source_id": "oa:PROC-1:FILE-9",
            "source_label": "packing.xlsx",
            "file_name": "packing.xlsx",
            "sheet_name": "发货明细",
            "source_hash": "hash-v1",
        },
    ]

    manifest = prepare_source_manifest(raw, selected_source_ids=[])

    approval, sheet = manifest
    assert approval["source_id"] == "approval:PROC-1:form"
    assert approval["locked"] is True
    assert approval["selected"] is True
    assert sheet["parent_source_id"] == "oa:PROC-1:FILE-9"
    assert sheet["source_id"].startswith("oa:PROC-1:FILE-9:sheet:")
    assert "ATT-LOCAL-NAME" not in sheet["source_id"]
    assert sheet["resolver_source_id"] == "ATT-LOCAL-NAME"
    assert sheet["selected"] is False


def test_source_manifest_rejects_unknown_or_unavailable_selection() -> None:
    raw = [{"source_kind": "manual_attachment", "source_id": "ATT-1", "file_name": "a.xlsx"}]

    with pytest.raises(ValueError, match="不属于当前批次"):
        prepare_source_manifest(raw, selected_source_ids=["ATT-OTHER"])

    with pytest.raises(ValueError, match="不可选"):
        prepare_source_manifest(
            [{**raw[0], "excluded": True, "exclude_reason": "审计专用"}],
            selected_source_ids=["ATT-1"],
        )


def test_archived_dingtalk_attachment_is_selectable_before_local_download() -> None:
    manifest = prepare_source_manifest(
        [
            {
                "source_kind": "approval_attachment",
                "source_id": "oa:PROC-1:FILE-1",
                "source_label": "装箱单.xlsx",
                "file_name": "装箱单.xlsx",
                "available": False,
                "can_download": True,
                "download_required": True,
            }
        ]
    )

    assert manifest[0]["selected"] is True
    assert manifest[0]["selectable"] is True
    assert manifest[0]["parse_method"] == "SYSTEM_EXCEL"


def test_progress_manifest_exposes_only_safe_source_metadata() -> None:
    manifest = prepare_source_manifest(
        [
            {
                "source_kind": "approval_comment",
                "source_id": "COMMENT-1",
                "source_label": "评论",
                "actor_name": "张三",
                "occurred_at": "2026-09-01 10:00:00",
                "comment_text": "不应返回浏览器",
                "file_url": "/private/files/secret.pdf",
            }
        ]
    )

    progress = source_progress_manifest(manifest)

    assert progress[0]["parse_method"] == "AI_TEXT"
    assert progress[0]["read_status"] == "NO_RESULT"
    assert progress[0]["actor_name"] == "张三"
    assert progress[0]["occurred_at"] == "2026-09-01 10:00:00"
    assert "comment_text" not in progress[0]
    assert "secret.pdf" not in str(progress[0])


def test_allocate_gross_weight_uses_decimal_and_last_row_absorbs_rounding() -> None:
    result = allocate_gross_weight(
        Decimal("4200"),
        [Decimal("1494"), Decimal("990"), Decimal("396"), Decimal("396"), Decimal("216")],
    )

    assert result == [
        Decimal("1796.907216"),
        Decimal("1190.721649"),
        Decimal("476.288660"),
        Decimal("476.288660"),
        Decimal("259.793815"),
    ]
    assert sum(result) == Decimal("4200.000000")


def test_logistics_approval_is_system_read_and_kg_quantity_becomes_net_weight() -> None:
    items = [
        {"name": "I1", "material_code": "SKU-1", "actual_shipped_qty": None, "net_weight_kg": None},
        {"name": "I2", "material_code": "SKU-2", "actual_shipped_qty": None, "net_weight_kg": None},
    ]
    source = {
        "source_kind": "approval_form",
        "source_id": "approval:PROC-1:form",
        "source_label": "国际物流审批正文",
        "process_instance_id": "PROC-1",
        "approval_no": "LOG-001",
        "approval_role": "international_logistics",
        "form_fields": {
            "货物信息": [
                {"物料编码": "SKU-1", "数量": "1494", "单位": "KG"},
                {"物料编码": "SKU-2", "数量": "990", "单位": "kg"},
            ],
            "重量Peso（KG）": "4,200 kg",
        },
    }

    proposals = build_system_approval_proposals(items, source, transport_mode="SEA")

    rows = [row for row in proposals if row["proposal_type"] == "item_update"]
    assert [row["payload"]["fields"]["actual_shipped_qty"] for row in rows] == ["1494", "990"]
    assert [row["payload"]["fields"]["net_weight_kg"] for row in rows] == ["1494", "990"]
    assert [row["payload"]["fields"]["gross_weight_kg"] for row in rows] == [
        "2526.086957",
        "1673.913043",
    ]
    assert all(row["result_origin"] == "SYSTEM" for row in rows)
    assert all(row["default_selected"] is True for row in rows)


def test_purchase_approval_is_readonly_matching_fact_and_creates_no_updates() -> None:
    proposals = build_system_approval_proposals(
        [{"name": "I1", "material_code": "SKU-1", "quantity": 10}],
        {
            "source_kind": "approval_form",
            "source_id": "approval:BUY-1:form",
            "approval_role": "purchase",
            "form_fields": {"采购明细": [{"物料编码": "SKU-1", "数量": 20}]},
        },
    )

    assert proposals == []


def test_non_kg_shipping_quantity_never_becomes_net_weight() -> None:
    proposals = build_system_approval_proposals(
        [{"name": "I1", "material_code": "SKU-1"}],
        {
            "source_kind": "approval_form",
            "source_id": "approval:LOG-1:form",
            "approval_role": "international_logistics",
            "form_fields": {
                "货物信息": [{"物料编码": "SKU-1", "数量": 12, "单位": "箱"}],
                "重量Peso（KG）": 4200,
            },
        },
    )

    fields = proposals[0]["payload"]["fields"]
    assert fields["actual_shipped_qty"] == "12"
    assert fields["shipped_uom"] == "箱"
    assert "net_weight_kg" not in fields
    assert "gross_weight_kg" not in fields


def test_snvq1vekp5_system_approval_values_and_gross_allocation_are_exact() -> None:
    quantities = [1494, 990, 396, 396, 216]
    items = [
        {"name": f"I{index}", "material_code": f"SKU-{index}"}
        for index in range(1, 6)
    ]
    source = {
        "source_kind": "approval_form",
        "source_id": "approval:SNVQ:form",
        "approval_role": "international_logistics",
        "form_fields": {
            "货物信息": [
                {"物料编码": f"SKU-{index}", "数量": quantity, "单位": "KG"}
                for index, quantity in enumerate(quantities, start=1)
            ],
            "重量Peso（KG）": 4200,
        },
    }

    proposals = build_system_approval_proposals(items, source)
    fields = [row["payload"]["fields"] for row in proposals]

    assert sum(Decimal(row["net_weight_kg"]) for row in fields) == Decimal("3492")
    assert [row["gross_weight_kg"] for row in fields] == [
        "1796.907216",
        "1190.721649",
        "476.288660",
        "476.288660",
        "259.793815",
    ]
    assert sum(Decimal(row["gross_weight_kg"]) for row in fields) == Decimal("4200.000000")
