"""Concentrate existing procurement routes; preserve native finance and custom links."""

import json

import frappe

ENTRIES = (
	("采购订单", "DocType", "Purchase Order", "receipt-text"),
	("采购入库", "DocType", "Purchase Receipt", "warehouse"),
	("采购应付", "Page", "purchase-payables", "liabilities"),
	("采购付款记录", "Page", "purchase-payment-records", "landmark"),
)
TARGETS = {entry[2] for entry in ENTRIES} | {"Purchase Invoice"}


def reconcile_links(doc, table, type_field="link_type"):
	"""One ordered upsert for Sidebar items, Workspace links and shortcuts.

	Existing canonical child rows keep their identity; filtered/custom routes stay.
	"""
	original = list(doc.get(table) or [])
	matches = [
		row
		for row in original
		if row.get("link_to") in TARGETS
		and not any(row.get(key) for key in ("filters", "route_options", "url"))
	]
	by_target = {row.link_to: row for row in reversed(matches)}
	remaining = [row for row in original if row not in matches]
	anchor = next((original.index(row) for row in matches if row.link_to == "Purchase Order"), 0)
	index = sum(row in remaining for row in original[:anchor])
	targets, changed = [], False
	for label, kind, name, icon in ENTRIES:
		row = by_target.get(name)
		if row is None:
			row = doc.append(table, {})
			changed = True
		values = {"label": label, type_field: kind, "link_to": name}
		if table == "items":
			values.update(type="Link", child=0, icon=icon)
		elif table == "links":
			values.update(type="Link", onboard=0, dependencies="")
		for key, value in values.items():
			if row.get(key) != value:
				row.set(key, value)
				changed = True
		targets.append(row)
	result = remaining[:index] + targets + remaining[index:]
	if result != original:
		changed = True
	doc.set(table, result)
	for idx, row in enumerate(result, 1):
		if row.idx != idx:
			row.idx = idx
			changed = True
	return changed


def reconcile_workspace(doc):
	labels = {
		row.label
		for row in doc.get("shortcuts") or []
		if row.get("link_to") in TARGETS
		and not any(row.get(key) for key in ("filters", "route_options", "url"))
	}
	changed = reconcile_links(doc, "links")
	changed = reconcile_links(doc, "shortcuts", "type") or changed
	content = json.loads(doc.content or "[]")
	labels.update(entry[0] for entry in ENTRIES)
	blocks = [
		block
		for block in content
		if not (
			block.get("id", "").startswith("dlp-procurement-")
			or (block.get("type") == "shortcut" and block.get("data", {}).get("shortcut_name") in labels)
		)
	]
	shortcuts = [
		{"id": f"dlp-procurement-{index}", "type": "shortcut", "data": {"shortcut_name": label, "col": 3}}
		for index, (label, *_rest) in enumerate(ENTRIES)
	]
	desired = shortcuts + blocks
	if desired != content:
		doc.content = json.dumps(desired, ensure_ascii=False)
		changed = True
	return changed


def ensure_procurement_navigation():
	"""Navigation configuration only. Native permission filtering remains authoritative."""
	for page in ("purchase-payables", "purchase-payment-records"):
		if not frappe.db.exists("Page", page):
			return {"ok": False, "missing_page": page}
	for source in ("Purchase Order", "Purchase Receipt"):
		if not frappe.db.exists("DocType", source):
			return {"ok": False, "missing_doctype": source}
	changed = []
	for doctype, reconcile in (
		("Workspace Sidebar", lambda doc: reconcile_links(doc, "items")),
		("Workspace", reconcile_workspace),
	):
		if frappe.db.exists(doctype, "Buying"):
			doc = frappe.get_doc(doctype, "Buying")
			if reconcile(doc):
				# Suppress developer-mode export into the native ERPNext app.
				previous = frappe.flags.in_import
				developer_mode = frappe.conf.developer_mode
				frappe.flags.in_import = True
				frappe.conf.developer_mode = False
				try:
					# Existing custom/report links may be stale; preserve them exactly.
					# Every new canonical target has been verified above.
					doc.flags.ignore_links = True
					doc.save(ignore_permissions=True)
				finally:
					frappe.flags.in_import = previous
					frappe.conf.developer_mode = developer_mode
				changed.append(doctype)
	return {"ok": True, "changed": changed}
