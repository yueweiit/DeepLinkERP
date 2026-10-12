from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from phone_watch import db
from phone_watch.cleaning import clean_scope, compare_and_clean_candidates, normalize_model


class CleaningTests(unittest.TestCase):
    def test_three_stage_cleaning_and_compare(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "phones.sqlite"
            db.init_db(db_path)
            now = datetime.now(timezone.utc).isoformat(timespec="seconds")
            rows = [
                {
                    "brand": "SAMSUNG",
                    "country": "MX",
                    "source_name": "Samsung Mexico",
                    "source_url": "https://www.samsung.com/mx/",
                    "page_url": "https://www.samsung.com/mx/smartphones/galaxy-s25/",
                    "raw_title": "Galaxy S25",
                    "raw_badge": "Nuevo",
                    "raw_image_url": "https://example.com/s25.png",
                    "fetched_at": now,
                },
                {
                    "brand": "SAMSUNG",
                    "country": "KR",
                    "source_name": "Samsung Korea",
                    "source_url": "https://www.samsung.com/sec/",
                    "page_url": "https://www.samsung.com/sec/smartphones/galaxy-s25-edge/",
                    "raw_title": "Galaxy S25 Edge",
                    "raw_badge": "신제품",
                    "raw_image_url": "https://example.com/s25-edge.png",
                    "fetched_at": now,
                },
                {
                    "brand": "OPPO",
                    "country": "CN",
                    "source_name": "OPPO China",
                    "source_url": "https://www.oppo.com/cn/",
                    "page_url": "https://www.oppo.com/cn/smartphones/reno16-pro/",
                    "raw_title": "OPPO Reno16 Pro 5G",
                    "raw_badge": "新品",
                    "raw_image_url": "https://example.com/reno16.png",
                    "fetched_at": now,
                },
            ]
            with db.connect(db_path) as conn:
                db.insert_raw_items(conn, rows)
                self.assertEqual(clean_scope(conn, "mx", new_only=True), 1)
                self.assertEqual(clean_scope(conn, "origin", new_only=True), 2)
                self.assertEqual(compare_and_clean_candidates(conn), 2)
                candidates = db.list_candidates(conn)

            names = {row["model"] for row in candidates}
            self.assertIn("Galaxy S25 Edge", names)
            self.assertIn("OPPO Reno16 Pro 5G", names)

    def test_normalize_keeps_plus_distinct(self) -> None:
        self.assertEqual(normalize_model("Redmi Note 14 Pro+ 5G", "XIAOMI"), "redminote14proplus5g")

    def test_pad_context_is_filtered(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "phones.sqlite"
            db.init_db(db_path)
            now = datetime.now(timezone.utc).isoformat(timespec="seconds")
            with db.connect(db_path) as conn:
                db.insert_raw_items(
                    conn,
                    [
                        {
                            "brand": "HONOR",
                            "country": "MX",
                            "source_name": "HONOR Mexico",
                            "source_url": "https://www.honor.com/mx/",
                            "page_url": "https://www.honor.com/mx/tablets/honor-pad-x9/",
                            "raw_title": "HONOR Pad X9",
                            "raw_badge": "Nuevo",
                            "raw_image_url": "https://example.com/pad.png",
                            "fetched_at": now,
                        }
                    ],
                )
                self.assertEqual(clean_scope(conn, "mx", new_only=True), 0)

    def test_accessory_and_url_only_matches_are_filtered(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "phones.sqlite"
            db.init_db(db_path)
            now = datetime.now(timezone.utc).isoformat(timespec="seconds")
            with db.connect(db_path) as conn:
                db.insert_raw_items(
                    conn,
                    [
                        {
                            "brand": "SAMSUNG",
                            "country": "MX",
                            "source_name": "Samsung Mexico",
                            "source_url": "https://www.samsung.com/mx/",
                            "page_url": "https://www.samsung.com/mx/smartphones/galaxy-s25/",
                            "raw_title": "Funda transparente",
                            "raw_badge": "Nuevo",
                            "raw_image_url": "https://example.com/case.png",
                            "fetched_at": now,
                        },
                        {
                            "brand": "SAMSUNG",
                            "country": "MX",
                            "source_name": "Samsung Mexico",
                            "source_url": "https://www.samsung.com/mx/",
                            "page_url": "https://www.samsung.com/mx/smartphones/galaxy-s25/",
                            "raw_title": "Galaxy S25",
                            "raw_badge": "Nuevo",
                            "raw_image_url": "https://example.com/s25.png",
                            "fetched_at": now,
                        },
                    ],
                )
                self.assertEqual(clean_scope(conn, "mx", new_only=True), 1)
                phones = db.list_phones(conn)

            self.assertEqual([row["model"] for row in phones], ["Galaxy S25"])


if __name__ == "__main__":
    unittest.main()
