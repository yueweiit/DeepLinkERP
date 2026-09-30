"""Saved trials must use exactly the same allocation as the workspace preview."""

from copy import deepcopy
from decimal import Decimal
import json

import pytest

from overseas_costing.services import cost_preview_service as service, fee_service


def inputs():
    items = [
        dict(name="I1", stable_line_key="L1", material_code="CW000023", goods_value=12300,
             quantity=1000, actual_shipped_qty=990, actual_shipped_qty_mode="EXPLICIT_SOURCE",
             gross_weight_kg=100, chargeable_weight_kg=120,
             unit="个", purchase_uom="个", unit_price_uom="个", shipped_uom="个"),
        dict(name="I2", stable_line_key="L2", material_code="OTHER", goods_value=28500,
             quantity=7000, gross_weight_kg=200, chargeable_weight_kg=230,
             unit="个", purchase_uom="个", unit_price_uom="个", shipped_uom="个"),
    ]
    fees = fee_service.build_default_fee_templates("AIR")
    # Keep the historical surcharge from this saved case; it is no longer a new default.
    fees.insert(1, dict(name="SAVED-SURCHARGE", logical_fee_key="air_forwarder_surcharge",
                        rule_code="air_forwarder_surcharge", expense_category="空运附加费",
                        allocation_basis="chargeable_weight", scope_type="ALL_ITEMS", currency="RMB"))
    for fee, amount in zip(fees, [7000, 5000, 12000, 0, 0]):
        fee.update(amount=amount, amount_status="ACTUAL", virtual=False, currency="RMB")
    return items, fees, dict(fx_rmb_to_mxn=2.5, fx_usd_to_rmb=7)


def test_saved_projection_conserves_preview_cost_and_uses_shipped_quantity():
    items, fees, fx = inputs()
    original = deepcopy(items)
    result = service.build_saved_cost_data(items, fees, fx, "AIR")
    assert result["summary"]["total_cost_rmb"] == "64677.00"
    assert sum(Decimal(row["total_cost_rmb"]) for row in result["item_updates"]) == Decimal("64677")
    backpack = result["item_updates"][0]
    assert Decimal(backpack["total_unit_rmb"]) == (Decimal(backpack["total_cost_rmb"]) / 990).quantize(Decimal("0.000001"))
    assert backpack["transport_mode"] == "AIR"
    assert "goods_value" not in backpack and "quantity" not in backpack
    assert result["summary_snapshot"]["calculation_schema"] == 2
    assert result["summary_snapshot"]["input_hash"]
    assert items == original
    assert result["items"][0]["shipping_quantity_difference"] == "-10"


def test_cost_input_hash_ignores_private_trial_projection_fields():
    items, fees, fx = inputs()
    projected = deepcopy(fees)
    projected[0]["trial_allocation_basis"] = "gross_weight"
    projected[0]["trial_suggestion_id"] = "private-suggestion"

    assert service.cost_input_hash(items, projected, fx, "AIR") == service.cost_input_hash(
        items, fees, fx, "AIR"
    )


# The two call paths into the fingerprint build item dicts with different loaders.
# ``cost_trial_ai_service.load_trial_inputs`` merges the batch decision columns
# (``category`` / ``transport_mode``) into every item, while the read side
# (``batch_service._load_erp_push_context``) does not.  None of those keys are
# calculation inputs, but hashing the raw dict meant the save path and the read
# path could never agree, so a batch that had ever been through the AI trial flow
# stayed pinned on ``RESULT_STALE`` no matter how often it was recalculated.
LOADER_ONLY_ITEM_COLUMNS = (
    {"category": "Material物料"},
    {"transport_mode": "SEA"},
    {"category": "Material物料", "transport_mode": "SEA", "source_context": {"fingerprint": "abc"}},
    {"subsidiary_code": "S1"},
    {"route_status": "RESOLVED", "route_revision": "r7"},
    {"excel_row_no": 12},
    {"erp_site_code": "MEX01"},
    # Calculation *outputs* the read side happens to carry around; they are not
    # inputs either.  They must not be able to stale a saved result.
    {"total_cost_rmb": "999.99", "freight_alloc_rmb": "1", "alloc_price_mxn": "2"},
    {"derived_json": '{"anything":1}', "goods_value_ratio": "50"},
)


