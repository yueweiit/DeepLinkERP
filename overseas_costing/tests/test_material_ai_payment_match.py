from copy import deepcopy
import json

import pytest

from overseas_costing.services.logistics_settlement.model import dumps
from overseas_costing.tests.test_payment_adoption import payment_setup


def _candidate_values(candidate, **changes):
    value = {**candidate, "method": "identifier", "issues": [], **changes}
    return {
        "id": value["id"],
        "logistics_id": value["logistics_id"],
        "expense_id": value["expense_id"],
        "status": value["status"],
        "data": dumps(value),
    }


def _strong_context():
    context = payment_setup()
    store, _ledger, _batch, _version, _logistics, _source, candidate = context
    store.put("freight_candidate", _candidate_values(candidate))
    return context


def test_unique_strong_current_freight_candidate_is_selected_by_server():
    from overseas_costing.services import material_ai_payment_match as service

    store, ledger, batch, version, _logistics, _source, candidate = _strong_context()

    selected = service.select_preview_candidate(
        store, ledger, batch["name"], version["name"], freight_mode=True
    )

    assert selected == {
        "candidate_id": candidate["id"],
        "revision": candidate["revision"],
        "version": version["name"],
    }


@pytest.mark.parametrize(
    "changes",
    [
        {"status": "rejected"},
        {"status": "conflict"},
        {"method": "deepseek", "confidence": "0.89"},
        {"method": "deepseek", "confidence": None},
    ],
)
def test_rejected_conflicting_or_low_confidence_match_is_not_selected(changes):
    from overseas_costing.services import material_ai_payment_match as service

    store, ledger, batch, version, _logistics, _source, candidate = _strong_context()
    store.put("freight_candidate", _candidate_values(candidate, **changes))

    assert service.select_preview_candidate(
        store, ledger, batch["name"], version["name"], freight_mode=True
    ) is None


def test_multiple_strong_payment_matches_are_not_selected_arbitrarily():
    from overseas_costing.services import material_ai_payment_match as service

    store, ledger, batch, version, _logistics, source, candidate = _strong_context()
    second_source = {
        **source,
        "id": "payment-2",
        "instance": "PAY-2",
        "snapshot": "payment-snapshot-2",
        "match_hash": "pm2",
    }
    store.insert(
        "source",
        {
            "id": second_source["id"],
            "corp": second_source["corp"],
            "instance": second_source["instance"],
            "kind": second_source["kind"],
            "snapshot": second_source["snapshot"],
            "match_hash": second_source["match_hash"],
            "updated_at": second_source["updated_at"],
            "data": dumps(second_source),
        },
    )
    second_candidate = {
        **candidate,
        "id": "candidate-2",
        "expense_id": second_source["id"],
        "expense_snapshot": second_source["snapshot"],
        "revision": "candidate-revision-2",
        "method": "explicit",
        "issues": [],
    }
    store.insert("freight_candidate", _candidate_values(second_candidate))

    assert service.select_preview_candidate(
        store, ledger, batch["name"], version["name"], freight_mode=True
    ) is None
    visible = service.preview_process_sources(
        store, ledger, batch["name"], version["name"], freight_mode=True
    )
    assert {row["process_instance_id"] for row in visible} == {
        source["instance"], second_source["instance"]
    }
    assert all("payment_match_candidate" not in row for row in visible)
    assert all(row["metadata_only_process"] is True for row in visible)


@pytest.mark.parametrize(
    "changes",
    [
        {"status": "conflict", "method": "explicit", "issues": []},
        {"status": "pending", "method": "explicit", "issues": ["跨票冲突"]},
    ],
)
def test_manual_payment_range_cannot_promote_unsafe_candidates(changes):
    from overseas_costing.services import material_ai_payment_match as service

    store, ledger, batch, version, _logistics, _source, candidate = _strong_context()
    store.put("freight_candidate", _candidate_values(candidate, **changes))
    reference = {
        "candidate_id": candidate["id"],
        "revision": candidate["revision"],
        "version": version["name"],
    }

    with pytest.raises(ValueError, match="变化"):
        service.validate_preview_references(
            store, ledger, batch["name"], version["name"], [reference]
        )


