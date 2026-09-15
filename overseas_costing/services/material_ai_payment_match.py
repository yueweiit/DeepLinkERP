"""Server-owned payment-match selection for material AI previews.

The production freight-line matcher remains the only authority that decides
whether a payment process belongs to a shipment.  This module merely admits a
single strong, current candidate into the AI preview and confirms that exact
candidate inside the caller's transaction.
"""
from __future__ import annotations

from copy import deepcopy
from decimal import Decimal, InvalidOperation

from .logistics_settlement.model import digest, dumps


POLICY = "material-ai-payment-match-1"
STRONG_METHODS = frozenset({"manual", "explicit", "identifier"})
AI_CONFIDENCE_MINIMUM = Decimal("0.90")
REFERENCE_KEYS = frozenset({"candidate_id", "revision", "version"})
RELATION_KEYS = frozenset({
    "policy", "candidate_id", "candidate_revision", "version",
    "logistics_id", "expense_id", "logistics_snapshot", "expense_snapshot",
    "confirmed_by", "confirmed_at",
})


def _confidence(value) -> Decimal | None:
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return number if number.is_finite() else None


def _strong(candidate: dict) -> bool:
    if str(candidate.get("status") or "").lower() not in {"pending", "confirmed"}:
        return False
    if candidate.get("issues"):
        return False
    method = str(candidate.get("method") or "").lower()
    if method in STRONG_METHODS:
        return True
    return method == "deepseek" and (_confidence(candidate.get("confidence")) or Decimal("-1")) >= AI_CONFIDENCE_MINIMUM


def _current_logistics(store, ledger, batch_name: str, version_name: str, *, lock=False):
    batch = ledger.get("batch", batch_name, lock=lock) or {}
    version = ledger.get("version", version_name, lock=lock) or {}
    if batch.get("current_version") != version_name or version.get("batch") != batch_name:
        raise ValueError("当前成本版本已变化，请刷新")
    mappings = store.find("batch_map", batch=batch_name)
    if len(mappings) != 1:
        return None
    logistics_id = str(mappings[0].get("source_id") or "")
    # A logistics source is allowed to own one and only one batch.  This also
    # prevents a browser-provided candidate from being replayed across tickets.
    owned = store.find("batch_map", source_id=logistics_id)
    if len(owned) != 1 or owned[0].get("batch") != batch_name:
        return None
    logistics = store.get("source", logistics_id, lock=lock) or {}
    if logistics.get("kind") != "logistics" or logistics.get("invalid"):
        return None
    return logistics


def _current_candidates(store, ledger, batch_name: str, version_name: str, *, lock=False):
    logistics = _current_logistics(store, ledger, batch_name, version_name, lock=lock)
    if not logistics:
        return []
    from .logistics_settlement.freight_matching import candidates

    rows = []
    for raw in candidates(store, logistics["id"]):
        candidate = store.get("freight_candidate", raw["id"], lock=lock) if lock else raw
        if candidate and _strong(candidate):
            rows.append(candidate)
    return rows


def select_preview_candidate(store, ledger, batch_name: str, version_name: str, *, freight_mode: bool):
    """Return the only browser-safe match reference, never source values."""

    if not freight_mode:
        # The legacy whole-source matcher has its own binding confirmation
        # workflow.  Pending freight candidate IDs must never cross into it.
        return None
    rows = _current_candidates(store, ledger, batch_name, version_name)
    if len(rows) != 1:
        return None
    candidate = rows[0]
    return {
        "candidate_id": str(candidate["id"]),
        "revision": str(candidate["revision"]),
        "version": str(version_name),
    }


def _validate_reference(reference: dict, version_name: str) -> dict:
    if not isinstance(reference, dict) or set(reference) != REFERENCE_KEYS:
        raise ValueError("付款匹配凭证格式不正确")
    clean = {key: str(reference.get(key) or "") for key in REFERENCE_KEYS}
    if not all(clean.values()) or clean["version"] != str(version_name):
        raise ValueError("付款匹配凭证已变化，请刷新")
    return clean


