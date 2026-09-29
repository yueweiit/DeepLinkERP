import copy
import importlib
import sys
import types
import unittest


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
	sys.modules.pop("deeplinkerp_branding.deeplinkerp_branding.interface_mode", None)
	branding = importlib.import_module("deeplinkerp_branding.deeplinkerp_branding.branding")
finally:
	if previous_frappe is None:
		del sys.modules["frappe"]
	else:
		sys.modules["frappe"] = previous_frappe


class BootBrandingTest(unittest.TestCase):
	def setUp(self):
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


if __name__ == "__main__":
	unittest.main()
