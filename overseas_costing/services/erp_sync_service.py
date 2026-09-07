"""Idempotent ERP synchronization identities, ledger states and reconciliation."""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal, InvalidOperation


ALLOWED_TRANSITIONS = {
    "PENDING": {"RUNNING", "SUPERSEDED"},
    "RUNNING": {"SUCCESS", "FAILED", "UNCERTAIN", "MANUAL_REQUIRED", "SUPERSEDED"},
    "FAILED": {"RUNNING", "SUPERSEDED"},
    "UNCERTAIN": {"SUCCESS", "FAILED", "MANUAL_REQUIRED", "SUPERSEDED"},
    "SUCCESS": set(),
    "MANUAL_REQUIRED": set(),
    "SUPERSEDED": set(),
}

SECRET_KEYS = frozenset({"authorization", "password", "token", "api_key", "api_secret"})


def _canonical(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _hash(value) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def payload_hash(payload: dict) -> str:
    return _hash(payload or {})


def purchase_business_key(*, batch: str, site: str, group, version: str = "") -> str:
    """Return a purchase identity that intentionally excludes the cost version."""

    del version
    group_identity = group if isinstance(group, str) else _canonical(group)
    identity = "\x1f".join((str(batch or "").strip(), str(site or "").strip(), str(group_identity or "").strip()))
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


def build_request_id(
    *, operation: str, site_code: str, business_key: str, cost_result_hash: str, intent_key: str
) -> str:
    return _hash(
        {
            "operation": str(operation or "").upper(),
            "site_code": str(site_code or "").strip(),
            "business_key": str(business_key or "").strip(),
            "cost_result_hash": str(cost_result_hash or "").strip(),
            "intent_key": str(intent_key or "").strip(),
        }
    )


def redact_secrets(value):
    if isinstance(value, dict):
        return {
            str(key): ("[REDACTED]" if str(key).casefold() in SECRET_KEYS else redact_secrets(item))
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_secrets(item) for item in value]
    return value


def prepare_sync_request(
    existing_requests: list[dict],
    *,
    operation: str,
    batch: str,
    version: str,
    cost_result_hash: str,
    site_code: str,
    business_key: str,
    payload: dict,
    intent_key: str,
) -> dict:
    operation = str(operation or "").upper()
    digest = payload_hash(payload)
    request_id = build_request_id(
        operation=operation,
        site_code=site_code,
        business_key=business_key,
        cost_result_hash=cost_result_hash,
        intent_key=intent_key,
    )
    for saved in existing_requests or []:
        if str(saved.get("request_id") or "") == request_id:
            return {"action": "REPLAY", "request": saved}
    for saved in existing_requests or []:
        if (
            str(saved.get("operation") or "").upper() == operation
            and str(saved.get("site_code") or "") == str(site_code or "")
            and str(saved.get("business_key") or "") == str(business_key or "")
            and str(saved.get("payload_hash") or "") == digest
            and str(saved.get("status") or "").upper() == "SUCCESS"
        ):
            return {"action": "NOOP", "request": saved}
    request = {
        "request_id": request_id,
        "operation": operation,
        "batch": str(batch or ""),
        "version": str(version or ""),
        "cost_result_hash": str(cost_result_hash or ""),
        "site_code": str(site_code or ""),
        "business_key": str(business_key or ""),
        "payload_hash": digest,
        "status": "PENDING",
        "attempt_count": 0,
        "safe_payload": redact_secrets(payload or {}),
        "safe_response": {},
    }
    return {"action": "EXECUTE", "request": request}


def transition_request(request: dict, target_status: str, **changes) -> dict:
    current = str(request.get("status") or "PENDING").upper()
    target = str(target_status or "").upper()
    if target not in ALLOWED_TRANSITIONS.get(current, set()):
        raise ValueError(f"INVALID_SYNC_TRANSITION:{current}->{target}")
    updated = {**request, **changes, "status": target}
    if target == "RUNNING":
        updated["attempt_count"] = int(request.get("attempt_count") or 0) + 1
    return updated


def apply_sync_response(request: dict, response: dict, *, latest_cost_result_hash: str) -> dict:
    if str(request.get("cost_result_hash") or "") != str(latest_cost_result_hash or ""):
        return {
            "applied": False,
            "request": transition_request(request, "SUPERSEDED", safe_response=redact_secrets(response or {})),
        }
    status = str((response or {}).get("status") or "FAILED").upper()
    if status in {"CREATED", "EXISTS", "UPDATED", "NOOP"}:
        status = "SUCCESS"
    if status not in {"SUCCESS", "FAILED", "UNCERTAIN", "MANUAL_REQUIRED"}:
        status = "FAILED"
    return {
        "applied": True,
        "request": transition_request(request, status, safe_response=redact_secrets(response or {})),
    }


def plan_uncertain_retry(request: dict, lookup_result: dict) -> dict:
    if str(request.get("status") or "").upper() != "UNCERTAIN":
        raise ValueError("REQUEST_IS_NOT_UNCERTAIN")
    if lookup_result.get("ambiguous"):
        return {"action": "MANUAL_REQUIRED", "code": "AMBIGUOUS_REMOTE_BUSINESS_KEY"}
    if lookup_result.get("found"):
        return {
            "action": "RECONCILE_SUCCESS",
            "remote_document": str(lookup_result.get("name") or ""),
        }
    return {"action": "RETRY", "request_id": str(request.get("request_id") or "")}


def _decimal(value) -> Decimal:
    try:
        return Decimal(str(value or 0))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal("0")


def _item_quantities(items: list[dict]) -> dict[str, Decimal]:
    return {
        str(row.get("stable_line_key") or ""): _decimal(
            row.get("effective_shipped_qty") or row.get("actual_shipped_qty") or row.get("quantity")
        )
        for row in items or []
        if row.get("stable_line_key")
    }


def verify_legacy_document_candidates(candidates: list[dict], expected_items: list[dict]) -> dict:
    """Fail closed unless exactly one historical document has matching row identities and quantities."""

    if not candidates:
        return {"status": "CREATE_CANDIDATE"}
    if len(candidates) != 1:
        return {"status": "MANUAL_REQUIRED", "code": "AMBIGUOUS_LEGACY_DOCUMENTS"}
    candidate = candidates[0]
    if _item_quantities(candidate.get("items") or []) != _item_quantities(expected_items):
        return {"status": "MANUAL_REQUIRED", "code": "LEGACY_LINE_MISMATCH"}
    return {"status": "VERIFIED", "remote_document": str(candidate.get("name") or "")}
