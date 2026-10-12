from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from phone_watch import db
from phone_watch.static_export import export_html
from phone_watch.ui import render_app_html


class NewsStaticExportAndDailyScriptsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmpdir.name)
        self.db_path = self.tmp_path / "phones.sqlite"
        db.init_db(self.db_path)

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def test_static_export_embeds_news_items_for_offline_news_page(self) -> None:
        with db.connect(self.db_path) as conn:
            db.upsert_news_item(
                conn,
                {
                    "brand": "VIVO",
                    "source_type": "ithome_brand_search",
                    "source_name": "IT之家品牌 Tag",
                    "title": "vivo static export news",
                    "url": "https://www.ithome.com/0/999/901.htm",
                    "first_collected_at": "2026-06-30T08:00:00+00:00",
                    "last_collected_at": "2026-06-30T08:00:00+00:00",
                    "seen_date": "2026-06-30",
                },
            )

        output = self.tmp_path / "phone_watch.html"
        export_html(self.db_path, output)

        html = output.read_text(encoding="utf-8")
        self.assertIn('"news": {"status": "ok"', html)
        self.assertIn('"mode": "recent_retained"', html)
        self.assertIn('"date": "today"', html)
        self.assertIn('"retention_days": 7', html)
        self.assertIn('"title": "vivo static export news"', html)
        self.assertIn('"source_type": "ithome_brand_search"', html)
        self.assertIn('id="news-category"', html)
        self.assertIn("手机分区当日新闻", html)
        self.assertIn('<option value="HUAWEI">HUAWEI</option>', html)

    def test_news_refresh_button_is_rendered_next_to_news_filter(self) -> None:
        html = render_app_html(api_mode=True)

        self.assertIn('id="news-filter-actions"', html)
        self.assertIn('id="news-category-filter"', html)
        self.assertIn('id="news-refresh"', html)
        self.assertIn('refreshNews()', html)
        self.assertIn('$("#news-filter-actions")?.classList.toggle("hidden", !newsMode)', html)

    def test_news_status_uses_news_specific_note_class(self) -> None:
        html = render_app_html(api_mode=True)

        self.assertIn(".news-status-note", html)
        self.assertIn('status.className = "news-status-note"', html)
        self.assertNotIn('status.className = "note";', html)

    def test_windows_daily_script_runs_news_after_main_collect_without_blocking(self) -> None:
        script = Path("scripts/daily_collect.bat").read_text(encoding="utf-8")

        self.assertIn("collect --max-pages", script)
        self.assertIn("collect-news --timeout", script)
        self.assertIn("daily news collect failed", script)
        self.assertIn("daily collect failed", script)
        self.assertNotIn("exit /b 1\r\n)\r\necho ==== %date% %time% daily news collect failed", script)

    def test_linux_daily_script_runs_news_after_main_collect_without_blocking(self) -> None:
        script = Path("scripts/daily_collect.sh").read_text(encoding="utf-8")

        self.assertIn("-m phone_watch collect \\", script)
        self.assertIn("-m phone_watch collect-news", script)
        self.assertIn("daily news collect failed", script)
        self.assertIn("set +e", script)
        self.assertIn("set -e", script)

    def test_local_windows_web_scripts_default_to_postgres_with_timeout_guard(self) -> None:
        for script_name in ("start_web.bat", "start_web_background.bat"):
            with self.subTest(script=script_name):
                script = Path("scripts", script_name).read_text(encoding="utf-8")

                self.assertIn('if "%PHONE_WATCH_DB_BACKEND%"=="" set PHONE_WATCH_DB_BACKEND=postgres', script)
                self.assertIn('if "%PHONE_WATCH_PG_HOST%"=="" set PHONE_WATCH_PG_HOST=127.0.0.1', script)
                self.assertIn('if "%PHONE_WATCH_PG_CONNECT_TIMEOUT%"=="" set PHONE_WATCH_PG_CONNECT_TIMEOUT=10', script)
                self.assertIn('if "%PHONE_WATCH_PG_PASSWORD%"==""', script)
                self.assertNotIn('if "%PHONE_WATCH_PG_CONNECT_TIMEOUT%"==replace_with_local_password', script)

    def test_windows_server_script_keeps_postgres_default(self) -> None:
        script = Path("scripts/run_server_windows.bat").read_text(encoding="utf-8")

        self.assertIn('if "%PHONE_WATCH_DB_BACKEND%"=="" set PHONE_WATCH_DB_BACKEND=postgres', script)
        self.assertIn('if "%PHONE_WATCH_PG_HOST%"=="" set PHONE_WATCH_PG_HOST=127.0.0.1', script)
        self.assertIn('if "%PHONE_WATCH_PG_PASSWORD%"==""', script)


if __name__ == "__main__":
    unittest.main()