def confirm_preview_candidate(
    store,
    ledger,
    batch_name: str,
    reference: dict,
    actor: str,
    *,
    freight_mode: bool,
):
    """Revalidate an exact candidate and return a server-owned relation."""

    if not freight_mode:
        raise ValueError("当前模式不支持付款明细匹配")
    version_name = str((reference or {}).get("version") or "")
    clean = _validate_reference(reference, version_name)
    # Serialize candidate arbitration with freight_matching.save_candidate.
    # The caller owns the surrounding transaction, so this row lock remains
    # held through the unique-candidate check and the downstream AI writes.
    store.get("state", "match_lock", lock=True)
    from .logistics_settlement.payment_adoption import _resolve_context

    _batch, _version, candidate, _source, _logistics, _lines = _resolve_context(
        store,
        ledger,
        batch_name,
        version_name,
        clean["candidate_id"],
        clean["revision"],
        lock=True,
    )
    # Re-run the unique/strong arbitration under locks.  The user cannot turn
    # a candidate ID into authority, and a newly appeared peer blocks adoption.
    current = _current_candidates(
        store, ledger, batch_name, version_name, lock=True
    )
    if len(current) != 1 or current[0].get("id") != clean["candidate_id"]:
        raise ValueError("付款匹配候选已变化或存在冲突，请刷新")
    from .logistics_settlement.jobs import utcnow
    return {
        "policy": POLICY,
        "candidate_id": str(candidate["id"]),
        "candidate_revision": str(candidate["revision"]),
        "version": version_name,
        "logistics_id": str(candidate["logistics_id"]),
        "expense_id": str(candidate["expense_id"]),
        "logistics_snapshot": str(candidate["logistics_snapshot"]),
        "expense_snapshot": str(candidate["expense_snapshot"]),
        "confirmed_by": str(actor or ""),
        "confirmed_at": utcnow(),
    }


def _validate_relation(relation: dict, version_name: str, actor: str) -> dict:
    if not isinstance(relation, dict) or set(relation) != RELATION_KEYS:
        raise ValueError("付款匹配关系格式不正确")
    clean = {key: str(relation.get(key) or "") for key in RELATION_KEYS}
    if (not all(clean.values()) or clean["policy"] != POLICY
            or clean["version"] != str(version_name)
            or clean["confirmed_by"] != str(actor or "")):
        raise ValueError("付款匹配关系已变化，请刷新")
    return clean


def persist_relation(store, ledger, batch_name: str, version_name: str,
                     relation: dict, actor: str) -> dict:
    """Persist a version-scoped relation without freezing matcher state."""

    clean = _validate_relation(relation, version_name, actor)
    store.get("state", "match_lock", lock=True)
    from .logistics_settlement.payment_adoption import _resolve_context
    _batch, version, candidate, _source, _logistics, _lines = _resolve_context(
        store, ledger, batch_name, version_name,
        clean["candidate_id"], clean["candidate_revision"], lock=True,
    )
    current = _current_candidates(store, ledger, batch_name, version_name, lock=True)
    if len(current) != 1 or current[0].get("id") != clean["candidate_id"]:
        raise ValueError("付款匹配候选已变化或存在冲突，请刷新")
    expected = {
        "logistics_id": candidate.get("logistics_id"),
        "expense_id": candidate.get("expense_id"),
        "logistics_snapshot": candidate.get("logistics_snapshot"),
        "expense_snapshot": candidate.get("expense_snapshot"),
    }
    if any(clean[key] != str(value or "") for key, value in expected.items()):
        raise ValueError("付款匹配来源快照已变化，请刷新")

    from .logistics_settlement.application import row_meta
    metadata = row_meta(version)
    prior = metadata.get("material_ai_payment_match") or {}
    identity_keys = RELATION_KEYS - {"confirmed_by", "confirmed_at"}
    if (isinstance(prior, dict) and set(prior) == RELATION_KEYS
            and all(str(prior.get(key) or "") == clean[key] for key in identity_keys)):
        return {key: str(prior.get(key) or "") for key in RELATION_KEYS}
    metadata["material_ai_payment_match"] = clean
    ledger.put("version", version_name, {"extra_json": dumps(metadata)})
    store.audit(
        batch_name,
        "material_ai_payment_match_confirmed",
        actor,
        candidate_id=clean["candidate_id"],
        candidate_revision=clean["candidate_revision"],
        version=version_name,
        logistics_id=clean["logistics_id"],
        expense_id=clean["expense_id"],
    )
    return deepcopy(clean)


