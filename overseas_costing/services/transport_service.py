"""运输方式继承；保留明确来源证据，避免将海运当作缺失值。"""

from __future__ import annotations

import json

from overseas_costing.utils.field_mapper import normalize_transport_mode


def resolve_item_transport_mode(source_mode: object, batch_transport_mode: object) -> str:
    return normalize_transport_mode(source_mode) or normalize_transport_mode(batch_transport_mode) or ""


def prepare_item_transport(values: dict, batch_transport_mode: object) -> dict:
    """Return item fields with explicit-source versus batch-default provenance."""

    result = dict(values or {})
    source_mode = normalize_transport_mode(result.get("transport_mode")) or ""
    batch_mode = normalize_transport_mode(batch_transport_mode) or ""
    extra = result.get("extra_json")
    if not isinstance(extra, dict):
        try:
            extra = json.loads(str(extra or "{}"))
        except (TypeError, ValueError):
            extra = {}
    extra = dict(extra) if isinstance(extra, dict) else {}
    extra["transport_provenance"] = {
        "mode": "EXPLICIT_SOURCE" if source_mode else "BATCH_DEFAULT",
        "source_mode": source_mode,
        "batch_mode": batch_mode,
    }
    result["transport_mode"] = resolve_item_transport_mode(source_mode, batch_mode)
    result["extra_json"] = json.dumps(extra, ensure_ascii=False, default=str)
    return result
