import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.convert_plm_seeds_to_import_xlsx import build_conversion, write_simple_workbook


class ConvertPlmSeedsToImportXlsxTest(unittest.TestCase):
    def test_root_product_rows_are_product_lines(self):
        data = build_conversion()

        invalid_rows = [
            row["product_code"]
            for row in data["product"]
            if row.get("product_type") == "model_variant" and not row.get("parent_product_code")
        ]

        self.assertEqual([], invalid_rows)

    def test_inventory_conversion_uses_material_import_headers(self):
        data = build_conversion()

        self.assertGreater(len(data["inventory"]), 0)
        first_inventory = data["inventory"][0]
        for header in ["物料组", "物料编码", "物料名称", "规格型号", "规格", "新增日期"]:
            self.assertIn(header, first_inventory)

    def test_simple_import_workbook_uses_shared_strings_for_poi_compatibility(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "product_import.xlsx"
            write_simple_workbook(
                path,
                "product_template",
                ["product_code", "product_name"],
                [{"product_code": "P001", "product_name": "Demo"}],
                [],
            )

            with zipfile.ZipFile(path) as workbook:
                names = set(workbook.namelist())
                sheet_xml = workbook.read("xl/worksheets/sheet1.xml").decode("utf-8")
                shared_strings_xml = workbook.read("xl/sharedStrings.xml").decode("utf-8")

            self.assertIn("xl/sharedStrings.xml", names)
            self.assertIn("product_code", shared_strings_xml)
            self.assertNotIn('t="inlineStr"', sheet_xml)


if __name__ == "__main__":
    unittest.main()