def test_server_confirmation_revalidates_relation_without_freezing_candidate():
    from overseas_costing.services import material_ai_payment_match as service

    store, ledger, batch, version, _logistics, _source, candidate = _strong_context()
    reference = service.select_preview_candidate(
        store, ledger, batch["name"], version["name"], freight_mode=True
    )

    with pytest.raises(RuntimeError, match="downstream failed"):
        with store.atomic():
            service.confirm_preview_candidate(
                store, ledger, batch["name"], reference, "user", freight_mode=True
            )
            raise RuntimeError("downstream failed")
    assert store.get("freight_candidate", candidate["id"])["status"] == "pending"

    stale = {**reference, "revision": "stale"}
    with pytest.raises(ValueError, match="变化"):
        service.confirm_preview_candidate(
            store, ledger, batch["name"], stale, "user", freight_mode=True
        )
    assert store.get("freight_candidate", candidate["id"])["status"] == "pending"

    relation = service.confirm_preview_candidate(
        store, ledger, batch["name"], reference, "user", freight_mode=True
    )
    assert relation == {
        "policy": service.POLICY,
        "candidate_id": candidate["id"],
        "candidate_revision": candidate["revision"],
        "version": version["name"],
        "logistics_id": candidate["logistics_id"],
        "expense_id": candidate["expense_id"],
        "logistics_snapshot": candidate["logistics_snapshot"],
        "expense_snapshot": candidate["expense_snapshot"],
        "confirmed_by": "user",
        "confirmed_at": relation["confirmed_at"],
    }
    assert relation["confirmed_at"]
    assert store.get("freight_candidate", candidate["id"])["status"] == "pending"
    assert not any(
        row["action"] == "material_ai_payment_match_confirmed"
        for row in store.find("audit", binding_id=batch["name"])
    )


def test_confirmation_locks_match_arbitration_before_candidate_context(monkeypatch):
    from overseas_costing.services import material_ai_payment_match as service

    store, ledger, batch, version, _logistics, _source, candidate = _strong_context()
    reference = service.select_preview_candidate(
        store, ledger, batch["name"], version["name"], freight_mode=True
    )
    original_get = store.get
    locked_reads = []

    def traced_get(table, row_id, lock=False):
        if lock:
            locked_reads.append((table, row_id))
        return original_get(table, row_id, lock=lock)

    monkeypatch.setattr(store, "get", traced_get)

    with store.atomic():
        service.confirm_preview_candidate(
            store, ledger, batch["name"], reference, "user", freight_mode=True
        )

    assert locked_reads[0] == ("state", "match_lock")
    assert locked_reads.index(("state", "match_lock")) < locked_reads.index(
        ("freight_candidate", candidate["id"])
    )


def test_version_relation_is_safe_audited_and_idempotent():
    from overseas_costing.services import material_ai_payment_match as service

    store, ledger, batch, version, _logistics, _source, candidate = _strong_context()
    reference = service.select_preview_candidate(
        store, ledger, batch["name"], version["name"], freight_mode=True
    )
    relation = service.confirm_preview_candidate(
        store, ledger, batch["name"], reference, "user", freight_mode=True
    )

    first = service.persist_relation(
        store, ledger, batch["name"], version["name"], relation, "user"
    )
    second = service.persist_relation(
        store, ledger, batch["name"], version["name"], relation, "user"
    )

    metadata = json.loads(ledger.get("version", version["name"])["extra_json"])
    assert metadata["material_ai_payment_match"] == first == second
    assert set(first) == {
        "policy", "candidate_id", "candidate_revision", "version",
        "logistics_id", "expense_id", "logistics_snapshot", "expense_snapshot",
        "confirmed_by", "confirmed_at",
    }
    assert "amount" not in json.dumps(first) and "text" not in json.dumps(first)
    audits = [
        row for row in store.find("audit", binding_id=batch["name"])
        if row["action"] == "material_ai_payment_match_confirmed"
    ]
    assert len(audits) == 1
    assert audits[0]["user_selected"] is False
    assert store.get("freight_candidate", candidate["id"])["status"] == "pending"


