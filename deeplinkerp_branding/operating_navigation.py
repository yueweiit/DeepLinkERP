"""Add one operating-expense route to existing finance navigation only."""

import frappe

from deeplinkerp_branding.procurement_navigation import reconcile_links, reconcile_workspace

ENTRIES = (("运营费用", "Page", "operating-expenses", "receipt-text"),)
TARGETS = {"operating-expenses"}


def _anchor(doc, table):
	rows = list(doc.get(table) or [])
	return next(
		(
			index
			for index, row in enumerate(rows)
			if row.get("link_to") in TARGETS
			and not any(row.get(field) for field in ("filters", "route_options", "url"))
		),
		len(rows),
	)


def ensure_operating_navigation():
	if not frappe.db.exists("Page", "operating-expenses"):
		return {"ok": False, "missing_page": "operating-expenses"}
	changed = []
	for name in ("Accounting", "China Finance"):
		for doctype in ("Workspace Sidebar", "Workspace"):
			if not frappe.db.exists(doctype, name):
				continue
			doc = frappe.get_doc(doctype, name)
			if doctype == "Workspace Sidebar":
				modified = reconcile_links(
					doc, "items", entries=ENTRIES, targets=TARGETS, anchor=_anchor(doc, "items")
				)
			else:
				modified = reconcile_workspace(
					doc,
					entries=ENTRIES,
					targets=TARGETS,
					prefix="dlp-operating-",
					anchor=_anchor(doc, "links"),
				)
			if not modified:
				continue
			previous, developer_mode = frappe.flags.in_import, frappe.conf.developer_mode
			frappe.flags.in_import, frappe.conf.developer_mode = True, False
			try:
				doc.flags.ignore_links = True
				doc.save(ignore_permissions=True)
			finally:
				frappe.flags.in_import, frappe.conf.developer_mode = previous, developer_mode
			changed.append({"doctype": doctype, "name": name})
	return {"ok": True, "changed": changed}
