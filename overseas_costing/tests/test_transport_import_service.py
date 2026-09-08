"""Transport inheritance and retired fee rules must survive source synchronization."""

import json
from types import SimpleNamespace

import pytest

from overseas_costing.services import import_service
from overseas_costing.scripts import import_oa_logistics


@pytest.mark.parametrize("batch_mode", ["AIR", "EXPRESS"])
def test_imported_items_inherit_batch_transport_without_inventing_sea(batch_mode):
    values = import_service._prepare_imported_item_values(
        {"material_code": "M1", "quantity": 10}, batch_transport_mode=batch_mode)
    assert values["transport_mode"] == batch_mode
    assert json.loads(values["extra_json"])["transport_provenance"] == {
        "mode": "BATCH_DEFAULT", "source_mode": "", "batch_mode": batch_mode}


def test_import_preserves_explicit_source_transport_as_conflict_evidence():
    values = import_service._prepare_imported_item_values(
        {"material_code": "M1", "transport_mode": "SEA", "extra_json": '{"original":1}'},
        batch_transport_mode="AIR")
    assert values["transport_mode"] == "SEA"
    assert json.loads(values["extra_json"]) == {
        "original": 1, "transport_provenance": {"mode": "EXPLICIT_SOURCE", "source_mode": "SEA", "batch_mode": "AIR"}}


def test_import_without_source_or_batch_transport_stays_unspecified():
    values = import_service._prepare_imported_item_values({"material_code": "M1"})
    assert values["transport_mode"] == ""


@pytest.mark.parametrize("batch_mode", ["AIR", "EXPRESS"])
def test_new_packing_item_inherits_batch_transport(monkeypatch, batch_mode):
    monkeypatch.setattr(import_service, "frappe", SimpleNamespace(db=SimpleNamespace(
        get_value=lambda doctype, name, field: batch_mode)))
    monkeypatch.setattr(import_service, "_filter_doctype_values", lambda _doctype, values, **_kwargs: values)
    values = import_service._build_packing_unmatched_item_values(
        batch_doc_name="B1", version_name="V1", row_no=1,
        mapped_row={"material_code": "M1", "actual_shipped_qty": 10}, attachment_provenance={})
    assert values["transport_mode"] == batch_mode


@pytest.mark.parametrize("batch_mode", ["AIR", "EXPRESS"])
def test_linked_purchase_item_inherits_batch_transport(monkeypatch, batch_mode):
    monkeypatch.setattr(import_oa_logistics, "frappe", SimpleNamespace(db=SimpleNamespace(
        get_value=lambda doctype, name, field: batch_mode)))
    monkeypatch.setattr(import_oa_logistics, "_filter_item_values", lambda values: values)
    values = import_oa_logistics._build_purchase_expense_item_doc_values(
        row={"material_code": "M1", "quantity": 1000, "goods_value": 12300}, row_no=1,
        batch_name="B1", version_name="V1", approval_item={})
    assert values["transport_mode"] == batch_mode
    assert values["quantity"] == 1000
    assert values["goods_value"] == 12300


def test_disabled_oa_logistics_rule_is_not_revived_when_source_amount_changes(monkeypatch):
    writes = []
    class DB:
        def get_value(self, doctype, key, fields, as_dict=False):
            if isinstance(key, dict):
                return "RETIRED-RULE"
            return {"is_enabled": 0, "amount": 100, "rule_code": "oa_logistics_freight"}
        def set_value(self, *args, **kwargs):
            writes.append(args)
    monkeypatch.setattr(import_oa_logistics, "frappe", SimpleNamespace(db=DB()))
    monkeypatch.setattr(import_service, "_invalid_batch_cost_write_response", lambda *args: None)
    monkeypatch.setattr(import_oa_logistics, "_insert_batch_audit_log", lambda **kwargs: None)
    for amount in (200, 300):
        result = import_oa_logistics._sync_oa_logistics_allocation_rule(
            batch_name="B1", version_name="V1", approval_item={"logistics_fee": {"amount": amount, "currency": "RMB"}})
        assert result["ok"] is True
        assert result["action"] == "retired"
        assert result["rule_name"] == "RETIRED-RULE"
        assert result["created_count"] == result["updated_count"] == 0
    assert writes == []


def test_excel_upsert_inherits_batch_for_new_and_refreshed_items(monkeypatch):
    writes = []
    class DB:
        def get_value(self, doctype, key, field, as_dict=False):
            if doctype == "Overseas Cost Batch":
                return "EXPRESS"
            if isinstance(key, dict):
                return "EXISTING" if key.get("row_no") == 2 else None
            return {}
        def set_value(self, doctype, name, values, **kwargs):
            writes.append(values)
    def get_doc(values):
        writes.append(values)
        return SimpleNamespace(insert=lambda **kwargs: SimpleNamespace(name="NEW"))
    monkeypatch.setattr(import_service, "frappe", SimpleNamespace(db=DB(), get_doc=get_doc))
    monkeypatch.setattr(import_service, "_filter_doctype_values", lambda doctype, values, **kwargs: values)
    result = import_service._upsert_excel_items(batch_doc_name="B1", version_name="V1",
        mapped_rows=[{"material_code": "M1"}, {"material_code": "M2"}], raw_rows=[])
    assert result["created_count"] == result["updated_count"] == 1
    assert [row["transport_mode"] for row in writes] == ["EXPRESS", "EXPRESS"]


