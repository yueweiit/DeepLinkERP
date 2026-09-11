"""Preview-first repair for the live 8-row shipment value batch."""
from copy import deepcopy
from datetime import datetime, timedelta
import gzip
import importlib
import json
from decimal import Decimal
from types import SimpleNamespace

import pytest

from overseas_costing.services.cost_preview_service import preview_comprehensive_cost_data
from overseas_costing.services.material_input_service import present_material_row
from overseas_costing.services.shipment_cost_service import shipment_value


def service():
    return importlib.import_module("overseas_costing.scripts.repair_shipment_valuation")


GOODS = [
    ("FL000429", "96000", "14496"),
    ("FL000429", "4000", "604"),
    ("FL000427", "4000", "604"),
    ("FL000427", "96000", "14496"),
    ("FL000428", "100000", "15100"),
    ("FL000430", "100000", "15100"),
    ("FL003377", "22000", "2860"),
    ("CW000191", "2400", None),
]
PURCHASE = {
    "FL000429": ("0.151", "100000", "15100"),
    "FL000427": ("0.151", "100000", "15100"),
    "FL000428": ("0.151", "100000", "15100"),
    "FL000430": ("0.151", "100000", "15100"),
    "FL003377": ("0.13", "200000", "26000"),
}


def _item(index, code, qty, amount, *, damaged=True):
    purchase = PURCHASE.get(code)
    cargo = {"quantity": qty, "unit": "个", "material_code": code, "binding_id": "PACK-1"}
    extra = {"ai_fill_original_values": {"goods_value": "26000" if code == "FL003377" else 0}}
    if purchase:
        extra["logistics_row"] = {
            "purchase_key": f"PUR:{code}",
            "purchase_source_id": "approval:PUR-1:form",
            "purchase_fact": {
                "unit_price": purchase[0],
                "purchase_currency": "人民币RMB",
                "unit_price_uom": "个",
                "purchase_uom": "个",
                "unit": "个",
                "quantity": purchase[1],
                "goods_value": purchase[2],
                "source_doc_no": "PUR-1",
                "material_code": code,
            },
        }
        extra["settlement_cargo"] = cargo
        extra["settlement_valuation"] = {
            "amount_rmb": None,
            "status": "missing",
            "error": "SETTLEMENT_PURCHASE_CURRENCY_OR_FX_REQUIRED",
            "currency": "RMB",
            "quantity": qty,
            "uom": "个",
            "method": "settlement_purchase_unit_price",
        }
        goods_value = 26000 if code == "FL003377" else 0
        unit_price, purchase_qty = purchase[0], purchase[1]
    else:
        extra["settlement_cargo"] = cargo
        extra["settlement_valuation"] = {
            "amount_rmb": None,
            "status": "missing",
            "error": "SETTLEMENT_PURCHASE_PRICE_EVIDENCE_REQUIRED",
            "currency": "RMB",
            "quantity": qty,
            "uom": "个",
        }
        goods_value, unit_price, purchase_qty = 0, None, 0
    if not damaged:
        extra.pop("settlement_cargo", None)
        extra.pop("settlement_valuation", None)
    return {
        "name": f"I{index}",
        "row_no": index,
        "material_code": code,
        "product_name": code,
        "quantity": purchase_qty,
        "actual_shipped_qty": qty,
        "actual_shipped_qty_mode": "EXPLICIT_SOURCE",
        "shipped_uom": "个",
        "unit": "个",
        "unit_price": unit_price,
        "unit_price_uom": "个",
        "purchase_uom": "个",
        "purchase_currency": "人民币RMB" if purchase else "",
        "source_doc_no": "PUR-1" if purchase else "",
        "goods_value": goods_value,
        "extra_json": json.dumps(extra, ensure_ascii=False),
    }