def test_historical_version_exposes_safe_payment_source_relation_summary():
    from overseas_costing.services import material_ai_payment_match as service
    from overseas_costing.services.logistics_settlement.freight_runtime import batch_status

    store, ledger, batch, version, _logistics, source, candidate = _strong_context()
    source.update(title="月结付款")
    store.put("source", {"id": source["id"], "data": dumps(source)})
    reference = service.select_preview_candidate(
        store, ledger, batch["name"], version["name"], freight_mode=True
    )
    relation = service.confirm_preview_candidate(
        store, ledger, batch["name"], reference, "user", freight_mode=True
    )
    service.persist_relation(
        store, ledger, batch["name"], version["name"], relation, "user", user_selected=True
    )
    next_version = ledger.create(
        "version", {"batch": batch["name"], "status": "Active", "is_current": 1}
    )
    ledger.put("batch", batch["name"], {"current_version": next_version["name"]})

    public = batch_status(store, ledger, batch["name"], version["name"])

    assert public["historical"] is True
    assert public["payment_source_history"] == [{
        "title": "月结付款",
        "approval_no": "APP-1",
        "workflow_template": "月结付款",
        "confirmed_by": "user",
        "confirmed_at": relation["confirmed_at"],
    }]
    audit = next(row for row in public["audit"]
                 if row["action"] == "material_ai_payment_match_confirmed")
    assert audit["source_approval_no"] == "APP-1"
    assert audit["user_selected"] is True


def test_version_relation_and_audit_roll_back_when_later_apply_fails():
    from overseas_costing.services import material_ai_payment_match as service

    store, ledger, batch, version, _logistics, _source, candidate = _strong_context()
    reference = service.select_preview_candidate(
        store, ledger, batch["name"], version["name"], freight_mode=True
    )
    relation = service.confirm_preview_candidate(
        store, ledger, batch["name"], reference, "user", freight_mode=True
    )

    with pytest.raises(RuntimeError, match="later write failed"):
        with store.atomic():
            service.persist_relation(
                store, ledger, batch["name"], version["name"], relation, "user"
            )
            raise RuntimeError("later write failed")

    metadata = json.loads(ledger.get("version", version["name"]).get("extra_json") or "{}")
    assert "material_ai_payment_match" not in metadata
    assert not any(
        row["action"] == "material_ai_payment_match_confirmed"
        for row in store.find("audit", binding_id=batch["name"])
    )
    assert store.get("freight_candidate", candidate["id"])["status"] == "pending"


