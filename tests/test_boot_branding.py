import copy
import importlib
import hashlib
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch


class FakeDB:
	def __init__(self):
		self.doctype_exists = True
		self.company_default = "dl"

	def exists(self, doctype, name):
		if doctype == "DocType" and name == "DeepLinkERP Interface Settings":
			return self.doctype_exists
		return False

	def get_single_value(self, doctype, fieldname):
		return self.company_default


class FakeDefaults:
	def __init__(self):
		self.values = {}

	def get_user_default(self, key, user=None):
		return self.values.get((user, key))


FAKE_FRAPPE = types.ModuleType("frappe")
FAKE_FRAPPE.session = types.SimpleNamespace(user="Guest")
FAKE_FRAPPE.db = FakeDB()
FAKE_FRAPPE.defaults = FakeDefaults()
FAKE_FRAPPE.whitelist = lambda function=None: function if function else (lambda method: method)
FAKE_FRAPPE.PermissionError = type("PermissionError", (Exception,), {})
FAKE_FRAPPE.ValidationError = type("ValidationError", (Exception,), {})

previous_frappe = sys.modules.get("frappe")
sys.modules["frappe"] = FAKE_FRAPPE
try:
	branding = importlib.import_module("deeplinkerp_branding.deeplinkerp_branding.branding")
finally:
	if previous_frappe is None:
		del sys.modules["frappe"]
	else:
		sys.modules["frappe"] = previous_frappe


