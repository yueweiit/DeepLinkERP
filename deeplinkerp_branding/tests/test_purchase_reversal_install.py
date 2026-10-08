"""One narrow pointer field, preflighted before additive metadata writes."""
import importlib.util
import unittest
from unittest.mock import Mock, patch

import frappe


class ReversalInstallTests(unittest.TestCase):
    def setUp(self):
        path = "deeplinkerp_branding.purchase_reversal_install"
        self.assertIsNotNone(importlib.util.find_spec(path), "Narrow reversal metadata installer is missing")
        self.install = __import__(path, fromlist=["install"])
        self.expected = {"Bin", "Purchase Order", "Purchase Receipt", "Purchase Invoice", "Payment Entry", "Repost Item Valuation"}

    def test_only_six_pointer_fields_and_indexes_are_added_without_business_backfill(self):
        db = Mock(); db.exists.return_value = True
        meta = Mock(); meta.get_field.return_value = None
        with patch.object(frappe, "db", db), patch.object(frappe, "get_meta", return_value=meta), \
                patch("frappe.custom.doctype.custom_field.custom_field.create_custom_fields") as create:
            self.install.after_migrate()
        definitions = create.call_args.args[0]
        self.assertEqual(set(definitions), self.expected)
        for fields in definitions.values():
            self.assertEqual(len(fields), 1)
            field = fields[0]
            self.assertEqual({key: field[key] for key in ("fieldname", "fieldtype", "options", "hidden", "read_only", "no_copy")},
                {"fieldname": "custom_purchase_reversal_operation", "fieldtype": "Link", "options": "Integration Request", "hidden": 1, "read_only": 1, "no_copy": 1})
        self.assertEqual({call.args[0] for call in db.add_index.call_args_list}, self.expected)
        db.set_value.assert_not_called(); db.sql.assert_not_called(); db.commit.assert_not_called()

    def test_existing_compatible_definitions_are_preserved_on_repeated_install(self):
        definition = frappe._dict(fieldtype="Link", options="Integration Request", hidden=1, read_only=1, no_copy=1, label="Existing")
        meta = Mock(); meta.get_field.return_value = definition
        db = Mock(); db.exists.return_value = True
        with patch.object(frappe, "db", db), patch.object(frappe, "get_meta", return_value=meta), \
                patch("frappe.custom.doctype.custom_field.custom_field.create_custom_fields") as create:
            self.install.after_migrate(); self.install.after_migrate()
        create.assert_not_called()
        self.assertEqual(definition.label, "Existing")

    def test_conflicting_field_or_missing_doctype_refuses_before_any_metadata_write(self):
        for kind in ("conflict", "missing"):
            with self.subTest(kind=kind):
                db = Mock(); db.exists.side_effect = lambda dt, name: not (kind == "missing" and name == "Payment Entry")
                meta = Mock(); meta.get_field.return_value = frappe._dict(fieldtype="Data") if kind == "conflict" else None
                with patch.object(frappe, "db", db), patch.object(frappe, "get_meta", return_value=meta), \
                        patch("frappe.custom.doctype.custom_field.custom_field.create_custom_fields") as create:
                    with self.assertRaises(frappe.ValidationError): self.install.after_migrate()
                create.assert_not_called(); db.add_index.assert_not_called()

    def test_missing_native_metadata_refuses_before_any_addition(self):
        db = Mock(); db.exists.return_value = True
        meta = Mock(); meta.get_field.return_value = None; meta.has_field.return_value = False
        with patch.object(frappe, "db", db), patch.object(frappe, "get_meta", return_value=meta), \
                patch("frappe.custom.doctype.custom_field.custom_field.create_custom_fields") as create:
            with self.assertRaises(frappe.ValidationError): self.install.after_migrate()
        create.assert_not_called(); db.add_index.assert_not_called()

    def test_metadata_only_virtual_or_missing_native_columns_refuse_before_addition(self):
        for kind in ("pointer_column", "native_column", "virtual"):
            with self.subTest(kind=kind):
                definition = frappe._dict(fieldtype="Link", options="Integration Request", hidden=1,
                    read_only=1, no_copy=1, is_virtual=int(kind == "virtual"))
                db = Mock(); db.exists.return_value = True
                db.has_column.side_effect = lambda dt, field: not (
                    kind == "pointer_column" and dt == "Payment Entry" and field == self.install.FIELDNAME or
                    kind == "native_column" and dt == "Payment Entry" and field == "company")
                meta = Mock(); meta.get_field.return_value = definition
                with patch.object(frappe, "db", db), patch.object(frappe, "get_meta", return_value=meta), \
                        patch("frappe.custom.doctype.custom_field.custom_field.create_custom_fields") as create:
                    with self.assertRaises(frappe.ValidationError): self.install.after_migrate()
                create.assert_not_called(); db.add_index.assert_not_called()
