"""Source facts must enter through trusted services, not browser document payloads."""

import importlib.util
import json
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace

import pytest

from overseas_costing.services import calculate_service


SOURCE_METADATA = {
    "shipment_valuation": {"amount_rmb": "10560", "quantity": "2400", "uom": "个"},
    "logistics_row": {"identity": "logistics:1", "purchase_fact": {"unit_price": "4.4"}},
    "autofill_review": {"run_id": "RUN-1", "source_refs": [{"source_id": "X"}]},
}
POLICY = {"method": "PROJECT_GROSS_WEIGHT", "projects": ["项目一", "项目二"],
          "source_refs": [{"source_id": "APPROVAL-1"}]}


class DocumentDouble:
    """Only replace Frappe persistence; real controller validation runs on every save.

    Frappe BaseDocument reserves flags and _doc_before_save against payload update.
    The double retains that boundary and the server's ignore_permissions argument.
    """

    def __init__(self, payload, previous=None):
        self.transport_mode = ""
        self.material_code = ""
        self.product_name = ""
        self.__dict__.update({key: value for key, value in payload.items()
                              if key not in {"flags", "_doc_before_save"}})
        self.flags = {}
        self._previous = SimpleNamespace(**previous) if previous is not None else None
        self.saved = False

    def get_doc_before_save(self):
        return self._previous

    def save(self, ignore_permissions=False):
        self.flags["ignore_permissions"] = ignore_permissions
        self.validate()
        self.saved = True
        return self

    insert = save

    def as_dict(self):
        return {key: value for key, value in vars(self).items()
                if key not in {"flags", "_previous", "saved"}}


