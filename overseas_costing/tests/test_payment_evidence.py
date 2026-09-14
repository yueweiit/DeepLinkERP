from copy import deepcopy

import pytest

from overseas_costing.services.logistics_settlement.model import digest, dumps
from overseas_costing.tests.test_payment_adoption import (
    NOW,
    _add_second_structured_line,
    confirm_preview,
    make_preview,
    payment_setup,
    selection,
)


def payment_document(identity="payment-document", *, origin="form", status="archived", file_url="/private/files/payment.pdf",
                     file_name="payment-invoice.pdf", attachment_type="Commercial Invoice", fingerprint="sha-payment"):
    return {
        "id": identity,
        "file_name": file_name,
        "file_url": file_url,
        "status": "parsed",
        "fingerprint": fingerprint,
        "manifest": {
            "file_id": "file-" + identity,
            "archive_status": status,
            "archive_quality": "original",
            "attachment_origin": origin,
            "attachment_type": attachment_type,
            "sha256": fingerprint,
            "source_field_id": "field-payment",
            "source_field_name": "付款附件",
        },
        "tables": [],
        "preview": {"classification": "invoice", "text_excerpt": "private parsed text"},
        "raw": {"account": "6222020202020202", "token": "secret-token"},
    }


def set_documents(ctx, documents):
    store, _ledger, _batch, _version, _logistics, source, _candidate = ctx
    source = deepcopy(store.get("source", source["id"]))
    source["documents"] = documents
    source["attachments"] = [doc["manifest"] for doc in documents]
    store.put("source", {"id": source["id"], "data": dumps(source)})
    return source


def attachment_choice(document_id, *keys, selected=True):
    return {"document_id": document_id, "selected": selected, "logical_fee_keys": list(keys)}


def test_candidate_and_preview_expose_only_safe_form_comment_attachment_summaries():
    from overseas_costing.services.logistics_settlement.freight_runtime import candidate_view

    ctx = payment_setup()
    form = payment_document()
    comment = payment_document("comment-document", origin="comment", file_name="tax-certificate.pdf",
                               attachment_type="Tax Certificate", fingerprint="sha-tax")
    source = set_documents(ctx, [form, comment])
    view = candidate_view(ctx[0], ctx[6], "SEA", ctx[1])
    preview = make_preview(ctx, [selection("40")])
    assert {row["origin"] for row in view["attachments"]} == {"Form", "Comment"}
    assert {row["document_id"] for row in preview["attachments"]} == {form["id"], comment["id"]}
    serialized = dumps({"view": view["attachments"], "preview": preview["attachments"]})
    for secret in ("file_url", "/private/files", "raw", "private parsed text", "6222020202020202", "secret-token"):
        assert secret not in serialized
    assert source["documents"][0]["file_url"] == "/private/files/payment.pdf"


def test_registered_attachment_index_is_visible_as_pending_without_exposing_archive_coordinates():
    from overseas_costing.services.logistics_settlement.freight_runtime import candidate_view

    ctx = payment_setup()
    source = deepcopy(ctx[0].get("source", ctx[5]["id"]))
    source["attachments"] = [{"file_id": "indexed-file", "file_name": "comment-tax.pdf", "origin": "comment",
                              "archive_status": "pending", "bucket": "private-bucket", "object_key": "secret/object"}]
    ctx[0].put("source", {"id": source["id"], "data": dumps(source)})
    summaries = candidate_view(ctx[0], ctx[6], "SEA", ctx[1])["attachments"]
    assert len(summaries) == 1 and summaries[0]["origin"] == "Comment"
    assert summaries[0]["availability"] == "pending"
    assert "private-bucket" not in dumps(summaries) and "secret/object" not in dumps(summaries)


def test_preview_is_read_only_and_cancelled_optional_attachment_is_not_materialized():
    ctx = payment_setup()
    set_documents(ctx, [payment_document()])
    preview = make_preview(ctx, [selection("40")], attachment_selections=[])
    assert not ctx[1].rows("attachment") and not ctx[1].rows("evidence")
    result = confirm_preview(ctx, preview)
    assert result["status"] == "applied"
    assert not ctx[1].rows("attachment") and not ctx[1].rows("evidence")


