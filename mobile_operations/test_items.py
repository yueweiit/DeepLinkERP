from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase, set_user

from mobile_operations.items import (
    create_mobile_item,
    get_mobile_item_creation_status,
    get_mobile_item_detail,
    get_mobile_item_form_options,
    get_mobile_item_list,
    search_mobile_item_references,
)


class TestMobileItems(IntegrationTestCase):
    def setUp(self):
        super().setUp()
        self.addCleanup(frappe.db.rollback)
        self.token = "ZZMOBILEITEM" + frappe.generate_hash(length=8).upper()
        self.group = frappe.db.get_value("Item Group", {"is_group": 0}, "name")
        self.uom = frappe.db.get_value("UOM", {}, "name")

    def insert_fixture(self, suffix, **values):
        code = self.token + suffix
        doc = frappe.get_doc(
            {
                "doctype": "Item",
                "item_code": code,
                "item_name": values.pop("item_name", "Mobile item " + suffix),
                "item_group": self.group,
                "stock_uom": self.uom,
                **values,
            }
        )
        doc.db_insert()
        return code

    def make_read_only_user(self):
        user = frappe.get_doc({
            "doctype": "User",
            "email": self.token.lower() + "@example.com",
            "first_name": "Mobile Item Reader",
            "user_type": "System User",
            "send_welcome_email": 0,
        }).insert(ignore_permissions=True)
        user.add_roles("Stock User")
        return user.name

    def test_list_search_detail_and_pagination(self):
        first = self.insert_fixture("-01", custom_specifications="SPEC-" + self.token)
        second = self.insert_fixture("-02", custom_mnemonic_code="MEMO-" + self.token)
        self.insert_fixture("-03", disabled=1)

        page = get_mobile_item_list(search=self.token, limit=1)
        self.assertEqual(page["total"], 2)
        self.assertEqual(page["entries"][0]["name"], first)
        self.assertTrue(page["has_more"])
        next_page = get_mobile_item_list(search=self.token, limit=1, offset=1)
        self.assertEqual(next_page["entries"][0]["name"], second)

        specification = get_mobile_item_list(search="SPEC-" + self.token)
        self.assertEqual([row["name"] for row in specification["entries"]], [first])
        mnemonic = get_mobile_item_list(search="MEMO-" + self.token)
        self.assertEqual([row["name"] for row in mnemonic["entries"]], [second])
        disabled = get_mobile_item_list(search=self.token, status="disabled")
        self.assertEqual([row["name"] for row in disabled["entries"]], [self.token + "-03"])

        detail = get_mobile_item_detail(first)
        self.assertEqual(detail["custom_specifications"], "SPEC-" + self.token)
        self.assertEqual(detail["stock_uom"], self.uom)

    def test_create_uses_standard_item_validation(self):
        code = self.token + "-NEW"
        self.assertFalse(get_mobile_item_creation_status(code)["name"])
        result = create_mobile_item(
            {
                "item_code": code,
                "item_name": "Created on mobile",
                "item_group": self.group,
                "stock_uom": self.uom,
                "custom_specifications": "Blue",
                "is_stock_item": 1,
                "is_purchase_item": 1,
                "is_sales_item": 0,
            }
        )
        self.assertEqual(result["name"], code)
        self.assertEqual(get_mobile_item_creation_status(code)["name"], code)
        doc = frappe.get_doc("Item", code)
        self.assertEqual(doc.item_name, "Created on mobile")
        self.assertEqual(doc.custom_specifications, "Blue")
        self.assertFalse(doc.is_sales_item)
        with self.assertRaises(frappe.DuplicateEntryError):
            create_mobile_item(
                {"item_code": code, "item_group": self.group, "stock_uom": self.uom}
            )

    def test_form_options_and_references(self):
        options = get_mobile_item_form_options()
        self.assertIn("is_stock_item", options["defaults"])
        groups = search_mobile_item_references("item_group", self.group, 10)
        self.assertIn(self.group, [row["value"] for row in groups])
        parent = frappe.db.get_value("Item Group", self.group, "parent_item_group")
        self.assertNotIn(parent, [row["value"] for row in search_mobile_item_references("item_group", parent, 50)])
        uoms = search_mobile_item_references("uom", self.uom, 10)
        self.assertIn(self.uom, [row["value"] for row in uoms])

    def test_read_only_custom_field_is_hidden_and_ignored_on_create(self):
        code = self.token + "-READONLY"
        field = frappe.get_meta("Item").get_field("custom_specifications")
        with patch.object(field, "read_only", 1):
            self.assertNotIn("custom_specifications", get_mobile_item_form_options()["custom_fields"])
            create_mobile_item({
                "item_code": code,
                "item_group": self.group,
                "stock_uom": self.uom,
                "custom_specifications": "Should not be saved",
            })
        self.assertFalse(frappe.db.get_value("Item", code, "custom_specifications"))

    def test_read_only_user_can_filter_parent_group_but_not_create(self):
        code = self.insert_fixture("-READ")
        parent = frappe.db.get_value("Item Group", self.group, "parent_item_group")
        self.assertTrue(parent)
        with set_user(self.make_read_only_user()):
            self.assertTrue(frappe.has_permission("Item", "read"))
            self.assertFalse(frappe.has_permission("Item", "create"))
            groups = search_mobile_item_references("list_item_group", parent, 50)
            self.assertIn(parent, [row["value"] for row in groups])
            entries = get_mobile_item_list(search=code, item_group=parent)["entries"]
            self.assertIn(code, [row["name"] for row in entries])
            with self.assertRaises(frappe.PermissionError):
                search_mobile_item_references("item_group", self.group)

    def test_restricted_custom_field_is_not_returned_or_searched(self):
        secret = "SECRET-" + self.token
        code = self.insert_fixture("-FIELD", custom_specifications=secret)
        field = frappe.get_meta("Item").get_field("custom_specifications")
        with patch.object(field, "permlevel", 1), set_user(self.make_read_only_user()):
            self.assertFalse(get_mobile_item_detail(code)["custom_specifications"])
            self.assertEqual(get_mobile_item_list(search=secret)["total"], 0)
            self.assertFalse(get_mobile_item_list(search=code)["entries"][0]["custom_specifications"])

    def test_endpoints_enforce_item_permissions(self):
        code = self.insert_fixture("-PERM")
        with set_user("Guest"):
            for function, args in (
                (get_mobile_item_list, {}),
                (get_mobile_item_detail, {"name": code}),
                (get_mobile_item_form_options, {}),
                (get_mobile_item_creation_status, {"item_code": code}),
                (search_mobile_item_references, {"kind": "list_item_group"}),
                (search_mobile_item_references, {"kind": "uom"}),
                (
                    create_mobile_item,
                    {"data": {"item_code": self.token + "-DENIED", "item_group": self.group, "stock_uom": self.uom}},
                ),
            ):
                with self.subTest(function=function.__name__), self.assertRaises(frappe.PermissionError):
                    function(**args)