def test_oa_goods_sync_inherits_saved_batch_transport(monkeypatch):
    writes = []
    db = SimpleNamespace(count=lambda *args: 0, get_value=lambda *args: "AIR", set_value=lambda *args, **kwargs: None)
    def get_doc(values):
        writes.append(values)
        return SimpleNamespace(insert=lambda **kwargs: SimpleNamespace(name="NEW"))
    monkeypatch.setattr(import_oa_logistics, "frappe", SimpleNamespace(db=db, get_doc=get_doc))
    monkeypatch.setattr(import_oa_logistics, "build_oa_item_values_from_approval", lambda _approval: [{"material_code": "M1"}])
    monkeypatch.setattr(import_oa_logistics, "_filter_item_values", lambda values: values)
    monkeypatch.setattr(import_oa_logistics, "_insert_batch_audit_log", lambda **kwargs: None)
    result = import_oa_logistics._sync_oa_goods_items(batch_name="B1", version_name="V1", approval_item={})
    assert result["created_count"] == 1
    assert writes[0]["transport_mode"] == "AIR"


def test_excel_batch_refresh_without_source_mode_preserves_saved_air(monkeypatch):
    updates = []
    class DB:
        def get_value(self, doctype, key, field, as_dict=False):
            return "EXISTING" if isinstance(key, dict) else "AIR"
        def set_value(self, doctype, name, values, **kwargs):
            updates.append(values)
    monkeypatch.setattr(import_service, "frappe", SimpleNamespace(db=DB(), get_doc=lambda *args: SimpleNamespace(name="EXISTING")))
    import_service._resolve_or_create_excel_batch(block={"id": "B1"}, source_name="new.xlsx", transport_mode="",
                                                  source_sheet=None, project_collection=None)
    assert "transport_mode" not in updates[0]
    assert "business_type" not in updates[0]


def test_oa_batch_sync_does_not_invent_transport_when_source_omits_it():
    values = import_oa_logistics.build_batch_values_from_approval({"source_approval_no": "LOG-1", "form_fields": {}})
    assert values["transport_mode"] == ""
    assert values["business_type"] == ""


def test_default_rule_upsert_preserves_explicitly_disabled_rules(monkeypatch):
    writes = []
    class DB:
        def get_value(self, doctype, key, field):
            return "RULE-" + key["rule_code"] if isinstance(key, dict) else 0
        def set_value(self, *args, **kwargs):
            writes.append(args)
    monkeypatch.setattr(import_service, "frappe", SimpleNamespace(db=DB()))
    result = import_service._upsert_default_allocation_rules(batch_doc_name="B1", version_name="V1",
        block={"chinaToMexicoFreightRmb": 900}, mapped_rows=[])
    assert len(result) == 3
    assert writes == []


@pytest.mark.parametrize("batch_mode", ["AIR", "EXPRESS"])
@pytest.mark.parametrize("template", ["oa_attachment_detail", "sisa_warehouse_receipt"])
def test_real_xlsx_without_transport_evidence_inherits_batch(tmp_path, batch_mode, template):
    from openpyxl import Workbook
    from overseas_costing.utils.excel_workbook import parse_yuewei_excel_workbook
    from overseas_costing.utils.field_mapper import map_yuewei_excel_block_item_to_item

    path = tmp_path / "unknown-transport.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "6月份宠物用品"
    if template == "oa_attachment_detail":
        sheet.append(["物料编码", "中文品名", "数量", "总毛重", "总体积"])
        sheet.append(["M1", "宠物包", 10, 12, .1])
    else:
        sheet.append(["SiSA墨西哥专线进仓单产品清单"])
        sheet.append(["箱号", "箱数", "型号", "品名", "总产品数", "总毛重kg", "总体积CBM"])
        sheet.append(["1", 1, "M1", "宠物包", 10, 12, .1])
    workbook.save(path)
    workbook.close()
    meta, blocks = parse_yuewei_excel_workbook(path)
    assert meta["parser"] == template
    assert blocks[0]["transportMode"] == ""
    mapped = map_yuewei_excel_block_item_to_item(blocks[0], blocks[0]["items"][0], row_index=1)
    values = import_service._prepare_imported_item_values(mapped, batch_transport_mode=batch_mode)
    assert values["transport_mode"] == batch_mode
    assert json.loads(values["extra_json"])["transport_provenance"]["mode"] == "BATCH_DEFAULT"


@pytest.mark.parametrize("sheet_name,column_label,column_value,expected", [
    ("6月份宠物用品", "出口方式", "海运", "SEA"),
    ("6月份宠物用品", "运输方式", "AIR", "AIR"),
    ("6月份宠物用品", "物流方式", "EXPRESS", "EXPRESS"),
    ("海运装箱单", "", "", "SEA"),
    ("空运装箱单", "", "", "AIR"),
    ("快递装箱单", "", "", "EXPRESS"),
])
def test_real_xlsx_preserves_explicit_transport_column_and_sheet_evidence(tmp_path, sheet_name, column_label, column_value, expected):
    from openpyxl import Workbook
    from overseas_costing.utils.excel_workbook import parse_yuewei_excel_workbook
    from overseas_costing.utils.field_mapper import map_yuewei_excel_block_item_to_item

    path = tmp_path / "explicit-transport.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = sheet_name
    headers = ["物料编码", "中文品名", "数量", "总毛重", "总体积"]
    row = ["M1", "宠物包", 10, 12, .1]
    if column_label:
        headers.append(column_label)
        row.append(column_value)
    sheet.append(headers)
    sheet.append(row)
    workbook.save(path)
    workbook.close()
    _meta, blocks = parse_yuewei_excel_workbook(path)
    mapped = map_yuewei_excel_block_item_to_item(blocks[0], blocks[0]["items"][0], row_index=1)
    values = import_service._prepare_imported_item_values(mapped, batch_transport_mode="EXPRESS")
    assert values["transport_mode"] == expected
    assert json.loads(values["extra_json"])["transport_provenance"]["mode"] == "EXPLICIT_SOURCE"
