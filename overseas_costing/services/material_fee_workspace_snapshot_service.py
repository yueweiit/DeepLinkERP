"""Persistent, last-known-good read snapshots for the material/fee workspace."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from typing import Any, Callable
import uuid

from overseas_costing.services.logistics_settlement.model import digest, dumps


SCHEMA_VERSION = 1
RUN_LEASE = timedelta(minutes=5)
DEFAULT_PAGE = 1
DEFAULT_PAGE_LENGTH = 200
MAX_PAGE_LENGTH = 500

_DROP = object()
_BINARY_KEYS = {
    "base64",
    "binary",
    "blob",
    "bytes",
    "file_content",
    "image",
    "image_url",
    "raw_attachment",
    "raw_payload",
    "thumbnail",
    "thumbnail_url",
}
_SENSITIVE_KEYS = {
    "edit_token",
    "lease_token",
    "preview_token",
    "run_token",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _datetime(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=parsed.tzinfo or timezone.utc).astimezone(timezone.utc)


def _page(value: Any, default: int, maximum: int | None = None) -> int:
    try:
        normalized = int(value)
    except (TypeError, ValueError):
        normalized = default
    normalized = max(1, normalized)
    return min(normalized, maximum) if maximum else normalized


def _context(batch_name: str, version_name: str | None) -> tuple[str, str]:
    batch = str(batch_name or "").strip()
    version = str(version_name or "").strip()
    from overseas_costing.services import batch_service

    if not getattr(getattr(batch_service, "frappe", None), "db", None):
        if batch and version:
            return batch, version
        raise ValueError("当前未连接成本数据库。")
    resolved_batch = batch_service._resolve_batch_name(batch)
    if not resolved_batch:
        raise ValueError(f"未找到批次：{batch_name}")
    resolved_version = version or batch_service._resolve_version_name(resolved_batch, None)
    if not resolved_version:
        raise ValueError("当前批次没有可用成本版本。")
    version_batch = batch_service.frappe.db.get_value(
        "Overseas Cost Version", resolved_version, "batch"
    )
    if str(version_batch or "") != str(resolved_batch):
        raise ValueError("版本不属于当前批次。")
    return str(resolved_batch), str(resolved_version)


def _state_id(batch_name: str, version_name: str, page: int, page_length: int) -> str:
    return digest(
        "material_fee_workspace_snapshot_v1",
        batch_name,
        version_name,
        page,
        page_length,
    )


def _default_store():
    from overseas_costing.services.logistics_settlement.store import Store

    return Store.frappe()


def _put_state(store, state_id: str, payload: dict, now: str) -> None:
    store.put("state", {"id": state_id, "updated_at": now, "data": dumps(payload)})


def _commit(store) -> None:
    commit = getattr(store, "commit", None)
    if callable(commit):
        commit()


def _sanitized(value: Any, *, key: str = ""):
    if key.lower() in _BINARY_KEYS or key.lower() in _SENSITIVE_KEYS:
        return _DROP
    if isinstance(value, (bytes, bytearray, memoryview)):
        return _DROP
    if isinstance(value, str) and value.lstrip().lower().startswith("data:image/"):
        return _DROP
    if isinstance(value, dict):
        cleaned = {}
        for child_key, child_value in value.items():
            item = _sanitized(child_value, key=str(child_key))
            if item is not _DROP:
                cleaned[child_key] = item
        return cleaned
    if isinstance(value, (list, tuple)):
        cleaned = []
        for child in value:
            item = _sanitized(child)
            if item is not _DROP:
                cleaned.append(item)
        return cleaned
    return value


def sanitize_snapshot(value: dict) -> dict:
    cleaned = _sanitized(value)
    return cleaned if isinstance(cleaned, dict) else {}


def _validate_snapshot_data(data: dict) -> dict:
    for section in ("detail", "materials", "fees", "preview", "settlement"):
        if section not in data or not isinstance(data.get(section), dict):
            raise ValueError(f"快照缺少有效 {section} 数据。")
        if data[section].get("ok") is False and section != "settlement":
            raise ValueError(data[section].get("message") or f"快照 {section} 数据读取失败。")
    return data


def _settlement_strip(data: dict) -> dict:
    data = data or {}
    source_fields = {
        "id",
        "instance",
        "approval_no",
        "title",
        "amount",
        "currency",
        "snapshot",
        "source_updated_at",
        "open_url",
    }
    result = {
        key: deepcopy(data.get(key))
        for key in (
            "ok",
            "mapped",
            "freight_mode",
            "historical",
            "viewed_version",
            "message",
            "payment_blocking_reasons",
        )
        if key in data
    }
    for key in ("logistics", "expense"):
        if isinstance(data.get(key), dict):
            result[key] = {field: data[key].get(field) for field in source_fields if field in data[key]}
    if isinstance(data.get("binding"), dict):
        result["binding"] = {
            key: data["binding"].get(key)
            for key in ("id", "revision", "application_status", "version", "source_snapshot")
            if key in data["binding"]
        }
    if isinstance(data.get("packing"), dict):
        result["packing"] = {"message": data["packing"].get("message")}
    if isinstance(data.get("freight"), dict):
        result["freight"] = {
            "claims": deepcopy(data["freight"].get("claims") or []),
            "issues": deepcopy(data["freight"].get("issues") or []),
        }
    if isinstance(data.get("payment_claims"), list):
        result["payment_claims"] = deepcopy(data["payment_claims"])
    return sanitize_snapshot(result)


def build_workspace_snapshot(
    batch_name: str,
    version_name: str,
    page: int,
    page_length: int,
) -> dict:
    """Build the page projection entirely from local persisted sources."""

    from overseas_costing.services import (
        batch_service,
        cost_preview_service,
        fee_service,
        material_input_service,
    )

    try:
        from overseas_costing.services.logistics_settlement import runtime

        settlement = runtime.batch_status(batch_name, version_name)
    except Exception as error:  # Main workspace remains available when its optional strip fails.
        settlement = {"ok": False, "viewed_version": version_name, "message": str(error)}
    return sanitize_snapshot(
        {
            "detail": batch_service.get_batch_detail(batch_name, version_name),
            "materials": material_input_service.get_material_grid(
                batch_name,
                version_name,
                page=page,
                page_length=page_length,
            ),
            "fees": fee_service.get_fee_worklist(batch_name, version_name),
            "preview": cost_preview_service.preview_comprehensive_cost(batch_name, version_name),
            "settlement": _settlement_strip(settlement),
        }
    )


def _table_revision(frappe, doctype: str, filters: dict) -> dict:
    clauses = []
    values = []
    for field, value in filters.items():
        clauses.append(f"`{field}`=%s")
        values.append(value)
    where = " AND ".join(clauses) or "1=1"
    rows = frappe.db.sql(
        f"SELECT COUNT(*) AS row_count, MAX(modified) AS last_modified "
        f"FROM `tab{doctype}` WHERE {where}",
        tuple(values),
        as_dict=True,
    )
    row = rows[0] if rows else {}
    return {
        "doctype": doctype,
        "count": int(row.get("row_count") or 0),
        "modified": str(row.get("last_modified") or ""),
    }


def _settlement_revision(batch_name: str, version_name: str) -> dict:
    try:
        from overseas_costing.services.logistics_settlement import runtime

        if not runtime.installed():
            return {}
        store = runtime.store()
        mappings = store.find("batch_map", batch=batch_name, limit=1)
        source = store.get("source", mappings[0]["source_id"]) if mappings else None
        source_id = str((source or {}).get("id") or "")
        bindings = store.find("binding", logistics_id=source_id, limit=1) if source_id else []
        binding = bindings[0] if bindings else {}
        return {
            "source": {
                key: (source or {}).get(key)
                for key in ("id", "snapshot", "updated_at", "approved", "invalid")
            },
            "binding": {
                key: binding.get(key)
                for key in ("id", "revision", "application_status", "last_application", "source_snapshot")
            },
            "freight_applications": [
                {key: row.get(key) for key in ("id", "revision", "status")}
                for row in store.find("freight_application", batch=batch_name, version=version_name)
            ],
            "freight_claims": [
                {
                    key: row.get(key)
                    for key in (
                        "id",
                        "source_id",
                        "line_id",
                        "charge_key",
                        "amount",
                        "applied_amount",
                        "currency",
                        "status",
                        "manual_corrected",
                    )
                }
                for row in store.find("freight_claim", batch=batch_name)
            ],
            "payment_claims": [
                {key: row.get(key) for key in ("id", "revision", "status", "amount", "currency")}
                for row in store.find("payment_claim", batch=batch_name, version=version_name)
            ],
            "payment_applications": [
                {key: row.get(key) for key in ("id", "revision", "status")}
                for row in store.find("payment_application", batch=batch_name, version=version_name)
            ],
            "packing_reviews": [
                {key: row.get(key) for key in ("id", "status")}
                for row in store.find("packing_review", batch=batch_name, version=version_name)
            ],
            "document_sync": [
                {key: row.get(key) for key in ("id", "status", "updated_at")}
                for row in store.find("document_sync", batch=batch_name)
            ],
        }
    except Exception:
        return {"unavailable": True}


def build_input_fingerprint(batch_name: str, version_name: str) -> str:
    """Cheap local revision fingerprint; never reads DingTalk or attachment bytes."""

    import frappe

    batch = frappe.db.get_value(
        "Overseas Cost Batch",
        batch_name,
        ["name", "modified", "current_version", "status", "confirm_status", "writeback_status"],
        as_dict=True,
    ) or {}
    version = frappe.db.get_value(
        "Overseas Cost Version",
        version_name,
        ["name", "modified", "status", "is_current", "calculated_at"],
        as_dict=True,
    ) or {}
    revisions = [
        _table_revision(frappe, "Overseas Cost Item", {"batch": batch_name, "version": version_name}),
        _table_revision(frappe, "Overseas Cost Allocation Rule", {"batch": batch_name, "version": version_name}),
        _table_revision(frappe, "Overseas Cost Fee Evidence", {"batch": batch_name, "version": version_name}),
        _table_revision(frappe, "Overseas Cost Fee SKU Component", {"batch": batch_name, "version": version_name}),
        _table_revision(frappe, "Overseas Cost Attachment", {"batch": batch_name}),
    ]
    return digest(
        "material_fee_workspace_input_v1",
        dict(batch),
        dict(version),
        revisions,
        _settlement_revision(batch_name, version_name),
    )


def _cache_meta(state: dict, *, served_from_cache: bool) -> dict:
    return {
        "source": "server_local_snapshot",
        "schema_version": int(state.get("schema_version") or SCHEMA_VERSION),
        "status": "refreshing" if state.get("run_status") == "running" else str(state.get("status") or "missing"),
        "served_from_cache": bool(served_from_cache),
        "input_fingerprint": str(state.get("input_fingerprint") or ""),
        "generated_at": str(state.get("generated_at") or ""),
        "last_checked_at": str(state.get("last_checked_at") or ""),
        "last_success_at": str(state.get("last_success_at") or ""),
        "refresh_error": str(state.get("refresh_error") or ""),
    }


def _public(state: dict, *, served_from_cache: bool) -> dict:
    return {
        "ok": True,
        "batch_name": str(state.get("batch_name") or ""),
        "version_name": str(state.get("version_name") or ""),
        "data": deepcopy(state.get("data") or {}),
        "cache": _cache_meta(state, served_from_cache=served_from_cache),
    }


def _begin_refresh(store, state_id: str, context: dict, now: str) -> tuple[str, dict] | None:
    token = uuid.uuid4().hex
    with store.atomic():
        # The permanent lock row also serializes the first insert for a new snapshot key.
        store.get("state", "job_lock", lock=True)
        previous = store.get("state", state_id, lock=True) or {}
        started_at = _datetime(previous.get("started_at"))
        current_at = _datetime(now)
        if (
            previous.get("run_status") == "running"
            and started_at
            and current_at
            and current_at - started_at <= RUN_LEASE
        ):
            return None
        running = {
            **{key: value for key, value in previous.items() if key not in {"id", "updated_at"}},
            **context,
            "schema_version": SCHEMA_VERSION,
            "run_status": "running",
            "run_token": token,
            "started_at": now,
            "last_checked_at": now,
            "refresh_error": "",
        }
        _put_state(store, state_id, running, now)
    _commit(store)
    return token, previous


def refresh_snapshot(
    batch_name: str,
    version_name: str | None = None,
    *,
    page: Any = DEFAULT_PAGE,
    page_length: Any = DEFAULT_PAGE_LENGTH,
    store=None,
    fingerprint_loader: Callable[[str, str], str] | None = None,
    snapshot_builder: Callable[[str, str, int, int], dict] | None = None,
    now: str | None = None,
) -> dict:
    batch, version = _context(batch_name, version_name)
    normalized_page = _page(page, DEFAULT_PAGE)
    normalized_length = _page(page_length, DEFAULT_PAGE_LENGTH, MAX_PAGE_LENGTH)
    state_id = _state_id(batch, version, normalized_page, normalized_length)
    store = store or _default_store()
    checked_at = now or _now()
    context = {
        "batch_name": batch,
        "version_name": version,
        "page": normalized_page,
        "page_length": normalized_length,
    }
    started = _begin_refresh(store, state_id, context, checked_at)
    if started is None:
        active = store.get("state", state_id) or context
        if active.get("data"):
            return _public(active, served_from_cache=True)
        raise RuntimeError("资料页快照正在生成，请稍后重试。")
    token, previous = started
    fingerprint_loader = fingerprint_loader or build_input_fingerprint
    snapshot_builder = snapshot_builder or build_workspace_snapshot
    try:
        fingerprint = str(fingerprint_loader(batch, version) or "")
        data = _validate_snapshot_data(
            sanitize_snapshot(snapshot_builder(batch, version, normalized_page, normalized_length))
        )
        ready = {
            **context,
            "schema_version": SCHEMA_VERSION,
            "status": "ready",
            "run_status": "idle",
            "run_token": token,
            "input_fingerprint": fingerprint,
            "generated_at": checked_at,
            "last_checked_at": checked_at,
            "last_success_at": checked_at,
            "refresh_error": "",
            "data": data,
        }
        with store.atomic():
            current = store.get("state", state_id, lock=True) or {}
            if current.get("run_token") != token:
                return _public(current, served_from_cache=True)
            _put_state(store, state_id, ready, checked_at)
        _commit(store)
        return _public(ready, served_from_cache=False)
    except Exception as error:
        failed = {
            **{key: value for key, value in previous.items() if key not in {"id", "updated_at"}},
            **context,
            "schema_version": SCHEMA_VERSION,
            "status": "stale" if previous.get("data") else "error",
            "run_status": "idle",
            "run_token": token,
            "last_checked_at": checked_at,
            "refresh_error": str(error),
        }
        with store.atomic():
            current = store.get("state", state_id, lock=True) or {}
            if current.get("run_token") == token:
                _put_state(store, state_id, failed, checked_at)
        _commit(store)
        if previous.get("data"):
            return _public(failed, served_from_cache=True)
        raise


def get_snapshot(
    batch_name: str,
    version_name: str | None = None,
    *,
    page: Any = DEFAULT_PAGE,
    page_length: Any = DEFAULT_PAGE_LENGTH,
    store=None,
    fingerprint_loader: Callable[[str, str], str] | None = None,
    snapshot_builder: Callable[[str, str, int, int], dict] | None = None,
    now: str | None = None,
) -> dict:
    batch, version = _context(batch_name, version_name)
    normalized_page = _page(page, DEFAULT_PAGE)
    normalized_length = _page(page_length, DEFAULT_PAGE_LENGTH, MAX_PAGE_LENGTH)
    store = store or _default_store()
    state = store.get("state", _state_id(batch, version, normalized_page, normalized_length)) or {}
    if state.get("data") and int(state.get("schema_version") or 0) == SCHEMA_VERSION:
        return _public(state, served_from_cache=True)
    return refresh_snapshot(
        batch,
        version,
        page=normalized_page,
        page_length=normalized_length,
        store=store,
        fingerprint_loader=fingerprint_loader,
        snapshot_builder=snapshot_builder,
        now=now,
    )


def check_freshness(
    batch_name: str,
    version_name: str | None = None,
    *,
    snapshot_fingerprint: str = "",
    page: Any = DEFAULT_PAGE,
    page_length: Any = DEFAULT_PAGE_LENGTH,
    store=None,
    fingerprint_loader: Callable[[str, str], str] | None = None,
    now: str | None = None,
) -> dict:
    batch, version = _context(batch_name, version_name)
    normalized_page = _page(page, DEFAULT_PAGE)
    normalized_length = _page(page_length, DEFAULT_PAGE_LENGTH, MAX_PAGE_LENGTH)
    state_id = _state_id(batch, version, normalized_page, normalized_length)
    store = store or _default_store()
    checked_at = now or _now()
    current_fingerprint = str((fingerprint_loader or build_input_fingerprint)(batch, version) or "")
    state = store.get("state", state_id) or {}
    client_fingerprint = str(snapshot_fingerprint or state.get("input_fingerprint") or "")
    unchanged = bool(client_fingerprint) and client_fingerprint == current_fingerprint
    if state:
        persisted_matches = str(state.get("input_fingerprint") or "") == current_fingerprint
        updated = {
            **{key: value for key, value in state.items() if key not in {"id", "updated_at"}},
            "last_checked_at": checked_at,
            "status": state.get("status") if persisted_matches else "stale",
        }
        _put_state(store, state_id, updated, checked_at)
        _commit(store)
    return {
        "ok": True,
        "batch_name": batch,
        "version_name": version,
        "unchanged": unchanged,
        "snapshot_fingerprint": client_fingerprint,
        "current_fingerprint": current_fingerprint,
        "checked_at": checked_at,
    }
