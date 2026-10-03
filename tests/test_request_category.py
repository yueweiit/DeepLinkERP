"""Source-category contract; runnable without a live ERP database."""
import importlib.util
import ast
import sys
from types import SimpleNamespace
from unittest.mock import patch
from pathlib import Path
import unittest


MODULE = Path(__file__).resolve().parents[1] / "mes_integration/mes_integration/request_category.py"


class TestRequestCategory(unittest.TestCase):
    def setUp(self):
        self.assertTrue(MODULE.exists(), "Missing MES source category contract")
        spec = importlib.util.spec_from_file_location("request_category", MODULE)
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)

    def test_optional_category_and_existing_values(self):
        for value in (None, "", "consumable", "semi_finished", "raw_material", "unclassified"):
            with self.subTest(value=value):
                self.assertEqual(self.module.validate_category(value), value or "")
        for value in ("Material Issue", "unknown", ["consumable"], 1):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.module.validate_category(value)

    def test_history_plan_only_unique_exact_identities(self):
        sources = [
            dict(company="CN", request_no="A", erp_name="MR-A", category="consumable"),
            dict(company="CN", request_no="B", erp_name="MR-B", category="raw_material"),
            dict(company="CN", request_no="C", erp_name="MR-C", category="semi_finished"),
            dict(company="CN", request_no="D", erp_name="MR-D", category="raw_material"),
        ]
        rows = [
            dict(name="MR-A", company="CN", custom_material_request_no="A", custom_mes_issue_category=""),
            dict(name="MR-B", company="OTHER", custom_material_request_no="B", custom_mes_issue_category=""),
            dict(name="MR-C", company="CN", custom_material_request_no="C", custom_mes_issue_category="consumable"),
            dict(name="MR-D", company="CN", custom_material_request_no="D", custom_mes_issue_category=""),
            dict(name="MR-DUP", company="CN", custom_material_request_no="D", custom_mes_issue_category=""),
        ]
        result = self.module.plan_category_backfill(sources, rows)
        self.assertEqual([r["name"] for r in result["updates"]], ["MR-A"])
        self.assertEqual(len(result["skipped"]), 3)
        self.assertEqual(result["updates"][0]["category"], "consumable")
        self.assertEqual(rows[0]["custom_mes_issue_category"], "")

    def test_duplicate_sources_and_missing_evidence_are_not_inferred(self):
        source = dict(company="CN", request_no="A", erp_name="MR-A", category="consumable")
        rows = [dict(name="MR-A", company="CN", custom_material_request_no="A", custom_odt="")]
        result = self.module.plan_category_backfill([source, source], rows)
        self.assertEqual(result["updates"], [])
        self.assertEqual(self.module.plan_category_backfill([dict(source, category="")], rows)["updates"], [])

    def test_snapshot_guard_includes_all_identity_fields_and_category(self):
        source = dict(company="CN", request_no="A", erp_name="MR-A", category="consumable")
        row = dict(name="MR-A", company="CN", custom_material_request_no="A", modified="2026-10-03", custom_mes_issue_category="")
        update = self.module.plan_category_backfill([source], [row])["updates"][0]
        self.assertEqual(update["expected"], {key: row.get(key) or "" for key in ("name", "company", "custom_material_request_no", "modified", "custom_mes_issue_category")})

    def test_payload_validation_rejects_unknown_category_before_queueing(self):
        path = MODULE.with_name("material_request.py")
        tree = ast.parse(path.read_text())
        fn = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "validate_mes_material_request_payload")
        class Frappe:
            @staticmethod
            def throw(message):
                raise ValueError(message)
        namespace = {"frappe": Frappe, "_": lambda value: value, "flt": float, "validate_category": self.module.validate_category}
        exec(compile(ast.Module(body=[fn], type_ignores=[]), str(path), "exec"), namespace)
        payload = dict(doctype="Material Request", company="CN", material_request_type="Material Issue", items=[dict(item_code="A", qty=1)])
        namespace[fn.name](payload)
        with self.assertRaises(ValueError):
            namespace[fn.name](dict(payload, custom_mes_issue_category="unknown"))

    def test_apply_requires_review_digest_and_unchanged_locked_identity(self):
        row = dict(name="MR-A", company="CN", custom_material_request_no="A", modified="today", custom_mes_issue_category="")
        plan = self.module.plan_category_backfill([dict(company="CN", request_no="A", erp_name="MR-A", category="consumable")], [row])
        self.assertTrue(hasattr(self.module, "apply_category_backfill"), "Missing guarded metadata backfill")
        from unittest.mock import MagicMock
        db = MagicMock()
        db.sql.return_value = [row]
        frappe = SimpleNamespace(db=db, only_for=MagicMock())
        with patch.dict(sys.modules, {"frappe": frappe}):
            with self.assertRaises(ValueError):
                self.module.apply_category_backfill(plan, "wrong")
            db.set_value.assert_not_called()
            digest = self.module.plan_digest(plan)
            db.sql.return_value = [dict(row, custom_mes_issue_category="raw_material")]
            with self.assertRaises(ValueError):
                self.module.apply_category_backfill(plan, digest)
            db.set_value.assert_not_called()
            db.sql.return_value = [row]
            result = self.module.apply_category_backfill(plan, digest)
        self.assertEqual(result["applied"][0]["name"], "MR-A")
        db.set_value.assert_called_once_with("Material Request", "MR-A", "custom_mes_issue_category", "consumable", update_modified=False)
        self.assertIn("FOR UPDATE", db.sql.call_args.args[0])
        frappe.only_for.assert_called_with("System Manager")


if __name__ == "__main__":
    unittest.main()