def snapshot(*, damaged=True):
    items = [_item(index, code, qty, amount, damaged=damaged)
             for index, (code, qty, amount) in enumerate(GOODS, 1)]
    return {
        "batch": dict(
            name="vunn2lvq4k",
            batch_no="202609032107000062462",
            current_version="vunna0uia0",
            transport_mode="SEA",
            status="Calculated",
            confirm_status="Pending",
            is_locked=0,
            writeback_status="Not Started",
            source_approval_status="COMPLETED",
            extra_json="{}",
            modified="2026-09-11 12:00:00",
        ),
        "version": dict(
            name="vunna0uia0",
            batch="vunn2lvq4k",
            status="Active",
            extra_json=json.dumps({"ai_row_adoption": {"run_id": "AI-6262", "fingerprint": "adopt-1"}}),
            fx_usd_to_rmb="7.1",
            fx_rmb_to_mxn="2.6",
        ),
        "items": items,
        "rules": [dict(name="R1", amount="2004", currency="RMB")],
    }


def test_damaged_batch_restores_six_rows_keeps_conflict_and_pending():
    data = snapshot()
    before = deepcopy(data)
    plan = service().plan_batch_repair(data)

    assert plan["status"] == "ready"
    assert data == before
    kinds = [change["kind"] for change in plan["changes"]]
    assert kinds == ["restore", "restore", "restore", "restore", "restore", "restore", "conflict", "missing"]
    amounts = [change["values"]["goods_value"] for change in plan["changes"] if change["kind"] == "restore"]
    assert [Decimal(str(amount)) for amount in amounts] == [Decimal("14496"), Decimal("604"), Decimal("604"),
                                                            Decimal("14496"), Decimal("15100"), Decimal("15100")]
    conflict = next(change for change in plan["changes"] if change["kind"] == "conflict")
    assert Decimal(str(conflict["prior_amount_rmb"])) == Decimal("26000")
    assert Decimal(str(conflict["calculated_amount_rmb"])) == Decimal("2860")
    assert conflict["values"]["goods_value"] == 0
    missing = next(change for change in plan["changes"] if change["kind"] == "missing")
    assert missing["item_name"] == "I8" and missing["values"]["goods_value"] == 0


def test_repeat_repair_is_noop_after_desired_state():
    data = snapshot()
    plan = service().plan_batch_repair(data)
    for change in plan["changes"]:
        item = next(row for row in data["items"] if row["name"] == change["item_name"])
        item.update(change["values"])
    assert service().plan_batch_repair(data)["status"] == "unchanged"


@pytest.mark.parametrize("section,field,value,code", [
    ("batch", "is_locked", 1, "FROZEN"),
    ("batch", "confirm_status", "Confirmed", "FROZEN"),
    ("batch", "status", "Written Back", "FROZEN"),
    ("version", "status", "Archived", "FROZEN"),
    ("batch", "current_version", "OTHER", "VERSION_CHANGED"),
    ("batch", "batch_no", "OTHER", "BATCH_CHANGED"),
    ("batch", "source_approval_status", "TERMINATED", "INVALID_APPROVAL"),
    ("batch", "edit_lock_expires_at", (datetime.now() + timedelta(hours=1)).isoformat(), "EDIT_IN_PROGRESS"),
])
def test_protected_batches_are_skipped(section, field, value, code):
    data = snapshot()
    data[section][field] = value
    result = service().plan_batch_repair(data)
    assert result["status"] == "skipped" and result["reason_code"] == code
    assert not result["changes"]


def test_padded_decimal_quantities_and_original_values_still_repair():
    data = snapshot()
    for item in data["items"]:
        item["actual_shipped_qty"] = f"{Decimal(str(item['actual_shipped_qty'])):.9f}"
        extra = json.loads(item["extra_json"])
        extra.pop("logistics_row", None)
        extra["settlement_original_values"] = {"goods_value": extra["ai_fill_original_values"]["goods_value"]}
        item["extra_json"] = json.dumps(extra, ensure_ascii=False)
        item["unit_price_uom"] = None
        item["purchase_uom"] = None
    plan = service().plan_batch_repair(data)
    assert plan["status"] == "ready"
    assert [change["kind"] for change in plan["changes"]] == [
        "restore", "restore", "restore", "restore", "restore", "restore", "conflict", "missing"]