def test_confirm_materializes_selected_private_attachment_and_links_idempotent_fee_evidence():
    ctx = payment_setup()
    doc = payment_document(origin="comment")
    set_documents(ctx, [doc])
    preview = make_preview(ctx, [selection("40")], attachment_selections=[
        attachment_choice(doc["id"], "customs_clearance_fee")
    ])
    result = confirm_preview(ctx, preview)
    attachment = ctx[1].rows("attachment")[0]
    evidence = ctx[1].rows("evidence")[0]
    rule = next(row for row in ctx[1].rows("rule") if row.get("source_binding_id"))
    assert attachment["batch"] == ctx[2]["name"] and attachment["version"] == ctx[3]["name"]
    assert attachment["oa_attachment_origin"] == "Comment" and attachment["file_url"].startswith("/private/files/")
    assert evidence["fee_rule"] == rule["name"] and evidence["attachment"] == attachment["name"]
    assert evidence["validation_status"] == "PENDING" and evidence["evidence_type"] == "FINAL_INVOICE"
    assert evidence["attachment_fingerprint"] == "sha-payment" and evidence["currency"] == "RMB"
    assert result["attachments"][0]["attachment_name"] == attachment["name"]
    retry = confirm_preview(ctx, preview)
    assert retry["cached"] is True and len(ctx[1].rows("attachment")) == len(ctx[1].rows("evidence")) == 1


def test_multiple_documents_map_to_only_the_selected_fee_keys():
    ctx = payment_setup(amount="100")
    invoice = payment_document("invoice")
    tax = payment_document("tax", file_name="tax.pdf", attachment_type="Tax Certificate", fingerprint="sha-tax")
    set_documents(ctx, [invoice, tax])
    preview = make_preview(ctx, [selection("40"), selection("20", key="import_tax")], attachment_selections=[
        attachment_choice(invoice["id"], "customs_clearance_fee"),
        attachment_choice(tax["id"], "import_tax"),
    ])
    confirm_preview(ctx, preview)
    evidence = ctx[1].rows("evidence")
    rules = {row["name"]: row for row in ctx[1].rows("rule") if row.get("source_binding_id")}
    assert {(rules[row["fee_rule"]]["logical_fee_key"], row["evidence_type"]) for row in evidence} == {
        ("customs_clearance_fee", "FINAL_INVOICE"), ("import_tax", "TAX_CERTIFICATE")
    }


def test_each_structured_document_evidence_uses_only_its_own_line_amount():
    ctx = payment_setup(structured=True, scope="customs", amount="100")
    store, _ledger, _batch, _version, _logistics, source, candidate = ctx
    first = payment_document("first", fingerprint="sha-first", file_name="first-invoice.pdf")
    second = payment_document("second", fingerprint="sha-second", file_name="second-invoice.pdf")
    set_documents(ctx, [first, second])
    line1 = store.get("freight_line", "payment-line-1")
    line1.update(amount="40", revision="rev-first",
                 evidence={"document_id": "first", "document_hash": "sha-first", "amount_field": "金额"})
    store.put("freight_line", {key: line1[key] for key in (
        "id", "source_id", "snapshot", "line_key", "waybill", "approval_no", "charge_key"
    )} | {"data": dumps(line1)})
    line2 = {**line1, "id": "payment-line-2", "line_key": "line-key-2", "amount": "60",
             "revision": "rev-second", "charge_key": "economic-charge-2",
             "evidence": {"document_id": "second", "document_hash": "sha-second", "amount_field": "金额"}}
    store.insert("freight_line", {key: line2[key] for key in (
        "id", "source_id", "snapshot", "line_key", "waybill", "approval_no", "charge_key"
    )} | {"data": dumps(line2)})
    updated_candidate = {**candidate, "line_ids": [line1["id"], line2["id"]]}
    store.put("freight_candidate", {"id": candidate["id"], "status": candidate["status"],
                                     "data": dumps(updated_candidate)})
    selections = [
        {**selection("40"), "source_line_id": line1["id"]},
        {**selection("60"), "source_line_id": line2["id"]},
    ]
    preview = make_preview(ctx, selections, attachment_selections=[
        attachment_choice("first", "customs_clearance_fee"),
        attachment_choice("second", "customs_clearance_fee"),
    ])
    confirm_preview(ctx, preview)
    by_attachment = {ctx[1].get("attachment", row["attachment"])["file_name"]: str(row["original_amount"])
                     for row in ctx[1].rows("evidence")}
    assert by_attachment == {"first-invoice.pdf": "40", "second-invoice.pdf": "60"}