@pytest.mark.parametrize("extra", LOADER_ONLY_ITEM_COLUMNS)
def test_cost_input_hash_ignores_loader_only_item_columns(extra):
    items, fees, fx = inputs()
    decorated = deepcopy(items)
    decorated[0].update(extra)

    assert service.cost_input_hash(decorated, fees, fx, "AIR") == service.cost_input_hash(
        items, fees, fx, "AIR"
    ), f"loader-only columns {sorted(extra)} must not participate in the fingerprint"


def test_cost_input_hash_tracks_every_cost_relevant_item_field():
    """The item projection must stay a faithful superset of the real inputs."""

    items, fees, fx = inputs()
    for field, value in (
        ("goods_value", 1),
        ("quantity", 1),
        ("actual_shipped_qty", 1),
        ("gross_weight_kg", 1),
        ("chargeable_weight_kg", 1),
        ("volume_m3", 1),
        ("net_weight_kg", 1),
        ("project_collection", "P-1"),
        ("supplier", "S-1"),
        ("extra_json", '{"row_meta":{"x":1}}'),
    ):
        mutated = deepcopy(items)
        mutated[0][field] = value
        assert service.cost_input_hash(mutated, fees, fx, "AIR") != service.cost_input_hash(
            items, fees, fx, "AIR"
        ), f"{field} changes the valuation and must stale the saved result"


def test_item_projection_is_the_declared_contract_minus_legacy_exclusions():
    projected = service.cost_hash_item_projection(
        {"name": "I1", "goods_value": 5, "category": "Material物料", "spec_model": "X"}
    )
    assert set(projected) == set(service.COST_INPUT_FIELDS) - set(service.COST_HASH_ITEM_SKIP_FIELDS)
    assert "category" not in projected
    assert "spec_model" not in projected
    assert "goods_value" in projected


def test_trial_loader_and_read_side_produce_the_same_fingerprint():
    """The regression this whole projection exists for, end to end."""

    items, fees, fx = inputs()
    # Read side hands in plain rows.
    read_side = deepcopy(items)
    # The AI trial loader hands in the same rows plus the decision columns.
    trial_side = [dict(row, category="Material物料", transport_mode="AIR") for row in items]

    assert service.cost_input_hash(trial_side, fees, fx, "AIR") == service.cost_input_hash(
        read_side, fees, fx, "AIR"
    )


# The same fact reaches the fingerprint in different *types* depending on the
# loader: ``extra_json`` is the DB column (a JSON string) on the read side, but an
# already-parsed mapping on the AI trial side.  Hashed verbatim that is a type
# difference dressed up as a data change, so the two sides could never agree.
# ``item_metadata.persist_item_meta`` defines the persisted form as
# ``json.dumps(..., sort_keys=True, separators=(",", ":"), default=str)``; the
# canonicaliser must land on exactly that byte string.
TRIAL_JSON_ITEM_ROWS = (
    {"anything": 1},
    {"nested": {"b": [1, 2], "a": None}},
    [{"list": True}],
    "already-a-string",
)


@pytest.mark.parametrize("payload", TRIAL_JSON_ITEM_ROWS)
def test_item_projection_canonicalises_json_payloads_the_way_they_are_persisted(payload):
    projected = service.cost_hash_item_projection({"name": "I1", "extra_json": payload})
    value = projected["extra_json"]
    assert isinstance(value, str), "extra_json must always fingerprint as its persisted string form"
    if isinstance(payload, str):
        assert value == payload, "an already-persisted string must not be rewritten"
    else:
        assert json.loads(value) == payload, "canonicalisation must preserve the payload"


