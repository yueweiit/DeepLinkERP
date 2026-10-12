from __future__ import annotations

import unittest
import tempfile
from pathlib import Path

from phone_watch import db


def insert_candidate(conn) -> int:
    db.upsert_candidate(
        conn,
        {
            "brand": "XIAOMI",
            "source_country": "CN",
            "missing_country": "MX",
            "model": "Redmi Test Trash",
            "normalized_model": "redmitesttrash",
            "source_url": "https://example.com/redmi-test-trash",
            "source_name": "Manual",
            "reason": "test",
            "first_seen_at": "2026-07-08T00:00:00+00:00",
            "last_seen_at": "2026-07-08T00:00:00+00:00",
            "sampling_status": "未开模",
        },
    )
    row = conn.execute(
        "SELECT id FROM candidates WHERE normalized_model = ?",
        ("redmitesttrash",),
    ).fetchone()
    return int(row["id"])


def insert_phone(conn) -> int:
    db.upsert_phone(
        conn,
        {
            "brand": "OPPO",
            "country": "MX",
            "model": "OPPO Test Trash",
            "normalized_model": "oppotesttrash",
            "source_url": "https://example.com/oppo-test-trash",
            "source_name": "Manual",
            "first_seen_at": "2026-07-08T00:00:00+00:00",
            "last_seen_at": "2026-07-08T00:00:00+00:00",
            "sampling_status": "未开模",
            "clean_stage": "manual",
        },
    )
    row = conn.execute(
        "SELECT id FROM phones WHERE normalized_model = ?",
        ("oppotesttrash",),
    ).fetchone()
    return int(row["id"])


class ModelTrashTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmpdir.name) / "phones.sqlite"
        db.init_db(self.db_path)

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def test_trash_restore_and_cleanup_candidate(self) -> None:
        with db.connect(self.db_path) as conn:
            candidate_id = insert_candidate(conn)

            updated = db.trash_models(
                conn,
                [{"type": "candidates", "id": candidate_id}],
                now="2026-07-08T00:00:00+00:00",
            )

            self.assertEqual(updated, 1)
            self.assertEqual(db.list_candidates(conn), [])
            trashed = db.trashed_models(conn)
            self.assertEqual(len(trashed), 1)
            self.assertEqual(trashed[0]["type"], "candidates")
            self.assertEqual(trashed[0]["id"], candidate_id)
            self.assertTrue(trashed[0]["purge_after"].startswith("2026-07-15"))

            restored = db.restore_models(conn, [{"type": "candidates", "id": candidate_id}])

            self.assertEqual(restored, 1)
            self.assertEqual(len(db.list_candidates(conn)), 1)
            self.assertEqual(db.trashed_models(conn), [])

            db.trash_models(
                conn,
                [{"type": "candidates", "id": candidate_id}],
                now="2026-07-01T00:00:00+00:00",
            )
            purged = db.cleanup_trashed_models(
                conn,
                now="2026-07-09T00:00:00+00:00",
                retention_days=7,
            )

            self.assertEqual(purged, 1)
            self.assertIsNone(
                conn.execute("SELECT id FROM candidates WHERE id = ?", (candidate_id,)).fetchone()
            )

    def test_trash_models_supports_mixed_tables_and_rejects_unknown_type(self) -> None:
        with db.connect(self.db_path) as conn:
            candidate_id = insert_candidate(conn)
            phone_id = insert_phone(conn)

            updated = db.trash_models(
                conn,
                [
                    {"type": "candidates", "id": candidate_id},
                    {"type": "phones", "id": phone_id},
                ],
                now="2026-07-08T00:00:00+00:00",
            )

            self.assertEqual(updated, 2)
            self.assertEqual(db.list_candidates(conn), [])
            self.assertEqual(db.list_phones(conn), [])
            self.assertEqual(
                sorted((row["type"], row["id"]) for row in db.trashed_models(conn)),
                [("candidates", candidate_id), ("phones", phone_id)],
            )
            with self.assertRaises(ValueError):
                db.trash_models(conn, [{"type": "news", "id": 1}])


if __name__ == "__main__":
    unittest.main()
