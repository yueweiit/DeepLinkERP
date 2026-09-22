import frappe
from frappe.tests import IntegrationTestCase, set_user

from mobile_operations.bom import (
    get_mobile_bom_detail,
    get_mobile_bom_form_options,
    get_mobile_bom_list,
    save_mobile_bom,
    search_mobile_bom_items,
    submit_mobile_bom,
)


class TestMobileBOM(IntegrationTestCase):
    def setUp(self):
        super().setUp()
        self.addCleanup(frappe.db.rollback)
        self.token = "MOBILE-BOM-TEST-" + frappe.generate_hash(length=8)
        self.company = self.token
        frappe.get_doc(
            {
                "doctype": "Company",
                "name": self.company,
                "company_name": self.company,
                "abbr": frappe.generate_hash(length=5),
                "default_currency": "USD",
            }
        ).db_insert()
        group = frappe.db.get_value("Item Group", {"is_group": 0}, "name")
        self.product = self.token + "-FG"
        self.component = self.token + "-RM"
        for code, uom in ((self.product, "Nos"), (self.component, "Kg")):
            if not frappe.db.exists("UOM", uom):
                frappe.get_doc({"doctype": "UOM", "name": uom, "uom_name": uom}).db_insert()
            frappe.get_doc(
                {
                    "doctype": "Item",
                    "name": code,
                    "item_code": code,
                    "item_name": code,
                    "item_group": group,
                    "stock_uom": uom,
                    "is_stock_item": 1,
                    "include_item_in_manufacturing": 1,
                    "custom_specifications": "BLUE " + self.token,
                }
            ).db_insert()
        self.payload = {
            "company": self.company,
            "item": self.product,
            "quantity": 2,
            "specification": "BLUE " + self.token,
            "items": [{"item_code": self.component, "qty": 0.04925, "scrap_rate": 2.5}],
        }

    def test_create_edit_and_submit_preserves_precise_quantities_and_metadata(self):
        created = save_mobile_bom(self.payload)
        self.assertEqual(created["docstatus"], 0)
        doc = frappe.get_doc("BOM", created["name"])
        self.assertEqual(doc.currency, "USD")
        self.assertEqual(doc.items[0].qty, 0.04925)
        self.assertEqual(doc.items[0].stock_uom, "Kg")
        doc.items[0].do_not_explode = 1
        doc.items[0].description = "Keep the original component notes"
        doc.save()
        detail = get_mobile_bom_detail(doc.name)
        self.assertTrue(detail["can_edit"])
        self.assertTrue(detail["can_submit"])
        detail["items"][0]["qty"] = 0.0985
        updated = save_mobile_bom(detail)
        doc.reload()
        self.assertEqual(doc.items[0].qty, 0.0985)
        self.assertEqual(doc.items[0].stock_qty, 0.0985)
        self.assertEqual(doc.items[0].do_not_explode, 1)
        self.assertEqual(doc.items[0].description, "Keep the original component notes")
        if doc.items[0].meta.has_field("custom_scrap_rate"):
            self.assertEqual(doc.items[0].custom_scrap_rate, 2.5)
        result = submit_mobile_bom(updated["name"], str(doc.modified))
        self.assertEqual(result["docstatus"], 1)
        detail = get_mobile_bom_detail(doc.name)
        self.assertEqual(detail["status"], "active")
        self.assertFalse(detail["can_edit"])
        self.assertAlmostEqual(detail["exploded_items"][0]["qty"], 0.0985)
        with self.assertRaises(frappe.ValidationError):
            save_mobile_bom(detail)

    def test_save_and_submit_and_filter_pagination(self):
        first = save_mobile_bom(self.payload, submit=1)
        second = save_mobile_bom(self.payload)
        active = get_mobile_bom_list(search=self.token)
        self.assertEqual([row["name"] for row in active["entries"]], [first["name"]])
        drafts = get_mobile_bom_list(search=self.token, status="draft")
        self.assertEqual([row["name"] for row in drafts["entries"]], [second["name"]])
        page = get_mobile_bom_list(company=self.company, status="all", limit=1)
        self.assertEqual(page["total"], 2)
        self.assertTrue(page["has_more"])
        next_page = get_mobile_bom_list(company=self.company, status="all", limit=1, offset=1)
        self.assertFalse(next_page["has_more"])
        self.assertNotEqual(page["entries"][0]["name"], next_page["entries"][0]["name"])
        self.assertEqual(page["entries"][0]["item_count"], 1)
        if frappe.get_meta("BOM").has_field("custom_bom_specification"):
            self.assertEqual(get_mobile_bom_list(search=self.payload["specification"])["total"], 1)

    def test_stale_edits_and_invalid_child_rows_are_rejected(self):
        created = save_mobile_bom(self.payload)
        detail = get_mobile_bom_detail(created["name"])
        save_mobile_bom(detail)
        with self.assertRaises(frappe.TimestampMismatchError):
            save_mobile_bom(detail)
        with self.assertRaises(frappe.TimestampMismatchError):
            submit_mobile_bom(detail["name"], detail["modified"])
        detail = get_mobile_bom_detail(created["name"])
        detail["items"][0]["name"] = "a-row-from-another-bom"
        with self.assertRaises(frappe.ValidationError):
            save_mobile_bom(detail)

    def test_invalid_quantities_are_rejected(self):
        for quantity in (0, -1, "NaN", "Infinity"):
            with self.subTest(quantity=quantity), self.assertRaises(frappe.ValidationError):
                save_mobile_bom({**self.payload, "quantity": quantity})
            with self.subTest(component_quantity=quantity), self.assertRaises(frappe.ValidationError):
                save_mobile_bom({**self.payload, "items": [{"item_code": self.component, "qty": quantity}]})

    def test_endpoints_enforce_bom_permissions(self):
        created = save_mobile_bom(self.payload)
        with set_user("Guest"):
            for function, args in (
                (get_mobile_bom_list, {}),
                (get_mobile_bom_detail, {"name": created["name"]}),
                (get_mobile_bom_form_options, {}),
                (search_mobile_bom_items, {"search": self.token}),
                (save_mobile_bom, {"data": self.payload}),
                (submit_mobile_bom, {"name": created["name"]}),
            ):
                with self.subTest(function=function.__name__), self.assertRaises(frappe.PermissionError):
                    function(**args)