def test_saved_ai_relation_does_not_freeze_candidate_rebuild_or_rejection():
    from overseas_costing.services import material_ai_payment_match as service
    from overseas_costing.services.logistics_settlement import freight_matching, freight_runtime
    from overseas_costing.services.logistics_settlement.model import parse_source
    from overseas_costing.tests.test_freight_lines import monthly, setup_cost

    store, ledger, batch, version, _item, logistics, expense = setup_cost()
    candidate = freight_matching.rule_pass(store, logistics["id"])[0]
    reference = service.select_preview_candidate(
        store, ledger, batch["name"], version["name"], freight_mode=True
    )
    relation = service.confirm_preview_candidate(
        store, ledger, batch["name"], reference, "user", freight_mode=True
    )
    service.persist_relation(
        store, ledger, batch["name"], version["name"], relation, "user"
    )

    changed = monthly()
    changed["raw_payload"]["comments"] = [{"text": "付款资料快照更新"}]
    changed["updated_at"] = "2026-09-16T10:00:00+00:00"
    refreshed_source = store.ingest(parse_source(changed, logistics_codes={"logistics"}))
    rebuilt = freight_matching.rule_pass(store, logistics["id"])[0]

    assert refreshed_source["snapshot"] != expense["snapshot"]
    assert rebuilt["revision"] != candidate["revision"]
    assert rebuilt["expense_snapshot"] == refreshed_source["snapshot"]
    assert rebuilt["status"] == "pending"

    rejected = freight_runtime.decide_payment_candidate(
        store, ledger, batch["name"], version["name"], rebuilt["id"], rebuilt["revision"],
        "reject", "新快照需重新核对", "user",
        lease_check=lambda *_args, **_kwargs: None,
        edit_token="token", expected_modified="modified",
    )
    assert rejected["candidate"]["status"] == "rejected"


def test_cross_ticket_candidate_cannot_be_confirmed():
    from overseas_costing.services import material_ai_payment_match as service

    store, ledger, _batch, version, _logistics, _source, candidate = _strong_context()
    other_batch = ledger.create("batch", {"status": "Dirty", "confirm_status": "Pending"})
    other_version = ledger.create(
        "version", {"batch": other_batch["name"], "status": "Active", "is_current": 1}
    )
    ledger.put("batch", other_batch["name"], {"current_version": other_version["name"]})

    with pytest.raises(ValueError, match="不属于当前批次"):
        service.confirm_preview_candidate(
            store,
            ledger,
            other_batch["name"],
            {
                "candidate_id": candidate["id"],
                "revision": candidate["revision"],
                "version": other_version["name"],
            },
            "user",
            freight_mode=True,
        )


def test_payment_match_sources_are_server_scoped_and_contain_stable_reference_only():
    from overseas_costing.services import material_ai_payment_match as service
    from overseas_costing.services.logistics_settlement import freight_matching
    from overseas_costing.tests.test_freight_lines import setup_cost

    store, ledger, batch, version, _item, logistics, source = setup_cost()
    candidate = freight_matching.rule_pass(store, logistics["id"])[0]
    reference = service.select_preview_candidate(
        store, ledger, batch["name"], version["name"], freight_mode=True
    )

    sources = service.preview_sources(
        store, ledger, batch["name"], version["name"], reference, freight_mode=True
    )

    assert sources
    assert {row["workflow_stage"] for row in sources} == {"payment"}
    assert {row["workflow_rank"] for row in sources} == {0}
    assert {row["payment_match_candidate_id"] for row in sources} == {candidate["id"]}
    assert {row["process_instance_id"] for row in sources} == {source["instance"]}
    assert all(row["scoped_packing"] for row in sources)
    assert all("payment_match_status" not in row for row in sources)
    assert all("amount" not in row and "currency" not in row for row in sources)


def test_material_source_listing_honors_explicit_payment_range_without_persisting(monkeypatch):
    from overseas_costing.services import packing_snapshot_service as packing
    from overseas_costing.services.logistics_settlement import freight_matching, ledger as ledger_module, runtime
    from overseas_costing.services.logistics_settlement.store import Store
    from overseas_costing.tests.test_freight_lines import setup_cost

    store, ledger, batch, version, _item, logistics, _source = setup_cost()
    candidate = freight_matching.rule_pass(store, logistics["id"])[0]
    reference = {
        "candidate_id": candidate["id"],
        "revision": candidate["revision"],
        "version": version["name"],
    }
    monkeypatch.setattr(Store, "frappe", classmethod(lambda _cls: store))
    monkeypatch.setattr(ledger_module, "FrappeLedger", lambda: ledger)
    monkeypatch.setattr(runtime, "freight_enabled", lambda: True)
    monkeypatch.setattr(packing, "_list_material_ai_sources", lambda *_args, **_kwargs: [])

    sources = packing.list_material_ai_sources(
        batch["name"], version["name"], payment_references=[reference]
    )

    assert sources
    assert {row["payment_match_candidate_id"] for row in sources} == {candidate["id"]}
    assert {row["payment_match_user_selected"] for row in sources} == {True}
    assert store.find("audit", binding_id=batch["name"]) == []


