"""Changing current versions must align batch locks/results with that version."""

from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from overseas_costing.services import calculate_service as service


class LifecycleFrappe:
    def __init__(self):
        self.records = {
            "Overseas Cost Batch": {"B1": dict(name="B1", current_version="CONFIRMED", status="Confirmed",
                confirm_status="Confirmed", is_locked=1, version_count=3, item_count=9, total_goods_value=900,
                total_gross_weight_kg=90, estimated_total_cost_rmb=990, actual_total_cost_rmb=990,
                writeback_status="Success", writeback_time="2026-09-01", writeback_message="old success", erp_target_doc="ERP-OLD")},
            "Overseas Cost Version": {
                "CONFIRMED": dict(name="CONFIRMED", batch="B1", status="Confirmed", is_current=1, version_type="Actual",
                    summary_snapshot_json=json.dumps(dict(item_count=1, total_goods_value=100, total_gross_weight_kg=10, total_cost_rmb=150)),
                    rule_snapshot_json='[{"amount":50}]', calculated_at="2026-09-01", fx_usd_to_rmb=7, fx_rmb_to_mxn=2.5),
                "ADJUSTMENT": dict(name="ADJUSTMENT", batch="B1", status="Active", is_current=0, version_type="Adjustment",
                    summary_snapshot_json='{"total_cost_rmb":888}', calculated_at="2026-09-02"),
                "ARCHIVED": dict(name="ARCHIVED", batch="B1", status="Archived", is_current=0, version_type="Estimated",
                    summary_snapshot_json=json.dumps(dict(item_count=1, total_goods_value=200, total_gross_weight_kg=20, total_cost_rmb=250))),
                "FOREIGN": dict(name="FOREIGN", batch="B2", status="Confirmed", is_current=1),
            },
            "Overseas Cost Item": {
                "I1": dict(name="I1", batch="B1", version="CONFIRMED", quantity=10, goods_value=100),
                "I2": dict(name="I2", batch="B1", version="ADJUSTMENT", quantity=20, goods_value=200),
            },
            "Overseas Cost Allocation Rule": {"R1": dict(name="R1", batch="B1", version="CONFIRMED", amount=50)},
        }
        self.records.setdefault('Overseas Cost Fee Evidence', {})
        self.records.setdefault('Overseas Cost Fee SKU Component', {})
        self.original = deepcopy(self.records)
        self.events = []
        self.commits = 0
        self.rollbacks = 0
        self.db = self
        self.next_id = 0

    def get_value(self, doctype, key, fields, as_dict=False):
        self.events.append(("read", doctype, key))
        row = self.records[doctype].get(key) if isinstance(key, str) else next((r for r in self.records[doctype].values() if all(r.get(k) == v for k, v in key.items())), None)
        if row is None:
            return None
        if isinstance(fields, str):
            return row.get(fields)
        values = {field: row.get(field) for field in fields}
        return values if as_dict else tuple(values.values())

    def sql(self, query, parameters):
        self.events.append(("lock", query, parameters))
        return []

    def get_all(self, doctype, *, filters, fields, **kwargs):
        self.events.append(("list", doctype, dict(filters)))
        return [dict(row) if fields == ['*'] else {field: row.get(field) for field in fields} for row in self.records[doctype].values()
                if all(row.get(key) == value for key, value in filters.items())]

    def count(self, doctype, filters):
        return len(self.get_all(doctype, filters=filters, fields=["name"]))

    def set_value(self, doctype, name, values, value=None, **kwargs):
        self.events.append(("write", doctype, name))
        updates = values if isinstance(values, dict) else {values: value}
        self.records[doctype][name].update(updates)

    def get_doc(self, doctype_or_values, name=None):
        if isinstance(doctype_or_values, dict):
            return self._doc(dict(doctype_or_values))
        return self._doc({"doctype": doctype_or_values, **self.records[doctype_or_values][name]})

    def _doc(self, values):
        doc = SimpleNamespace(**values)
        def insert(**kwargs):
            self.next_id += 1
            doc.name = f"NEW-{self.next_id}"
            row = {key: value for key, value in vars(doc).items() if key not in {"doctype", "insert", "as_dict"}}
            self.records[doc.doctype][doc.name] = row
            self.events.append(("insert", doc.doctype, doc.name))
            return doc
        doc.as_dict = lambda: {key: value for key, value in vars(doc).items() if key not in {'insert', 'as_dict'}}
        doc.insert = insert
        return doc

    def copy_doc(self, doc):
        return self._doc({key: value for key, value in vars(doc).items() if key not in {"name", "insert"}})

    def commit(self):
        self.commits += 1
        self.original = deepcopy(self.records)

    def rollback(self):
        self.rollbacks += 1
        self.records = deepcopy(self.original)


