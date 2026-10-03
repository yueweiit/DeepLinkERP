"""One-time, explicitly approved historical OA company repair. No application API/hooks."""

import argparse
import copy
import hashlib
import json
import os
from datetime import date
from pathlib import Path

DOCTYPE = "OA Purchase Request"
COMPANY = "YUEWEI MX"
CUTOFF = date(2026, 7, 1)
SITE = "deeplinkerp.com"
APPROVED_COUNT = 148
BENCH = Path("/home/frappe/frappe-bench")


def select_candidates(rows, linked_oa_names=()):
	names = set()
	selected = []
	linked_oa_names = {str(name or "").strip() for name in linked_oa_names}
	for row in rows:
		name = row.get("name")
		if not name or name in names:
			raise ValueError("Missing or duplicate OA identity")
		names.add(name)
		if str(row.get("target_company") or "").strip():
			continue
		try:
			source_date = date.fromisoformat(str(row.get("apply_date") or row.get("creation"))[:10])
		except ValueError as error:
			raise ValueError(f"Ambiguous source date: {name}") from error
		if source_date >= CUTOFF:
			continue
		if row.get("docstatus") != 0 or str(row.get("purchase_order") or "").strip() or name in linked_oa_names:
			raise ValueError(f"Historical candidate is not an unlinked draft: {name}")
		selected.append(row)
	return sorted(selected, key=lambda row: row["name"])


def manifest_digest(rows):
	payload = json.dumps(sorted(rows, key=lambda row: row["name"]), sort_keys=True,
		ensure_ascii=False, default=str, separators=(",", ":"))
	return hashlib.sha256(payload.encode()).hexdigest()


def verify_manifest(rows, expected_count, expected_digest):
	if len(rows) != expected_count or manifest_digest(rows) != expected_digest:
		raise ValueError("OA manifest/count changed; refusing partial or repeated repair")


def verify_rows(before, after, selected_names, actor):
	if len(before) != len(after):
		raise ValueError("OA row count changed")
	by_name = {row["name"]: row for row in after}
	for old in before:
		new = by_name.get(old["name"])
		if new is None:
			raise ValueError("OA identity changed")
		if old["name"] in selected_names:
			if new["target_company"] != COMPANY or new["modified_by"] != actor:
				raise ValueError("Company/actor readback mismatch")
			allowed = {"target_company", "modified", "modified_by"}
			if {k: v for k, v in old.items() if k not in allowed} != {k: v for k, v in new.items() if k not in allowed}:
				raise ValueError("Unexpected OA business-field change")
		elif old != new:
			raise ValueError("An unselected OA row changed")


def verify_version(data):
	changed = data.get("changed", [])
	if len(changed) != 1 or len(changed[0]) != 3 or changed[0][0] != "target_company" \
		or str(changed[0][1] or "").strip() or changed[0][2] != COMPANY \
		or any(data.get(key) for key in ("added", "removed", "row_changed")):
		raise ValueError("Version contains changes beyond the approved company assignment")


def verify_execution(site, mode, expected_count, maintenance):
	if site not in {SITE, "po-grid-qa.localhost"} or mode not in {"preview", "dry-run", "apply"}:
		raise ValueError("Unsupported site/mode")
	if site == SITE and expected_count != APPROVED_COUNT:
		raise ValueError("Production approval covers exactly 148 records")
	if mode == "apply" and site != SITE:
		raise ValueError("Apply is restricted to the approved production site")
	if mode != "preview" and site == SITE and not maintenance:
		raise ValueError("Production writes require the serialized maintenance window")


def apply_company_changes(frappe, rows):
	versions = []
	for row in rows:
		old = frappe.get_doc(DOCTYPE, row["name"])
		old.check_permission("write")
		frappe.db.set_value(DOCTYPE, old.name, "target_company", COMPANY)
		new = frappe.get_doc(DOCTYPE, old.name)
		version = frappe.new_doc("Version")
		if not version.update_version_info(old, new):
			raise ValueError("Missing Version diff")
		verify_version(json.loads(version.data))
		version.insert(ignore_permissions=True)  # Standard Document.save_version behavior after OA permission checks.
		versions.append({"oa_name": old.name, "version_name": version.name})
		new.clear_cache()
	return versions


def report_destination(path, site):
	root = BENCH / "sites" / site / "private/backups"
	target = Path(path)
	if target.parent.resolve() != root.resolve() or target.is_symlink() or target.exists():
		raise ValueError("Report must be a new file directly in this site's private/backups")
	return target


