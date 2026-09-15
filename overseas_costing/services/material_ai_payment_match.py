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
    """Confirm an exact current freight candidate inside the caller transaction."""

    if not freight_mode:
        raise ValueError("当前模式不支持付款明细匹配")
    version_name = str((reference or {}).get("version") or "")
    clean = _validate_reference(reference, version_name)
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
    if str(candidate.get("status") or "").lower() == "confirmed":
        return clean
    confirmed = {
        **candidate,
        "status": "confirmed",
        "confirmed_by": str(actor or ""),
        "confirmed_for": "material_ai_preview",
    }
    # Keep the matcher revision stable: it authenticates the source pair and
    # snapshots, while status is rechecked under the same transaction.
    store.put(
        "freight_candidate",
        {
            "id": confirmed["id"],
            "logistics_id": confirmed["logistics_id"],
            "expense_id": confirmed["expense_id"],
            "status": confirmed["status"],
            "data": dumps(confirmed),
        },
    )
    store.audit(
        batch_name,
        "material_ai_payment_match_confirmed",
        actor,
        candidate_id=clean["candidate_id"],
        candidate_revision=clean["revision"],
        version=version_name,
    )
    return clean


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

    _logistics, catalog = _catalog(store, ledger, batch_name, version_name)
    rows = [row for row in catalog if row.get("source_id") == source.get("id")]
    result = []
    for row in rows:
        if not (row.get("goods") or str(row.get("text") or "").strip()):
            continue
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
    return result
