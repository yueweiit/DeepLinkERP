"""Real-source and persistence regressions for per-row AI adoption."""
import json

from overseas_costing.services import material_ai_row_selection as rows
from overseas_costing.services.effective_logistics_source import load_source_bundle, project_ai_items
from overseas_costing.services.effective_source_values import project_source_values
from overseas_costing.services.logistics_autofill_service import build_logistics_reconciliation
from overseas_costing.services.material_ai_selection_writer import write_rows
from overseas_costing.services.shipment_cost_service import shipment_value
from overseas_costing.tests.test_logistics_autofill import approval, existing_items
from overseas_costing.tests.test_settlement_writer import setup as settlement_fixture


def preview(items, proposals, batch, version, *, mode, source_context=None):
    catalog = rows.catalog(items, proposals, [], {}, run_id="RUN")
    chosen = [row["row_id"] for row in catalog["rows"]
              if row["origin"] == ("source" if proposals else "current")]
    result = rows.project(items, catalog, chosen, [], mode)
    result.update(batch=batch["name"], version=version["name"], id="PREVIEW",
                  revision="REVISION", run_id="RUN", source_context=source_context or {})
    return result


def test_reconciliation_source_rows_do_not_claim_old_physical_values():
    items = existing_items()
    for item in items:
        item.update(gross_weight_kg=90, volume_m3=12)
    proposal = build_logistics_reconciliation(items, approval())
    catalog = rows.catalog(items, [proposal], [], {}, run_id="RUN")
    recognized = [row for row in catalog["rows"] if row["origin"] == "source"]

    # The approval has no per-row packing measurements. Inherited/apportioned
    # old values must never become new source evidence in the row catalog.
    assert recognized
    assert all(row["values"].get("gross_weight_kg") is None for row in recognized)
    assert all(row["values"].get("volume_m3") is None for row in recognized)


def test_fill_one_field_keeps_untouched_absent_numbers_missing():
    store, ledger, batch, version, item, *_ = settlement_fixture.__wrapped__()
    item = ledger.put("item", item["name"], {
        "gross_weight_kg": None, "volume_m3": None,
        "actual_shipped_qty": 2, "shipped_uom": "件", "extra_json": "{}",
    })
    proposal = {"proposal_id": "P", "proposal_type": "item_update",
                "target_item_name": item["name"], "payload": {"fields": {"volume_m3": 2}}}
    selected = preview([item], [proposal], batch, version, mode="fill_missing")

    write_rows(store, ledger, selected, {})
    saved = ledger.get("item", item["name"])

    assert saved["volume_m3"] == 2
    assert rows.missing(saved, "gross_weight_kg"), (
        "Filling volume must not turn the absent weight into an unmarked real zero"
    )


def test_replacement_of_legacy_bound_version_keeps_future_source_row_scope():
    store, ledger, batch, version, item, *_ = settlement_fixture.__wrapped__()
    original = load_source_bundle(batch["name"], version["name"], store=store, ledger=ledger)
    assert original["binding"]
    selected = preview([item], [], batch, version, mode="replace_all",
                       source_context=original["context"])

    new_version = write_rows(store, ledger, selected, {})
    bundle = load_source_bundle(batch["name"], new_version, store=store, ledger=ledger)

    assert json.loads(bundle["version"]["extra_json"])["ai_row_adoption"]["id"] == "PREVIEW"
    scope = (bundle["context"].get("packing") or bundle["context"]).get("selected_source")
    assert scope and scope["id"] == "PREVIEW"
    assert len(bundle["source"]["goods"]) == 1
    assert bundle["source"]["goods"][0]["material_code"] == item["material_code"]


