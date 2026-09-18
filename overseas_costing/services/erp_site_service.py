"""中文用途：ERP 站点配置读取与能力核验记录。"""

from __future__ import annotations

import json

from overseas_costing.services.erp_capability_service import verify_erpnext_site

try:
    import frappe
except ImportError:
    frappe = None


DOCTYPE = "Overseas Cost ERP Site"


def verify_and_record_site_capability(site_code: str, metadata_reader=None) -> dict:
    """仅管理员可触发：只读核验远端字段合同并保存本地脱敏结果。"""

    _require_system_manager()
    doc = frappe.get_doc(DOCTYPE, _text(site_code))
    config = _site_config(doc)
    result = verify_erpnext_site(config, metadata_reader=metadata_reader)
    summary = _safe_summary(result)
    doc.db_set("capability_status", result["capability_status"], update_modified=False)
    doc.db_set("capability_checked_at", frappe.utils.now_datetime(), update_modified=False)
    doc.db_set("capability_summary_json", json.dumps(summary, ensure_ascii=False, sort_keys=True, separators=(",", ":")), update_modified=True)
    return {"site": _safe_site(doc), **summary}


def get_site_push_config(site_code: str) -> dict:
    """返回给服务端同步客户端的站点配置；调用方不得把该值返回给普通页面。"""

    _require_frappe()
    return _site_config(frappe.get_doc(DOCTYPE, _text(site_code)))


def _site_config(doc) -> dict:
    return {
        "base_url": _text(doc.get("base_url")),
        "authorization": _password(doc, "authorization"),
        "push_mode": _text(doc.get("push_mode")) or "standard_purchase",
        "company": _text(doc.get("company")),
        "supplier": _text(doc.get("default_supplier")),
        "cost_center": _text(doc.get("cost_center")),
        "default_currency": _text(doc.get("default_currency")) or "CNY",
        "stock_uom": _text(doc.get("stock_uom")) or "Nos",
    }


def _safe_summary(result: dict) -> dict:
    metadata_read = result.get("metadata_read") or {}
    return {
        "ok": bool(result.get("ok")),
        "capability_status": _text(result.get("capability_status")) or "FAILED",
        "missing_fields": result.get("missing_fields") or {},
        "message": _text(result.get("message")),
        "request": metadata_read.get("request") or {},
        "errors": {
            doctype: {"http_status": error.get("http_status"), "message": _text(error.get("message"))}
            for doctype, error in (metadata_read.get("errors") or {}).items()
            if isinstance(error, dict)
        },
    }


def _safe_site(doc) -> dict:
    return {"site_code": _text(doc.get("site_code")), "label": _text(doc.get("label"))}


def _password(doc, fieldname: str) -> str:
    try:
        return _text(doc.get_password(fieldname, raise_exception=False))
    except TypeError:
        return _text(doc.get_password(fieldname))


def _require_system_manager() -> None:
    _require_frappe()
    frappe.only_for("System Manager")


def _require_frappe() -> None:
    if frappe is None:
        raise RuntimeError("Frappe 运行环境不可用，无法读取 ERP 站点配置。")


def _text(value) -> str:
    return str(value or "").strip()
