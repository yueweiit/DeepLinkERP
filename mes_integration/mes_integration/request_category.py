"""MES display metadata, deliberately separate from issue purpose and quantities."""
from collections import Counter, defaultdict
import hashlib
import json


FIELDNAME = "custom_mes_issue_category"
CATEGORIES = ("consumable", "semi_finished", "raw_material", "unclassified")
IDENTITY_FIELDS = ("name", "company", "custom_material_request_no", "modified", FIELDNAME)


def validate_category(value):
	if value is None or value == "":
		return ""
	if not isinstance(value, str) or value not in CATEGORIES:
		raise ValueError("Unsupported MES issue category")
	return value


def plan_category_backfill(sources, rows):
	"""Only an exact, unique source + ERP identity may fill empty metadata."""
	sources = list(sources)
	identities = Counter((s.get("company"), s.get("request_no")) for s in sources)
	by_identity = defaultdict(list)
	for row in rows:
		by_identity[(row.get("company"), row.get("custom_material_request_no"))].append(row)
	updates, skipped = [], []
	for source in sources:
		key = (source.get("company"), source.get("request_no"))
		matches = by_identity[key]
		reason = None
		try:
			category = validate_category(source.get("category"))
		except ValueError:
			category = ""
		if not all((*key, source.get("erp_name"), category)):
			reason = "missing_or_invalid_evidence"
		elif identities[key] != 1 or len(matches) != 1:
			reason = "ambiguous_or_missing_identity"
		elif matches[0].get("name") != source["erp_name"]:
			reason = "erp_name_mismatch"
		elif matches[0].get(FIELDNAME):
			reason = "already_equal" if matches[0][FIELDNAME] == category else "existing_category_conflict"
		if reason:
			skipped.append({**source, "reason": reason})
			continue
		row = matches[0]
		updates.append({
			"name": row["name"], "category": category,
			"expected": {field: row.get(field) or "" for field in IDENTITY_FIELDS},
		})
	return {"updates": updates, "skipped": skipped}


def plan_digest(plan):
	return hashlib.sha256(json.dumps(plan, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


def preview_category_backfill(sources):
	"""Administrative CLI only; no whitelisted or business-create endpoint."""
	import frappe
	frappe.only_for("System Manager")
	sources = list(sources)
	request_numbers = sorted({s.get("request_no") for s in sources if s.get("request_no")})
	rows = frappe.get_all("Material Request", filters={"custom_material_request_no": ["in", request_numbers]},
		fields=list(IDENTITY_FIELDS), limit_page_length=0) if request_numbers else []
	plan = plan_category_backfill(sources, rows)
	return {"plan": plan, "digest": plan_digest(plan)}


def apply_category_backfill(plan, expected_digest):
	"""Apply a reviewed plan only while every target still matches its snapshot.

	No save/submit hooks, business timestamps, ODT, quantities or hashes are touched.
	The caller commits and retains this result as its per-record audit receipt.
	"""
	import frappe
	frappe.only_for("System Manager")
	if plan_digest(plan) != expected_digest:
		raise ValueError("Category backfill review digest mismatch")
	updates = plan.get("updates") or []
	if len({u["name"] for u in updates}) != len(updates):
		raise ValueError("Duplicate category backfill targets")
	frappe.db.savepoint("mes_category_backfill")
	try:
		for update in sorted(updates, key=lambda entry: entry["name"]):
			if not validate_category(update["category"]):
				raise ValueError("Missing category backfill evidence")
			rows = frappe.db.sql(
				"SELECT name, company, custom_material_request_no, modified, custom_mes_issue_category "
				"FROM `tabMaterial Request` WHERE name=%s FOR UPDATE", (update["name"],), as_dict=True,
			)
			if len(rows) != 1 or {field: str(rows[0].get(field) or "") for field in IDENTITY_FIELDS} != {
				field: str(update["expected"].get(field) or "") for field in IDENTITY_FIELDS
			} or rows[0].get(FIELDNAME):
				raise ValueError("Category backfill target changed; preview again")
		for update in updates:
			frappe.db.set_value("Material Request", update["name"], FIELDNAME, update["category"], update_modified=False)
	except Exception:
		frappe.db.rollback(save_point="mes_category_backfill")
		raise
	return {"applied": updates, "skipped": plan.get("skipped") or [], "digest": expected_digest}