def test_item_projection_agrees_across_loader_representations_of_the_same_fact():
    persisted = service.cost_hash_item_projection(
        {"name": "I1", "goods_value": 5, "extra_json": '{"a":1,"b":[2]}'}
    )
    parsed = service.cost_hash_item_projection(
        {"name": "I1", "goods_value": 5, "extra_json": {"b": [2], "a": 1}}
    )
    assert persisted == parsed


# Audit labels are not valuation inputs.  The AI cost-trial save rewrites a rule's
# ``remark`` (and the human fee-status flow rewrites ``status_change_reason`` /
# ``status_changed_*``) without bumping ``amount_revision``/``scope_revision``,
# sometimes *after* it has already stored the snapshot.  When those labels entered
# the hash, the stored ``input_hash`` could never equal the hash recomputed from
# the live rule, so the batch stayed pinned on ``RESULT_STALE`` and the review
# button never became clickable even after repeated recalculation.
AUDIT_ONLY_FEE_MUTATIONS = (
    {"remark": "试算沿用上次：gross_weight"},
    {"status_change_reason": "本票为测试单，没有海运费"},
    {"status_changed_by": "someone@else.com"},
    {"status_changed_at": "2099-01-01 00:00:00.000001"},
    {"priority_no": 99},
    {"expense_category": "改过的类别"},
    {"basis_field": "改过的字段"},
    {"required_evidence_role": "changed_role"},
)

COST_RELEVANT_FEE_MUTATIONS = (
    {"amount": 4321},
    {"amount_status": "ESTIMATED"},
    {"allocation_basis": "volume"},
    {"currency": "USD"},
    {"scope_type": "ITEMS"},
    {"scope_value_json": '["L1"]'},
    {"included_in_fee_key": "included_into_other"},
    {"is_enabled": 0},
)


@pytest.mark.parametrize("mutation", AUDIT_ONLY_FEE_MUTATIONS)
def test_cost_input_hash_ignores_audit_and_label_fields(mutation):
    items, fees, fx = inputs()
    mutated = deepcopy(fees)
    mutated[0].update(mutation)

    assert service.cost_input_hash(items, mutated, fx, "AIR") == service.cost_input_hash(
        items, fees, fx, "AIR"
    ), f"{sorted(mutation)} must not participate in the saved-result fingerprint"


@pytest.mark.parametrize("mutation", COST_RELEVANT_FEE_MUTATIONS)
def test_cost_input_hash_tracks_every_cost_relevant_fee_field(mutation):
    items, fees, fx = inputs()
    mutated = deepcopy(fees)
    mutated[0].update(mutation)

    assert service.cost_input_hash(items, mutated, fx, "AIR") != service.cost_input_hash(
        items, fees, fx, "AIR"
    ), f"{sorted(mutation)} changes the valuation and must stale the saved result"


def test_cost_hash_fee_projection_covers_the_declared_fee_input_contract():
    """The projection must stay a superset of ``fee_service.COST_INPUT_FIELDS``."""

    assert set(fee_service.COST_INPUT_FIELDS) <= set(service.COST_HASH_FEE_FIELDS)
    assert {"remark", "status_change_reason", "status_changed_by", "status_changed_at"}.isdisjoint(
        service.COST_HASH_FEE_FIELDS
    )


# The AI-trial save hands the fingerprint an ``fx_context`` that already carries
# the whole rate-resolution audit blob (``_apply_fx_resolution`` stores it under
# ``fx_resolution``), while the read side rebuilds only the two rate columns from
# the version row.  The audit blob is not a calculation input -- the allocation
# reads only the two rates -- so hashing it verbatim pinned every AI-trial batch
# on ``RESULT_STALE``.  ``COST_HASH_FX_FIELDS`` is the single owner of that
# contract; both callers project through it inside ``cost_input_hash``.
FX_AUDIT_RESOLUTION = {
    "batch_name": "B1",
    "version_name": "V1",
    "ok": True,
    "calculation_date": "2026-09-30",
    "is_estimated": False,
    "blocking_errors": [],
    "rates": {
        "USD": {"currency": "USD", "cny_per_unit": 6.72, "source": "version_snapshot"},
        "MXN": {"currency": "MXN", "cny_per_unit": 0.38, "source": "version_snapshot"},
    },
}


