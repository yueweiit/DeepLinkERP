from copy import deepcopy

from overseas_costing.services import material_ai_fill_service as service
from overseas_costing.services.logistics_autofill_service import build_logistics_reconciliation
from overseas_costing.tests.test_logistics_autofill import approval, existing_items


def test_existing_stable_ids_still_use_distinct_logistics_rows():
    rows = build_logistics_reconciliation(existing_items(), approval())["payload"]["rows"]
    for i, row in enumerate(rows):
        row["stable_line_key"] = f"existing-stable-{i}"
    preview = {"material_rows": [
        {"source_row": 2, "material_code": "FL000429", "quantity": 96000, "gross_weight_kg": 388},
        {"source_row": 3, "material_code": "FL000429", "quantity": 4000, "gross_weight_kg": 9.7},
    ]}
    result = service._projection_candidates(rows, {"source_id": "X"}, preview)
    assert [(r["item_name"], r["suggested_value"]) for r in result] == [
        (rows[0]["name"], "388"), (rows[1]["name"], "9.7")]


def invalid_preview():
    return {"ok": False, "material_rows": [
        {"source_row": 2, "material_code": "FL000428", "quantity": 100000,
         "gross_weight_kg": 100, "net_weight_kg": 95}],
        "validation": {"blocking": [{"code": "total_mismatch", "field": "gross_weight_kg",
                                      "message": "毛重明细100与合计200不一致"}]}}


def test_total_mismatch_is_reported_and_affected_field_is_not_adopted():
    rows = build_logistics_reconciliation(existing_items(), approval())["payload"]["rows"]
    preview = invalid_preview()
    candidates = service._projection_candidates(rows, {"source_id": "X"}, preview)
    assert [r["fieldname"] for r in candidates] == ["net_weight_kg"]
    assert "毛重明细100与合计200不一致" in preview["autofill_warnings"]


def test_unknown_parse_blocker_does_not_autofill_any_fields():
    rows = build_logistics_reconciliation(existing_items(), approval())["payload"]["rows"]
    preview = invalid_preview()
    preview["validation"]["blocking"] = [{"code": "broken_grid", "message": "文件结构损坏"}]
    assert service._projection_candidates(rows, {"source_id": "X"}, preview) == []
    assert preview["autofill_warnings"] == ["文件结构损坏"]


def test_excel_reader_preserves_validation_error_with_partial_results(monkeypatch, tmp_path):
    from overseas_costing.services import attachment_parse_service, packing_source_service
    path = tmp_path / "packing.xlsx"
    source = {"source_id": "X", "source_kind": "local_attachment", "sheet_name": "装箱"}
    monkeypatch.setattr(service, "frappe", None)
    monkeypatch.setattr(service, "_ensure_local_attachment", lambda s: {**s, "file_name": "packing.xlsx", "file_url": "local"})
    monkeypatch.setattr(attachment_parse_service, "_resolve_source_file_path", lambda **kw: path)
    monkeypatch.setattr(service, "_read_excel_semantic_document", lambda *args: {})
    monkeypatch.setattr(packing_source_service, "resolve_trusted_packing_source", lambda **kw: {"preview": deepcopy(invalid_preview())})
    rows = build_logistics_reconciliation(existing_items(), approval())["payload"]["rows"]
    candidates, document = service._read_source(rows, source)
    assert [r["fieldname"] for r in candidates] == ["net_weight_kg"]
    assert document["parse_errors"] == ["毛重明细100与合计200不一致"]


def test_partial_excel_error_reaches_ready_unresolved_without_business_write(monkeypatch):
    from overseas_costing.tests.test_material_ai_fill_service import _LifecycleRepository
    from overseas_costing.services.source_review_manifest_service import prepare_source_manifest
    repo = _LifecycleRepository(status="QUEUED")
    repo.sources = [approval(), {"source_kind": "manual_attachment", "source_id": "X", "file_name": "packing.xlsx",
                                "source_hash": "h1", "sheet_name": "装箱", "source_label": "装箱单"}]
    repo.get_items = lambda *args: existing_items()
    manifest = prepare_source_manifest(repo.sources)
    repo.run.update(proposal_version=1, source_manifest_json=manifest,
                    input_fingerprint=service._source_review_fingerprint("B1", "V1", existing_items(), manifest, ""))
    read = service._read_source
    def read_source(items, source):
        if source.get("source_kind") == "approval_form":
            return read(items, source)
        return [], {"source_ref": service._source_reference(source), "structured_rows": [{"material_code": "FL000428"}],
                    "parse_errors": ["毛重明细100与合计200不一致"], "ai_eligible": False}
    monkeypatch.setattr(service, "_read_source", read_source)
    monkeypatch.setattr(service, "_call_source_review_ai", lambda *a, **kw: {"ok": False, "proposals": []})
    result = service.execute_material_ai_fill("RUN-1", repository=repo)
    assert result["status"] == "READY"
    assert any("毛重明细100与合计200不一致" in row["message"]
               for row in repo.run["draft_json"]["autofill_preview"]["unresolved"])
    assert repo.applied == []