def test_filled_shipment_quantity_refreshes_the_adopted_cargo_value():
    store, ledger, batch, version, item, *_ = settlement_fixture.__wrapped__()
    metadata = {
        "settlement_packing_missing": ["actual_shipped_qty", "quantity"],
        "settlement_cargo": {"material_code": "A", "quantity": None, "unit": "件",
                             "source_snapshot": "OLD", "binding_id": "OLD", "line_key": "L"},
        "settlement_valuation": {"error": "SETTLEMENT_QUANTITY_OR_PRICE_UNIT_INVALID",
                                 "fx_context": {}, "amount_rmb": None},
    }
    item = ledger.put("item", item["name"], {
        "actual_shipped_qty": 0, "shipped_uom": "件", "extra_json": json.dumps(metadata),
    })
    proposal = {"proposal_id": "P", "proposal_type": "item_update",
                "target_item_name": item["name"], "payload": {"fields": {"actual_shipped_qty": 2}}}
    selected = preview([item], [proposal], batch, version, mode="fill_missing")

    write_rows(store, ledger, selected, {})
    saved = ledger.get("item", item["name"])
    valuation = shipment_value(saved)

    assert saved["actual_shipped_qty"] == 2
    assert not valuation["error"]
    assert valuation["amount_rmb"] == "20.000000"


def test_stable_row_match_does_not_verify_price_for_a_different_specification():
    store, ledger, batch, version, item, *_ = settlement_fixture.__wrapped__()
    item = ledger.put("item", item["name"], {
        "product_name": "Widget", "spec_model": "old-spec", "stable_line_key": "LINE",
        "actual_shipped_qty": 2, "shipped_uom": "件",
    })
    source = {"material_code": "A", "product_name": "Widget", "spec_model": "new-spec",
              "stable_line_key": "LINE", "quantity": 2, "actual_shipped_qty": 2,
              "unit": "件", "shipped_uom": "件", "_review_origin": "source"}
    proposal = {"proposal_id": "P", "proposal_type": "logistics_reconcile",
                "payload": {"rows": [source]}}
    selected = preview([item], [proposal], batch, version, mode="replace_all")

    new_version = write_rows(store, ledger, selected, {})
    saved = ledger.rows("item", version=new_version)[0]
    valuation = shipment_value(saved)

    assert saved["spec_model"] == "new-spec"
    assert valuation["amount_rmb"] is None
    assert valuation["error"]


def test_replace_exact_match_preserves_purchase_evidence_when_value_agrees():
    store, ledger, batch, version, item, *_ = settlement_fixture.__wrapped__()
    item = ledger.put("item", item["name"], {
        "spec_model": "S1", "stable_line_key": "LINE", "actual_shipped_qty": 2,
        "shipped_uom": "件", "extra_json": json.dumps({"purchase_evidence": {"document": "PUR-1"}}),
    })
    source = {"material_code": "A", "spec_model": "S1", "stable_line_key": "LINE",
              "quantity": 2, "actual_shipped_qty": 2, "unit": "件", "shipped_uom": "件",
              "_review_origin": "source"}
    proposal = {"proposal_id": "P", "proposal_type": "logistics_reconcile", "payload": {"rows": [source]}}
    selected = preview([item], [proposal], batch, version, mode="replace_all")

    new_version = write_rows(store, ledger, selected, {})
    saved = ledger.rows("item", version=new_version)[0]
    valuation = shipment_value(saved)
    metadata = json.loads(saved["extra_json"])

    assert valuation["status"] == "automatic"
    assert valuation["amount_rmb"] == "20.000000"
    assert str(saved["goods_value"]) == "20.000000"
    assert metadata["settlement_original_values"]["source_doc_no"] == "GOODS-PURCHASE"
    assert metadata["purchase_evidence"] == {"document": "PUR-1"}


def test_replace_exact_match_quarantines_disagreeing_old_and_calculated_values():
    store, ledger, batch, version, item, *_ = settlement_fixture.__wrapped__()
    item = ledger.put("item", item["name"], {
        "spec_model": "S1", "stable_line_key": "LINE", "actual_shipped_qty": 2, "shipped_uom": "件",
    })
    source = {"material_code": "A", "spec_model": "S1", "stable_line_key": "LINE",
              "quantity": 3, "actual_shipped_qty": 3, "unit": "件", "shipped_uom": "件",
              "_review_origin": "source"}
    proposal = {"proposal_id": "P", "proposal_type": "logistics_reconcile", "payload": {"rows": [source]}}
    selected = preview([item], [proposal], batch, version, mode="replace_all")

    new_version = write_rows(store, ledger, selected, {})
    saved = ledger.rows("item", version=new_version)[0]
    valuation = shipment_value(saved)

    assert valuation["status"] == "conflict"
    assert valuation["amount_rmb"] is None
    assert valuation["prior_amount_rmb"] == "20"
    assert valuation["calculated_amount_rmb"] == "30.000000"
    assert valuation["prior_evidence"]["source_doc_no"] == "GOODS-PURCHASE"
    assert valuation["calculated_evidence"]["input_evidence"]["purchase_source"] == "GOODS-PURCHASE"
    assert saved["goods_value"] == 0