def test_fx_projection_is_the_declared_rate_contract():
    projected = service.cost_hash_fx_projection(
        {"fx_usd_to_rmb": 6.72, "fx_rmb_to_mxn": 2.631579, "fx_resolution": FX_AUDIT_RESOLUTION}
    )
    assert set(projected) == set(service.COST_HASH_FX_FIELDS)
    assert projected == {"fx_usd_to_rmb": 6.72, "fx_rmb_to_mxn": 2.631579}
    assert "fx_resolution" not in projected


def test_cost_input_hash_ignores_the_fx_resolution_audit_blob():
    """The regression this projection exists for, at the hash level."""

    items, fees, fx = inputs()
    trial_side = {**fx, "fx_resolution": FX_AUDIT_RESOLUTION}

    assert service.cost_input_hash(items, fees, trial_side, "AIR") == service.cost_input_hash(
        items, fees, fx, "AIR"
    ), "the fx audit blob must not participate in the saved-result fingerprint"


@pytest.mark.parametrize("mutation", ({"fx_usd_to_rmb": 6.9}, {"fx_rmb_to_mxn": 2.4}))
def test_cost_input_hash_tracks_every_declared_fx_rate(mutation):
    items, fees, fx = inputs()

    assert service.cost_input_hash(items, fees, {**fx, **mutation}, "AIR") != service.cost_input_hash(
        items, fees, fx, "AIR"
    ), f"{sorted(mutation)} changes the valuation and must stale the saved result"


def test_trial_loader_and_read_side_produce_the_same_fingerprint_with_fx_audit_blob():
    """Both loaders, same business facts, different fx_context shapes."""

    items, fees, fx = inputs()
    read_side_fx = {key: fx.get(key) for key in ("fx_usd_to_rmb", "fx_rmb_to_mxn")}
    trial_side_fx = {**read_side_fx, "fx_resolution": FX_AUDIT_RESOLUTION}

    assert service.cost_input_hash(items, fees, trial_side_fx, "AIR") == service.cost_input_hash(
        items, fees, read_side_fx, "AIR"
    )


def test_deactivated_fee_is_caught_by_selection_not_by_the_per_row_fingerprint():
    """Enabling is a *selection* concern; the composition layer drops the row.

    ``is_active`` is deliberately outside both ``fee_service.COST_INPUT_FIELDS``
    and the fingerprint, so flipping it on a raw rule dict does not move the
    hash.  That is safe because ``compose_fee_worklist_rows`` removes inactive
    rules first, so the *composed* fee set — which is what the hash actually
    sees — does change.  Guard both halves of that layering so nobody "fixes"
    it by pushing ``is_active`` back into the per-row projection.
    """

    items, fees, fx = inputs()
    deactivated = deepcopy(fees)
    deactivated[0]["is_active"] = 0

    assert "is_active" not in service.COST_HASH_FEE_FIELDS
    assert "is_active" not in fee_service.COST_INPUT_FIELDS

    def fingerprint(rows):
        return service.cost_input_hash(*service.normalize_saved_cost_inputs(items, rows, fx, "AIR"), fx, "AIR")

    # Raw rows: not a per-row input, so unchanged.
    assert fingerprint(fees) == fingerprint(deactivated)

    # After composition the row is gone, so the valued fee set did change.
    active_keys = [row["logical_fee_key"] for row in fee_service.compose_fee_worklist_rows(fees, "AIR")]
    dropped_keys = [row["logical_fee_key"] for row in fee_service.compose_fee_worklist_rows(deactivated, "AIR")]
    assert fees[0]["logical_fee_key"] in active_keys
    assert fees[0]["logical_fee_key"] not in dropped_keys
    assert fingerprint(fee_service.compose_fee_worklist_rows(deactivated, "AIR")) != fingerprint(
        fee_service.compose_fee_worklist_rows(fees, "AIR")
    )