@pytest.fixture(params=["canonical", "frappe_module"])
def controllers(monkeypatch, request):
    from overseas_costing.services import fee_service
    # This fixture replaces persistence only; all controller validation still runs.
    monkeypatch.setattr(fee_service, "_query_rules", lambda *args: [])
    frappe = ModuleType("frappe")
    model = ModuleType("frappe.model")
    document = ModuleType("frappe.model.document")
    document.Document = DocumentDouble
    monkeypatch.setitem(sys.modules, "frappe", frappe)
    monkeypatch.setitem(sys.modules, "frappe.model", model)
    monkeypatch.setitem(sys.modules, "frappe.model.document", document)
    classes = []
    for slug, name in (("overseas_cost_item", "OverseasCostItem"),
                       ("overseas_cost_allocation_rule", "OverseasCostAllocationRule")):
        root = Path(__file__).resolve().parents[1]
        path = root / "doctype" / slug / f"{slug}.py"
        module_name = f"overseas_costing.doctype.{slug}.{slug}"
        spec = importlib.util.spec_from_file_location(module_name, path)
        module = importlib.util.module_from_spec(spec)
        monkeypatch.setitem(sys.modules, module_name, module)
        spec.loader.exec_module(module)
        if request.param == "frappe_module":
            path = root / "overseas_costing" / "doctype" / slug / f"{slug}.py"
            spec = importlib.util.spec_from_file_location(f"security_test_nested_{slug}", path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        classes.append(getattr(module, name))
    return classes


def _item(metadata):
    return {"name": "I", "batch": "B", "version": "V", "material_code": "CW000191",
            "product_name": "", "transport_mode": "SEA", "extra_json": json.dumps(metadata)}


def _fee(scope):
    return {"name": "F", "batch": "B", "version": "V", "rule_code": "international_sea_freight",
            "scope_type": "ALL_ITEMS", "allocation_basis": "gross_weight", "amount": "7756.20",
            "scope_value_json": json.dumps(scope)}


@pytest.mark.parametrize("key", SOURCE_METADATA)
def test_public_single_and_batch_edit_reject_source_metadata_injection(monkeypatch, key):
    monkeypatch.setattr(calculate_service, "_frappe", None)
    value = json.dumps({key: SOURCE_METADATA[key]})
    single = calculate_service.update_item_field("I", "extra_json", value, version_name="V")
    batch = calculate_service.batch_update_items("B", json.dumps([
        {"item_name": "I", "fieldname": "extra_json", "value": value}]), version_name="V")
    assert single["ok"] is False
    assert batch["ok"] is False
    assert "服务器" in single["message"]


@pytest.mark.parametrize("key", SOURCE_METADATA)
def test_public_create_rejects_source_metadata_injection(monkeypatch, key):
    monkeypatch.setattr(calculate_service, "_frappe", None)
    result = calculate_service.create_item("B", _item({key: SOURCE_METADATA[key]}), "V")
    assert result["ok"] is False
    assert "服务器" in result["message"]


def test_public_create_and_edit_preserve_ordinary_business_extensions(monkeypatch):
    monkeypatch.setattr(calculate_service, "_frappe", None)
    metadata = {"customer_note": "客户自提", "erp_reference": "ERP-1"}
    result = calculate_service.create_item("B", _item(metadata), "V")
    assert result["ok"] is True
    assert json.loads(result["item"]["extra_json"])["customer_note"] == "客户自提"
    edited = calculate_service.update_item_field("I", "extra_json", json.dumps(metadata), "V")
    assert edited["ok"] is True


@pytest.mark.parametrize("key", SOURCE_METADATA)
@pytest.mark.parametrize("action", ["insert", "replace", "remove"])
def test_item_document_save_rejects_source_fact_changes(controllers, key, action):
    item_class, _ = controllers
    metadata = {key: SOURCE_METADATA[key]}
    previous = None if action == "insert" else _item(metadata)
    candidate = {} if action == "remove" else {key: {"forged": True}}
    payload = {**_item(candidate), "flags": {"ignore_permissions": True},
               "_doc_before_save": _item(candidate)}
    doc = item_class(payload, previous)
    with pytest.raises(ValueError, match="服务器"):
        doc.save()
    assert not doc.saved


def test_item_document_allows_ordinary_edit_without_losing_source_metadata(controllers):
    item_class, _ = controllers
    before = _item({**SOURCE_METADATA, "note": "old"})
    doc = item_class(_item({**SOURCE_METADATA, "note": "new"}), before)
    doc.save()
    assert json.loads(doc.extra_json) == {**SOURCE_METADATA, "note": "new"}


@pytest.mark.parametrize("action", ["insert", "replace", "remove"])
def test_fee_document_save_rejects_project_policy_changes(controllers, action):
    _, fee_class = controllers
    old_scope = {"item_keys": [], "project_allocation": POLICY}
    previous = None if action == "insert" else _fee(old_scope)
    candidate = [] if action == "remove" else {"project_allocation": {**POLICY, "source_refs": [{"source_id": "FORGED"}]}}
    doc = fee_class({**_fee(candidate), "flags": {"ignore_permissions": True}}, previous)
    with pytest.raises(ValueError, match="服务器"):
        doc.save()
    assert not doc.saved


def test_fee_document_amount_edit_preserves_project_policy(controllers):
    _, fee_class = controllers
    before = _fee({"item_keys": [], "project_allocation": POLICY})
    doc = fee_class({**before, "amount": "8000"}, before)
    doc.save()
    assert doc.amount == "8000"
    assert json.loads(doc.scope_value_json)["project_allocation"] == POLICY


@pytest.mark.parametrize("field,value", [("scope_type", "ITEMS"), ("allocation_basis", "volume"),
                                         ("basis_field", "volume")])
def test_fee_document_cannot_change_confirmed_project_scope_or_basis(controllers, field, value):
    _, fee_class = controllers
    before = _fee({"item_keys": [], "project_allocation": POLICY})
    doc = fee_class({**before, field: value}, before)
    with pytest.raises(ValueError, match="项目"):
        doc.save()


def test_trusted_server_insert_keeps_confirmed_source_facts_and_policy(controllers):
    item_class, fee_class = controllers
    item = item_class(_item(SOURCE_METADATA))
    fee = fee_class(_fee({"item_keys": [], "project_allocation": POLICY}))
    item.insert(ignore_permissions=True)
    fee.insert(ignore_permissions=True)
    assert item.saved and fee.saved
    assert json.loads(item.extra_json) == SOURCE_METADATA
    assert json.loads(fee.scope_value_json)["project_allocation"] == POLICY


@pytest.mark.parametrize("kind", ["item", "fee"])
@pytest.mark.parametrize("owner_field", ["batch", "version"])
def test_document_cannot_move_unchanged_trusted_metadata_between_scopes(controllers, kind, owner_field):
    item_class, fee_class = controllers
    document_class = item_class if kind == "item" else fee_class
    before = _item(SOURCE_METADATA) if kind == "item" else _fee({"project_allocation": POLICY})
    doc = document_class({**before, owner_field: "OTHER"}, before)
    with pytest.raises(ValueError, match="服务器.*批次|服务器.*版本"):
        doc.save()
    assert not doc.saved


@pytest.mark.parametrize("kind", ["item", "fee"])
def test_trusted_internal_version_copy_can_keep_verified_metadata(controllers, kind):
    item_class, fee_class = controllers
    document_class = item_class if kind == "item" else fee_class
    before = _item(SOURCE_METADATA) if kind == "item" else _fee({"project_allocation": POLICY})
    doc = document_class({**before, "version": "V-COPY"}, before)
    doc.save(ignore_permissions=True)
    assert doc.saved and doc.version == "V-COPY"


def test_confirmed_reconciliation_still_inserts_source_metadata_through_real_controller(controllers):
    from overseas_costing.services.logistics_autofill_service import (
        apply_reconciliation,
        build_logistics_reconciliation,
    )
    from overseas_costing.services.material_ai_fill_service import validate_source_review_application
    from overseas_costing.tests.test_logistics_autofill import approval, existing_items

    item_class, _ = controllers
    original = existing_items()
    proposal = build_logistics_reconciliation(original, approval())
    for row in proposal["payload"]["rows"]:
        metadata = json.loads(row["extra_json"])
        metadata["shipment_valuation"] = SOURCE_METADATA["shipment_valuation"]
        row["extra_json"] = json.dumps(metadata)
    selected = validate_source_review_application([proposal], [proposal["proposal_id"]], {}, original)
    inserted = []
    updates = []

    def get_doc(payload):
        doc = item_class({**payload, "name": f"CREATED-{len(inserted) + 1}"})
        inserted.append(doc)
        return doc

    fake = SimpleNamespace(get_doc=get_doc, db=SimpleNamespace(
        set_value=lambda *args, **kwargs: updates.append((args, kwargs))))
    created = apply_reconciliation(fake, selected[0], batch="B", version="V", current=original, run_id="RUN-1")
    assert len(created) == len(inserted) == 3
    assert all(doc.saved for doc in inserted)
    metadata = [json.loads(doc.extra_json) for doc in inserted]
    assert all(row["autofill_review"]["run_id"] == "RUN-1" for row in metadata)
    assert all(row["shipment_valuation"] == SOURCE_METADATA["shipment_valuation"] for row in metadata)
    assert all("purchase_fact" in row["logistics_row"] for row in metadata)
    assert sum(args[0] == "Overseas Cost Item" for args, _kwargs in updates) == 5


@pytest.mark.parametrize("replacement", [{}, {"shipment_valuation": {"amount_rmb": "1"}}])
def test_public_edit_cannot_bypass_guard_via_trusted_document_save(monkeypatch, controllers, replacement):
    item_class, _ = controllers
    doc = item_class(_item(SOURCE_METADATA), _item(SOURCE_METADATA))
    fake = SimpleNamespace(get_doc=lambda *_args: doc,
                           db=SimpleNamespace(set_value=lambda *_a, **_k: None,
                                              get_value=lambda *_a, **_k: "m2"))
    monkeypatch.setattr(calculate_service, "_frappe", fake)
    monkeypatch.setattr(calculate_service, "_insert_audit_log", lambda **_kwargs: None)
    result = calculate_service.update_item_field("I", "extra_json", json.dumps(replacement),
                                                 "V", _skip_edit_check=True, _skip_commit=True)
    assert result["ok"] is False
    assert not doc.saved


def test_public_edit_keeps_protected_metadata_while_changing_extension(monkeypatch, controllers):
    item_class, _ = controllers
    before = _item({**SOURCE_METADATA, "note": "old"})
    doc = item_class(before, before)
    fake = SimpleNamespace(get_doc=lambda *_args: doc,
                           db=SimpleNamespace(sql=lambda *args, **kwargs: [{"current_version":"V", "version_status":"Active", "confirm_status":"Pending", "writeback_status":"Not Started"}], set_value=lambda *_a, **_k: None,
                                              get_value=lambda *_a, **_k: "m2"))
    monkeypatch.setattr(calculate_service, "_frappe", fake)
    monkeypatch.setattr(calculate_service, "_insert_audit_log", lambda **_kwargs: None)
    result = calculate_service.update_item_field("I", "extra_json", json.dumps({**SOURCE_METADATA, "note": "new"}),
                                                 "V", _skip_edit_check=True, _skip_commit=True)
    assert result["ok"] is True
    assert json.loads(doc.extra_json) == {**SOURCE_METADATA, "note": "new"}


@pytest.fixture
def legacy_fee_records(monkeypatch):
    fee = _fee({"item_keys": [], "project_allocation": POLICY})
    fee["basis_field"] = "gross_weight"
    writes = []
    records = {"F": fee}
    versions = {"V": "B", "V-OLDER": "B", "V-OTHER": "B-OTHER"}

    def get_value(doctype, name, fields, as_dict=False):
        if doctype == "Overseas Cost Version":
            assert fields == "batch"
            return versions.get(name)
        assert doctype == "Overseas Cost Allocation Rule"
        if fields == "name":
            return next((key for key, row in records.items()
                         if all(row.get(field) == value for field, value in name.items())), None)
        assert as_dict
        record = records.get(name)
        return {field: record.get(field) for field in fields} if record else None

    fake = SimpleNamespace(db=SimpleNamespace(
        get_value=get_value, set_value=lambda *args, **kwargs: writes.append((args, kwargs)),
        commit=lambda: None))
    monkeypatch.setattr(calculate_service, "_frappe", fake)
    monkeypatch.setattr(calculate_service, "_resolve_batch_name", lambda *_args: "B")
    monkeypatch.setattr(calculate_service, "_insert_audit_log", lambda **_kwargs: None)
    from overseas_costing.services import fee_service
    monkeypatch.setattr(fee_service, '_query_rules', lambda batch, version: [dict(row) for row in records.values() if row.get('batch') == batch and row.get('version') == version])
    fake.db.sql = lambda *args, **kwargs: [{'current_version':'V', 'version_status':'Active', 'confirm_status':'Pending', 'writeback_status':'Not Started'}]
    return records, writes


@pytest.fixture
def legacy_fee_endpoint(legacy_fee_records):
    return legacy_fee_records[1]


@pytest.mark.parametrize("change", [
    {"allocation_basis": "volume"}, {"basis_field": "volume"}, {"scope_type": "ITEMS"},
    {"scope_value_json": "[]"}, {"scope_value_json": json.dumps({"project_allocation": {"forged": True}})},
])
def test_legacy_allocation_endpoint_cannot_bypass_project_policy_guard(legacy_fee_endpoint, change):
    with pytest.raises(ValueError, match="项目|服务器"):
        calculate_service.update_allocation_rule("B", "V", json.dumps({"name": "F", **change}))
    assert legacy_fee_endpoint == []


def test_legacy_allocation_endpoint_allows_normal_amount_edit(legacy_fee_endpoint):
    result = calculate_service.update_allocation_rule("B", "V", json.dumps({"name": "F", "amount": "8000"}))
    assert result["ok"] is True
    rule_writes = [args for args, _kwargs in legacy_fee_endpoint if args[0] == "Overseas Cost Allocation Rule"]
    assert len(rule_writes) == 1
    assert rule_writes[0][2]["amount"] == "8000"
    assert "scope_value_json" not in rule_writes[0][2]


@pytest.mark.parametrize("target_version", ["V-OTHER", "V-MISSING"])
def test_legacy_allocation_endpoint_rejects_version_outside_batch(legacy_fee_records, target_version):
    _records, writes = legacy_fee_records
    with pytest.raises(ValueError, match="版本.*批次|版本.*存在"):
        calculate_service.update_allocation_rule("B", target_version, json.dumps({"name": "F", "amount": "1"}))
    assert writes == []


@pytest.mark.parametrize("owner", [{"batch": "B-OTHER", "version": "V-OTHER"},
                                  {"batch": "B", "version": "V-OLDER"}, None])
def test_legacy_allocation_endpoint_cannot_move_foreign_or_missing_rule(legacy_fee_records, owner):
    records, writes = legacy_fee_records
    if owner is not None:
        records["F-OTHER"] = {**records["F"], **owner, "name": "F-OTHER"}
    with pytest.raises(ValueError, match="规则.*批次|规则.*版本|规则.*存在"):
        calculate_service.update_allocation_rule("B", "V", json.dumps({"rule_id": "F-OTHER", "amount": "1"}))
    assert writes == []


def test_legacy_allocation_endpoint_resolves_rule_by_code_within_batch_version(legacy_fee_endpoint):
    result = calculate_service.update_allocation_rule("B", "V", json.dumps({
        "rule_code": "international_sea_freight", "amount": "8000"}))
    assert result["ok"] is True and result["rule_name"] == "F"
    rule_writes = [args for args, _kwargs in legacy_fee_endpoint if args[0] == "Overseas Cost Allocation Rule"]
    assert len(rule_writes) == 1 and rule_writes[0][1] == "F"


def test_legacy_allocation_endpoint_cannot_change_settlement_owned_fee(legacy_fee_records):
    records,writes=legacy_fee_records
    records['F'].update(source_binding_id='BIND',source_snapshot='SNAP',is_final=1,covered_scopes='freight',amount_status='ACTUAL')
    with pytest.raises(ValueError,match='最终采购支出'):
        calculate_service.update_allocation_rule('B','V',json.dumps({'rule_id':'F','amount':'1'}))
    assert not writes
