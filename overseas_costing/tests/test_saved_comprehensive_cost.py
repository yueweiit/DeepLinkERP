"""Saved trials must use exactly the same allocation as the workspace preview."""

from copy import deepcopy
from decimal import Decimal

import pytest

from overseas_costing.services import cost_preview_service as service, fee_service


def inputs():
    items = [
        dict(name="I1", stable_line_key="L1", material_code="CW000023", goods_value=12300,
             quantity=1000, actual_shipped_qty=990, actual_shipped_qty_mode="EXPLICIT_SOURCE",
             unit="个", purchase_uom="个", unit_price_uom="个", shipped_uom="个"),
        dict(name="I2", stable_line_key="L2", material_code="OTHER", goods_value=28500,
             quantity=7000, unit="个", purchase_uom="个", unit_price_uom="个", shipped_uom="个"),
    ]
    fees = fee_service.build_default_fee_templates("AIR")
    for fee, amount in zip(fees, [7000, 5000, 12000, 0, 0]):
        fee.update(amount=amount, amount_status="ACTUAL", virtual=False)
    return items, fees, dict(fx_rmb_to_mxn=2.5, fx_usd_to_rmb=7)


def test_saved_projection_conserves_preview_cost_and_uses_shipped_quantity():
    items, fees, fx = inputs()
    original = deepcopy(items)
    result = service.build_saved_cost_data(items, fees, fx, "AIR")
    assert result["summary"]["total_cost_rmb"] == "64800.00"
    assert sum(Decimal(row["total_cost_rmb"]) for row in result["item_updates"]) == Decimal("64800")
    backpack = result["item_updates"][0]
    assert Decimal(backpack["total_unit_rmb"]) == (Decimal(backpack["total_cost_rmb"]) / 990).quantize(Decimal("0.000001"))
    assert backpack["transport_mode"] == "AIR"
    assert "goods_value" not in backpack and "quantity" not in backpack
    assert result["summary_snapshot"]["calculation_schema"] == 2
    assert result["summary_snapshot"]["input_hash"]
    assert items == original
    assert result["items"][0]["shipping_quantity_difference"] == "-10"


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
    assert preview["summary"]["total_cost_rmb"] == "64800.00"
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
    assert result["summary"]["total_cost_rmb"] == "64800.00"
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
    assert result["total_cost_rmb"] == 64800
    assert result["checks"]["has_tariff"]
    assert not result["field_gaps"]["rules"]
    assert result["blocking_reasons"] == ["当前批次缺少归属业务主体。"]
    batch.update(status="Dirty", subsidiary_code="MX01")
    result = batch_service._build_calculation_confirmation_readiness(batch, items, fees, "V")
    assert not result["ready"] and result["checks"]["has_dirty_data"]


def test_saved_consumers_ignore_replaced_raw_tax_and_use_effective_shipping():
    from overseas_costing.services import batch_service, workbench_service
    items, fees, fx = inputs()
    items[1].update(actual_shipped_qty=None, actual_shipped_qty_mode="DEFAULT_PURCHASE")
    saved = service.build_saved_cost_data(items, fees, fx, "AIR")
    for item, update in zip(items, saved["item_updates"]):
        item.update(update, product_name="商品", unit_price=1, purchase_currency="RMB",
                    mexico_customs_rmb=50, import_tax_total=75)
        quick = workbench_service.build_batch_result_preview_item(item, calculated=True)
        detail = batch_service._item_expense_detail(item)
        assert quick["tax_alloc_rmb"] == detail["clearance_and_tax"]["tax_alloc_rmb"] == 0
        assert quick["clearance_alloc_rmb"] == detail["clearance_and_tax"]["clearance_alloc_rmb"]
        extras = sum(quick[key] for key in ("freight_alloc_rmb", "tax_alloc_rmb", "clearance_alloc_rmb", "unlisted_other_cost_rmb"))
        assert extras == pytest.approx(float(item["total_cost_rmb"]) - item["goods_value"])
    batch = dict(current_version="V", status="Calculated", subsidiary_code="MX01", summary_snapshot=saved["summary_snapshot"])
    ready = batch_service._build_calculation_confirmation_readiness(batch, items, fees, "V")
    assert ready["ready"], ready
    assert ready["expense_pools"]["item_allocations"]["tariff_tax_total"] == 0
    assert ready["expense_pools"]["item_allocations"]["clearance_fee_rmb"] == 12000
    quick = workbench_service.build_batch_result_preview_payload(batch=batch, version={"calculated_at": "NOW"}, items=items)
    assert quick["summary"]["weighted_total_unit_rmb"] == pytest.approx(64800 / 7990, abs=1e-6)


def test_subcent_goods_rounding_conserves_saved_sku_and_summary_totals():
    items, fees, fx = inputs()
    for item in items:
        item["goods_value"] = "100.005"
    for fee in fees:
        fee["amount"] = 0
    saved = service.build_saved_cost_data(items, fees, fx, "AIR")
    assert sum(Decimal(row["total_cost_rmb"]) for row in saved["item_updates"]) == Decimal(saved["summary"]["total_cost_rmb"]) == Decimal("200.01")


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
