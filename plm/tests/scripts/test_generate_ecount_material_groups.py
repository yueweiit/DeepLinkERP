import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "generate_ecount_material_groups.py"


def load_module():
    spec = importlib.util.spec_from_file_location("generate_ecount_material_groups", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class GenerateEcountMaterialGroupsTest(unittest.TestCase):
    def test_build_groups_preserves_conflicting_major_names_and_links_minor_parent(self):
        module = load_module()

        groups = module.build_material_groups(
            [
                {
                    "ecount_major_code": "MJ",
                    "ecount_major_name": "模具",
                    "ecount_minor_code": "000001",
                    "ecount_minor_name": "模具A",
                },
                {
                    "ecount_major_code": "MJ",
                    "ecount_major_name": "模架",
                    "ecount_minor_code": "000001",
                    "ecount_minor_name": "模架A",
                },
                {
                    "ecount_major_code": "JG",
                    "ecount_major_name": "加工",
                    "ecount_minor_code": "000002",
                    "ecount_minor_name": "外协加工",
                },
                {
                    "ecount_major_code": "MJ",
                    "ecount_major_name": "模具",
                    "ecount_minor_code": "000001",
                    "ecount_minor_name": "模具A",
                },
            ]
        )

        self.assertEqual(["L1:JG:加工", "L1:MJ:模具", "L1:MJ:模架"], [g["group_key"] for g in groups["majors"]])
        self.assertEqual(3, len(groups["minors"]))

        mj_major = next(g for g in groups["majors"] if g["group_key"] == "L1:MJ:模具")
        self.assertEqual("MJ 模具/模架", mj_major["normalized_display_name"])
        self.assertEqual("tooling", mj_major["inventory_type"])
        self.assertEqual(1, mj_major["warning_flag"])

        minor = next(g for g in groups["minors"] if g["group_key"] == "L2:MJ:模具:000001:模具A")
        self.assertEqual("L1:MJ:模具", minor["parent_group_key"])
        self.assertEqual("000001 模具A", minor["display_name"])

        service_major = next(g for g in groups["majors"] if g["group_key"] == "L1:JG:加工")
        self.assertEqual("unsupported", service_major["inventory_type"])
        self.assertEqual(1, service_major["warning_flag"])
        self.assertIn("不建议自动导入 Inventory", service_major["warning_message"])

    def test_generate_sql_contains_table_indexes_and_seed_counts(self):
        module = load_module()

        groups = module.build_material_groups(
            [
                {
                    "ecount_major_code": "YL",
                    "ecount_major_name": "原料",
                    "ecount_minor_code": "000001",
                    "ecount_minor_name": "原料TPU",
                }
            ]
        )
        sql = module.generate_sql(groups)

        self.assertIn("create table if not exists plm_material_group", sql)
        self.assertIn("uk_plm_material_group_active_key", sql)
        self.assertIn("alter table if exists plm_inventory", sql)
        self.assertIn("'L1:YL:原料'", sql)
        self.assertIn("'L2:YL:原料:000001:原料TPU'", sql)
        self.assertIn("-- Seed counts: level1=1, level2=1", sql)


if __name__ == "__main__":
    unittest.main()