def test_saved_snapshot_hash_matches_a_rerun_after_an_audit_only_fee_edit():
    """A label-only rule edit must not stale the snapshot it was stored with."""

    items, fees, fx = inputs()
    saved = service.build_saved_cost_data(items, fees, fx, "AIR")
    stored_hash = saved["summary_snapshot"]["input_hash"]

    relabelled = deepcopy(fees)
    relabelled[0].update(remark="试算沿用上次：chargeable_weight",
                         status_change_reason="人工备注",
                         status_changed_by="someone@else.com")

    rerun_hash = service.cost_input_hash(
        *service.normalize_saved_cost_inputs(items, relabelled, fx, "AIR"), fx, "AIR"
    )
    assert rerun_hash == stored_hash


def test_sku_presentation_uses_saved_units_and_batch_transport():
    from overseas_costing.services import workbench_service
    items, fees, fx = inputs()
    result = service.build_saved_cost_data(items, fees, fx, "AIR")
    row = {**items[0], **result["item_updates"][0], "transport_mode": "SEA"}
    presented = workbench_service.present_saved_sku_result(row, "AIR")
    assert presented["transport_mode"] == "AIR"
    assert presented["shipping_unit_label"] == "个"
    assert "/ 个" in presented["purchase_pricing_unit_display"]
    assert Decimal(presented["calculated_customs_rmb"]) > 0


def test_disabled_legacy_fee_never_blocks_or_counts_again():
    items, fees, fx = inputs()
    fees.append(dict(name="OLD", rule_code="oa_logistics_freight", expense_category="国际物流费用",
                     amount=20360, amount_status="MISSING", is_enabled=0))
    active = fee_service.compose_fee_worklist_rows(fees, "AIR")
    assert not any(row.get("name") == "OLD" for row in active)
    preview = service.preview_comprehensive_cost_data(items, active, fx)
    assert preview["summary"]["total_cost_rmb"] == "64677.00"
    assert not preview["excluded_fees"]


class Repository:
    def __init__(self):
        self.items, self.fees, self.fx = inputs()
        self.context = dict(batch="B", version="V", batch_modified="M1", current_version="V",
                            status="Dirty", version_status="Active", transport_mode="AIR")
        self.writes = []
        self.committed = False
        self.rolled_back = False
        self.change_after_read = False
        self.fail_save = False

    def lock_and_load(self, batch, version, **kwargs):
        assert kwargs.get("edit_token") == "TOKEN"
        if kwargs.get("expected_modified") != self.context["batch_modified"]:
            raise RuntimeError("批次数据已被更新")
        return deepcopy(self.context), deepcopy(self.items), deepcopy(self.fees), dict(self.fx)

    def assert_unchanged(self, context):
        if self.change_after_read:
            raise RuntimeError("输入已变化")

    def save(self, context, result):
        if self.fail_save:
            raise RuntimeError("写入失败")
        self.writes.append(deepcopy(result))
        return "M2"

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True
        self.writes = []


def save(repo):
    return service.calculate_comprehensive_cost("B", "V", edit_token="TOKEN", expected_modified="M1", repository=repo)


def test_saved_trial_commits_one_coherent_result_without_confirming_or_pushing():
    repo = Repository()
    result = save(repo)
    assert result["ok"] and result["saved"] and not result["read_only"]
    assert result["batch_modified"] == "M2"
    assert len(repo.writes) == 1 and repo.committed
    assert result["summary"]["total_cost_rmb"] == "64677.00"
    assert "confirm_status" not in repo.writes[0]["summary_snapshot"]


@pytest.mark.parametrize("field,value", [("version_status", "Confirmed"), ("version_status", "Archived"),
                                         ("current_version", "OTHER"), ("confirm_status", "Confirmed")])
def test_saved_trial_rejects_locked_or_noncurrent_version(field, value):
    repo = Repository()
    repo.context[field] = value
    with pytest.raises((ValueError, PermissionError)):
        save(repo)
    assert not repo.writes and not repo.committed


