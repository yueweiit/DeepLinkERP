"""实际库存来源追溯字段回填接口。"""

from __future__ import annotations

import frappe
from frappe.utils import cint

from overseas_costing.services.inventory_trace_service import apply_inventory_trace


@frappe.whitelist()
def backfill_inventory_trace(rows, dry_run=1):
    """由 System Manager 先预演、再原子回填库存来源追溯字段。"""

    frappe.only_for("System Manager")
    parsed_rows = frappe.parse_json(rows) if isinstance(rows, str) else rows
    try:
        result = apply_inventory_trace(parsed_rows, dry_run=bool(cint(dry_run)))
        if not result["dry_run"] and result["applied"]:
            frappe.db.commit()
        return result
    except Exception:
        frappe.db.rollback()
        raise
