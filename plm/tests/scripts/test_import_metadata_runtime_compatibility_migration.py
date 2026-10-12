from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[2]
MIGRATION = (
    ROOT
    / "plm-server"
    / "src"
    / "main"
    / "resources"
    / "db"
    / "migration"
    / "V20260727_1320__import_metadata_runtime_compatibility.sql"
)


class ImportMetadataRuntimeCompatibilityMigrationTest(unittest.TestCase):
    def test_migration_aligns_legacy_import_metadata_with_runtime_values(self):
        sql = MIGRATION.read_text(encoding="utf-8").lower()

        self.assertIn("drop constraint if exists ck_plm_import_batch_object_type", sql)
        self.assertRegex(sql, r"ck_plm_import_batch_object_type[\s\S]*'inventory'")
        self.assertRegex(sql, r"ck_plm_import_batch_object_type[\s\S]*'inventory'")
        self.assertRegex(sql, r"ck_plm_import_batch_object_type[\s\S]*'attachment'")

        self.assertIn("drop constraint if exists ck_plm_import_detail_status", sql)
        self.assertRegex(sql, r"ck_plm_import_detail_status[\s\S]*'success'")
        self.assertRegex(sql, r"ck_plm_import_detail_status[\s\S]*'fail'")
        self.assertRegex(sql, r"ck_plm_import_detail_status[\s\S]*'skipped'")

        for column in ("raw_payload", "created_by", "updated_at", "updated_by", "deleted_flag"):
            self.assertRegex(
                sql,
                rf"alter table if exists plm_import_detail[\s\S]*add column if not exists {re.escape(column)}",
            )


if __name__ == "__main__":
    unittest.main()