@pytest.mark.parametrize("flag", ["change_after_read", "fail_save"])
def test_failed_or_stale_trial_rolls_back_without_partial_results(flag):
    repo = Repository()
    setattr(repo, flag, True)
    with pytest.raises(RuntimeError):
        save(repo)
    assert not repo.writes and not repo.committed and repo.rolled_back


def test_confirmation_uses_saved_snapshot_zero_fees_and_keeps_real_entity_gap():
    from overseas_costing.services import batch_service
    items, fees, fx = inputs()
    saved = service.build_saved_cost_data(items, fees, fx, "AIR")
    for item, update in zip(items, saved["item_updates"]):
        item.update(update, product_name="商品", unit_price=1, purchase_currency="RMB")
        item.setdefault("actual_shipped_qty", item["quantity"])
    batch = dict(current_version="V", status="Calculated", item_count=2,
                 estimated_total_cost_rmb=40800, actual_total_cost_rmb=100,
                 summary_snapshot=saved["summary_snapshot"])
    result = batch_service._build_calculation_confirmation_readiness(batch, items, fees, "V")
    assert result["total_cost_rmb"] == 64677
    assert result["checks"]["has_tariff"]
    assert not result["field_gaps"]["rules"]
    assert result["blocking_reasons"] == []
    assert result["ready"] is True
    batch.update(status="Dirty", subsidiary_code="MX01")
    result = batch_service._build_calculation_confirmation_readiness(batch, items, fees, "V")
    assert not result["ready"] and result["checks"]["has_dirty_data"]

    batch.update(status="Calculated")
    batch["summary_snapshot"]["formal_confirmation_blocked"] = True
    batch["summary_snapshot"]["formal_confirmation_block_reason"] = "TEMPORARY_ALLOCATION_BASIS"
    result = batch_service._build_calculation_confirmation_readiness(batch, items, fees, "V")
    assert not result["ready"]
    assert result["checks"]["has_formal_confirmation_block"]
    assert "暂行分摊口径" in "".join(result["blocking_reasons"])


def test_saved_consumers_ignore_replaced_raw_tax_and_use_effective_shipping():
    from overseas_costing.services import batch_service, workbench_service
    items, fees, fx = inputs()
    items[1].update(actual_shipped_qty=None, actual_shipped_qty_mode="DEFAULT_PURCHASE")
    saved = service.build_saved_cost_data(items, fees, fx, "AIR")
    for item, update, preview_item in zip(items, saved["item_updates"], saved["items"]):
        item.update(update, product_name="商品", unit_price=1, purchase_currency="RMB",
                    mexico_customs_rmb=50, import_tax_total=75)
        quick = workbench_service.build_batch_result_preview_item(item, calculated=True)
        detail = batch_service._item_expense_detail(item)
        assert quick["tax_alloc_rmb"] == detail["clearance_and_tax"]["tax_alloc_rmb"] == 0
        assert quick["clearance_alloc_rmb"] == detail["clearance_and_tax"]["clearance_alloc_rmb"]
        extras = sum(quick[key] for key in ("freight_alloc_rmb", "tax_alloc_rmb", "clearance_alloc_rmb", "unlisted_other_cost_rmb"))
        assert extras == pytest.approx(float(item["total_cost_rmb"]) - float(preview_item["goods_value_rmb"]))
    batch = dict(current_version="V", status="Calculated", subsidiary_code="MX01", summary_snapshot=saved["summary_snapshot"])
    ready = batch_service._build_calculation_confirmation_readiness(batch, items, fees, "V")
    assert ready["ready"], ready
    assert ready["expense_pools"]["item_allocations"]["tariff_tax_total"] == 0
    assert ready["expense_pools"]["item_allocations"]["clearance_fee_rmb"] == 12000
    quick = workbench_service.build_batch_result_preview_payload(batch=batch, version={"calculated_at": "NOW"}, items=items)
    assert quick["summary"]["weighted_total_unit_rmb"] == pytest.approx(64677 / 7990, abs=1e-6)


