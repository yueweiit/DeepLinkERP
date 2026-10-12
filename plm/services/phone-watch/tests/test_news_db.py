from __future__ import annotations

from contextlib import contextmanager
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from phone_watch import db


class FakePostgresCursor:
    rowcount = 0
    lastrowid = None

    def fetchall(self):
        return []

    def fetchone(self):
        return None


class FakePostgresConnection:
    driver = "pg8000"

    def __init__(self):
        self.statements = []

    def execute(self, sql, params=None):
        self.statements.append((sql, tuple(params or ())))
        return FakePostgresCursor()

    def executescript(self, script):
        self.statements.append(("SCRIPT", ()))

    def commit(self):
        self.statements.append(("COMMIT", ()))

    def close(self):
        self.statements.append(("CLOSE", ()))


class PostgresInitMigrationTests(unittest.TestCase):
    def test_postgres_init_takes_advisory_lock_before_schema_migrations(self) -> None:
        fake_conn = FakePostgresConnection()

        @contextmanager
        def fake_connect(db_path=db.DEFAULT_DB):
            yield fake_conn

        with (
            mock.patch.object(db, "connect", fake_connect),
            mock.patch.object(db, "is_postgres_connection", return_value=True),
        ):
            db.init_db()

        lock_index = next(
            index
            for index, (sql, _params) in enumerate(fake_conn.statements)
            if "pg_advisory_xact_lock" in sql
        )
        script_index = next(
            index
            for index, (sql, _params) in enumerate(fake_conn.statements)
            if sql == "SCRIPT"
        )
        self.assertLess(lock_index, script_index)

    def test_status_value_migration_uses_stable_table_order(self) -> None:
        fake_conn = FakePostgresConnection()

        db.migrate_status_values(fake_conn)

        updated_tables = []
        for sql, _params in fake_conn.statements:
            normalized_sql = " ".join(sql.split())
            if normalized_sql.startswith("UPDATE "):
                updated_tables.append(normalized_sql.split()[1])

        first_seen_tables = list(dict.fromkeys(updated_tables))
        self.assertEqual(first_seen_tables, ["phones", "candidates", "molding_records"])


class NewsDatabaseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmpdir.name) / "phones.sqlite"
        db.init_db(self.db_path)

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def news_row(self, **overrides):
        row = {
            "brand": "VIVO",
            "source_type": "ithome_brand_search",
            "source_name": "IT之家品牌搜索",
            "title": "vivo 新机发布",
            "url": "https://www.ithome.com/0/001/001.htm",
            "first_collected_at": "2026-06-29T08:00:00+00:00",
            "last_collected_at": "2026-06-29T08:00:00+00:00",
            "seen_date": "2026-06-29",
            "published_at": "2026-06-29T08:00:00+00:00",
        }
        row.update(overrides)
        return row

    def test_init_db_migrates_legacy_news_items_before_window_index(self) -> None:
        legacy_path = Path(self.tmpdir.name) / "legacy.sqlite"
        with db.connect(legacy_path) as conn:
            conn.execute(
                """
                CREATE TABLE news_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    brand TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    source_name TEXT NOT NULL,
                    title TEXT NOT NULL,
                    url TEXT NOT NULL,
                    first_collected_at TEXT NOT NULL,
                    last_collected_at TEXT NOT NULL,
                    seen_date TEXT NOT NULL,
                    last_error TEXT,
                    UNIQUE (brand, source_type, title, url)
                )
                """
            )

        db.init_db(legacy_path)

        with db.connect(legacy_path) as conn:
            columns = db.column_names(conn, "news_items")
            indexes = {row["name"] for row in conn.execute("PRAGMA index_list(news_items)").fetchall()}

        self.assertIn("published_at", columns)
        self.assertIn("collect_run_id", columns)
        self.assertIn("collect_window_start", columns)
        self.assertIn("collect_window_end", columns)
        self.assertIn("idx_news_items_window", indexes)

    def test_upsert_news_item_deduplicates_by_brand_source_title_and_url(self) -> None:
        with db.connect(self.db_path) as conn:
            first_id = db.upsert_news_item(conn, self.news_row())
            second_id = db.upsert_news_item(
                conn,
                self.news_row(
                    source_name="IT之家品牌搜索更新",
                    first_collected_at="2026-06-30T08:00:00+00:00",
                    last_collected_at="2026-06-30T08:00:00+00:00",
                    seen_date="2026-06-30",
                ),
            )
            rows = db.list_news_items(conn, brand="VIVO")

        self.assertEqual(first_id, second_id)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["source_name"], "IT之家品牌搜索更新")
        self.assertEqual(rows[0]["first_collected_at"], "2026-06-29T08:00:00+00:00")
        self.assertEqual(rows[0]["last_collected_at"], "2026-06-30T08:00:00+00:00")
        self.assertEqual(rows[0]["seen_date"], "2026-06-30")

    def test_same_url_with_different_title_is_kept_as_distinct_news(self) -> None:
        with db.connect(self.db_path) as conn:
            db.upsert_news_item(conn, self.news_row(title="vivo 新机发布"))
            db.upsert_news_item(conn, self.news_row(title="vivo 新机发布详情"))
            rows = db.list_news_items(conn, brand="VIVO")

        self.assertEqual(len(rows), 2)
        self.assertEqual({row["title"] for row in rows}, {"vivo 新机发布", "vivo 新机发布详情"})

    def test_list_news_for_brand_with_fallback_prefers_today_all_items(self) -> None:
        with db.connect(self.db_path) as conn:
            db.upsert_news_item(conn, self.news_row(title="历史新闻", seen_date="2026-06-28"))
            db.upsert_news_item(conn, self.news_row(title="今日新闻 A", url="https://www.ithome.com/a.htm"))
            db.upsert_news_item(conn, self.news_row(title="今日新闻 B", url="https://www.ithome.com/b.htm"))

            rows, fallback_used = db.list_news_for_brand_with_fallback(
                conn,
                brand="VIVO",
                seen_date="2026-06-29",
                fallback_limit=3,
            )

        self.assertFalse(fallback_used)
        self.assertEqual([row["title"] for row in rows], ["今日新闻 B", "今日新闻 A"])

    def test_list_news_for_brand_with_fallback_returns_recent_three_when_today_empty(self) -> None:
        with db.connect(self.db_path) as conn:
            for index in range(5):
                db.upsert_news_item(
                    conn,
                    self.news_row(
                        title=f"历史新闻 {index}",
                        url=f"https://www.ithome.com/history-{index}.htm",
                        seen_date=f"2026-06-2{index}",
                        last_collected_at=f"2026-06-2{index}T08:00:00+00:00",
                    ),
                )

            rows, fallback_used = db.list_news_for_brand_with_fallback(
                conn,
                brand="VIVO",
                seen_date="2026-06-29",
                fallback_limit=3,
            )

        self.assertTrue(fallback_used)
        self.assertEqual([row["title"] for row in rows], ["历史新闻 4", "历史新闻 3", "历史新闻 2"])

    def test_list_recent_news_items_orders_by_published_then_collected_time(self) -> None:
        with db.connect(self.db_path) as conn:
            db.upsert_news_item(
                conn,
                self.news_row(
                    brand="SAMSUNG",
                    title="older published samsung",
                    url="https://www.ithome.com/0/999/701.htm",
                    seen_date="2026-07-14",
                    published_at="2026-07-14T10:00:00+00:00",
                    first_collected_at="2026-07-14T10:05:00+00:00",
                    last_collected_at="2026-07-14T10:05:00+00:00",
                ),
            )
            db.upsert_news_item(
                conn,
                self.news_row(
                    brand="SAMSUNG",
                    title="newer collected samsung",
                    url="https://www.ithome.com/0/999/702.htm",
                    seen_date="2026-07-16",
                    published_at=None,
                    first_collected_at="2026-07-16T09:00:00+00:00",
                    last_collected_at="2026-07-16T09:30:00+00:00",
                ),
            )
            db.upsert_news_item(
                conn,
                self.news_row(
                    brand="OPPO",
                    title="oppo hidden by brand filter",
                    url="https://www.ithome.com/0/999/703.htm",
                    seen_date="2026-07-16",
                    published_at="2026-07-16T11:00:00+00:00",
                    first_collected_at="2026-07-16T11:05:00+00:00",
                    last_collected_at="2026-07-16T11:05:00+00:00",
                ),
            )

            rows = db.list_recent_news_items(conn, brand="SAMSUNG", source_type="ithome_brand_search")

        self.assertEqual([row["title"] for row in rows], ["newer collected samsung", "older published samsung"])

    def test_list_recent_news_items_applies_limit(self) -> None:
        with db.connect(self.db_path) as conn:
            for index in range(5):
                db.upsert_news_item(
                    conn,
                    self.news_row(
                        brand="VIVO",
                        title=f"vivo recent {index}",
                        url=f"https://www.ithome.com/0/999/80{index}.htm",
                        seen_date="2026-07-16",
                        first_collected_at=f"2026-07-16T0{index}:00:00+00:00",
                        last_collected_at=f"2026-07-16T0{index}:00:00+00:00",
                    ),
                )

            rows = db.list_recent_news_items(conn, brand="VIVO", limit=3)

        self.assertEqual(len(rows), 3)
        self.assertEqual([row["title"] for row in rows], ["vivo recent 4", "vivo recent 3", "vivo recent 2"])

    def test_news_items_store_collect_window_fields_and_query_window(self) -> None:
        with db.connect(self.db_path) as conn:
            run_id = db.start_run(conn, "collect-news", "2026-07-02T10:00:00+00:00")
            db.finish_run(conn, run_id, "2026-07-02T10:03:00+00:00")
            db.upsert_news_item(
                conn,
                self.news_row(
                    title="窗口内新闻",
                    url="https://www.ithome.com/0/001/101.htm",
                    published_at="2026-07-02T09:00:00+00:00",
                    collect_run_id=run_id,
                    collect_window_start="2026-07-01T10:05:00+00:00",
                    collect_window_end="2026-07-02T10:03:00+00:00",
                ),
            )
            db.upsert_news_item(
                conn,
                self.news_row(
                    title="窗口外新闻",
                    url="https://www.ithome.com/0/001/102.htm",
                    published_at="2026-07-01T09:00:00+00:00",
                    collect_run_id=run_id,
                    collect_window_start="2026-07-01T10:05:00+00:00",
                    collect_window_end="2026-07-02T10:03:00+00:00",
                ),
            )

            rows = db.list_news_items(
                conn,
                brand="VIVO",
                window_start="2026-07-01T10:05:00+00:00",
                window_end="2026-07-02T10:03:00+00:00",
            )
            latest_run = db.latest_successful_news_run(conn)

        self.assertEqual([row["title"] for row in rows], ["窗口内新闻"])
        self.assertEqual(rows[0]["collect_run_id"], run_id)
        self.assertEqual(rows[0]["collect_window_start"], "2026-07-01T10:05:00+00:00")
        self.assertEqual(rows[0]["collect_window_end"], "2026-07-02T10:03:00+00:00")
        self.assertEqual(latest_run["id"], run_id)
        self.assertEqual(latest_run["finished_at"], "2026-07-02T10:03:00+00:00")

    def test_find_and_count_recent_news_for_brand_use_source_and_url(self) -> None:
        with db.connect(self.db_path) as conn:
            for index in range(3):
                db.upsert_news_item(
                    conn,
                    self.news_row(
                        title=f"历史新闻 {index}",
                        url=f"https://www.ithome.com/0/001/20{index}.htm",
                        last_collected_at=f"2026-07-0{index + 1}T08:00:00+00:00",
                    ),
                )

            existing = db.find_news_item_by_brand_source_url(
                conn,
                "vivo",
                "ithome_brand_search",
                "https://www.ithome.com/0/001/201.htm",
            )
            count = db.count_recent_news_for_brand(conn, "vivo", "ithome_brand_search")

        self.assertEqual(existing["title"], "历史新闻 1")
        self.assertEqual(count, 3)

    def test_cleanup_old_news_items_uses_first_collected_at(self) -> None:
        with db.connect(self.db_path) as conn:
            db.upsert_news_item(
                conn,
                self.news_row(
                    title="超过保留期",
                    url="https://www.ithome.com/old.htm",
                    first_collected_at="2026-06-20T08:00:00+00:00",
                    last_collected_at="2026-06-29T08:00:00+00:00",
                ),
            )
            db.upsert_news_item(
                conn,
                self.news_row(
                    title="保留期内",
                    url="https://www.ithome.com/new.htm",
                    first_collected_at="2026-06-24T08:00:00+00:00",
                ),
            )

            deleted = db.cleanup_old_news_items(conn, retention_days=7, now="2026-06-29T12:00:00+00:00")
            rows = db.list_news_items(conn, brand="VIVO")

        self.assertEqual(deleted, 1)
        self.assertEqual([row["title"] for row in rows], ["保留期内"])


if __name__ == "__main__":
    unittest.main()
