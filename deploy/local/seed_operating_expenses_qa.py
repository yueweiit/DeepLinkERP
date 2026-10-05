"""Bootstrap only the isolated operating-expenses QA site; never create postings."""

import argparse
import hashlib
import json
import runpy

import frappe


QA_SITE = "operating-expenses-qa.localhost"


def bootstrap():
	if frappe.local.site != QA_SITE or frappe.conf.db_host != "db":
		raise RuntimeError("This bootstrap is restricted to the dedicated local QA site")
	frappe.set_user("Administrator")
	frappe.flags.mute_emails = True
	if frappe.db.count("GL Entry") or frappe.db.count("Payment Entry"):
		raise RuntimeError("Expected an unposted, dedicated QA site")
	if not frappe.db.exists("Warehouse Type", "Transit"):
		from erpnext.setup.setup_wizard.operations.install_fixtures import install
		install(country="China")
	if not frappe.db.exists("Fiscal Year", "2026"):
		frappe.get_doc({"doctype": "Fiscal Year", "year": "2026", "year_start_date": "2026-01-01",
			"year_end_date": "2026-12-31"}).insert()
	for name, abbr, currency, country in (
		("QA Operating China", "QOC", "CNY", "China"),
		("QA Operating Mexico", "QOM", "MXN", "Mexico"),
	):
		if not frappe.db.exists("Company", name):
			frappe.get_doc({"doctype": "Company", "company_name": name, "abbr": abbr,
				"default_currency": currency, "country": country}).insert()
	frappe.db.set_single_value("System Settings", "setup_complete", 1)
	frappe.db.set_single_value("System Settings", "language", "zh")
	frappe.db.set_single_value("System Settings", "time_zone", "Asia/Shanghai")
	frappe.db.set_single_value("DeepLinkERP Interface Settings", "default_navigation_mode", "classic")
	from frappe.desk.page.setup_wizard.setup_wizard import enable_setup_wizard_complete
	for app in ("frappe", "erpnext"):
		enable_setup_wizard_complete(app)
	frappe.defaults.set_global_default("company", "QA Operating China")
	frappe.db.commit()
	frappe.clear_cache()
	return {"site": QA_SITE, "companies": 2, "gl_entries": frappe.db.count("GL Entry"),
		"payment_entries": frappe.db.count("Payment Entry")}


def seed_browser_data():
	"""Reuse the native QA helpers and public sync path for synthetic UI records.

	This does not post vouchers. Run only after transaction tests, since the
	concurrency runner deliberately requires an empty dedicated database.
	"""
	bootstrap()
	if frappe.db.count("Journal Entry"):
		raise RuntimeError("Existing QA voucher drafts must be reviewed before reseeding")
	case = runpy.run_path("/workspace/deploy/local/test_operating_expenses_native_qa.py")[
		"OperatingExpenseNativeQA"
	]("test_settings_disabled_and_secret_not_exposed")
	service = case._sync()
	supplier = case._supplier()
	if not frappe.db.exists("Gender", "Male"):
		frappe.get_doc({"doctype": "Gender", "gender": "Male"}).insert()
	employee = frappe.db.get_value("Employee", {
		"first_name": "QA Operating Employee", "company": "QA Operating China"
	}, "name")
	if not employee:
		employee = frappe.get_doc({"doctype": "Employee", "first_name": "QA Operating Employee",
			"company": "QA Operating China", "gender": "Male", "date_of_birth": "1990-01-01",
			"date_of_joining": "2026-01-01", "status": "Active"}).insert().name
	# Demo cache stays visible but background synchronization stays disabled.
	service.save_sync_settings({"QA Operating China": "QA Operating China",
		"QA Operating Mexico": "QA Operating Mexico"})
	frappe.db.commit()
	return {"site": QA_SITE, "sources": frappe.db.count("Operating Expense Source"),
		"supplier": supplier, "employee": employee,
		"cost_center": frappe.db.get_value("Company", "QA Operating China", "cost_center"),
		"sync_enabled": service.get_sync_settings()["enabled"],
		"journal_entries": frappe.db.count("Journal Entry"), "gl_entries": frappe.db.count("GL Entry"),
		"payment_entries": frappe.db.count("Payment Entry")}