@pytest.fixture
def lifecycle(monkeypatch):
    frappe = LifecycleFrappe()
    monkeypatch.setattr(service, "_frappe", frappe)
    monkeypatch.setattr(service, "_resolve_batch_name", lambda _name: "B1")
    monkeypatch.setattr(service, "_insert_audit_log", lambda **kwargs: None)
    monkeypatch.setattr(service, "_now", lambda: "2026-09-08 10:00:00")
    return frappe


def test_switch_to_active_adjustment_unlocks_batch_and_clears_previous_results(lifecycle):
    original_versions = deepcopy(lifecycle.records["Overseas Cost Version"])
    result = service.switch_version("B1", "ADJUSTMENT")
    batch = lifecycle.records["Overseas Cost Batch"]["B1"]
    assert result["ok"] is True
    assert batch["current_version"] == "ADJUSTMENT"
    assert (batch["status"], batch["confirm_status"], batch["is_locked"]) == ("Dirty", "Pending", 0)
    assert batch["estimated_total_cost_rmb"] == batch["actual_total_cost_rmb"] == 0
    assert batch["writeback_status"] == "Not Started"
    assert batch["writeback_time"] is None
    assert batch["writeback_message"] == batch["erp_target_doc"] == ""
    assert batch["item_count"] == 1
    for name, before in original_versions.items():
        assert {k: v for k, v in lifecycle.records["Overseas Cost Version"][name].items() if k != "is_current"} == {k: v for k, v in before.items() if k != "is_current"}
    locks = [event for event in lifecycle.events if event[0] == "lock"]
    assert "tabOverseas Cost Batch" in locks[0][1]
    assert "tabOverseas Cost Version" in locks[1][1]
    assert all("FOR UPDATE" in event[1] for event in locks)
    assert lifecycle.events[0][0] == "lock"


@pytest.mark.parametrize("target,total", [("CONFIRMED", 150), ("ARCHIVED", 250)])
def test_switch_to_historical_version_remains_locked_and_uses_its_snapshot(lifecycle, target, total):
    lifecycle.records["Overseas Cost Batch"]["B1"].update(current_version="ADJUSTMENT", status="Dirty", confirm_status="Pending", is_locked=0)
    result = service.switch_version("B1", target)
    batch = lifecycle.records["Overseas Cost Batch"]["B1"]
    assert result["ok"] is True
    assert (batch["status"], batch["confirm_status"], batch["is_locked"]) == ("Confirmed", "Confirmed", 1)
    assert batch["estimated_total_cost_rmb"] == total
    assert batch["actual_total_cost_rmb"] == (total if target == "CONFIRMED" else 0)
    assert lifecycle.records["Overseas Cost Version"][target]["status"] == lifecycle.original["Overseas Cost Version"][target]["status"]


def test_clone_rejects_source_version_from_other_batch_before_inserting(lifecycle):
    result = service.create_version("B1", "FOREIGN", "Adjustment")
    assert result["ok"] is False
    assert "源版本不属于" in result["message"]
    assert not [event for event in lifecycle.events if event[0] in {"insert", "write"}]
    assert lifecycle.commits == 0


def test_confirmed_version_clone_starts_uncalculated_and_switches_to_editable(lifecycle):
    original = deepcopy(lifecycle.records["Overseas Cost Version"]["CONFIRMED"])
    result = service.create_version("B1", "CONFIRMED", "Adjustment")
    assert result["ok"] is True
    version = lifecycle.records["Overseas Cost Version"][result["version_name"]]
    assert version["status"] == "Active"
    assert not version.get("summary_snapshot_json") and not version.get("calculated_at")
    assert lifecycle.records["Overseas Cost Version"]["CONFIRMED"] == original
    locks = [event[1] for event in lifecycle.events if event[0] == "lock"]
    assert "tabOverseas Cost Batch" in locks[0]
    assert "tabOverseas Cost Version" in locks[1]
    assert any("tabOverseas Cost Item" in query for query in locks)
    assert any("tabOverseas Cost Allocation Rule" in query for query in locks)
    service.switch_version("B1", result["version_name"])
    assert lifecycle.records["Overseas Cost Batch"]["B1"]["is_locked"] == 0


