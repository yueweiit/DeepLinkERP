"""Original-value snapshots and post-calculation extra_json cache must stay compact."""
import json

from overseas_costing.services.logistics_settlement.item_metadata import (
    original_value_snapshot,
    persist_item_meta,
    prune_analysis_cache,
    prune_version_meta,
)
from overseas_costing.services.material_ai_selection_writer import write_rows
from overseas_costing.services.shipment_cost_service import shipment_value
from overseas_costing.tests.test_ai_row_review_regressions import preview
from overseas_costing.tests.test_settlement_writer import setup as settlement_fixture


def _bloated_item():
    nested = {
        "autofill_review": {"source_refs": [{"file": "packing.xlsx", "row": n, "cell": f"A{n}"} for n in range(1, 40)]},
        "ai_row_fields": {"gross_weight_kg": {"source_refs": [{"file": "packing.xlsx", "field_ranges": {"A1:Z99": {}}}]}},
        "logistics_row": {"purchase_fact": {"unit_price": 0.151, "purchase_currency": "人民币RMB",
                                           "source_doc_no": "PUR-1", "material_code": "FL000429"},
                          "purchase_fact_history": [{"unit_price": 0.15}]},
    }
    return {
        "name": "ITEM-1",
        "material_code": "FL000429",
        "product_name": "指环扣",
        "spec_model": "S1",
        "quantity": 100000,
        "unit": "个",
        "actual_shipped_qty": 96000,
        "shipped_uom": "个",
        "unit_price": 0.151,
        "purchase_currency": "人民币RMB",
        "goods_value": 14496,
        "source_doc_no": "PUR-1",
        "extra_json": json.dumps({
            **nested,
            "ai_fill_original_values": {"goods_value": 14496, "extra_json": json.dumps(nested)},
            "settlement_original_values": {"goods_value": 14496, "name": "ITEM-1", "extra_json": json.dumps(nested)},
        }, ensure_ascii=False),
    }


def test_original_snapshot_keeps_price_evidence_and_drops_nested_extra_json():
    snapshot = original_value_snapshot(_bloated_item())
    packed = json.dumps(snapshot, ensure_ascii=False)

    assert snapshot["goods_value"] == 14496
    assert snapshot["source_doc_no"] == "PUR-1"
    assert snapshot["unit_price"] == 0.151
    assert snapshot["material_code"] == "FL000429"
    assert "extra_json" not in snapshot
    assert "autofill_review" not in snapshot
    assert "source_refs" not in packed
    assert "field_ranges" not in packed
    assert "packing.xlsx" not in packed
    assert snapshot["ai_fill_original_values"]["goods_value"] == 14496
    assert "extra_json" not in snapshot["ai_fill_original_values"]


def test_persisted_item_meta_compacts_existing_bloated_originals():
    meta = json.loads(_bloated_item()["extra_json"])
    payload = persist_item_meta(meta)
    saved = json.loads(payload)

    assert saved["ai_fill_original_values"]["goods_value"] == 14496
    assert "extra_json" not in saved["ai_fill_original_values"]
    assert "extra_json" not in saved["settlement_original_values"]
    assert "source_refs" not in payload
    assert len(payload) < len(_bloated_item()["extra_json"]) / 2


def test_prune_after_calculation_drops_analysis_cache_and_keeps_valuation():
    meta = {
        "settlement_cargo": {"material_code": "FL000429", "quantity": 96000, "unit": "个"},
        "settlement_valuation": {"status": "automatic", "amount_rmb": "14496.000000",
                                 "input_fingerprint": "abc"},
        "ai_row_fields": {"gross_weight_kg": {"source_refs": [{"file": "packing.xlsx"}]}},
        "ai_row_selection": {"row_id": "R1", "source_refs": [{"file": "packing.xlsx"}]},
        "autofill_review": {"source_refs": [{"file": "packing.xlsx"}]},
        "packing_source_history": [{"previous": _bloated_item(), "evidence": {"source_refs": []}}],
        "ai_fill_original_values": {"goods_value": 14496, "extra_json": _bloated_item()["extra_json"]},
        "settlement_packing_missing": ["volume_m3"],
        "ai_row_packing_values": {"package_count": 10, "packaging_type": "箱"},
        "effective_logistics_source": {"fingerprint": "fp", "secret_path": "/tmp/file"},
    }

    pruned = prune_analysis_cache(meta)

    assert "ai_row_fields" not in pruned
    assert "ai_row_selection" not in pruned
    assert "autofill_review" not in pruned
    assert "packing_source_history" not in pruned
    assert pruned["settlement_valuation"]["amount_rmb"] == "14496.000000"
    assert pruned["settlement_cargo"]["quantity"] == 96000
    assert pruned["ai_fill_original_values"]["goods_value"] == 14496
    assert "extra_json" not in pruned["ai_fill_original_values"]
    assert pruned["settlement_packing_missing"] == ["volume_m3"]
    assert pruned["ai_row_packing_values"] == {"package_count": 10, "packaging_type": "箱"}
    assert pruned["effective_logistics_source"]["fingerprint"] == "fp"
    packed = json.dumps(pruned, ensure_ascii=False)
    assert "packing.xlsx" not in packed
    assert "secret_path" not in packed


def test_prune_version_meta_drops_application_history_not_adoption():
    meta = prune_version_meta({
        "ai_row_adoption": {"id": "PREVIEW", "goods": [{"material_code": "A"}]},
        "ai_row_applications": [{"preview_id": "P1", "changes": [{"fieldname": "x"} for _ in range(50)]}],
        "freight_settlement": {"policy": "shipment-freight-1"},
    })
    assert meta["ai_row_adoption"]["id"] == "PREVIEW"
    assert "ai_row_applications" not in meta
    assert meta["freight_settlement"]["policy"] == "shipment-freight-1"


def test_whole_table_replace_does_not_store_nested_extra_json():
    store, ledger, batch, version, item, *_ = settlement_fixture.__wrapped__()
    bloated = json.dumps({
        "purchase_evidence": {"document": "PUR-1"},
        "autofill_review": {"source_refs": [{"file": "packing.xlsx", "row": 1}]},
    })
    item = ledger.put("item", item["name"], {
        "spec_model": "S1", "stable_line_key": "LINE", "actual_shipped_qty": 2,
        "shipped_uom": "件", "extra_json": bloated,
    })
    source = {"material_code": "A", "spec_model": "S1", "stable_line_key": "LINE",
              "quantity": 2, "actual_shipped_qty": 2, "unit": "件", "shipped_uom": "件",
              "_review_origin": "source"}
    selected = preview([item], [{"proposal_id": "P", "proposal_type": "logistics_reconcile",
                                 "payload": {"rows": [source]}}], batch, version, mode="replace_all")

    new_version = write_rows(store, ledger, selected, {})
    saved = ledger.rows("item", version=new_version)[0]
    metadata = json.loads(saved["extra_json"])
    original = metadata["settlement_original_values"]
    fill = metadata.get("ai_fill_original_values") or {}

    assert shipment_value(saved)["status"] == "automatic"
    assert original["source_doc_no"] == "GOODS-PURCHASE"
    assert original["goods_value"] == 20
    assert "extra_json" not in original
    assert "extra_json" not in fill
    assert "autofill_review" not in original
    assert metadata["purchase_evidence"] == {"document": "PUR-1"}
    assert "packing.xlsx" not in saved["extra_json"]