def test_replace_new_row_does_not_inherit_old_value_or_purchase_evidence():
    store, ledger, batch, version, item, *_ = settlement_fixture.__wrapped__()
    source = {"material_code": "NEW", "spec_model": "S2", "stable_line_key": "NEW-LINE",
              "quantity": 3, "actual_shipped_qty": 3, "unit": "件", "shipped_uom": "件",
              "_review_origin": "source"}
    proposal = {"proposal_id": "P", "proposal_type": "logistics_reconcile", "payload": {"rows": [source]}}
    selected = preview([item], [proposal], batch, version, mode="replace_all")

    new_version = write_rows(store, ledger, selected, {})
    saved = ledger.rows("item", version=new_version)[0]
    valuation = shipment_value(saved)

    assert saved["material_code"] == "NEW"
    assert saved["goods_value"] == 0
    assert valuation["status"] == "missing"
    assert valuation["amount_rmb"] is None
    assert not saved.get("source_doc_no")
    assert "settlement_original_values" not in json.loads(saved["extra_json"])


def test_replace_exact_match_keeps_valid_manual_value_above_automatic_value():
    from overseas_costing.services.shipment_cost_service import build_manual_shipment_valuation

    store, ledger, batch, version, item, *_ = settlement_fixture.__wrapped__()
    item = ledger.put("item", item["name"], {
        "spec_model": "S1", "stable_line_key": "LINE", "actual_shipped_qty": 2, "shipped_uom": "件",
    })
    metadata = {"manual_shipment_valuation": build_manual_shipment_valuation(
        item, 25, actor="finance", reason="confirmed", confirmed_at="now")}
    item = ledger.put("item", item["name"], {"extra_json": json.dumps(metadata)})
    source = {"material_code": "A", "spec_model": "S1", "stable_line_key": "LINE",
              "quantity": 2, "actual_shipped_qty": 2, "unit": "件", "shipped_uom": "件",
              "_review_origin": "source"}
    proposal = {"proposal_id": "P", "proposal_type": "logistics_reconcile", "payload": {"rows": [source]}}
    selected = preview([item], [proposal], batch, version, mode="replace_all")

    new_version = write_rows(store, ledger, selected, {})
    saved = ledger.rows("item", version=new_version)[0]

    assert shipment_value(saved)["status"] == "manual"
    assert shipment_value(saved)["amount_rmb"] == "25"
    assert saved["goods_value"] == "25"