def write_private_report(path, report, site):
	target = report_destination(path, site)
	with os.fdopen(os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w") as stream:
		json.dump(report, stream, sort_keys=True, ensure_ascii=False, default=str)
		stream.flush()
		os.fsync(stream.fileno())


def commit_and_record(frappe, path, site, summary, verify_durable):
	commit_error = None
	try:
		frappe.db.commit()
	except Exception as error:
		# Frappe can raise in begin()/callbacks after SQL COMMIT, or before COMMIT.
		commit_error = error
	try:
		verify_durable()  # Always reopen the DB connection and compare durable state.
	except Exception as error:
		raise RuntimeError("Commit outcome not confirmed. Do not retry; inspect the private report and durable database state.") from error
	result = {**summary, "status": "committed"}
	if commit_error is not None:
		result["commit_warning"] = str(commit_error)
	try:
		write_private_report(path + ".committed", result, site)
	except (OSError, ValueError) as error:
		# The DB has committed. Never misreport this as rollback or invite a blind retry.
		result["report_marker_warning"] = str(error)
	return result


def run(args):
	import frappe
	try:
		from . import audit_unified_purchase as audit
	except ImportError:  # Direct operational invocation, with both scripts in the same directory.
		import audit_unified_purchase as audit

	frappe.init(site=args.site, sites_path=str(BENCH / "sites"))
	frappe.connect()
	outcome = None
	try:
		verify_execution(args.site, args.mode, args.expected_count, bool(frappe.conf.get("maintenance_mode")))
		frappe.set_user(args.actor)
		frappe.get_doc("Company", COMPANY).check_permission("read")
		if not frappe.get_meta(DOCTYPE).track_changes:
			raise ValueError("Standard Version tracking is required")
		locking = " for update" if args.mode != "preview" else ""
		before_rows = frappe.db.sql(f"select * from `tabOA Purchase Request` order by name{locking}", as_dict=True)
		if not frappe.get_meta("Purchase Order").has_field("custom_oa_purchase_expense"):
			raise ValueError("Reverse OA-to-order linkage must be available for eligibility verification")
		reverse_links = frappe.db.sql("select custom_oa_purchase_expense from `tabPurchase Order` "
			f"where coalesce(custom_oa_purchase_expense, '') != ''{locking}", as_list=True)
		selected = select_candidates(before_rows, {link[0] for link in reverse_links})
		for row in selected:
			frappe.get_doc(DOCTYPE, row["name"]).check_permission("write")
		digest = manifest_digest(selected)
		if args.mode == "preview":
			return {"site": args.site, "count": len(selected), "company": COMPANY, "cutoff_exclusive": str(CUTOFF),
				"manifest_sha256": digest, "date_min": min((str(r.get("apply_date") or r["creation"])[:10] for r in selected), default=None),
				"date_max": max((str(r.get("apply_date") or r["creation"])[:10] for r in selected), default=None)}
		verify_manifest(selected, args.expected_count, args.expected_manifest)
		if not args.report:
			raise ValueError("A private report path is required")
		report_destination(args.report, args.site)
		if args.mode == "apply":
			report_destination(args.report + ".committed", args.site)
		before_audit = audit.capture_audit()
		version_count = frappe.db.count("Version")
		versions = apply_company_changes(frappe, selected)
		after_rows = frappe.db.sql("select * from `tabOA Purchase Request` order by name", as_dict=True)
		verify_rows(before_rows, after_rows, {r["name"] for r in selected}, args.actor)
		after_audit = audit.capture_audit()
		protected_before, protected_after = copy.deepcopy(before_audit), copy.deepcopy(after_audit)
		protected_before["tables"].pop(DOCTYPE)
		protected_after["tables"].pop(DOCTYPE)
		if protected_before != protected_after or frappe.db.count("Version") != version_count + len(selected):
			raise ValueError("Protected data/source audit changed or Version count mismatch")
		report = {"mode": args.mode, "site": args.site, "actor": args.actor, "count": len(selected), "company": COMPANY,
			"cutoff_exclusive": str(CUTOFF), "manifest_sha256": digest, "versions": versions,
			"before": before_audit, "after": after_audit,
			"original_values": [{k: r.get(k) for k in ("name", "target_company", "modified", "modified_by")} for r in selected]}
		if args.mode == "dry-run":
			frappe.db.rollback()
			if audit.capture_audit() != before_audit or frappe.db.count("Version") != version_count:
				raise ValueError("Dry-run rollback verification failed")
			report["status"] = "rolled_back_verified"
		else:
			report["status"] = "verified_pending_commit"
		write_private_report(args.report, report, args.site)
		summary = {"mode": args.mode, "count": len(selected), "manifest_sha256": digest, "report": args.report}
		if args.mode == "apply":
			def verify_durable():
				frappe.db.close()
				frappe.db.connect()
				frappe.db.begin(read_only=True)
				durable_rows = frappe.db.sql("select * from `tabOA Purchase Request` order by name", as_dict=True)
				verify_rows(before_rows, durable_rows, {r["name"] for r in selected}, args.actor)
				if audit.capture_audit() != after_audit or frappe.db.count("Version") != version_count + len(selected):
					raise ValueError("Durable audit/Version mismatch")
				for version in versions:
					stored = frappe.db.get_value("Version", version["version_name"], ["ref_doctype", "docname", "data"], as_dict=True)
					if not stored or stored.ref_doctype != DOCTYPE or stored.docname != version["oa_name"]:
						raise ValueError("Durable Version identity mismatch")
					verify_version(json.loads(stored.data))
			outcome = commit_and_record(frappe, args.report, args.site, summary, verify_durable)
			return outcome
		return {**summary, "status": "rolled_back_verified"}
	finally:
		try:
			try:
				frappe.db.rollback()
			finally:
				frappe.destroy()
		except Exception as error:
			if outcome is None or outcome.get("status") != "committed":
				raise
			outcome["cleanup_warning"] = str(error)


def main():
	parser = argparse.ArgumentParser(description=__doc__)
	parser.add_argument("--site", default=SITE)
	parser.add_argument("--mode", choices=("preview", "dry-run", "apply"), default="preview")
	parser.add_argument("--actor", required=True)
	parser.add_argument("--expected-count", type=int, default=APPROVED_COUNT)
	parser.add_argument("--expected-manifest")
	parser.add_argument("--report")
	print(json.dumps(run(parser.parse_args()), ensure_ascii=False))


if __name__ == "__main__":
	main()
