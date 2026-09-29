import csv
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOCTYPE_JSON = (
	ROOT
	/ "deeplinkerp_branding"
	/ "deeplinkerp_branding"
	/ "doctype"
	/ "deeplinkerp_interface_settings"
	/ "deeplinkerp_interface_settings.json"
)
WORKSPACE_JSON = (
	ROOT
	/ "deeplinkerp_branding"
	/ "deeplinkerp_branding"
	/ "workspace"
	/ "deeplinkerp_settings"
	/ "deeplinkerp_settings.json"
)
ZH_TRANSLATIONS = ROOT / "deeplinkerp_branding" / "translations" / "zh.csv"


class InterfaceModeMetadataTest(unittest.TestCase):
	def test_single_doctype_has_one_required_company_default_field(self):
		self.assertTrue(DOCTYPE_JSON.exists(), "interface settings DocType JSON must exist")
		metadata = json.loads(DOCTYPE_JSON.read_text())

		self.assertEqual(metadata["name"], "DeepLinkERP Interface Settings")
		self.assertEqual(metadata["doctype"], "DocType")
		self.assertEqual(metadata["module"], "Deeplinkerp Branding")
		self.assertEqual(metadata["issingle"], 1)
		self.assertEqual(metadata["field_order"], ["default_navigation_mode"])
		self.assertEqual(len(metadata["fields"]), 1)

		field = metadata["fields"][0]
		self.assertEqual(field["fieldname"], "default_navigation_mode")
		self.assertEqual(field["fieldtype"], "Select")
		self.assertEqual(set(field["options"].splitlines()), {"classic", "dl"})
		self.assertEqual(field["default"], "dl")
		self.assertEqual(field["reqd"], 1)

	def test_single_doctype_is_managed_only_by_system_manager(self):
		self.assertTrue(DOCTYPE_JSON.exists(), "interface settings DocType JSON must exist")
		metadata = json.loads(DOCTYPE_JSON.read_text())

		self.assertEqual(len(metadata["permissions"]), 1)
		permission = metadata["permissions"][0]
		self.assertEqual(permission["role"], "System Manager")
		self.assertEqual(permission["read"], 1)
		self.assertEqual(permission["write"], 1)
		self.assertEqual(permission["create"], 1)

	def test_existing_settings_workspace_adds_one_interface_shortcut(self):
		workspace = json.loads(WORKSPACE_JSON.read_text())
		shortcuts = [
			shortcut
			for shortcut in workspace["shortcuts"]
			if shortcut.get("link_to") == "DeepLinkERP Interface Settings"
		]
		content = json.loads(workspace["content"])
		content_shortcuts = [
			block
			for block in content
			if block.get("type") == "shortcut"
			and block.get("data", {}).get("shortcut_name") == "界面与导航"
		]

		self.assertEqual(len(shortcuts), 1)
		self.assertEqual(shortcuts[0]["label"], "界面与导航")
		self.assertEqual(shortcuts[0]["type"], "DocType")
		self.assertEqual(len(content_shortcuts), 1)
		self.assertIn("System Settings", [item["label"] for item in workspace["shortcuts"]])
		self.assertIn("Global Defaults", [item["label"] for item in workspace["shortcuts"]])

	def test_chinese_translations_keep_storage_values_user_friendly(self):
		self.assertTrue(ZH_TRANSLATIONS.exists(), "Chinese translations must exist")
		with ZH_TRANSLATIONS.open(newline="") as translation_file:
			translations = {row[0]: row[1] for row in csv.reader(translation_file) if len(row) >= 2}

		self.assertEqual(translations["classic"], "经典模式")
		self.assertEqual(translations["dl"], "DL 模式")
		self.assertEqual(translations["Default Interface Mode"], "公司默认界面模式")


if __name__ == "__main__":
	unittest.main()
