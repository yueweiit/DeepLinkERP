from __future__ import annotations

import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from phone_watch import db
from phone_watch.webapp import PhoneWatchHandler


class NewsApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmpdir.name) / "phones.sqlite"
        db.init_db(self.db_path)
        PhoneWatchHandler.db_path = str(self.db_path)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), PhoneWatchHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_address[1]}"

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.tmpdir.cleanup()

    def news_row(self, **overrides):
        row = {
            "brand": "VIVO",
            "source_type": "ithome_brand_search",
            "source_name": "IT之家品牌 Tag",
            "title": "vivo X news",
            "url": "https://www.ithome.com/0/999/001.htm",
            "first_collected_at": "2026-06-30T08:00:00+00:00",
            "last_collected_at": "2026-06-30T08:00:00+00:00",
            "seen_date": "2026-06-30",
        }
        row.update(overrides)
        return row

    def get_json(self, path: str) -> tuple[int, dict]:
        try:
            with urllib.request.urlopen(f"{self.base_url}{path}", timeout=5) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read().decode("utf-8"))

    def post_json(self, path: str, payload: dict | None = None) -> tuple[int, dict]:
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            data=json.dumps(payload or {}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read().decode("utf-8"))

    def test_api_news_returns_recent_retained_brand_items_newest_first(self) -> None:
        with db.connect(self.db_path) as conn:
            db.upsert_news_item(conn, self.news_row(title="old vivo", seen_date="2026-06-29"))
            db.upsert_news_item(conn, self.news_row(title="today vivo A", url="https://www.ithome.com/0/999/101.htm"))
            db.upsert_news_item(conn, self.news_row(title="today vivo B", url="https://www.ithome.com/0/999/102.htm"))

        status, body = self.get_json("/api/news?brand=VIVO&date=today")

        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "ok")
        self.assertEqual(body["mode"], "recent_retained")
        self.assertEqual(body["date"], "today")
        self.assertEqual(body["retention_days"], 7)
        self.assertIsNone(body["window_start"])
        self.assertIsNone(body["window_end"])
        self.assertFalse(body["fallback_used"])
        self.assertEqual(body["fallback_limit"], 3)
        self.assertEqual([item["title"] for item in body["items"]], ["today vivo B", "today vivo A", "old vivo"])
        self.assertTrue(all(item["source_type"] == "ithome_brand_search" for item in body["items"]))

    def test_api_news_returns_all_retained_brand_items_without_recent_three_fallback(self) -> None:
        with db.connect(self.db_path) as conn:
            for index in range(5):
                db.upsert_news_item(
                    conn,
                    self.news_row(
                        title=f"history vivo {index}",
                        url=f"https://www.ithome.com/0/999/20{index}.htm",
                        seen_date=f"2026-06-2{index}",
                        last_collected_at=f"2026-06-2{index}T08:00:00+00:00",
                    ),
                )
            db.upsert_news_item(
                conn,
                self.news_row(
                    brand="OPPO",
                    title="today oppo",
                    url="https://www.ithome.com/0/999/300.htm",
                    seen_date="2026-06-30",
                    last_collected_at="2026-06-30T08:00:00+00:00",
                ),
            )

        status, body = self.get_json("/api/news?brand=VIVO&date=today")

        self.assertEqual(status, 200)
        self.assertEqual(body["mode"], "recent_retained")
        self.assertEqual(body["date"], "today")
        self.assertFalse(body["fallback_used"])
        self.assertEqual(
            [item["title"] for item in body["items"]],
            ["history vivo 4", "history vivo 3", "history vivo 2", "history vivo 1", "history vivo 0"],
        )

    def test_api_news_ignores_collect_news_window_and_uses_retained_rows(self) -> None:
        with db.connect(self.db_path) as conn:
            run_id = db.start_run(conn, "collect-news", "2026-07-02T10:00:00+00:00")
            db.finish_run(conn, run_id, "2026-07-02T10:03:00+00:00")
            db.upsert_news_item(
                conn,
                self.news_row(
                    title="window vivo",
                    url="https://www.ithome.com/0/999/601.htm",
                    seen_date="2026-07-02",
                    published_at="2026-07-02T09:30:00+00:00",
                    collect_run_id=run_id,
                    collect_window_start="2026-07-01T10:05:00+00:00",
                    collect_window_end="2026-07-02T10:03:00+00:00",
                ),
            )
            db.upsert_news_item(
                conn,
                self.news_row(
                    title="outside vivo",
                    url="https://www.ithome.com/0/999/602.htm",
                    seen_date="2026-07-02",
                    published_at="2026-07-01T09:30:00+00:00",
                ),
            )

        status, body = self.get_json("/api/news?brand=VIVO&date=today")

        self.assertEqual(status, 200)
        self.assertEqual(body["date"], "today")
        self.assertEqual(body["mode"], "recent_retained")
        self.assertIsNone(body["window_start"])
        self.assertIsNone(body["window_end"])
        self.assertFalse(body["fallback_used"])
        self.assertEqual([item["title"] for item in body["items"]], ["window vivo", "outside vivo"])

    def test_api_news_source_type_filter_returns_recent_retained_rows(self) -> None:
        with db.connect(self.db_path) as conn:
            run_id = db.start_run(conn, "collect-news", "2026-07-03T09:40:00+00:00")
            db.finish_run(conn, run_id, "2026-07-03T09:45:55+00:00")
            db.upsert_news_item(
                conn,
                self.news_row(
                    title="old window vivo",
                    url="https://www.ithome.com/0/999/701.htm",
                    seen_date="2026-07-03",
                    published_at="2026-07-03T09:30:00+00:00",
                    collect_run_id=run_id,
                    collect_window_start="2026-07-03T08:18:57+00:00",
                    collect_window_end="2026-07-03T09:45:55+00:00",
                ),
            )
            db.upsert_news_item(
                conn,
                self.news_row(
                    brand="ALL",
                    source_type="ithome_phone_today",
                    source_name="IT之家手机分区当日新闻",
                    title="new phone channel",
                    url="https://www.ithome.com/0/999/702.htm",
                    seen_date="2026-07-06",
                    published_at="2026-07-06T00:00:00+00:00",
                    first_collected_at="2026-07-06T10:00:00+00:00",
                    last_collected_at="2026-07-06T10:00:00+00:00",
                    collect_window_start=None,
                    collect_window_end="2026-07-06T10:00:00+00:00",
                ),
            )

        status, body = self.get_json("/api/news?source_type=ithome_phone_today&date=today")

        self.assertEqual(status, 200)
        self.assertEqual(body["mode"], "recent_retained")
        self.assertEqual(body["date"], "today")
        self.assertIsNone(body["window_start"])
        self.assertIsNone(body["window_end"])
        self.assertEqual([item["title"] for item in body["items"]], ["new phone channel"])

    def test_api_news_filters_by_source_type_without_mixing_ithome_sources(self) -> None:
        with db.connect(self.db_path) as conn:
            db.upsert_news_item(conn, self.news_row(title="vivo tag", url="https://www.ithome.com/0/999/401.htm"))
            db.upsert_news_item(
                conn,
                self.news_row(
                    brand="ALL",
                    source_type="ithome_phone_today",
                    source_name="IT之家手机分区",
                    title="phone channel today",
                    url="https://www.ithome.com/0/999/402.htm",
                ),
            )

        status, body = self.get_json("/api/news?source_type=ithome_phone_today&date=today")

        self.assertEqual(status, 200)
        self.assertEqual(body["mode"], "recent_retained")
        self.assertFalse(body["fallback_used"])
        self.assertEqual([item["source_type"] for item in body["items"]], ["ithome_phone_today"])
        self.assertEqual(body["items"][0]["title"], "phone channel today")

    def test_api_news_treats_mobile_keyword_filter_as_successful_fallback_note(self) -> None:
        with db.connect(self.db_path) as conn:
            db.upsert_news_item(
                conn,
                self.news_row(
                    brand="SAMSUNG",
                    title="Samsung phone from mobile fallback",
                    url="https://www.ithome.com/0/999/601.htm",
                    seen_date="2026-07-03",
                    first_collected_at="2026-07-03T08:00:00+00:00",
                    last_collected_at="2026-07-03T08:00:00+00:00",
                    last_error="brand tag failed or empty; used mobile_phone_keyword_filter",
                ),
            )

        status, body = self.get_json("/api/news?brand=SAMSUNG&source_type=ithome_brand_search&date=2026-07-03")

        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "ok")
        self.assertEqual(body["mode"], "recent_retained")
        self.assertFalse(body["crawl_failed"])
        self.assertIsNone(body["crawl_error"])
        self.assertTrue(body["fallback_note"])
        self.assertEqual(body["items"][0]["last_error"], "brand tag failed or empty; used mobile_phone_keyword_filter")

    def test_api_news_treats_latest_when_no_today_as_retained_news(self) -> None:
        with db.connect(self.db_path) as conn:
            db.upsert_news_item(
                conn,
                self.news_row(
                    brand="OPPO",
                    title="OPPO recent fallback news",
                    url="https://www.ithome.com/0/999/801.htm",
                    seen_date="2026-07-06",
                    first_collected_at="2026-07-08T08:00:00+00:00",
                    last_collected_at="2026-07-08T08:00:00+00:00",
                    last_error="latest_when_no_today; requested_date=2026-07-08",
                ),
            )

        status, body = self.get_json("/api/news?brand=OPPO&source_type=ithome_brand_search&date=2026-07-06")

        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "ok")
        self.assertEqual(body["mode"], "recent_retained")
        self.assertFalse(body["empty_today"])
        self.assertEqual(body["empty_message"], "")
        self.assertFalse(body["crawl_failed"])
        self.assertIsNone(body["crawl_error"])
        self.assertEqual([item["title"] for item in body["items"]], ["OPPO recent fallback news"])

    def test_api_news_reports_crawl_failure_marker_without_showing_it_as_item(self) -> None:
        with db.connect(self.db_path) as conn:
            db.upsert_news_item(
                conn,
                self.news_row(
                    brand="HUAWEI",
                    title="IT之家品牌关键词搜索 当日爬取失败",
                    url="https://www.ithome.com/tags/%E5%8D%8E%E4%B8%BA%E6%89%8B%E6%9C%BA/",
                    seen_date="2026-07-03",
                    first_collected_at="2026-07-03T08:00:00+00:00",
                    last_collected_at="2026-07-03T08:00:00+00:00",
                    last_error="brand tag failed or empty; used mobile_phone_keyword_filter",
                ),
            )

        status, body = self.get_json("/api/news?brand=HUAWEI&source_type=ithome_brand_search&date=2026-07-03")

        self.assertEqual(status, 200)
        self.assertEqual(body["mode"], "recent_retained")
        self.assertTrue(body["crawl_failed"])
        self.assertIn("brand tag failed", body["crawl_error"])
        self.assertEqual(body["items"], [])

    def test_api_news_recent_retained_filters_failure_marker_rows_when_real_news_exists(self) -> None:
        with db.connect(self.db_path) as conn:
            db.upsert_news_item(
                conn,
                self.news_row(
                    brand="HUAWEI",
                    title="IT之家品牌关键词搜索 当日爬取失败",
                    url="https://www.ithome.com/tags/%E5%8D%8E%E4%B8%BA/",
                    seen_date="2026-07-16",
                    last_error="brand tag failed or empty; used mobile_phone_keyword_filter",
                ),
            )
            db.upsert_news_item(
                conn,
                self.news_row(
                    brand="HUAWEI",
                    title="Huawei real news",
                    url="https://www.ithome.com/0/999/903.htm",
                    seen_date="2026-07-16",
                    published_at="2026-07-16T10:00:00+00:00",
                ),
            )

        status, body = self.get_json("/api/news?brand=HUAWEI&source_type=ithome_brand_search&date=today")

        self.assertEqual(status, 200)
        self.assertEqual(body["mode"], "recent_retained")
        self.assertFalse(body["crawl_failed"])
        self.assertEqual([item["title"] for item in body["items"]], ["Huawei real news"])

    def test_api_news_without_filters_returns_all_recent_retained_items_newest_first(self) -> None:
        with db.connect(self.db_path) as conn:
            db.upsert_news_item(conn, self.news_row(title="today vivo tag", url="https://www.ithome.com/0/999/501.htm"))
            db.upsert_news_item(
                conn,
                self.news_row(
                    brand="ALL",
                    source_type="ithome_phone_today",
                    source_name="IT之家手机分区当日新闻",
                    title="phone channel public",
                    url="https://www.ithome.com/0/999/502.htm",
                ),
            )

        status, body = self.get_json("/api/news?date=today")

        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "ok")
        self.assertEqual(body["mode"], "recent_retained")
        self.assertEqual([item["title"] for item in body["items"]], ["phone channel public", "today vivo tag"])
        self.assertFalse(body["fallback_used"])

    def test_api_news_empty_database_returns_ok_empty_items(self) -> None:
        status, body = self.get_json("/api/news?brand=VIVO&date=today")

        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "ok")
        self.assertEqual(body["mode"], "recent_retained")
        self.assertEqual(body["date"], "today")
        self.assertEqual(body["retention_days"], 7)
        self.assertFalse(body["fallback_used"])
        self.assertEqual(body["items"], [])

    @patch("phone_watch.webapp.collect_news_once")
    def test_post_news_refresh_runs_collect_once(self, collect_news_once) -> None:
        collect_news_once.return_value = {
            "ok": True,
            "window_start": "2026-07-10T09:00:00+00:00",
            "window_end": "2026-07-10T10:00:00+00:00",
            "counts": {"inserted": 1},
            "cleanup_deleted": 0,
            "retention_days": 7,
        }

        status, body = self.post_json("/api/news/refresh", {})

        self.assertEqual(status, 200)
        self.assertTrue(body["ok"])
        self.assertEqual(body["counts"]["inserted"], 1)
        collect_news_once.assert_called_once_with(str(self.db_path))


if __name__ == "__main__":
    unittest.main()
