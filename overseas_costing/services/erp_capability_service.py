"""Read-only capability checks and safe summaries for explicitly configured ERP sites."""

from __future__ import annotations

from urllib.parse import quote

from overseas_costing.services import erp_client


REQUIRED_ERP_FIELDS = {
    "Purchase Order": frozenset(
        {
            "custom_overseas_business_key",
            "custom_overseas_cost_result_hash",
            "custom_overseas_amount_status",
        }
    ),
    "Purchase Order Item": frozenset({"custom_overseas_stable_line_key"}),
}

SAFE_SITE_FIELDS = (
    "site_code",
    "label",
    "subsidiary_code",
    "enabled",
    "push_mode",
    "company",
    "default_supplier",
    "cost_center",
    "default_currency",
    "stock_uom",
    "cost_update_mode",
    "capability_status",
    "capability_checked_at",
)


def build_safe_site_summary(config: dict) -> dict:
    summary = {key: config.get(key) for key in SAFE_SITE_FIELDS if key in config}
    summary.setdefault("site_code", str(config.get("site_code") or ""))
    summary.setdefault("enabled", int(config.get("enabled", 1) or 0))
    summary.setdefault("cost_update_mode", str(config.get("cost_update_mode") or "DISABLED"))
    summary.setdefault("capability_status", str(config.get("capability_status") or "UNVERIFIED"))
    return summary


def _metadata_url(config: dict, doctype: str) -> str:
    base = str(config.get("base_url") or "").rstrip("/")
    root = base.split("/api/resource", 1)[0]
    return f"{root}/api/method/frappe.desk.form.load.getdoctype?doctype={quote(doctype, safe='')}"


def _load_metadata(doctype: str, config: dict) -> dict:
    return erp_client._request_json(
        config,
        method="GET",
        url=_metadata_url(config, doctype),
    )


def _fieldnames(metadata: dict) -> set[str]:
    rows = metadata.get("fields") if isinstance(metadata, dict) else []
    if not rows and isinstance(metadata, dict):
        docs = metadata.get("docs") or (metadata.get("message") or {}).get("docs") or []
        if docs:
            rows = (docs[0] or {}).get("fields") or []
    return {str(row.get("fieldname") or "") for row in rows or [] if isinstance(row, dict)}


def verify_site_capabilities(config: dict, *, metadata_loader=None) -> dict:
    """Inspect metadata only; this function never sends POST, PUT, PATCH or DELETE."""

    loader = metadata_loader or _load_metadata
    missing = []
    errors = []
    for doctype, required in REQUIRED_ERP_FIELDS.items():
        try:
            present = _fieldnames(loader(doctype, config))
        except Exception as exc:
            errors.append(f"{doctype}:{type(exc).__name__}")
            continue
        missing.extend(f"{doctype}.{fieldname}" for fieldname in sorted(required - present))
    if not int(config.get("enabled", 1) or 0):
        missing.append("SITE_ENABLED")
    status = "VERIFIED" if not missing and not errors else "FAILED"
    return {
        "site": build_safe_site_summary(config),
        "status": status,
        "missing_capabilities": missing,
        "errors": errors,
        "read_only": True,
    }
