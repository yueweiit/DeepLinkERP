"""Stable workbench release marker used by already-open browser pages."""

from __future__ import annotations

import hashlib
from pathlib import Path

try:
    import frappe
except Exception:  # pragma: no cover - pure unit tests provide a stub
    frappe = None


WORKBENCH_ASSET_DIR = (
    Path(__file__).resolve().parents[1]
    / "page"
    / "overseas_cost_workbench"
)


def get_release_id() -> str:
    """Return the configured deploy SHA, or a deterministic asset fallback."""

    configured = ""
    if frappe is not None:
        configured = str(getattr(frappe, "conf", {}).get("overseas_costing_release_id") or "").strip()
    if configured:
        return configured

    digest = hashlib.sha256()
    for suffix in ("js", "css"):
        path = WORKBENCH_ASSET_DIR / f"overseas_cost_workbench.{suffix}"
        digest.update(suffix.encode("ascii"))
        digest.update(path.read_bytes() if path.is_file() else b"")
    return f"assets-{digest.hexdigest()[:16]}"