class BootBrandingTest(unittest.TestCase):
	def setUp(self):
		if hasattr(branding, "_purchase_page_code_version"):
			branding._purchase_page_code_version.cache_clear()
		dependency = patch.object(branding, "frappe", FAKE_FRAPPE)
		dependency.start()
		self.addCleanup(dependency.stop)
		# Patch the actual imported function, including when branding was cached.
		navigation = patch.dict(branding.apply_interface_mode_bootinfo.__globals__, {"frappe": FAKE_FRAPPE})
		navigation.start()
		self.addCleanup(navigation.stop)
		FAKE_FRAPPE.db = FakeDB()
		FAKE_FRAPPE.defaults = FakeDefaults()
		self.configure_user("employee@example.com", roles=["Employee"])

	def configure_user(self, user, roles, blocked_by_user=None):
		blocked_by_user = blocked_by_user or {}
		FAKE_FRAPPE.session.user = user
		FAKE_FRAPPE.get_roles = lambda user=None: list(roles)

		def get_cached_doc(doctype, docname):
			self.assertEqual(doctype, "User")
			return types.SimpleNamespace(
				get_blocked_modules=lambda: list(blocked_by_user.get(docname, []))
			)

		FAKE_FRAPPE.get_cached_doc = get_cached_doc

	def bootinfo(self, desktop_icons, workspace_sidebar_item=None):
		return {
			"app_data": [],
			"desktop_icons": copy.deepcopy(desktop_icons),
			"module_app": {},
			"workspace_sidebar_item": copy.deepcopy(workspace_sidebar_item or {}),
		}

	def test_regular_user_cannot_see_framework_settings_or_framework_children(self):
		bootinfo = self.bootinfo(
			[
				{"name": "DLP Framework", "label": "DLP Framework", "hidden": 0},
				{
					"name": "Customize Form",
					"label": "Customize Form",
					"parent_icon": "Framework",
					"hidden": 0,
				},
				{
					"name": "Deeplinkerp Settings",
					"label": "Deeplinkerp Settings",
					"hidden": 0,
				},
				{"name": "Stock", "label": "Stock", "hidden": 0},
			]
		)

		branding.apply_boot_branding(bootinfo)

		self.assertEqual([icon["name"] for icon in bootinfo["desktop_icons"]], ["Stock"])

	def test_administrator_and_system_manager_keep_admin_entries_and_reparent_children(self):
		admin_icons = [
			{"name": "DLP Framework", "label": "DLP Framework", "hidden": 0},
			{
				"name": "Customize Form",
				"label": "Customize Form",
				"parent_icon": "Framework",
				"hidden": 0,
			},
			{
				"name": "Deeplinkerp Settings",
				"label": "Deeplinkerp Settings",
				"hidden": 0,
			},
		]
		identities = (
			("Administrator", ["Administrator"]),
			("manager@example.com", ["System Manager"]),
		)

		for user, roles in identities:
			with self.subTest(user=user):
				self.configure_user(user, roles)
				bootinfo = self.bootinfo(
					admin_icons,
					{
						"deeplinkerp settings": {
							"label": "Deeplinkerp Settings",
							"module": "Deeplinkerp Branding",
						}
					},
				)

				branding.apply_boot_branding(bootinfo)

				by_name = {icon["name"]: icon for icon in bootinfo["desktop_icons"]}
				self.assertEqual(by_name["DLP Framework"]["hidden"], 0)
				self.assertEqual(by_name["Deeplinkerp Settings"]["hidden"], 0)
				self.assertEqual(by_name["Customize Form"]["parent_icon"], "DLP Framework")
				visible_roots = {
					icon["label"]
					for icon in bootinfo["desktop_icons"]
					if not icon.get("parent_icon") and icon.get("hidden") != 1
				}
				for icon in bootinfo["desktop_icons"]:
					if icon.get("parent_icon"):
						self.assertIn(icon["parent_icon"], visible_roots)

	def test_blocked_module_removes_sidebar_and_matching_workspace_icon(self):
		self.configure_user(
			"employee@example.com",
			["Employee"],
			blocked_by_user={"Administrator": ["China Finance"]},
		)
		bootinfo = self.bootinfo(
			[
				{
					"name": "China Finance",
					"label": "China Finance",
					"link_to": "China Finance",
					"link_type": "Workspace Sidebar",
				},
				{
					"name": "Stock",
					"label": "Stock",
					"link_to": "Stock",
					"link_type": "Workspace Sidebar",
				},
			],
			{
				"china finance": {"label": "China Finance", "module": "China Finance"},
				"stock": {"label": "Stock", "module": "Stock"},
			},
		)

		branding.apply_boot_branding(bootinfo)

		self.assertEqual(list(bootinfo["workspace_sidebar_item"]), ["stock"])
		self.assertEqual([icon["name"] for icon in bootinfo["desktop_icons"]], ["Stock"])

	def test_unrelated_icons_keep_labels_order_and_unknown_entries(self):
		original_icons = [
			{
				"name": "Custom First",
				"label": "Custom First Label",
				"idx": 80,
				"link": "/desk/custom-first",
				"link_type": "External",
			},
			{
				"name": "Quality Portal",
				"label": "Quality Display Name",
				"idx": 3,
				"link_to": "Quality Portal",
				"link_type": "Workspace Sidebar",
			},
			{
				"name": "Unknown Last",
				"label": "Unregistered Extension",
				"idx": -5,
				"link": "/desk/unknown-last",
				"link_type": "External",
			},
		]
		bootinfo = self.bootinfo(
			original_icons,
			{
				"quality portal": {
					"label": "Quality Portal",
					"module": "Quality Management",
				}
			},
		)

		branding.apply_boot_branding(bootinfo)

		self.assertEqual(
			[(icon["name"], icon["label"], icon["idx"]) for icon in bootinfo["desktop_icons"]],
			[(icon["name"], icon["label"], icon["idx"]) for icon in original_icons],
		)

	def test_boot_includes_the_server_resolved_interface_mode(self):
		FAKE_FRAPPE.db.company_default = "classic"
		FAKE_FRAPPE.defaults.values[
			("employee@example.com", "deeplinkerp_navigation_mode_override")
		] = "dl"
		bootinfo = self.bootinfo([{"name": "Stock", "label": "Stock", "hidden": 0}])

		branding.apply_boot_branding(bootinfo)

		self.assertIn("deeplinkerp_interface_mode", bootinfo)
		self.assertEqual(
			bootinfo["deeplinkerp_interface_mode"],
			{
				"company_default": "classic",
				"user_override": "dl",
				"effective_mode": "dl",
				"can_manage_company_default": False,
			},
		)

	def test_missing_settings_doctype_keeps_existing_boot_filtering_and_falls_back_to_dl(self):
		FAKE_FRAPPE.db.doctype_exists = False
		bootinfo = self.bootinfo(
			[
				{"name": "DLP Framework", "label": "DLP Framework", "hidden": 0},
				{"name": "Stock", "label": "Stock", "hidden": 0},
			]
		)

		branding.apply_boot_branding(bootinfo)

		self.assertEqual([icon["name"] for icon in bootinfo["desktop_icons"]], ["Stock"])
		self.assertIn("deeplinkerp_interface_mode", bootinfo)
		self.assertEqual(bootinfo["deeplinkerp_interface_mode"]["effective_mode"], "dl")

	def test_purchase_page_code_versions_invalidate_only_two_native_page_caches_without_layout_or_writes(self):
		bootinfo = self.bootinfo([])
		bootinfo["page_info"] = {
			"purchase-payables": {"modified": "native-ap-v1", "roles": ["Accounts User"]},
			"purchase-payment-records": {"modified": "native-payment-v1", "roles": ["Accounts User"]},
			"operating-expenses": {"modified": "native-operating-v1", "roles": ["Accounts User"]},
		}
		previous = copy.deepcopy(bootinfo["page_info"])
		with patch.object(FAKE_FRAPPE.db, "set_value", side_effect=AssertionError("boot must not write"), create=True):
			branding.apply_boot_branding(bootinfo)
		self.assertNotEqual(bootinfo["page_info"]["purchase-payables"]["modified"], previous["purchase-payables"]["modified"])
		self.assertNotEqual(bootinfo["page_info"]["purchase-payment-records"]["modified"], previous["purchase-payment-records"]["modified"])
		self.assertEqual(bootinfo["page_info"]["operating-expenses"], previous["operating-expenses"])
		self.assertEqual(bootinfo["page_info"]["purchase-payables"]["roles"], ["Accounts User"])
		# Native Desk.sync_pages removes only _page:<name> whose modified changed.
		storage = {"_page:" + name: "old-code" for name in previous}
		storage["dlp-list:site:finance:Purchase%20Invoice"] = "custom-layout"
		for name, page in bootinfo["page_info"].items():
			if previous[name]["modified"] != page["modified"]:
				storage.pop("_page:" + name, None)
		self.assertEqual(storage, {"_page:operating-expenses": "old-code", "dlp-list:site:finance:Purchase%20Invoice": "custom-layout"})
		versions = copy.deepcopy(bootinfo["page_info"])
		branding.apply_boot_branding(bootinfo)
		self.assertEqual(bootinfo["page_info"], versions, "unchanged code must not evict cached pages repeatedly")

	def test_page_source_change_updates_only_its_hash_and_does_not_add_unauthorized_pages(self):
		bootinfo = self.bootinfo([])
		bootinfo["page_info"] = {"purchase-payables": {"modified": "native-v1"}}
		with patch.object(Path, "read_bytes", return_value=b"approved-page-code-v1"):
			branding.apply_boot_branding(bootinfo)
		self.assertEqual(set(bootinfo["page_info"]), {"purchase-payables"})
		first = bootinfo["page_info"]["purchase-payables"]["modified"]
		self.assertIn(hashlib.sha256(b"approved-page-code-v1").hexdigest(), first)
		branding._purchase_page_code_version.cache_clear()  # deployment starts a fresh process
		with patch.object(Path, "read_bytes", return_value=b"approved-page-code-v2"):
			branding.apply_boot_branding(bootinfo)
		self.assertNotEqual(bootinfo["page_info"]["purchase-payables"]["modified"], first)
		self.assertTrue(bootinfo["page_info"]["purchase-payables"]["modified"].startswith("native-v1|"))

	def test_purchase_page_source_hashes_read_three_fixed_files_once_per_process(self):
		with patch.object(Path, "read_bytes", return_value=b"approved-code") as read:
			for _ in range(2):
				bootinfo = self.bootinfo([])
				bootinfo["page_info"] = {name: {"modified": "native-v1"} for name in ("purchase-payables", "purchase-payment-records")}
				branding.apply_boot_branding(bootinfo)
		self.assertEqual(read.call_count, 3, "one AP source plus payment wrapper/adapter are process cached")


if __name__ == "__main__":
	unittest.main()