def test_structured_attachment_amount_is_required_and_cannot_be_confirmed_when_unavailable():
    ctx = payment_setup(structured=True, scope="customs")
    doc = payment_document(status="pending", file_url="")
    set_documents(ctx, [doc])
    line = ctx[0].get("freight_line", "payment-line-1")
    line["evidence"] = {"document_id": doc["id"], "document_hash": "sha-payment", "amount_field": "金额"}
    ctx[0].put("freight_line", {key: line[key] for key in (
        "id", "source_id", "snapshot", "line_key", "waybill", "approval_no", "charge_key"
    )} | {"data": dumps(line)})
    selected = {**selection("100"), "source_line_id": line["id"]}
    preview = make_preview(ctx, [selected], attachment_selections=[attachment_choice(doc["id"], "customs_clearance_fee")])
    assert preview["payment_blocking_reasons"] and preview["attachments"][0]["required"] is True
    with pytest.raises(ValueError, match="附件"):
        confirm_preview(ctx, preview)
    assert not ctx[1].rows("attachment") and not ctx[1].rows("evidence") and not ctx[0].find("payment_claim")


def test_amount_dependent_attachment_cannot_be_deselected():
    ctx = payment_setup(structured=True, scope="customs")
    doc = payment_document()
    set_documents(ctx, [doc])
    line = ctx[0].get("freight_line", "payment-line-1")
    line["evidence"] = {"document_id": doc["id"], "document_hash": "sha-payment", "amount_field": "金额"}
    ctx[0].put("freight_line", {key: line[key] for key in (
        "id", "source_id", "snapshot", "line_key", "waybill", "approval_no", "charge_key"
    )} | {"data": dumps(line)})
    selected = {**selection("100"), "source_line_id": line["id"]}
    preview = make_preview(ctx, [selected], attachment_selections=[])
    assert any("必须" in reason for reason in preview["payment_blocking_reasons"])
    with pytest.raises(ValueError, match="附件"):
        confirm_preview(ctx, preview)


def test_structured_line_cannot_be_bound_to_different_document_bytes():
    ctx = payment_setup(structured=True, scope="customs")
    doc = payment_document(fingerprint="different-sha")
    set_documents(ctx, [doc])
    line = ctx[0].get("freight_line", "payment-line-1")
    line["evidence"] = {"document_id": doc["id"], "document_hash": "original-sha", "amount_field": "金额"}
    ctx[0].put("freight_line", {key: line[key] for key in (
        "id", "source_id", "snapshot", "line_key", "waybill", "approval_no", "charge_key"
    )} | {"data": dumps(line)})
    selected = {**selection("100"), "source_line_id": line["id"]}
    with pytest.raises(ValueError, match="指纹"):
        make_preview(ctx, [selected], attachment_selections=[attachment_choice(doc["id"], "customs_clearance_fee")])


def test_trusted_form_total_can_confirm_while_unavailable_optional_attachment_stays_pending():
    ctx = payment_setup()
    doc = payment_document(status="pending", file_url="")
    set_documents(ctx, [doc])
    preview = make_preview(ctx, [selection("40")], attachment_selections=[attachment_choice(doc["id"], "customs_clearance_fee")])
    assert preview["attachments"][0]["availability"] == "pending"
    result = confirm_preview(ctx, preview)
    assert result["status"] == "applied" and not ctx[1].rows("attachment") and not ctx[1].rows("evidence")


@pytest.mark.parametrize("change", ["fingerprint", "availability", "relationship", "removed"])
def test_source_document_change_invalidates_old_preview(change):
    ctx = payment_setup()
    doc = payment_document()
    set_documents(ctx, [doc])
    preview = make_preview(ctx, [selection("40")], attachment_selections=[attachment_choice(doc["id"], "customs_clearance_fee")])
    changed = deepcopy(doc)
    if change == "fingerprint":
        changed["manifest"]["sha256"] = changed["fingerprint"] = "new-sha"
    elif change == "availability":
        changed["manifest"]["archive_status"] = "pending"
    elif change == "relationship":
        changed["manifest"]["source_field_id"] = "different-field"
    set_documents(ctx, [] if change == "removed" else [changed])
    with pytest.raises(ValueError, match="附件|来源"):
        confirm_preview(ctx, preview)
    assert not ctx[1].rows("attachment") and not ctx[1].rows("evidence")


def test_required_materialization_failure_rolls_back_claim_rule_attachment_and_evidence():
    from overseas_costing.services.logistics_settlement.payment_adoption import confirm_payment_adoption

    ctx = payment_setup(structured=True, scope="customs")
    doc = payment_document()
    set_documents(ctx, [doc])
    line = ctx[0].get("freight_line", "payment-line-1")
    line["evidence"] = {"document_id": doc["id"], "document_hash": "sha-payment", "amount_field": "金额"}
    ctx[0].put("freight_line", {key: line[key] for key in (
        "id", "source_id", "snapshot", "line_key", "waybill", "approval_no", "charge_key"
    )} | {"data": dumps(line)})
    selected = {**selection("100"), "source_line_id": line["id"]}
    preview = make_preview(ctx, [selected], attachment_selections=[attachment_choice(doc["id"], "customs_clearance_fee")])

    def fail(*_args):
        raise RuntimeError("private archive registration failed")

    with pytest.raises(RuntimeError, match="registration"):
        confirm_payment_adoption(ctx[0], ctx[1], ctx[2]["name"], preview["preview_id"], preview["revision"],
                                 "user", now=NOW, register_file=fail)
    assert not ctx[0].find("payment_claim") and not ctx[0].find("payment_application")
    assert not ctx[1].rows("attachment") and not ctx[1].rows("evidence")
    assert not [row for row in ctx[1].rows("rule") if row.get("source_binding_id")]