def test_failed_switch_rolls_back_current_flags_and_batch_state(lifecycle, monkeypatch):
    original = deepcopy(lifecycle.records)
    def fail(**kwargs):
        raise RuntimeError("audit failed")
    monkeypatch.setattr(service, "_insert_audit_log", fail)
    with pytest.raises(RuntimeError, match="audit failed"):
        service.switch_version("B1", "ADJUSTMENT")
    assert lifecycle.records == original
    assert lifecycle.rollbacks == 1 and lifecycle.commits == 0


def test_switching_to_current_version_is_noop_and_preserves_saved_push_state(lifecycle):
    original = deepcopy(lifecycle.records)
    result = service.switch_version("B1", "CONFIRMED")
    assert result["ok"] is True
    assert lifecycle.records == original
    assert not [event for event in lifecycle.events if event[0] == "write"]


def test_failed_clone_rolls_back_new_version_and_child_copies(lifecycle, monkeypatch):
    original = deepcopy(lifecycle.records)
    def fail(**kwargs):
        raise RuntimeError("audit failed")
    monkeypatch.setattr(service, "_insert_audit_log", fail)
    with pytest.raises(RuntimeError, match="audit failed"):
        service.create_version("B1", "CONFIRMED", "Adjustment")
    assert lifecycle.records == original
    assert lifecycle.rollbacks == 1 and lifecycle.commits == 0


def test_cloned_adjustment_passes_saved_calculation_lifecycle_guards(lifecycle):
    from overseas_costing.services import cost_preview_service, fee_service

    created = service.create_version("B1", "CONFIRMED", "Adjustment")
    version_name = created["version_name"]
    service.switch_version("B1", version_name)
    saved = []
    class Repository:
        def lock_and_load(self, batch, version, **kwargs):
            record = lifecycle.records["Overseas Cost Batch"][batch]
            version_record = lifecycle.records["Overseas Cost Version"][version]
            fees = fee_service.build_default_fee_templates("AIR")
            for fee in fees:
                fee.update(amount=0, amount_status="ACTUAL", virtual=False)
            return ({**record, "batch": batch, "version": version, "version_status": version_record["status"], "transport_mode": "AIR"},
                    [dict(name="ITEM", stable_line_key="LINE", material_code="M1", quantity=10, goods_value=100,
                          unit="个", purchase_uom="个", shipped_uom="个", actual_shipped_qty_mode="DEFAULT_PURCHASE")],
                    fees, dict(fx_usd_to_rmb=7, fx_rmb_to_mxn=2.5))
        def assert_unchanged(self, context):
            assert context["current_version"] == version_name
        def save(self, context, result):
            saved.append(result)
            return "M2"
        def commit(self):
            pass
        def rollback(self):
            raise AssertionError("valid active adjustment must calculate")
    result = cost_preview_service.calculate_comprehensive_cost("B1", version_name, repository=Repository())
    assert result["ok"] is True
    assert len(saved) == 1


def test_manual_adjustment_preserves_fee_evidence_components_and_legacy_scope(lifecycle):
    lifecycle.records['Overseas Cost Fee Evidence']['E1'] = dict(name='E1',batch='B1',version='CONFIRMED',fee_rule='R1',attachment='FILE1')
    lifecycle.records['Overseas Cost Fee SKU Component']['C1'] = dict(name='C1',batch='B1',version='CONFIRMED',fee_rule='R1',item='I1',evidence='E1',amount_rmb='80',is_active=1)
    lifecycle.records['Overseas Cost Allocation Rule']['R1'].update(scope_type='DIRECT_ITEM',scope_value_json='["legacy:I1"]')
    result=service.create_version('B1','CONFIRMED','Adjustment')
    version=result['version_name']
    item=next(r for r in lifecycle.records['Overseas Cost Item'].values() if r['version']==version)
    evidence=next(r for r in lifecycle.records['Overseas Cost Fee Evidence'].values() if r['version']==version)
    component=next(r for r in lifecycle.records['Overseas Cost Fee SKU Component'].values() if r['version']==version)
    assert item['stable_line_key']=='legacy:I1'
    assert component['item']==item['name'] and component['evidence']==evidence['name']
    assert component['fee_rule']==evidence['fee_rule'] and evidence['fee_rule']!='R1'
    assert component['amount_rmb']=='80' and evidence['attachment']=='FILE1'
