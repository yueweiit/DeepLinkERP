"""Sync regressions for archived approval 202609032107000062462: 8 shipment / 5 purchase rows."""

from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from overseas_costing.scripts import import_oa_logistics as sync
from overseas_costing.services import import_service


GOODS = [("FL000429", 96000), ("FL000429", 4000), ("FL000427", 4000),
         ("FL000427", 96000), ("FL000428", 100000), ("FL000430", 100000),
         ("FL003377", 22000), ("CW000191", 2400)]
PURCHASE = [("FL000427", 100000, 15100), ("FL000428", 100000, 15100),
            ("FL000429", 100000, 15100), ("FL000430", 100000, 15100),
            ("FL003377", 200000, 26000)]


def approval():
    return {"source_approval_no": "202609032107000062462", "source_instance_id": "LOG-6262",
            "linked_purchase_approvals": [{"source_instance_id": "PUR-1"}],
            "form_fields": {"货物信息Bienes": [
                {"物料编码": code, "物料名称": code, "数量": qty, "单位": "个"}
                for code, qty in GOODS]}}


def purchase_rows():
    return [{"name": f"PURCHASE-{index}", "material_code": code, "product_name": code,
             "quantity": qty, "goods_value": value, "unit_price": value / qty,
             "unit": "个", "purchase_currency": "RMB", "source_type": "PURCHASE_EXPENSE_OA",
             "source_instance_id": "PUR-1", "dingtalk_instance_id": "PUR-1"}
            for index, (code, qty, value) in enumerate(PURCHASE, 1)]


def logistics_rows():
    facts = {row["material_code"]: row for row in purchase_rows()}
    rows = []
    for index, (code, qty) in enumerate(GOODS, 1):
        fact = facts.get(code, {})
        shipment_total = sum(q for c, q in GOODS if c == code)
        rows.append({"name": f"SHIPMENT-{index}", "material_code": code,
                     "quantity": fact["quantity"] * qty / shipment_total if fact else None,
                     "goods_value": fact["goods_value"] * qty / shipment_total if fact else None,
                     "actual_shipped_qty": qty, "actual_shipped_qty_mode": "EXPLICIT_SOURCE",
                     "shipped_uom": "个", "source_type": "OA_LOGISTICS_ROW",
                     "stable_line_key": f"logistics:{index}", "net_weight_kg": index,
                     "extra_json": json.dumps({"logistics_row": {"purchase_fact": fact}})})
    return rows


class MemoryFrappe:
    def __init__(self, rows):
        self.items = deepcopy(rows)
        self.deleted = []
        self.audits = []
        self.batch = {"name": "B1", "batch_no": "LOG-6262", "current_version": "V1",
                      "transport_mode": "SEA", "extra_json": json.dumps({
                          "source": "dingtalk_oa_logistics", **approval()})}
        self.db = self

    def get_all(self, doctype, **kwargs):
        if doctype == "Overseas Cost Batch":
            return [deepcopy(self.batch)]
        if doctype == "Overseas Cost Item":
            return deepcopy(self.items)
        return []

    def count(self, doctype, filters):
        return len(self.items)

    def get_value(self, doctype, name, field):
        return self.batch.get(field)

    def set_value(self, doctype, name, values, **kwargs):
        assert doctype == "Overseas Cost Batch"
        self.batch.update(values)

    def delete(self, doctype, filters):
        self.deleted.append((doctype, filters))
        self.items.clear()

    def get_meta(self, doctype):
        return SimpleNamespace(has_field=lambda field: True)

    def get_doc(self, payload):
        def insert(**kwargs):
            row = deepcopy(payload)
            row["name"] = f"CREATED-{len(self.items) + len(self.audits) + 1}"
            (self.items if row["doctype"] == "Overseas Cost Item" else self.audits).append(row)
            return SimpleNamespace(name=row["name"])
        return SimpleNamespace(insert=insert)

    def savepoint(self, name):
        pass

    def rollback(self, **kwargs):
        raise AssertionError("read-only sync should not require rollback")


def install_preview(monkeypatch, rows):
    monkeypatch.setattr(import_service, "preview_linked_purchase_expense_oa", lambda **kwargs: {
        "ok": True, "mapped_preview_items": deepcopy(rows)})
    monkeypatch.setattr(import_service, "apply_linked_purchase_expense_fillable_fields", lambda **kwargs: (
        pytest.fail("logistics rows and purchase facts must remain read-only until confirmation")))