def test_row_identity_or_adoption_change_stops_repair():
    moved = snapshot()
    moved["items"][0]["actual_shipped_qty"] = "96001"
    result = service().plan_batch_repair(moved)
    assert result["reason_code"] == "ROWS_CHANGED" and not result["changes"]

    adopted = snapshot()
    adopted["version"]["extra_json"] = "{}"
    result = service().plan_batch_repair(adopted)
    assert result["reason_code"] == "ADOPTION_CHANGED" and not result["changes"]


def test_manual_override_is_left_alone_and_does_not_block_other_rows():
    data = snapshot()
    data["items"][0]["extra_json"] = json.dumps({
        **json.loads(data["items"][0]["extra_json"]),
        "manual_shipment_valuation": {
            "amount_rmb": "1", "currency": "RMB", "confirmed": True, "manual": True,
            "status": "manual", "input_fingerprint": "x",
        },
    })
    plan = service().plan_batch_repair(data)
    assert all(change["item_name"] != "I1" for change in plan["changes"])
    assert any(change["kind"] == "conflict" for change in plan["changes"])


class Repository:
    def __init__(self, data=None):
        self.data = {"vunn2lvq4k": data or snapshot()}
        self.original = deepcopy(self.data)
        self.saved = []
        self.commits = 0
        self.rollbacks = 0
        self.lock_count = 0
        self.authorized = True
        self.backup_valid = True
        self.fail_save = False
        self.drift = False

    def assert_operator(self):
        if not self.authorized:
            raise PermissionError("System Manager required")

    def candidates(self):
        return list(self.data)

    def load(self, batch, *, lock=False):
        self.lock_count += int(lock)
        data = deepcopy(self.data[batch])
        if lock and self.drift:
            data["items"][0]["actual_shipped_qty"] = "1"
        return data

    def validate_backup(self, path):
        if not self.backup_valid:
            raise ValueError("backup required")
        return {"path": path, "sha256": "backup-digest"}

    def save(self, before, plan):
        batch = before["batch"]["name"]
        self.transaction = deepcopy(self.data[batch])
        for change in plan["changes"]:
            item = next(row for row in self.data[batch]["items"] if row["name"] == change["item_name"])
            item.update(change["values"])
        self.data[batch]["batch"]["status"] = "Dirty"
        if self.fail_save:
            raise RuntimeError("audit failed")
        self.saved.append(deepcopy(plan))
        return "AUDIT-1"

    def commit(self):
        self.commits += 1
        self.transaction = None

    def rollback(self):
        self.rollbacks += 1
        if getattr(self, "transaction", None):
            self.data["vunn2lvq4k"] = self.transaction
            self.transaction = None


def test_run_default_preview_does_not_lock_or_write():
    repo = Repository()
    result = service().run(repository=repo)
    assert result["ready_count"] == 1 and result["applied_count"] == 0
    assert result["manifest"]["vunn2lvq4k"] == service().snapshot_hash(repo.original["vunn2lvq4k"])
    assert not repo.saved and not repo.lock_count and not repo.commits
    assert repo.data == repo.original


def test_apply_requires_manifest_backup_and_operator():
    repo = Repository()
    with pytest.raises(ValueError):
        service().run(apply=True, repository=repo)
    manifest = service().run(repository=repo)["manifest"]
    repo.backup_valid = False
    with pytest.raises(ValueError):
        service().run(apply=True, manifest=manifest, backup_path="backup", repository=repo)
    repo.authorized = False
    with pytest.raises(PermissionError):
        service().run(repository=repo)
    assert not repo.saved


