import frappe


def boot_session(bootinfo):
    """Expose the site-specific MES portal URL to Desk pages."""
    bootinfo.mes_portal_url = frappe.conf.get("mes_portal_url")
