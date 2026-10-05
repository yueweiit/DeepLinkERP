"""Navigation configuration contracts; no database or role mutations."""
import copy
import importlib.util
import json
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch


class Row(dict):
    def __getattr__(self, key):
        if key.startswith("__"):
            raise AttributeError(key)
        return self.get(key)

    def __setattr__(self, key, value):
        self[key] = value

    def set(self, key, value):
        self[key] = value


class Doc(Row):
    def append(self, table, values):
        row = Row(values, name=f"new-{len(self[table])}")
        self[table].append(row)
        return row


fake = types.ModuleType("frappe")
spec = importlib.util.spec_from_file_location("navigation_contract", Path(__file__).parents[1] / "deeplinkerp_branding/procurement_navigation.py")
navigation = importlib.util.module_from_spec(spec)
with patch.dict(sys.modules, {"frappe": fake}):
    spec.loader.exec_module(navigation)


class ProcurementNavigationTest(unittest.TestCase):
    def test_shared_sidebar_keeps_native_row_identity_and_custom_filtered_routes(self):
        rows = [Row(name="home", link_to="Buying", label="Home"),
                Row(name="order", link_type="DocType", link_to="Purchase Order", label="Purchase Order"),
                Row(name="invoice", link_type="DocType", link_to="Purchase Invoice", label="Purchase Invoice"),
                Row(name="custom", link_type="DocType", link_to="Purchase Order", label="My filter", filters='[["status","=","Draft"]]'),
                Row(name="report", link_type="Report", link_to="Purchase Analytics", label="Analytics")]
        doc = Doc(items=rows)
        custom = copy.deepcopy(rows[3])
        self.assertTrue(navigation.reconcile_links(doc, "items"))
        self.assertEqual([row.link_to for row in doc["items"][1:5]], [entry[2] for entry in navigation.ENTRIES])
        self.assertEqual(doc["items"][1].name, "order")
        self.assertEqual(doc["items"][5].filters, custom["filters"])
        self.assertEqual(doc["items"][5].name, custom["name"])
        snapshot = copy.deepcopy(doc)
        self.assertFalse(navigation.reconcile_links(doc, "items"))
        self.assertEqual(doc, snapshot)

    def test_workspace_keeps_custom_shortcut_chart_and_card_content(self):
        doc = Doc(links=[Row(name="card", type="Card Break", label="Buying"), Row(name="po", link_to="Purchase Order", label="Purchase Order")],
                  shortcuts=[Row(name="mine", type="DocType", link_to="Purchase Invoice", label="My operations", filters='[["company","=","C"]]')],
                  content=json.dumps([{"id":"chart","type":"chart","data":{"chart_name":"Purchase Order Trends"}},
                                      {"id":"mine","type":"shortcut","data":{"shortcut_name":"My operations","col":4}}]))
        self.assertTrue(navigation.reconcile_workspace(doc))
        content = json.loads(doc.content)
        self.assertEqual([block["data"]["shortcut_name"] for block in content[:4]], [entry[0] for entry in navigation.ENTRIES])
        self.assertEqual(content[-1]["id"], "mine")
        self.assertEqual(doc.shortcuts[-1].name, "mine")
        self.assertEqual(doc.links[0].name, "card")
        snapshot = copy.deepcopy(doc)
        self.assertFalse(navigation.reconcile_workspace(doc))
        self.assertEqual(doc, snapshot)

    def test_configuration_hook_does_not_save_pages_roles_or_other_workspaces(self):
        sidebar = Doc(items=[])
        workspace = Doc(links=[], shortcuts=[], content="[]")
        saved = []
        sidebar.save = lambda **kwargs: saved.append("Workspace Sidebar")
        workspace.save = lambda **kwargs: saved.append("Workspace")
        fake.db = types.SimpleNamespace(exists=lambda doctype, name: True)
        fake.get_doc = lambda doctype, name: {"Workspace Sidebar": sidebar, "Workspace": workspace}[doctype]
        fake.flags = Row(in_import=False)
        fake.conf = Row(developer_mode=True)
        self.assertEqual(navigation.ensure_procurement_navigation()["changed"], ["Workspace Sidebar", "Workspace"])
        self.assertEqual(navigation.ensure_procurement_navigation()["changed"], [])
        self.assertEqual(saved, ["Workspace Sidebar", "Workspace"])
        self.assertFalse(fake.flags.in_import)
        self.assertTrue(fake.conf.developer_mode)