def test_optional_materialization_failure_keeps_trusted_form_claim_and_returns_pending_attachment():
    from overseas_costing.services.logistics_settlement.payment_adoption import confirm_payment_adoption

    ctx = payment_setup()
    doc = payment_document()
    set_documents(ctx, [doc])
    preview = make_preview(ctx, [selection("40")], attachment_selections=[
        attachment_choice(doc["id"], "customs_clearance_fee")
    ])

    def fail(*_args):
        raise RuntimeError("private archive registration failed")

    result = confirm_payment_adoption(ctx[0], ctx[1], ctx[2]["name"], preview["preview_id"], preview["revision"],
                                      "user", now=NOW, register_file=fail)
    assert result["status"] == "applied" and result["attachments"][0]["status"] == "pending"
    assert ctx[0].find("payment_claim") and not ctx[1].rows("attachment") and not ctx[1].rows("evidence")


def test_optional_evidence_failure_rolls_back_attachment_persists_pending_and_cached_confirm_retries():
    from overseas_costing.services.logistics_settlement.payment_adoption import (
        confirm_payment_adoption,
        public_payment_context,
    )

    ctx = payment_setup()
    doc = payment_document()
    set_documents(ctx, [doc])
    preview = make_preview(ctx, [selection("40")], attachment_selections=[
        attachment_choice(doc["id"], "customs_clearance_fee")
    ])
    original_create = ctx[1].create

    def fail_evidence(kind, values):
        if kind == "evidence":
            raise RuntimeError("evidence insert failed")
        return original_create(kind, values)

    ctx[1].create = fail_evidence
    result = confirm_payment_adoption(ctx[0], ctx[1], ctx[2]["name"], preview["preview_id"], preview["revision"],
                                      "user", now=NOW)
    assert result["status"] == "applied" and not ctx[1].rows("attachment") and not ctx[1].rows("evidence")
    public = public_payment_context(ctx[0], ctx[1], ctx[2]["name"], ctx[3]["name"])
    assert public["payment_evidence_pending"][0]["status"] == "pending"
    assert "insert failed" not in dumps(public)
    ctx[1].create = original_create
    retried = confirm_preview(ctx, preview)
    assert retried["cached"] is True and len(ctx[1].rows("attachment")) == len(ctx[1].rows("evidence")) == 1
    assert not public_payment_context(ctx[0], ctx[1], ctx[2]["name"], ctx[3]["name"])["payment_evidence_pending"]


def _applied_with_unavailable_optional_document():
    ctx = payment_setup()
    document = payment_document(status="pending", file_url="")
    set_documents(ctx, [document])
    preview = make_preview(ctx, [selection("40")], attachment_selections=[
        attachment_choice(document["id"], "customs_clearance_fee")
    ])
    result = confirm_preview(ctx, preview)
    assert result["attachments"][0]["status"] == "pending"
    assert ctx[0].find("payment_evidence_pending", batch=ctx[2]["name"], version=ctx[3]["name"])
    return ctx, document, preview, result


def test_applied_pending_attachment_can_retry_after_only_archive_availability_changes():
    from overseas_costing.services.logistics_settlement.payment_adoption import public_payment_context

    ctx, document, preview, _result = _applied_with_unavailable_optional_document()
    available = deepcopy(document)
    available["manifest"]["archive_status"] = "archived"
    available["file_url"] = "/private/files/payment.pdf"
    set_documents(ctx, [available])

    retried = confirm_preview(ctx, preview)
    assert retried["cached"] is True
    assert retried["attachments"][0]["status"] == "archived"
    assert len(ctx[1].rows("attachment")) == len(ctx[1].rows("evidence")) == 1
    assert public_payment_context(ctx[0], ctx[1], ctx[2]["name"], ctx[3]["name"])["payment_evidence_pending"] == []
    repeated = confirm_preview(ctx, preview)
    assert repeated["cached"] is True
    assert len(ctx[1].rows("attachment")) == len(ctx[1].rows("evidence")) == 1