def test_subcent_goods_rounding_conserves_saved_sku_and_summary_totals():
    items, fees, fx = inputs()
    for item in items:
        item["goods_value"] = "100.005"
    for fee in fees:
        fee["amount"] = 0
    saved = service.build_saved_cost_data(items, fees, fx, "AIR")
    assert sum(Decimal(row["total_cost_rmb"]) for row in saved["item_updates"]) == Decimal(saved["summary"]["total_cost_rmb"]) == Decimal("199.01")


def test_batch_detail_loads_purchase_source_status_without_visiting_approval_tab(monkeypatch):
    import json
    from types import SimpleNamespace
    from overseas_costing.services import batch_service
    stored = dict(name="B", current_version="V", transport_mode="AIR", source_approval_status="COMPLETED",
                  source_approval_no="OA", source_attachment_count=1,
                  extra_json=json.dumps({"linked_purchase_approvals": [{"approval_no": "P1", "approval_status": "COMPLETED"}]}))
    def get_value(doctype, name, fields, **kwargs):
        data = stored if doctype == "Overseas Cost Batch" else dict(name="V", summary_snapshot_json="{}")
        return {key:data.get(key) for key in fields}
    monkeypatch.setattr(batch_service, "frappe", SimpleNamespace(db=SimpleNamespace(get_value=get_value), get_all=lambda *a, **kw: []))
    monkeypatch.setattr(batch_service, "_resolve_batch_name", lambda name: "B")
    monkeypatch.setattr(batch_service, "_resolve_version_name", lambda *args: "V")
    monkeypatch.setattr(batch_service, "_db_has_column", lambda *args: True)
    result = batch_service.get_batch_detail("B")
    status = result["header"]["source_status"]
    assert status["purchase_approval_sync_state"] == "valid"
    assert status["linked_purchase_count"] == 1 and status["linked_purchase_approval_statuses"] == ["COMPLETED"]
    assert "extra_json" not in result["header"]


def test_batch_detail_projects_legacy_snapshot_unit_price_without_writing(monkeypatch):
    import json
    from types import SimpleNamespace
    from overseas_costing.services import batch_service

    snapshot = {
        "comprehensive_cost": {
            "items": [{
                "name": "ITEM-1",
                "goods_value_rmb": "2067.00",
                "shipping_unit_cost": {"amount_rmb": "2.820924", "uom": "个"},
            }]
        }
    }
    stored = {
        "name": "B",
        "current_version": "V",
        "transport_mode": "EXPRESS",
        "extra_json": "{}",
    }
    version = {"name": "V", "summary_snapshot_json": json.dumps(snapshot)}
    item_rows = [{
        "name": "ITEM-1",
        "derived_json": json.dumps({
            "shipping_quantity": "1700",
            "shipping_unit_cost": {"amount_rmb": "2.820924", "uom": "个"},
        }),
    }]

    def get_value(doctype, name, fields, **kwargs):
        data = stored if doctype == "Overseas Cost Batch" else version
        return {key: data.get(key) for key in fields}

    def get_all(doctype, *args, **kwargs):
        if doctype == "Overseas Cost Item" and "derived_json" in kwargs.get("fields", []):
            return item_rows
        return []

    monkeypatch.setattr(
        batch_service,
        "frappe",
        SimpleNamespace(db=SimpleNamespace(get_value=get_value), get_all=get_all),
    )
    monkeypatch.setattr(batch_service, "_resolve_batch_name", lambda name: "B")
    monkeypatch.setattr(batch_service, "_resolve_version_name", lambda *args: "V")
    monkeypatch.setattr(batch_service, "_db_has_column", lambda *args: True)

    result = batch_service.get_batch_detail("B")

    assert result["summary"]["comprehensive_cost"]["items"][0]["shipping_unit_price"] == {
        "amount_rmb": "1.215882",
        "uom": "个",
    }
    assert "shipping_unit_price" not in snapshot["comprehensive_cost"]["items"][0]