def test_payment_preview_uses_only_matched_line_when_catalog_row_is_unreadable(monkeypatch):
    from overseas_costing.services import material_ai_payment_match as service
    from overseas_costing.services.logistics_settlement import packing_selection

    store, ledger, batch, version, logistics, source, candidate = payment_setup(
        structured=True,
        scope="freight",
        amount="44075.13",
        mode="EXPRESS",
    )
    line = store.get("freight_line", "payment-line-1")
    line.update(
        amount="3322.784523",
        currency="RMB",
        label="DHL 快递运费",
        billing_weight="46",
        cargo_text="MWV101144 IP17PRO TPU\n规格33*20*23,重量：42.05kg\n1套模具+3个手机壳",
        packing={
            "material_code_hints": ["MWV101144", "IP17PRO"],
            "chargeable_weight_kg": "46",
            "gross_weight_kg": "42.05",
            "package_count": "1",
            "dimensions_cm": ["33", "20", "23"],
            "volume_m3": "0.01518",
        },
        evidence={
            "document_id": "payment-document-1",
            "file_name": "DHL(6.29-7.24)快递明细.xlsx",
            "sheet": "DHL",
            "row": 8,
        },
    )
    store.put(
        "freight_line",
        {
            "id": line["id"],
            "source_id": line["source_id"],
            "snapshot": line["snapshot"],
            "line_key": line["line_key"],
            "waybill": line["waybill"],
            "approval_no": line["approval_no"],
            "charge_key": line["charge_key"],
            "data": dumps(line),
        },
    )
    candidate.update(method="explicit", issues=[])
    store.put("freight_candidate", _candidate_values(candidate))
    monkeypatch.setattr(packing_selection, "_catalog", lambda *_args: (logistics, []))

    reference = service.select_preview_candidate(
        store, ledger, batch["name"], version["name"], freight_mode=True
    )
    sources = service.preview_sources(
        store, ledger, batch["name"], version["name"], reference, freight_mode=True
    )

    assert len(sources) == 1
    preview = sources[0]
    assert preview["workflow_stage"] == "payment"
    assert preview["process_instance_id"] == source["instance"]
    assert preview["source_kind"] == "approval_attachment"
    assert preview["selected_source"]["document_id"] == "payment-document-1"
    assert preview["scoped_goods"] == [{
        "material_code": "MWV101144",
        "product_name": "",
        "spec_model": "",
        "quantity": None,
        "unit": "",
        "gross_weight_kg": "42.05",
        "chargeable_weight_kg": "46",
        "package_count": "1",
        "volume_m3": "0.01518",
        "dimensions_cm": ["33", "20", "23"],
        "physical": {
            "gross_weight_kg": "42.05",
            "chargeable_weight_kg": "46",
            "package_count": "1",
            "volume_m3": "0.01518",
        },
        "evidence": {
            "document_id": "payment-document-1",
            "file_name": "DHL(6.29-7.24)快递明细.xlsx",
            "sheet": "DHL",
            "row": 8,
        },
    }]
    assert "运费金额: 3322.784523 RMB" in preview["scoped_text"]
    assert "计费重量: 46 kg" in preview["scoped_text"]
    assert "MWV101144 IP17PRO TPU" in preview["scoped_text"]
    assert "44075.13" not in preview["scoped_text"]