def test_applied_pending_attachment_allows_archive_only_source_snapshot_refresh():
    from overseas_costing.services.logistics_settlement.payment_adoption import public_payment_context

    ctx, document, preview, _result = _applied_with_unavailable_optional_document()
    confirm_preview(ctx, make_preview(ctx, [selection("20", key="import_tax")], attachment_selections=[]))
    source = deepcopy(ctx[0].get("source", ctx[5]["id"]))
    available = deepcopy(document)
    available["manifest"]["archive_status"] = "archived"
    available["file_url"] = "/private/files/payment.pdf"
    source.update(snapshot="payment-snapshot-after-archive", documents=[available],
                  attachments=[available["manifest"]], updated_at="2026-09-14T04:00:00+00:00")
    ctx[0].put("source", {"id": source["id"], "snapshot": source["snapshot"], "data": dumps(source)})

    retried = confirm_preview(ctx, preview)
    assert retried["cached"] is True and len(ctx[1].rows("evidence")) == 1
    assert ctx[1].rows("evidence")[0]["source_revision"] == "payment-snapshot-after-archive"
    claims = ctx[0].find("payment_claim", batch=ctx[2]["name"], version=ctx[3]["name"], status="active")
    rules = [row for row in ctx[1].rows("rule") if row.get("is_active") not in (0, False, "0")]
    application = ctx[0].get("payment_application", retried["application_id"])
    assert {claim["source_snapshot"] for claim in claims} == {"payment-snapshot-after-archive"}
    assert {rule["source_snapshot"] for rule in rules} == {"payment-snapshot-after-archive"}
    assert application["source_snapshot"] == "payment-snapshot-after-archive"
    assert application["result"]["claims"][0]["source_snapshot"] == "payment-snapshot-after-archive"
    assert public_payment_context(ctx[0], ctx[1], ctx[2]["name"], ctx[3]["name"])["payment_blocking_reasons"] == []


def test_archive_snapshot_retry_rejects_other_source_document_identity_or_content_change():
    ctx, document, preview, _result = _applied_with_unavailable_optional_document()
    available = deepcopy(document)
    available["manifest"]["archive_status"] = "archived"
    available["file_url"] = "/private/files/payment.pdf"
    unrelated = payment_document("unexpected-document", fingerprint="unexpected-content")
    source = deepcopy(ctx[0].get("source", ctx[5]["id"]))
    source.update(snapshot="snapshot-with-unexpected-document", documents=[available, unrelated],
                  attachments=[available["manifest"], unrelated["manifest"]])
    ctx[0].put("source", {"id": source["id"], "snapshot": source["snapshot"], "data": dumps(source)})

    with pytest.raises(ValueError, match="来源.*变化"):
        confirm_preview(ctx, preview)
    assert not ctx[1].rows("attachment") and not ctx[1].rows("evidence")


def test_applied_pending_attachment_retry_rejects_changed_document_content():
    ctx, document, preview, _result = _applied_with_unavailable_optional_document()
    changed = deepcopy(document)
    changed["manifest"].update(archive_status="archived", sha256="sha-replaced")
    changed.update(file_url="/private/files/payment.pdf", fingerprint="sha-replaced")
    set_documents(ctx, [changed])

    with pytest.raises(ValueError, match="内容指纹"):
        confirm_preview(ctx, preview)
    assert not ctx[1].rows("attachment") and not ctx[1].rows("evidence")
    assert ctx[0].find("payment_evidence_pending", batch=ctx[2]["name"], version=ctx[3]["name"], status="pending")


def test_applied_pending_attachment_retry_rejects_replaced_active_rule():
    ctx, document, preview, result = _applied_with_unavailable_optional_document()
    old_rule = next(row for row in ctx[1].rows("rule") if row.get("source_binding_id"))
    ctx[1].put("rule", old_rule["name"], {"is_enabled": 0, "is_active": 0})
    ctx[1].create("rule", {**{key: value for key, value in old_rule.items() if key != "name"},
                            "is_enabled": 1, "is_active": 1,
                            "source_binding_id": result["claims"][0]["id"]})
    available = deepcopy(document)
    available["manifest"]["archive_status"] = "archived"
    available["file_url"] = "/private/files/payment.pdf"
    set_documents(ctx, [available])

    with pytest.raises(ValueError, match="费用规则"):
        confirm_preview(ctx, preview)
    assert not ctx[1].rows("attachment") and not ctx[1].rows("evidence")