def test_apply_writes_audit_and_is_idempotent():
    repo = Repository()
    manifest = service().run(repository=repo)["manifest"]
    result = service().run(apply=True, manifest=manifest, backup_path="backup", repository=repo)
    assert result["applied_count"] == 1 and repo.commits == 1 and repo.lock_count == 1
    items = repo.data["vunn2lvq4k"]["items"]
    presented = [present_material_row(row) for row in items]
    assert [shipment_value(row)["status"] for row in presented[:6]] == ["automatic"] * 6
    assert [Decimal(str(row["shipment_value_rmb"])) for row in presented[:6]] == [
        Decimal("14496"), Decimal("604"), Decimal("604"), Decimal("14496"), Decimal("15100"), Decimal("15100")]
    seventh = shipment_value(presented[6])
    assert seventh["status"] == "conflict"
    assert Decimal(str(seventh["prior_amount_rmb"])) == Decimal("26000")
    assert Decimal(str(seventh["calculated_amount_rmb"])) == Decimal("2860")
    assert seventh["amount_rmb"] is None
    eighth = shipment_value(presented[7])
    assert eighth["status"] == "missing" and eighth["amount_rmb"] is None
    assert repo.data["vunn2lvq4k"]["rules"] == repo.original["vunn2lvq4k"]["rules"]
    preview = preview_comprehensive_cost_data(items, [], {})
    assert preview["summary"]["purchase_goods_value_rmb"] == "60400.00"
    assert any(row["reason_code"] == "SETTLEMENT_SHIPMENT_VALUE_CONFLICT" for row in preview["incomplete_reasons"])
    assert service().run(repository=repo)["ready_count"] == 0


def test_real_save_accepts_database_coerced_numbers_and_json():
    data = snapshot()
    plan = service().plan_batch_repair(data)
    state = deepcopy(data)
    audits = []

    def set_value(doctype, name, values, *args, **kwargs):
        if doctype == "Overseas Cost Batch":
            state["batch"].update(values if isinstance(values, dict) else {values: args[0]})
            state["batch"]["modified"] = "AFTER"
            return
        item = next(row for row in state["items"] if row["name"] == name)
        payload = values if isinstance(values, dict) else {values: args[0]}
        if "goods_value" in payload:
            item["goods_value"] = Decimal(str(payload["goods_value"]))
        if "extra_json" in payload:
            item["extra_json"] = json.dumps(json.loads(payload["extra_json"]), ensure_ascii=True, indent=2)
        item["modified"] = "AFTER"
        item["modified_by"] = "Administrator"

    def get_doc(payload):
        def insert(**kwargs):
            audits.append(payload)
            return SimpleNamespace(name="AUDIT-REAL-SAVE")
        return SimpleNamespace(insert=insert)

    repo = service().FrappeRepairRepository.__new__(service().FrappeRepairRepository)
    repo.frappe = SimpleNamespace(db=SimpleNamespace(set_value=set_value),
                                  session=SimpleNamespace(user="Administrator"), get_doc=get_doc)
    repo.load = lambda *args, **kwargs: deepcopy(state)
    assert repo.save(data, plan) == "AUDIT-REAL-SAVE"
    assert Decimal(str(state["items"][0]["goods_value"])) == Decimal("14496")
    assert json.loads(state["items"][6]["extra_json"])["settlement_valuation"]["status"] == "conflict"
    assert len(audits) == 1
    assert "packing list" not in audits[0]["old_value"]
    assert len(audits[0]["old_value"]) < 4000
    assert json.loads(audits[0]["old_value"])["items"][0]["extra_json_sha256"]


@pytest.mark.parametrize("failure,reason", [("drift", "SOURCE_CHANGED"), ("fail_save", "TRANSACTION_FAILED")])
def test_apply_detects_drift_and_rolls_back_partial_failure(failure, reason):
    repo = Repository()
    manifest = service().run(repository=repo)["manifest"]
    setattr(repo, failure, True)
    result = service().run(apply=True, manifest=manifest, backup_path="backup", repository=repo)
    assert result["applied_count"] == 0 and result["results"][0]["reason_code"] == reason
    assert repo.data == repo.original and repo.commits == 0


def test_database_backup_must_pass_full_gzip_integrity_check(tmp_path):
    directory = tmp_path / "private" / "backups"
    directory.mkdir(parents=True)
    path = directory / "20260911-site-database.sql.gz"
    compressed = gzip.compress(b"-- SQL backup\n" + bytes(range(256)) * 200)
    path.write_bytes(compressed)
    repo = service().FrappeRepairRepository.__new__(service().FrappeRepairRepository)
    repo.frappe = SimpleNamespace(get_site_path=lambda *parts: str(tmp_path.joinpath(*parts)))
    assert repo.validate_backup(str(path))["sha256"]
    path.write_bytes(compressed[:-8])
    with pytest.raises((ValueError, EOFError, gzip.BadGzipFile)):
        repo.validate_backup(str(path))