def preview_sources(
    store,
    ledger,
    batch_name: str,
    version_name: str,
    reference: dict | None,
    *,
    freight_mode: bool,
):
    """Build shipment-scoped payment evidence without copying the matcher."""

    if not reference or not freight_mode:
        return []
    clean = _validate_reference(reference, version_name)
    selected = select_preview_candidate(
        store, ledger, batch_name, version_name, freight_mode=freight_mode
    )
    if selected != clean:
        return []
    candidate = store.get("freight_candidate", clean["candidate_id"]) or {}
    source = store.get("source", candidate.get("expense_id")) or {}
    if not source:
        return []
    from .logistics_settlement.packing_selection import _catalog
    from .logistics_settlement.freight_packing import text_goods

    _logistics, catalog = _catalog(store, ledger, batch_name, version_name)
    rows = [row for row in catalog if row.get("source_id") == source.get("id")]
    result = []
    covered_documents = {}
    for row in rows:
        if not (row.get("goods") or str(row.get("text") or "").strip()):
            continue
        row_evidence = row.get("evidence") or {}
        document_id = str(row.get("document_id") or row_evidence.get("document_id") or "")
        document_key = (document_id, str(row.get("sheet") or row_evidence.get("sheet") or ""))
        evidence_id = digest(POLICY, clean, row.get("id"), row.get("revision"))
        selected_source = {
            key: deepcopy(row.get(key))
            for key in (
                "id",
                "source_id",
                "source_kind",
                "source_label",
                "approval_no",
                "source_snapshot",
                "process_instance_id",
                "occurred_at",
                "actor_name",
                "evidence",
                "document_id",
                "sheet",
                "revision",
            )
            if row.get(key) not in (None, "")
        }
        result.append(
            {
                "source_id": evidence_id,
                "logical_source_id": evidence_id,
                "source_kind": str(row.get("source_kind") or "approval_form"),
                "source_label": str(row.get("source_label") or source.get("title") or "实际付款流程"),
                "file_name": str((row.get("evidence") or {}).get("file_name") or ""),
                "sheet_name": str(row.get("sheet") or ""),
                "approval_no": str(source.get("approval_no") or ""),
                "process_instance_id": str(source.get("instance") or ""),
                "approval_role": "payment",
                "approval_title": str(source.get("title") or "实际付款流程"),
                "source_updated_at": str(row.get("occurred_at") or source.get("source_updated_at") or ""),
                "actor_name": str(row.get("actor_name") or ""),
                "available": True,
                "excluded": False,
                "selected": True,
                "workflow_stage": "payment",
                "workflow_rank": 0,
                "payment_match_candidate": True,
                "payment_match_candidate_id": clean["candidate_id"],
                "payment_match_candidate_revision": clean["revision"],
                "payment_match_version": clean["version"],
                "selected_source": selected_source,
                "scoped_packing": True,
                "scoped_goods": deepcopy(row.get("goods") or []),
                "scoped_text": str(row.get("text") or ""),
                "form_fields": {},
                "approval_decisions": [],
                "can_download": False,
                "source_hash": evidence_id,
                "content_hash": evidence_id,
            }
        )
        if document_id:
            covered_documents[document_key] = len(result) - 1
    # A monthly payment attachment may have a valid, shipment-scoped freight
    # line even when its packing catalog row is not readable (for example an
    # older archive marked ``review`` instead of ``original``).  Reuse only the
    # exact line IDs authenticated by the matcher.  Never expose the payment
    # approval total or the other shipments in the monthly source.
    for line_id in candidate.get("line_ids") or []:
        line = store.get("freight_line", line_id) or {}
        if (line.get("source_id") != source.get("id")
                or line.get("snapshot") != source.get("snapshot")):
            continue
        evidence = deepcopy(line.get("evidence") or {})
        document_id = str(evidence.get("document_id") or "")
        sheet = str(evidence.get("sheet") or "")
        cargo_text = str(line.get("cargo_text") or "").strip()
        amount = line.get("amount")
        billing_weight = line.get("billing_weight")
        text_lines = []
        if line.get("label"):
            text_lines.append(f"费用项目: {line['label']}")
        if amount is not None and str(amount).strip():
            amount_label = "运费金额" if str(line.get("scope") or "") == "freight" else "费用金额"
            text_lines.append(
                f"{amount_label}: {amount} {str(line.get('currency') or source.get('currency') or '').strip()}".rstrip()
            )
        if line.get("waybill"):
            text_lines.append(f"运单号: {line['waybill']}")
        if line.get("approval_no"):
            text_lines.append(f"关联审批号: {line['approval_no']}")
        if billing_weight is not None and str(billing_weight).strip():
            text_lines.append(f"计费重量: {billing_weight} kg")
        if cargo_text:
            text_lines.append(f"发货明细: {cargo_text}")
        if not text_lines:
            continue
        if document_id and (document_id, sheet) in covered_documents:
            existing = result[covered_documents[(document_id, sheet)]]
            existing_text = str(existing.get("scoped_text") or "").strip()
            matched_text = "\n".join(text_lines)
            existing["scoped_text"] = "\n".join(filter(None, (existing_text, matched_text)))
            existing["content_hash"] = digest(
                existing.get("content_hash"), line_id, line.get("line_key"), matched_text
            )
            continue
        source_kind = (
            "approval_comment_attachment" if document_id and evidence.get("comment_id")
            else "approval_attachment" if document_id
            else "approval_comment" if evidence.get("comment_id")
            else "approval_form"
        )
        file_name = str(evidence.get("file_name") or "")
        source_label = file_name or str(source.get("title") or "实际付款流程")
        if sheet:
            source_label += f" · {sheet}"
        evidence_id = digest(POLICY, clean, "freight_line", line_id, line.get("line_key"), evidence)
        selected_source = {
            "id": evidence_id,
            "source_id": str(source.get("id") or ""),
            "source_kind": source_kind,
            "source_label": source_label,
            "approval_no": str(source.get("approval_no") or ""),
            "source_snapshot": str(source.get("snapshot") or ""),
            "process_instance_id": str(source.get("instance") or ""),
            "occurred_at": str(source.get("source_updated_at") or ""),
            "evidence": evidence,
            "revision": evidence_id,
        }
        if document_id:
            selected_source["document_id"] = document_id
        if sheet:
            selected_source["sheet"] = sheet
        scoped_text = "\n".join(text_lines)
        scoped_goods = text_goods(cargo_text, evidence) if cargo_text else []
        result.append(
            {
                "source_id": evidence_id,
                "logical_source_id": evidence_id,
                "source_kind": source_kind,
                "source_label": source_label,
                "file_name": file_name,
                "sheet_name": sheet,
                "approval_no": str(source.get("approval_no") or ""),
                "process_instance_id": str(source.get("instance") or ""),
                "approval_role": "payment",
                "approval_title": str(source.get("title") or "实际付款流程"),
                "source_updated_at": str(source.get("source_updated_at") or ""),
                "available": True,
                "excluded": False,
                "selected": True,
                "workflow_stage": "payment",
                "workflow_rank": 0,
                "payment_match_candidate": True,
                "payment_match_candidate_id": clean["candidate_id"],
                "payment_match_candidate_revision": clean["revision"],
                "payment_match_version": clean["version"],
                "selected_source": selected_source,
                "scoped_packing": True,
                "scoped_goods": scoped_goods,
                "scoped_text": scoped_text,
                "form_fields": {"物流报价": scoped_text} if source_kind == "approval_form" else {},
                "approval_decisions": [],
                "can_download": False,
                "source_hash": evidence_id,
                "content_hash": evidence_id,
            }
        )
    if not result:
        # A strong process-level relation is still useful provenance even when
        # a monthly statement cannot be narrowed to one shipment line.  Keep
        # the matched payment process visible, but publish no amount, document
        # contents, or AI input; downstream stage arbitration will safely fall
        # through to the logistics stage for every missing field.
        evidence_id = digest(POLICY, clean, "matched_process_without_safe_line")
        reason = "已匹配支付流程，但未识别出属于本票的可采用明细；已继续使用下一优先级阶段。"
        result.append(
            {
                "source_id": evidence_id,
                "logical_source_id": evidence_id,
                "source_kind": "approval_form",
                "source_label": str(source.get("title") or "实际付款流程"),
                "file_name": "",
                "sheet_name": "",
                "approval_no": str(source.get("approval_no") or ""),
                "process_instance_id": str(source.get("instance") or ""),
                "approval_role": "payment",
                "approval_title": str(source.get("title") or "实际付款流程"),
                "source_updated_at": str(source.get("source_updated_at") or ""),
                "available": True,
                "excluded": False,
                "selected": True,
                "workflow_stage": "payment",
                "workflow_rank": 0,
                "payment_match_candidate": True,
                "payment_match_candidate_id": clean["candidate_id"],
                "payment_match_candidate_revision": clean["revision"],
                "payment_match_version": clean["version"],
                "selected_source": {
                    "id": evidence_id,
                    "source_id": str(source.get("id") or ""),
                    "source_kind": "approval_form",
                    "source_label": str(source.get("title") or "实际付款流程"),
                    "approval_no": str(source.get("approval_no") or ""),
                    "source_snapshot": str(source.get("snapshot") or ""),
                    "process_instance_id": str(source.get("instance") or ""),
                    "occurred_at": str(source.get("source_updated_at") or ""),
                    "revision": evidence_id,
                },
                "scoped_packing": True,
                "scoped_goods": [],
                "scoped_text": "",
                "form_fields": {},
                "approval_decisions": [],
                "can_download": False,
                "read_status": "PARTIAL",
                "analysis_reason": reason,
                "error": reason,
                "ai_eligible": False,
                "source_hash": evidence_id,
                "content_hash": evidence_id,
            }
        )
    return result