def test_applied_pending_attachment_retry_rejects_changed_selection_or_claim_amount():
    ctx, document, preview, result = _applied_with_unavailable_optional_document()
    available = deepcopy(document)
    available["manifest"]["archive_status"] = "archived"
    available["file_url"] = "/private/files/payment.pdf"
    set_documents(ctx, [available])
    private = ctx[0].get("payment_preview", preview["preview_id"])
    private["attachment_plan"]["selected"] = []
    ctx[0].put("payment_preview", {key: private[key] for key in (
        "id", "batch", "version", "logistics_id", "source_id", "status", "revision", "expires_at"
    )} | {"data": dumps(private)})
    with pytest.raises(ValueError, match="选择"):
        confirm_preview(ctx, preview)

    private["attachment_plan"] = deepcopy(ctx[0].get("payment_preview", preview["preview_id"])["attachment_plan"])
    private["attachment_plan"]["selected"] = [{
        "document_id": document["id"], "document_fingerprint": "ignored-on-safe-retry",
        "logical_fee_keys": ["customs_clearance_fee"], "availability": "pending",
        "required": False, "role": "invoice",
    }]
    ctx[0].put("payment_preview", {key: private[key] for key in (
        "id", "batch", "version", "logistics_id", "source_id", "status", "revision", "expires_at"
    )} | {"data": dumps(private)})
    claim = ctx[0].get("payment_claim", result["claims"][0]["id"])
    claim.update(amount="41", revision="changed-claim-revision")
    ctx[0].put("payment_claim", {key: claim[key] for key in (
        "id", "batch", "version", "logistics_id", "source_id", "source_snapshot", "source_line_id",
        "logical_fee_key", "amount", "currency", "status", "exclusive", "claim_key", "revision",
    )} | {"data": dumps(claim)})
    with pytest.raises(ValueError, match="认领|金额"):
        confirm_preview(ctx, preview)
    assert not ctx[1].rows("attachment") and not ctx[1].rows("evidence")


def test_applied_pending_attachment_retry_rejects_cross_version_replay():
    ctx, document, preview, _result = _applied_with_unavailable_optional_document()
    other = ctx[1].create("version", {"batch": ctx[2]["name"], "status": "Active", "is_current": 1})
    ctx[1].put("batch", ctx[2]["name"], {"current_version": other["name"]})
    available = deepcopy(document)
    available["manifest"]["archive_status"] = "archived"
    available["file_url"] = "/private/files/payment.pdf"
    set_documents(ctx, [available])

    with pytest.raises(ValueError, match="版本"):
        confirm_preview(ctx, preview)
    assert not ctx[1].rows("attachment") and not ctx[1].rows("evidence")


@pytest.mark.parametrize("action,edits,new_key,expected_amount", [
    ("amount", {"amount": "50"}, "customs_clearance_fee", "50"),
    ("reclassify", {"logical_fee_key": "import_tax"}, "import_tax", "40"),
])
def test_pending_attachment_follows_amended_claim_and_current_rule(action, edits, new_key, expected_amount):
    from overseas_costing.services.logistics_settlement.payment_adoption import amend_payment_claim

    ctx, document, preview, result = _applied_with_unavailable_optional_document()
    claim = result["claims"][0]
    amended = amend_payment_claim(ctx[0], ctx[1], ctx[2]["name"], ctx[3]["name"], claim["id"], claim["revision"],
                                  action, "更正待归档付款", edits, "reviewer")["claim"]
    available = deepcopy(document)
    available["manifest"]["archive_status"] = "archived"
    available["file_url"] = "/private/files/payment.pdf"
    set_documents(ctx, [available])

    retried = confirm_preview(ctx, preview)
    rule = next(row for row in ctx[1].rows("rule") if row.get("is_active") not in (0, False, "0")
                and row.get("logical_fee_key") == new_key)
    evidence = ctx[1].rows("evidence")
    assert retried["cached"] is True and amended["logical_fee_key"] == new_key
    assert len(evidence) == 1 and evidence[0]["fee_rule"] == rule["name"]
    assert evidence[0]["original_amount"] == expected_amount
    assert not ctx[0].find("payment_evidence_pending", batch=ctx[2]["name"], version=ctx[3]["name"], status="pending")


def test_revoking_claim_cancels_pending_evidence_and_removes_public_retry():
    from overseas_costing.services.logistics_settlement.payment_adoption import amend_payment_claim, public_payment_context

    ctx, _document, preview, result = _applied_with_unavailable_optional_document()
    claim = result["claims"][0]
    amend_payment_claim(ctx[0], ctx[1], ctx[2]["name"], ctx[3]["name"], claim["id"], claim["revision"],
                        "revoke", "撤销该笔费用", {}, "reviewer")
    assert public_payment_context(ctx[0], ctx[1], ctx[2]["name"], ctx[3]["name"])["payment_evidence_pending"] == []
    assert ctx[0].find("payment_evidence_pending", batch=ctx[2]["name"], version=ctx[3]["name"], status="cancelled")
    retried = confirm_preview(ctx, preview)
    assert retried["cached"] is True and not ctx[1].rows("attachment") and not ctx[1].rows("evidence")