def seed_restricted_browser_user():
	"""Create a synthetic company-limited user for actual browser acceptance."""
	if frappe.local.site != QA_SITE or frappe.conf.db_host != "db":
		raise RuntimeError("Restricted browser fixtures require the dedicated local QA site")
	frappe.set_user("Administrator")
	frappe.flags.mute_emails = True
	if frappe.db.count("GL Entry") or frappe.db.count("Payment Entry"):
		raise RuntimeError("Expected an unposted, dedicated QA site")
	email = "operating-browser-china@example.invalid"
	created = not frappe.db.exists("User", email)
	if created:
		frappe.get_doc({"doctype": "User", "email": email, "first_name": "QA China Finance",
			"send_welcome_email": 0, "enabled": 1, "language": "zh",
			"new_password": "operating-company-qa-only", "roles": [{"role": "Accounts User"}]}).insert()
	filters = {"user": email, "allow": "Company", "for_value": "QA Operating China"}
	if not frappe.db.exists("User Permission", filters):
		frappe.get_doc({"doctype": "User Permission", **filters,
			"apply_to_all_doctypes": 1}).insert()
	frappe.db.commit()
	frappe.clear_cache(user=email)
	return {"site": QA_SITE, "user": email, "company": "QA Operating China", "created": created,
		"journal_entries": frappe.db.count("Journal Entry"), "gl_entries": frappe.db.count("GL Entry"),
		"payment_entries": frappe.db.count("Payment Entry")}


def seed_joint_purchase_draft():
	"""One identifiable order to verify merged shared drawers, without posting."""
	if frappe.local.site != QA_SITE or frappe.conf.db_host != "db":
		raise RuntimeError("Joint purchase fixtures require the dedicated local QA site")
	if frappe.db.count("GL Entry") or frappe.db.count("Payment Entry"):
		raise RuntimeError("Expected an unposted, dedicated QA site")
	frappe.set_user("Administrator")
	frappe.flags.mute_emails = True

	def preserved():
		return {
			dt: hashlib.sha256(
				json.dumps(
					frappe.db.sql(f"select * from `tab{dt}` order by name", as_dict=True),
					sort_keys=True,
					default=str,
				).encode()
			).hexdigest()
			for dt in (
				"Journal Entry", "Journal Entry Account", "Operating Expense Source",
				"Operating Expense Event", "GL Entry", "Payment Entry",
			)
		}

	before = preserved()
	item, name = "QA-JOINT-PO-ITEM", "QA-JOINT-PO-01"
	created = not frappe.db.exists("Purchase Order", name)
	if not frappe.db.exists("Item", item):
		frappe.get_doc({"doctype": "Item", "item_code": item, "item_name": "QA 联合采购验收",
			"item_group": "All Item Groups", "stock_uom": "Nos", "is_stock_item": 0}).insert()
	if created:
		from frappe.utils import add_days, nowdate
		frappe.get_doc({"doctype": "Purchase Order", "company": "QA Operating China",
			"supplier": "QA Operating Supplier", "currency": "CNY", "conversion_rate": 1,
			"transaction_date": nowdate(), "schedule_date": add_days(nowdate(), 7),
			"items": [{"item_code": item, "qty": 2, "rate": 50,
				"schedule_date": add_days(nowdate(), 7)}]}).insert(set_name=name)
	assert frappe.db.get_value("Purchase Order", name, "docstatus") == 0
	assert before == preserved(), "Joint UI fixture changed protected QA finance/source rows"
	frappe.db.commit()
	return {"site": QA_SITE, "order": name, "created": created, "docstatus": 0,
		"protected_unchanged": True, "gl_entries": 0, "payment_entries": 0}


if __name__ == "__main__":
	parser = argparse.ArgumentParser()
	parser.add_argument("--restricted-browser-user", action="store_true")
	parser.add_argument("--joint-purchase-draft", action="store_true")
	args = parser.parse_args()
	frappe.init(site=QA_SITE, sites_path=".")
	frappe.connect()
	try:
		operation = (seed_joint_purchase_draft if args.joint_purchase_draft else
			seed_restricted_browser_user if args.restricted_browser_user else bootstrap)
		print(json.dumps(operation()))
	finally:
		frappe.db.rollback()
		frappe.destroy()