@pytest.mark.parametrize("legacy_archive_row", [False, True])
def test_exact_monthly_payment_row_becomes_complete_payment_stage_field_candidates(
    monkeypatch, legacy_archive_row
):
    from overseas_costing.services import material_ai_fill_service as ai_fill
    from overseas_costing.services import material_ai_payment_match as service
    from overseas_costing.services.logistics_settlement import packing_selection

    store, ledger, batch, version, logistics, source, candidate = payment_setup(
        structured=True,
        scope="freight",
        amount="3414.19",
        mode="EXPRESS",
    )
    line = store.get("freight_line", "payment-line-1")
    line.update(
        amount="3414.19",
        currency="RMB",
        billing_weight="46",
        cargo_text="MWV101144 IP17PRO TPU\n规格33*20*23,重量：42.05kg\n1套模具+3个手机壳",
        packing={
            "material_code_hints": ["MWV101144", "IP17PRO"],
            "chargeable_weight_kg": "46",
            "gross_weight_kg": "42.05",
            "package_count": "1",
            "dimensions_cm": ["33", "20", "23"],
            "volume_m3": "0.01518",
        },
        evidence={
            "document_id": "payment-document-1",
            "file_name": "DHL(6.29-7.24)快递明细.xlsx",
            "sheet": "DHL快递",
            "row": 14,
        },
    )
    if legacy_archive_row:
        # Production contains statement rows archived before ``packing`` was
        # persisted.  The unified AI preview must derive the same exact-row
        # physical facts as the payment-source summary instead of dropping
        # every packing field while still accepting the freight amount.
        line.pop("packing", None)
        line["fields"] = {"件数": 1, "重量": 46}
    store.put(
        "freight_line",
        {
            "id": line["id"],
            "source_id": line["source_id"],
            "snapshot": line["snapshot"],
            "line_key": line["line_key"],
            "waybill": line["waybill"],
            "approval_no": line["approval_no"],
            "charge_key": line["charge_key"],
            "data": dumps(line),
        },
    )
    candidate.update(method="explicit", issues=[])
    store.put("freight_candidate", _candidate_values(candidate))
    monkeypatch.setattr(packing_selection, "_catalog", lambda *_args: (logistics, []))

    reference = service.select_preview_candidate(
        store, ledger, batch["name"], version["name"], freight_mode=True
    )
    payment_source = service.preview_sources(
        store, ledger, batch["name"], version["name"], reference, freight_mode=True
    )[0]
    items = [
        {
            "name": "ITEM-144",
            "stable_line_key": "ITEM-144",
            "material_code": "MWV101144",
            "product_name": "薇武士IP17 PRO",
            "actual_shipped_qty": "1",
            "quantity": "1",
            "gross_weight_kg": "0",
            "volume_m3": "0",
            "extra_json": "{}",
        },
        {
            "name": "ITEM-145",
            "stable_line_key": "ITEM-145",
            "material_code": "MWV101145",
            "product_name": "薇武士IP17 PRO MAX",
            "actual_shipped_qty": "1",
            "quantity": "1",
            "gross_weight_kg": "0",
            "volume_m3": "0",
            "extra_json": "{}",
        },
    ]

    candidates, document = ai_fill._read_source(items, payment_source)

    assert {
        (row["item_name"], row["fieldname"], row["suggested_value"])
        for row in candidates
    } == {
        ("ITEM-144", "gross_weight_kg", "42.05"),
        ("ITEM-144", "chargeable_weight_kg", "46"),
        ("ITEM-144", "package_count", "1"),
        ("ITEM-144", "volume_m3", "0.01518"),
    }
    assert all(row["source_refs"][0]["row"] == 14 for row in candidates)
    assert all(row["source_refs"][0]["sheet"] == "DHL快递" for row in candidates)

    document["document_id"] = "DOC-1"
    proposals = ai_fill._excel_review_entries(
        0, payment_source, candidates, document
    )[0][2]
    normalized = ai_fill.normalize_source_review_proposals(
        proposals,
        items,
        [document],
        trusted_system_proposal_ids={row["proposal_id"] for row in proposals},
    )
    from overseas_costing.services import material_ai_row_selection

    catalog = material_ai_row_selection.catalog(
        items, normalized, [], {}, run_id="RUN-PAYMENT", sources=[payment_source]
    )
    payment_stage = catalog["stage_snapshots"][0]
    payment_item = next(row for row in payment_stage["rows"] if row["item_name"] == "ITEM-144")
    assert set(payment_item["field_candidates"]) == {
        "gross_weight_kg", "chargeable_weight_kg", "package_count", "volume_m3",
    }
    assert {
        row["fieldname"]: row["suggested_value"]
        for row in catalog["field_candidates"]
        if row["default_selected"]
    } == {
        "gross_weight_kg": "42.05",
        "chargeable_weight_kg": "46",
        "package_count": "1",
        "volume_m3": "0.01518",
    }