def _two_claim_pending_group():
    ctx = payment_setup(structured=True, scope="freight", amount="40")
    _add_second_structured_line(ctx)
    document = payment_document(status="pending", file_url="")
    set_documents(ctx, [document])
    preview = make_preview(ctx, [
        {"source_line_id": "payment-line-1", "amount": "40", "currency": "RMB"},
        {"source_line_id": "payment-line-2", "amount": "60", "currency": "RMB"},
    ], attachment_selections=[attachment_choice(document["id"], "international_sea_freight")])
    result = confirm_preview(ctx, preview)
    return ctx, document, preview, result


def _allow_aggregate_amendment(ctx, claim):
    current = ctx[0].get("payment_claim", claim["id"])
    current["exclusive"] = 0
    ctx[0].put("payment_claim", {key: current[key] for key in (
        "id", "batch", "version", "logistics_id", "source_id", "source_snapshot", "source_line_id",
        "logical_fee_key", "amount", "currency", "status", "exclusive", "claim_key", "revision",
    )} | {"data": dumps(current)})
    return current


@pytest.mark.parametrize("action,edits,amounts", [
    ("amount", {"amount": "30"}, {"international_sea_freight": "90"}),
    ("reclassify", {"logical_fee_key": "customs_clearance_fee"},
     {"international_sea_freight": "60", "customs_clearance_fee": "40"}),
    ("revoke", {}, {"international_sea_freight": "60"}),
])
def test_multi_claim_pending_groups_recompute_after_one_claim_amendment(action, edits, amounts):
    from overseas_costing.services.logistics_settlement.payment_adoption import amend_payment_claim

    ctx, document, preview, result = _two_claim_pending_group()
    target = result["claims"][0]
    if action != "revoke":
        target = _allow_aggregate_amendment(ctx, target)
    amend_payment_claim(ctx[0], ctx[1], ctx[2]["name"], ctx[3]["name"], target["id"], target["revision"],
                        action, "更正聚合付款组", edits, "reviewer")
    pending = ctx[0].find("payment_evidence_pending", batch=ctx[2]["name"], version=ctx[3]["name"], status="pending")
    assert {row["logical_fee_key"]: row["selection_amount"] for row in pending} == amounts
    assert all(len(row["claim_ids"]) == 1 if action in {"reclassify", "revoke"} else len(row["claim_ids"]) == 2
               for row in pending)

    available = deepcopy(document)
    available["manifest"]["archive_status"] = "archived"
    available["file_url"] = "/private/files/payment.pdf"
    set_documents(ctx, [available])
    confirm_preview(ctx, preview)
    evidence = ctx[1].rows("evidence")
    rules = {row["name"]: row for row in ctx[1].rows("rule")}
    assert {rules[row["fee_rule"]]["logical_fee_key"]: row["original_amount"] for row in evidence} == amounts


def test_payment_evidence_reuses_packing_attachment_without_overwriting_metadata():
    ctx = payment_setup()
    document = payment_document()
    set_documents(ctx, [document])
    packing_parse = dumps({"settlement_document": {"document_id": document["id"], "tables": [{"kind": "packing"}]}})
    packing_mapped = dumps({"settlement_document": {"document_id": document["id"], "packing": True}})
    attachment = ctx[1].create("attachment", {
        "batch": ctx[2]["name"], "version": ctx[3]["name"], "attachment_type": "Packing List",
        "file_name": document["file_name"], "file_url": document["file_url"], "parse_status": "Parsed",
        "parse_result_json": packing_parse, "mapped_result_json": packing_mapped,
    })
    key = digest(document["id"], ctx[3]["name"])
    ctx[0].put("attachment_map", {"id": key, "document_id": document["id"], "version": ctx[3]["name"],
                                  "attachment": attachment["name"], "data": dumps({"source_id": ctx[5]["id"]})})

    result = confirm_preview(ctx, make_preview(ctx, [selection("40")], attachment_selections=[
        attachment_choice(document["id"], "customs_clearance_fee")
    ]))
    reused = ctx[1].get("attachment", attachment["name"])
    assert result["attachments"][0]["attachment_name"] == attachment["name"]
    assert len(ctx[1].rows("attachment")) == 1 and len(ctx[1].rows("evidence")) == 1
    assert reused["parse_result_json"] == packing_parse and reused["mapped_result_json"] == packing_mapped
    assert reused["attachment_type"] == "Packing List"