def test_two_consecutive_replace_all_runs_keep_current_values_conflicts_and_version_history():
    from copy import deepcopy
    from overseas_costing.services.shipment_cost_service import build_manual_shipment_valuation

    store, ledger, batch, version, first, *_ = settlement_fixture.__wrapped__()
    common = {"spec_model": "S1", "unit": "件", "actual_shipped_qty": 2, "shipped_uom": "件",
              "quantity": 2, "unit_price": 10, "goods_value": 20, "purchase_currency": "RMB",
              "purchase_uom": "件", "unit_price_uom": "件", "source_doc_no": "PUR"}
    first = ledger.put("item", first["name"], {**common, "material_code": "A", "stable_line_key": "LINE-A"})
    manual_row = {**common, "material_code": "B", "stable_line_key": "LINE-B"}
    manual_row["extra_json"] = json.dumps({"manual_shipment_valuation": build_manual_shipment_valuation(
        manual_row, 25, actor="finance", reason="confirmed", confirmed_at="now")})
    second = ledger.create("item", {**manual_row, "batch": batch["name"], "version": version["name"]})
    third = ledger.create("item", {**common, "material_code": "C", "stable_line_key": "LINE-C",
                                   "batch": batch["name"], "version": version["name"]})

    def replace(current, current_version, run_id):
        source_rows = [
            {"material_code": row["material_code"], "spec_model": "S1", "stable_line_key": row["stable_line_key"],
             "quantity": 3 if row["material_code"] == "C" else 2,
             "actual_shipped_qty": 3 if row["material_code"] == "C" else 2,
             "unit": "件", "shipped_uom": "件", "_review_origin": "source"}
            for row in current
        ]
        proposal = {"proposal_id": "P-" + run_id, "proposal_type": "logistics_reconcile",
                    "default_selected": True, "payload": {"rows": source_rows}}
        catalog = rows.catalog(current, [proposal], [], {}, run_id=run_id)
        selected_ids = [row["row_id"] for row in catalog["rows"] if row["origin"] == "source"]
        projected = rows.project(current, catalog, selected_ids, [], "replace_all")
        assert projected["mode"] == "replace_all"
        projected.update(batch=batch["name"], version=current_version, id="PREVIEW-" + run_id,
                         revision="REV-" + run_id, run_id=run_id, source_context={}, sources=[])
        return write_rows(store, ledger, projected, {})

    original_items = deepcopy(ledger.rows("item", version=version["name"]))
    first_version = replace([first, second, third], version["name"], "ONE")
    first_saved = deepcopy(ledger.rows("item", version=first_version))
    second_version = replace(first_saved, first_version, "TWO")
    final = {row["material_code"]: row for row in ledger.rows("item", version=second_version)}

    assert first_version != version["name"] and second_version != first_version
    assert ledger.get("batch", batch["name"])["current_version"] == second_version
    assert ledger.rows("item", version=version["name"]) == original_items
    assert ledger.rows("item", version=first_version) == first_saved
    assert shipment_value(final["A"])["status"] == "automatic"
    assert shipment_value(final["A"])["amount_rmb"] == "20.000000"
    assert shipment_value(final["B"])["status"] == "manual"
    assert shipment_value(final["B"])["amount_rmb"] == "25"
    assert final["B"]["goods_value"] == "25"
    conflict = shipment_value(final["C"])
    assert conflict["status"] == "conflict"
    assert conflict["amount_rmb"] is None and final["C"]["goods_value"] == 0
    assert conflict["prior_amount_rmb"] == "20"
    assert conflict["calculated_amount_rmb"] == "30.000000"


def test_next_ai_input_preserves_both_selected_duplicate_sku_rows():
    store, ledger, batch, version, first, *_ = settlement_fixture.__wrapped__()
    first = ledger.put("item", first["name"], {
        "stable_line_key": "LINE-1", "actual_shipped_qty": 2, "shipped_uom": "件",
    })
    second = ledger.create("item", {
        **{key: value for key, value in first.items() if key != "name"},
        "stable_line_key": "LINE-2", "actual_shipped_qty": 3,
    })
    original = load_source_bundle(batch["name"], version["name"], store=store, ledger=ledger)
    selected = preview([first, second], [], batch, version, mode="replace_all",
                       source_context=original["context"])

    new_version = write_rows(store, ledger, selected, {})
    bundle = load_source_bundle(batch["name"], new_version, store=store, ledger=ledger)
    saved = ledger.rows("item", version=new_version)
    projected = project_ai_items(saved, bundle)

    assert len(saved) == 2
    assert {item["name"] for item in projected} == {item["name"] for item in saved}


def test_fillability_uses_current_source_blank_instead_of_historical_raw_weight():
    context = {"root_kind": "expense", "available": True, "approved": True,
               "invalid": False, "source_snapshot": "CURRENT", "fingerprint": "CTX"}
    item = {"name": "ITEM", "material_code": "A", "unit": "件", "shipped_uom": "件",
            "gross_weight_kg": 9, "actual_shipped_qty": 2, "extra_json": json.dumps({
                "effective_logistics_source": context,
                "settlement_physical": {"source_context_fingerprint": "CTX", "values": {}},
            })}
    assert project_source_values(item, context)["gross_weight_kg"] is None
    proposal = {"proposal_id": "P", "proposal_type": "item_update",
                "target_item_name": "ITEM", "payload": {"fields": {"gross_weight_kg": 10}}}

    catalog = rows.catalog([item], [proposal], [], context, run_id="RUN")
    recognized = next(row for row in catalog["rows"] if row["origin"] == "source")

    assert recognized["can_fill"], "A raw historical value is not an effective current-source value"


