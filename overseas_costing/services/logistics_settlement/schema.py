"""Idempotent schema installation only. No source reads or ERP effects during migration."""
def install():
    try:
        import frappe
    except ImportError:
        return {"ok": False, "message": "当前未连接 Frappe"}
    from .store import Store
    # Frappe migration hooks may enter with earlier metadata writes pending.
    # DDL is a migration-only boundary, never part of a settlement application.
    frappe.db.commit()
    Store.frappe().install()
