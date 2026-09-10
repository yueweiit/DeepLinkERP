"""Batch preview copies only explicit shipment/declaration facts."""
import copy
import json

from overseas_costing.services import air_sea_batch as adapter


def item(**values):
    return {"name": "I1", "modified": "2026-09-10", "material_code": "AA1", "product_name": "测试", "quantity": 8, "actual_shipped_qty": 3,
            "actual_shipped_qty_mode": "MANUAL_CONFIRMED", "shipped_uom": "套", "purchase_uom": "件",
            "unit_price": 99, "goods_value": 792, "purchase_currency": "RMB", **values}


def test_explicit_shipped_quantity_and_no_purchase_price_substitution():
    row = adapter.build_payload({"name": "B", "current_version": "V"}, [item()], None)["payload"]["rows"][0]
    assert row[20] == "3"
    assert row[4] == "套"
    assert row[25] == row[26] == ""


def test_purchase_approval_number_uses_workbench_provenance():
    row = adapter.build_payload({"name": "B"}, [item(source_doc_no="202609101234567890", purchase_order_no="PUR-ORD-0001")], None)["payload"]["rows"][0]
    assert row[0] == "202609101234567890"


def test_mxn_declared_value_stays_mxn_and_snapshot_totals_not_repeated():
    records = [item(customs_declared_value_mxn=200), item(name="I2", customs_declared_value_mxn=300)]
    snap = {"name": "S1", "total_gross_weight_kg": 50, "total_volume_m3": 2, "idempotency_key": "R1"}
    before = copy.deepcopy(records)
    result = adapter.build_payload({"name": "B", "current_version": "V"}, records, snap)
    payload = result["payload"]
    assert payload["currencies"]["declaredCurrency"] == "MXN"
    assert [row[26] for row in payload["rows"]] == ["200", "300"]
    assert payload["totals_override"] == {"grossWeight": "50", "volume": "2"}
    assert all(row[23] == "" for row in payload["rows"])
    assert records == before


def test_source_revision_tracks_item_change_not_only_header():
    header = {"name": "B", "modified": "x", "current_version": "V"}
    records = [item()]
    first = adapter.source_revision(header, records, None)
    records[0]["actual_shipped_qty"] = 2
    assert adapter.source_revision(header, records, None) != first


def test_settlement_cargo_resolves_quantity_without_old_purchase_fallback():
    result = adapter.build_payload({"name": "B"}, [item(extra_json='{"settlement_cargo":{"quantity":"5","unit":"箱"}}')], None)
    assert result["payload"]["rows"][0][20] == "5"
    assert result["payload"]["rows"][0][4] == "箱"


def test_all_rows_preserved_and_zero_default_declaration_left_missing():
    result = adapter.build_payload({"name": "B"}, [item(name=str(n), customs_declared_value_mxn=0) for n in range(205)], None)
    assert len(result["payload"]["rows"]) == 205
    assert all(row[26] == "" for row in result["payload"]["rows"])
    assert result["warnings"]


def test_current_source_overlays_and_stale_cargo_follow_workbench_semantics():
    context = {"root_kind": "expense", "fingerprint": "CURRENT", "available": True, "approved": True}
    metadata = {"effective_logistics_source": context,
        "settlement_cargo": {"quantity": "5", "unit": "箱"},
        "settlement_physical": {"source_context_fingerprint": "CURRENT", "values": {"gross_weight_kg": "25", "volume_m3": "0.2"}}}
    raw = item(gross_weight_kg=999, volume_m3=9, extra_json=json.dumps(metadata))
    current = adapter.build_payload({"name": "B"}, [raw], None, context)["payload"]["rows"][0]
    assert current[23:25] == ["25", "0.2"]
    assert current[20] == "5"
    stale = adapter.build_payload({"name": "B"}, [raw], None, {**context, "fingerprint": "NEW"})["payload"]["rows"][0]
    assert stale[20] == stale[23] == stale[24] == ""
