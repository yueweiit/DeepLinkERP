"""Operating navigation uses the shared upsert and preserves all other links."""

import copy
import importlib.util
import json
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from tests.test_procurement_navigation import Doc, Row, navigation

ROOT = Path(__file__).parents[1]
MODULE = ROOT / "deeplinkerp_branding/operating_navigation.py"


class OperatingNavigationTest(unittest.TestCase):
	def test_shared_reconcile_accepts_narrow_entries_without_reordering_custom_links(self):
		doc = Doc(
			items=[
				Row(name="a", link_to="Sales Invoice"),
				Row(name="b", link_to="Journal Entry"),
				Row(name="custom", link_to="operating-expenses", filters="mine"),
			]
		)
		original = copy.deepcopy(doc["items"])
		args = dict(
			entries=(("运营费用", "Page", "operating-expenses", "receipt-text"),),
			targets={"operating-expenses"},
			anchor=3,
		)
		self.assertTrue(navigation.reconcile_links(doc, "items", **args))
		self.assertEqual([r.name for r in doc["items"][:3]], [r.name for r in original])
		self.assertEqual(doc["items"][2].filters, "mine")
		snapshot = copy.deepcopy(doc)
		self.assertFalse(navigation.reconcile_links(doc, "items", **args))
		self.assertEqual(doc, snapshot)

	def test_workspace_prefix_preserves_procurement_blocks_and_custom_shortcut_order(self):
		doc = Doc(
			links=[],
			shortcuts=[],
			content=json.dumps(
				[
					{"id": "dlp-procurement-0", "type": "shortcut", "data": {"shortcut_name": "采购订单"}},
					{"id": "chart", "type": "chart"},
				]
			),
		)
		args = dict(
			entries=(("运营费用", "Page", "operating-expenses", "receipt-text"),),
			prefix="dlp-operating-",
			targets={"operating-expenses"},
			anchor=0,
		)
		self.assertTrue(navigation.reconcile_workspace(doc, **args))
		self.assertEqual([b["id"] for b in json.loads(doc.content)][1:], ["dlp-procurement-0", "chart"])
		self.assertFalse(navigation.reconcile_workspace(doc, **args))

	def test_custom_shortcut_with_same_label_keeps_its_block(self):
		block = {"id": "custom", "type": "shortcut", "data": {"shortcut_name": "运营费用"}}
		doc = Doc(
			links=[],
			shortcuts=[
				Row(name="custom-row", link_to="operating-expenses", label="运营费用", filters="mine")
			],
			content=json.dumps([block]),
		)
		navigation.reconcile_workspace(
			doc,
			entries=(("运营费用", "Page", "operating-expenses", "receipt-text"),),
			targets={"operating-expenses"},
			prefix="dlp-operating-",
			anchor=0,
		)
		self.assertIn(block, json.loads(doc.content))
		self.assertEqual(doc["shortcuts"][-1].name, "custom-row")

	def load_module(self, fake):
		self.assertTrue(MODULE.exists(), "Narrow operating navigation hook missing")
		spec = importlib.util.spec_from_file_location("operating_navigation_contract", MODULE)
		module = importlib.util.module_from_spec(spec)
		with patch.dict(
			sys.modules, {"frappe": fake, "deeplinkerp_branding.procurement_navigation": navigation}
		):
			spec.loader.exec_module(module)
		return module

	def test_only_existing_finance_workspaces_are_saved_and_second_run_is_idle(self):
		sidebar = Doc(
			items=[
				Row(name="daily", type="Section Break", label="日常工作"),
				Row(name="je", link_to="Journal Entry"),
			],
			flags=Row(),
		)
		workspace = Doc(links=[], shortcuts=[], content="[]", flags=Row())
		saved = []
		sidebar.save = lambda **kw: saved.append("sidebar")
		workspace.save = lambda **kw: saved.append("workspace")
		fake = types.ModuleType("frappe")
		fake.flags = Row(in_import=False)
		fake.conf = Row(developer_mode=True)
		fake.db = types.SimpleNamespace(
			exists=lambda dt, name: name == "operating-expenses" if dt == "Page" else name == "China Finance"
		)
		requested = []

		def get_doc(dt, name):
			requested.append((dt, name))
			return sidebar if dt == "Workspace Sidebar" else workspace

		fake.get_doc = get_doc
		module = self.load_module(fake)
		self.assertEqual(len(module.ensure_operating_navigation()["changed"]), 2)
		self.assertEqual(module.ensure_operating_navigation()["changed"], [])
		self.assertEqual(saved, ["sidebar", "workspace"])
		self.assertEqual({n for dt, n in requested}, {"China Finance"})
		self.assertEqual(sidebar["items"][0].name, "daily")
		self.assertEqual(sidebar["items"][1].name, "je")
		self.assertFalse(fake.flags.in_import)
		self.assertTrue(fake.conf.developer_mode)

	def test_missing_page_prevents_any_navigation_read_or_write(self):
		fake = types.ModuleType("frappe")
		fake.db = types.SimpleNamespace(exists=lambda *_: False)
		fake.get_doc = lambda *_: self.fail("No Workspace read before native Page exists")
		result = self.load_module(fake).ensure_operating_navigation()
		self.assertFalse(result["ok"])
		self.assertEqual(result["missing_page"], "operating-expenses")
