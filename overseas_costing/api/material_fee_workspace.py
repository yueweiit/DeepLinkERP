"""Read-only and cache-refresh APIs for the material/fee workspace snapshot."""

from __future__ import annotations

import frappe

from overseas_costing.services import material_fee_workspace_snapshot_service as snapshot_service
from overseas_costing.services.access_control import require_batch_permission


def _positive_int(value, default: int, maximum: int | None = None) -> int:
    try:
        result = int(value)
    except (TypeError, ValueError):
        result = default
    result = max(1, result)
    return min(result, maximum) if maximum else result


@frappe.whitelist()
def get_snapshot(batch_name, version_name=None, page=1, page_length=200):
    batch_name = require_batch_permission(batch_name, "read")
    return snapshot_service.get_snapshot(
        batch_name,
        str(version_name or "") or None,
        page=_positive_int(page, 1),
        page_length=_positive_int(page_length, 200, 500),
    )


@frappe.whitelist()
def check_freshness(
    batch_name,
    version_name=None,
    snapshot_fingerprint="",
    page=1,
    page_length=200,
):
    batch_name = require_batch_permission(batch_name, "read")
    return snapshot_service.check_freshness(
        batch_name,
        str(version_name or "") or None,
        snapshot_fingerprint=str(snapshot_fingerprint or "")[:200],
        page=_positive_int(page, 1),
        page_length=_positive_int(page_length, 200, 500),
    )


@frappe.whitelist(methods=["POST"])
def refresh_snapshot(batch_name, version_name=None, page=1, page_length=200):
    batch_name = require_batch_permission(batch_name, "read")
    return snapshot_service.refresh_snapshot(
        batch_name,
        str(version_name or "") or None,
        page=_positive_int(page, 1),
        page_length=_positive_int(page_length, 200, 500),
    )
