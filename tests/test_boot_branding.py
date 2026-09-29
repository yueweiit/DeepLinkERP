import copy
import importlib
import sys
import types
import unittest


FAKE_FRAPPE = types.ModuleType("frappe")
FAKE_FRAPPE.session = types.SimpleNamespace(user="Guest")

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
		self.configure_user("employee@example.com", roles=["Employee"])

	def configure_user(self, user, roles, blocked_by_user=None):
		blocked_by_user = blocked_by_user or {}
		FAKE_FRAPPE.session.user = user
		FAKE_FRAPPE.get_roles = lambda: list(roles)

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


if __name__ == "__main__":
	unittest.main()