def test_new_import_keeps_eight_logistics_rows_and_explicit_shipment_quantities(monkeypatch):
    store = MemoryFrappe([])
    monkeypatch.setattr(sync, "frappe", store)
    install_preview(monkeypatch, purchase_rows())
    created = sync._sync_oa_goods_items(batch_name="B1", version_name="V1", approval_item=approval())
    result = sync._sync_linked_purchase_fields(batch_name="B1", version_name="V1", approval_item=approval())
    assert created["created_count"] == 8
    assert [(row["material_code"], row.get("actual_shipped_qty")) for row in store.items] == GOODS
    assert all(row["actual_shipped_qty_mode"] == "EXPLICIT_SOURCE" and row["shipped_uom"] == "个"
               for row in store.items)
    assert store.deleted == []
    assert result["updated_count"] == result["deleted_count"] == 0


@pytest.mark.parametrize("existing", [logistics_rows, purchase_rows])
def test_linked_purchase_sync_preserves_confirmed_eight_rows_or_legacy_five(monkeypatch, existing):
    store = MemoryFrappe(existing())
    before = deepcopy(store.items)
    monkeypatch.setattr(sync, "frappe", store)
    install_preview(monkeypatch, purchase_rows())
    result = sync._sync_linked_purchase_fields(batch_name="B1", version_name="V1", approval_item=approval())
    assert store.items == before
    assert store.deleted == []
    assert result["confirmation_required"] is True
    assert result["purchase_preview"]["mapped_preview_items"] == purchase_rows()


@pytest.mark.parametrize("source", [approval(), {}])
def test_direct_purchase_rebuild_cannot_delete_logistics_rows(monkeypatch, source):
    store = MemoryFrappe(logistics_rows())
    before = deepcopy(store.items)
    monkeypatch.setattr(sync, "frappe", store)
    result = sync._replace_items_with_purchase_expense_rows(
        batch_name="B1", version_name="V1", approval_item=source, purchase_rows=purchase_rows())
    assert store.items == before
    assert store.deleted == []
    assert result["created_count"] == result["updated_count"] == 0


def test_empty_purchase_preview_does_not_fall_through_to_logistics_field_write(monkeypatch):
    store = MemoryFrappe(logistics_rows())
    monkeypatch.setattr(sync, "frappe", store)
    install_preview(monkeypatch, [])
    result = sync._sync_linked_purchase_fields(
        batch_name="B1", version_name="V1", approval_item={"linked_purchase_approvals": [{"source_instance_id": "PUR-1"}]})
    assert result["confirmation_required"] is True
    assert result["updated_count"] == 0


def test_excluded_purchase_sync_does_not_migrate_legacy_five_to_eight(monkeypatch):
    store = MemoryFrappe(purchase_rows())
    before = deepcopy(store.items)
    monkeypatch.setattr(sync, "frappe", store)
    result = sync._restore_main_logistics_items_after_excluded_purchases(
        batch_name="B1", version_name="V1", approval_item=approval(),
        excluded_purchase_summaries=[{"source_instance_id": "PUR-1", "excluded": True}])
    assert store.items == before
    assert store.deleted == []
    assert result["action"] == "manual_required"
    assert result["deleted_count"] == result["created_count"] == 0


def test_existing_batch_sync_carries_main_logistics_rows_from_stored_trace(monkeypatch):
    store = MemoryFrappe(purchase_rows())
    before = deepcopy(store.items)
    monkeypatch.setattr(sync, "frappe", store)
    install_preview(monkeypatch, purchase_rows())
    result = sync.sync_existing_linked_purchase_fields()
    assert store.items == before
    assert store.deleted == []
    assert result["items"][0]["purchase_sync"]["confirmation_required"] is True


def test_purchase_process_sync_preserves_logistics_purchase_facts(monkeypatch):
    store = MemoryFrappe(logistics_rows())
    before = deepcopy(store.items)
    monkeypatch.setattr(sync, "frappe", store)
    monkeypatch.setattr(sync, "resolve_dingtalk_env_file", lambda value: "")
    monkeypatch.setattr(sync, "pull_purchase_expense_approvals", lambda **kwargs: {
        "ok": True, "items": [{"source_instance_id": "PUR-1", "mapped_preview_items": purchase_rows()}]})
    install_preview(monkeypatch, purchase_rows())
    result = sync.sync_purchase_expenses_from_process(process_code="PROC-PURCHASE", start="2026-09-01", end="2026-09-09")
    assert store.items == before
    assert store.deleted == []
    assert result["items"][0]["purchase_sync"]["confirmation_required"] is True