def test_payment_preview_keeps_matched_process_when_no_shipment_line_is_safe(monkeypatch):
    from overseas_costing.services import material_ai_payment_match as service
    from overseas_costing.services.logistics_settlement import packing_selection

    store, ledger, batch, version, logistics, source, candidate = payment_setup(
        structured=True,
        scope="freight",
        amount="44075.13",
        mode="EXPRESS",
    )
    candidate.update(method="explicit", issues=[], line_ids=[], amount_pending=True)
    store.put("freight_candidate", _candidate_values(candidate))
    monkeypatch.setattr(packing_selection, "_catalog", lambda *_args: (logistics, []))

    reference = service.select_preview_candidate(
        store, ledger, batch["name"], version["name"], freight_mode=True
    )
    sources = service.preview_sources(
        store, ledger, batch["name"], version["name"], reference, freight_mode=True
    )

    assert len(sources) == 1
    preview = sources[0]
    assert preview["workflow_stage"] == "payment"
    assert preview["process_instance_id"] == source["instance"]
    assert preview["source_kind"] == "approval_form"
    assert preview["read_status"] == "PARTIAL"
    assert preview["ai_eligible"] is False
    assert preview["scoped_goods"] == []
    assert preview["scoped_text"] == ""
    assert "未识别出属于本票的可采用明细" in preview["analysis_reason"]
    assert preview["error"] == preview["analysis_reason"]
    assert "44075.13" not in json.dumps(preview, ensure_ascii=False)


def test_conflicting_rule_match_remains_visible_as_metadata_only_payment_process():
    from overseas_costing.services import material_ai_payment_match as service

    store, ledger, batch, version, _logistics, source, candidate = _strong_context()
    store.put(
        "freight_candidate",
        _candidate_values(
            candidate,
            status="conflict",
            method="explicit",
            issues=["本笔费用已用于其他票"],
            line_ids=[],
            amount_pending=True,
        ),
    )

    assert service.select_preview_candidate(
        store, ledger, batch["name"], version["name"], freight_mode=True
    ) is None

    sources = service.preview_process_sources(
        store, ledger, batch["name"], version["name"], freight_mode=True
    )

    assert len(sources) == 1
    preview = sources[0]
    assert preview["workflow_stage"] == "payment"
    assert preview["process_instance_id"] == source["instance"]
    assert preview["metadata_only_process"] is True
    assert preview["ai_eligible"] is False
    assert preview["scoped_goods"] == []
    assert preview["scoped_text"] == ""
    assert "payment_match_candidate" not in preview
    assert "存在冲突" in preview["analysis_reason"]
    assert "44075.13" not in json.dumps(preview, ensure_ascii=False)