def test_fillability_preserves_real_zero_in_current_source_overlay():
    context = {"root_kind": "expense", "available": True, "approved": True,
               "invalid": False, "source_snapshot": "CURRENT", "fingerprint": "CTX"}
    item = {"name": "ITEM", "material_code": "A", "unit": "件", "shipped_uom": "件",
            "gross_weight_kg": None, "actual_shipped_qty": 2, "extra_json": json.dumps({
                "effective_logistics_source": context,
                "settlement_physical": {"source_context_fingerprint": "CTX",
                                        "values": {"gross_weight_kg": 0}},
            })}
    assert project_source_values(item, context)["gross_weight_kg"] == 0
    proposal = {"proposal_id": "P", "proposal_type": "item_update",
                "target_item_name": "ITEM", "payload": {"fields": {"gross_weight_kg": 10}}}

    catalog = rows.catalog([item], [proposal], [], context, run_id="RUN")
    recognized = next(row for row in catalog["rows"] if row["origin"] == "source")

    assert not recognized["can_fill"], "A real current-source zero must not be fillable"


def test_retained_rows_publish_effective_packing_values_to_next_ai_scope():
    store,ledger,batch,version,item,*_=settlement_fixture.__wrapped__()
    original=load_source_bundle(batch['name'],version['name'],store=store,ledger=ledger)
    context=original['context']
    item=ledger.put('item',item['name'],{'gross_weight_kg':99,'extra_json':json.dumps({
        'effective_logistics_source':context,'settlement_physical':{'source_context_fingerprint':context['fingerprint'],'values':{'gross_weight_kg':5}}})})
    selected=preview([item],[],batch,version,mode='replace_all',source_context=context)
    new=write_rows(store,ledger,selected,{})
    bundle=load_source_bundle(batch['name'],new,store=store,ledger=ledger)
    assert bundle['source']['goods'][0]['physical']['gross_weight_kg']==5


def test_replace_clears_old_dimensional_weight_and_weight_ratio():
    store,ledger,batch,version,item,*_=settlement_fixture.__wrapped__()
    item=ledger.put('item',item['name'],{'volume_weight_kg':900,'weight_ratio':0.9,'shipped_uom':'件'})
    proposal={'proposal_id':'P','proposal_type':'logistics_reconcile','payload':{'rows':[
        {'material_code':'A','product_name':item.get('product_name'),'quantity':2,'unit':'件','_review_origin':'source'}]}}
    selected=preview([item],[proposal],batch,version,mode='replace_all')
    new=write_rows(store,ledger,selected,{})
    saved=ledger.rows('item',version=new)[0]
    assert rows.missing(saved,'volume_weight_kg') and rows.missing(saved,'weight_ratio')
    assert saved['volume_weight_kg']==0


def test_bound_source_fill_updates_the_effective_overlay_at_write_time():
    store,ledger,batch,version,item,*_=settlement_fixture.__wrapped__()
    context=load_source_bundle(batch['name'],version['name'],store=store,ledger=ledger)['context']
    item=ledger.put('item',item['name'],{'gross_weight_kg':99,'extra_json':json.dumps({
        'effective_logistics_source':context,'settlement_physical':{'source_context_fingerprint':context['fingerprint'],'values':{}}})})
    proposal={'proposal_id':'P','proposal_type':'item_update','target_item_name':item['name'],'payload':{'fields':{'gross_weight_kg':10}}}
    cat=rows.catalog([item],[proposal],[],context,run_id='RUN')
    selected=rows.project([item],cat,[cat['rows'][0]['row_id']],[],'fill_missing')
    selected.update(batch=batch['name'],version=version['name'],id='PREVIEW',revision='REV',run_id='RUN',source_context=context)
    write_rows(store,ledger,selected,{})
    assert project_source_values(ledger.get('item',item['name']))['gross_weight_kg']==10