def test_different_actor_with_valid_lease_can_finish_pending_evidence_retry_and_is_audited():
    from overseas_costing.services.logistics_settlement.payment_adoption import confirm_payment_adoption

    ctx, document, preview, _result = _applied_with_unavailable_optional_document()
    available = deepcopy(document)
    available["manifest"]["archive_status"] = "archived"
    available["file_url"] = "/private/files/payment.pdf"
    set_documents(ctx, [available])
    leases = []

    def assert_lease(batch_name, *, edit_token, expected_modified):
        leases.append((batch_name, edit_token, expected_modified))

    retried = confirm_payment_adoption(
        ctx[0], ctx[1], ctx[2]["name"], preview["preview_id"], preview["revision"], "mexico.finance",
        now=NOW, lease_check=assert_lease, edit_token="valid-token", expected_modified="current-modified",
    )
    assert retried["cached"] is True and len(ctx[1].rows("evidence")) == 1
    assert leases == [(ctx[2]["name"], "valid-token", "current-modified")]
    audits = ctx[0].find("audit", binding_id=ctx[2]["name"], action="payment_evidence_retried")
    assert audits and audits[-1]["actor"] == "mexico.finance"


@pytest.mark.parametrize("action,edits,new_key", [
    ("amount", {"amount": "50"}, "customs_clearance_fee"),
    ("status", {"amount_status": "ESTIMATED"}, "customs_clearance_fee"),
    ("reclassify", {"logical_fee_key": "import_tax"}, "import_tax"),
])
def test_amendment_copies_current_evidence_to_the_new_payment_rule(action, edits, new_key):
    from overseas_costing.services.logistics_settlement.payment_adoption import amend_payment_claim

    ctx = payment_setup()
    doc = payment_document()
    set_documents(ctx, [doc])
    result = confirm_preview(ctx, make_preview(ctx, [selection("40")], attachment_selections=[
        attachment_choice(doc["id"], "customs_clearance_fee")
    ]))
    claim = result["claims"][0]
    old_evidence = ctx[1].rows("evidence")[0]
    old_rule = ctx[1].get("rule", old_evidence["fee_rule"])
    amend_payment_claim(ctx[0], ctx[1], ctx[2]["name"], ctx[3]["name"], claim["id"], claim["revision"],
                        action, "财务更正", edits, "user")
    active_rule = next(row for row in ctx[1].rows("rule") if row.get("logical_fee_key") == new_key
                       and row.get("is_active") not in (0, False, "0"))
    current_evidence = [row for row in ctx[1].rows("evidence") if row["fee_rule"] == active_rule["name"]]
    assert len(current_evidence) == 1 and current_evidence[0]["attachment"] == old_evidence["attachment"]
    assert ctx[1].get("rule", old_rule["name"])["is_active"] == 0
    assert ctx[1].get("evidence", old_evidence["name"])["fee_rule"] == old_rule["name"]


def test_cross_batch_and_historical_guards_run_before_any_evidence_write():
    ctx = payment_setup()
    doc = payment_document()
    set_documents(ctx, [doc])
    preview = make_preview(ctx, [selection("40")], attachment_selections=[attachment_choice(doc["id"], "customs_clearance_fee")])
    ctx[1].put("version", ctx[3]["name"], {"status": "Confirmed"})
    with pytest.raises(ValueError, match="不可修改"):
        confirm_preview(ctx, preview)
    assert not ctx[1].rows("attachment") and not ctx[1].rows("evidence")


def test_pending_preview_from_old_policy_cannot_bypass_attachment_binding():
    ctx = payment_setup()
    preview = make_preview(ctx, [selection("40")])
    private = ctx[0].get("payment_preview", preview["preview_id"])
    private.pop("policy")
    ctx[0].put("payment_preview", {key: private[key] for key in (
        "id", "batch", "version", "logistics_id", "source_id", "status", "revision", "expires_at"
    )} | {"data": dumps(private)})
    with pytest.raises(ValueError, match="策略"):
        confirm_preview(ctx, preview)
    assert not ctx[0].find("payment_claim")


def test_attachment_selection_rejects_client_source_credentials_and_unknown_documents():
    ctx = payment_setup()
    set_documents(ctx, [payment_document()])
    for choice in (
        {"document_id": "missing", "selected": True, "logical_fee_keys": ["customs_clearance_fee"]},
        {"document_id": "payment-document", "selected": True, "logical_fee_keys": ["customs_clearance_fee"],
         "file_url": "/private/files/forged.pdf"},
    ):
        with pytest.raises(ValueError, match="附件"):
            make_preview(ctx, [selection("40")], attachment_selections=[choice])