def test_payment_preview_merges_matched_fee_line_into_same_document_snapshot(monkeypatch):
    from overseas_costing.services import material_ai_payment_match as service
    from overseas_costing.services.logistics_settlement import packing_selection

    store, ledger, batch, version, logistics, source, candidate = payment_setup(
        structured=True, scope="freight", amount="3322.784523", mode="EXPRESS"
    )
    line = store.get("freight_line", "payment-line-1")
    line.update(
        label="DHL 快递运费",
        evidence={"document_id": "doc", "file_name": "DHL.xlsx", "sheet": "DHL", "row": 8},
    )
    store.put(
        "freight_line",
        {
            "id": line["id"], "source_id": line["source_id"], "snapshot": line["snapshot"],
            "line_key": line["line_key"], "waybill": line["waybill"],
            "approval_no": line["approval_no"], "charge_key": line["charge_key"],
            "data": dumps(line),
        },
    )
    candidate.update(method="explicit", issues=[])
    store.put("freight_candidate", _candidate_values(candidate))
    catalog_row = {
        "id": "catalog-row", "source_id": source["id"], "source_kind": "approval_attachment",
        "source_label": "DHL.xlsx · DHL", "approval_no": source["approval_no"],
        "source_snapshot": source["snapshot"], "process_instance_id": source["instance"],
        "evidence": {"document_id": "doc", "file_name": "DHL.xlsx", "sheet": "DHL", "row": 8},
        "document_id": "doc", "sheet": "DHL", "revision": "catalog-revision",
        "goods": [{"material_code": "MWV101144", "quantity": "1"}],
        "text": "装箱资料",
    }
    monkeypatch.setattr(packing_selection, "_catalog", lambda *_args: (logistics, [catalog_row]))

    reference = service.select_preview_candidate(
        store, ledger, batch["name"], version["name"], freight_mode=True
    )
    sources = service.preview_sources(
        store, ledger, batch["name"], version["name"], reference, freight_mode=True
    )

    assert len(sources) == 1
    assert sources[0]["scoped_goods"] == catalog_row["goods"]
    assert sources[0]["scoped_text"].splitlines() == [
        "装箱资料", "费用项目: DHL 快递运费", "运费金额: 3322.784523 RMB", "运单号: WB-1",
    ]


def test_payment_preview_never_widens_missing_row_evidence_to_whole_monthly_sheet(monkeypatch):
    from overseas_costing.services import material_ai_payment_match as service
    from overseas_costing.services.logistics_settlement import packing_selection

    store, ledger, batch, version, logistics, source, candidate = payment_setup(
        structured=True, scope="freight", amount="3414.19", mode="EXPRESS"
    )
    line = store.get("freight_line", "payment-line-1")
    line.update(
        cargo_text="MWV101144 本票货物",
        evidence={"document_id": "monthly-doc", "file_name": "DHL.xlsx", "sheet": "DHL"},
    )
    store.put("freight_line", {"id": line["id"], "data": dumps(line)})
    candidate.update(method="explicit", issues=[])
    store.put("freight_candidate", _candidate_values(candidate))
    sibling = {
        "id": "other-ticket-row", "source_id": source["id"],
        "source_kind": "approval_attachment", "source_label": "DHL.xlsx · DHL",
        "approval_no": source["approval_no"], "source_snapshot": source["snapshot"],
        "process_instance_id": source["instance"], "document_id": "monthly-doc", "sheet": "DHL",
        "evidence": {"document_id": "monthly-doc", "file_name": "DHL.xlsx", "sheet": "DHL", "row": 99},
        "revision": "other-ticket-revision",
        "goods": [{"material_code": "SECRET999", "quantity": "999"}],
        "text": "其他票私密明细",
    }
    monkeypatch.setattr(packing_selection, "_catalog", lambda *_args: (logistics, [sibling]))

    reference = service.select_preview_candidate(
        store, ledger, batch["name"], version["name"], freight_mode=True
    )
    sources = service.preview_sources(
        store, ledger, batch["name"], version["name"], reference, freight_mode=True
    )

    payload = json.dumps(sources, ensure_ascii=False)
    assert "SECRET999" not in payload
    assert "其他票私密明细" not in payload
    assert "MWV101144 本票货物" in payload
