from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from phone_watch import db
from phone_watch.cli import build_parser, main


def write_news_config(path: Path) -> None:
    payload = {
        "retention_days": 7,
        "fallback_limit": 3,
        "brand_keywords": {
            "ZTE": ["zte phone"],
            "MOTOROLA": ["motorola phone"],
            "XIAOMI": ["xiaomi"],
            "SAMSUNG": ["samsung phone"],
            "OPPO": ["OPPO"],
            "HONOR": ["honor phone"],
            "VIVO": ["vivo phone"],
            "HUAWEI": ["huawei phone"],
        },
        "sources": [
            {
                "brand": "VIVO",
                "source_type": "ithome_brand_search",
                "source_name": "IT Home brand search",
                "search_keywords": ["vivo phone"],
            }
        ],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


class CollectNewsCommandTests(unittest.TestCase):
    def test_collect_news_help_exposes_expected_options(self) -> None:
        help_text = build_parser().format_help()

        self.assertIn("collect-news", help_text)

        parser = build_parser()
        stream = io.StringIO()
        with self.assertRaises(SystemExit) as raised, redirect_stdout(stream):
            parser.parse_args(["collect-news", "--help"])

        self.assertEqual(raised.exception.code, 0)
        command_help = stream.getvalue()
        self.assertIn("--brand", command_help)
        self.assertIn("--source-type", command_help)
        self.assertIn("--timeout", command_help)
        self.assertIn("--render-mode", command_help)
        self.assertIn("--no-render-fallback", command_help)
        self.assertNotIn("official", command_help)

    def test_collect_news_rejects_official_source_type(self) -> None:
        parser = build_parser()
        with self.assertRaises(SystemExit) as raised, redirect_stderr(io.StringIO()):
            parser.parse_args(["collect-news", "--source-type", "official"])

        self.assertEqual(raised.exception.code, 2)

    def test_collect_news_runs_single_brand_source_and_cleans_old_items(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            db_path = tmp_path / "phones.sqlite"
            config_path = tmp_path / "news_sources.json"
            write_news_config(config_path)

            captured_options = {}

            def fake_collect(
                conn,
                config,
                *,
                brand=None,
                source_type=None,
                timeout=20,
                render_mode="config",
                allow_render_fallback=True,
                now=None,
                window_start=None,
                window_end=None,
                collect_run_id=None,
            ):
                captured_options.update(
                    {
                        "brand": brand,
                        "source_type": source_type,
                        "timeout": timeout,
                        "render_mode": render_mode,
                        "allow_render_fallback": allow_render_fallback,
                        "now": now,
                        "window_start": window_start,
                        "window_end": window_end,
                        "collect_run_id_is_int": isinstance(collect_run_id, int),
                    }
                )
                db.upsert_news_item(
                    conn,
                    {
                        "brand": brand or "VIVO",
                        "source_type": source_type or "ithome_brand_search",
                        "source_name": "IT Home brand search",
                        "title": "vivo phone news",
                        "url": "https://www.ithome.com/0/999/401.htm",
                        "first_collected_at": "2026-06-30T08:00:00+00:00",
                        "last_collected_at": "2026-06-30T08:00:00+00:00",
                        "seen_date": "2026-06-30",
                    },
                )
                db.upsert_news_item(
                    conn,
                    {
                        "brand": brand or "VIVO",
                        "source_type": source_type or "ithome_brand_search",
                        "source_name": "IT Home brand search",
                        "title": "old vivo phone news",
                        "url": "https://www.ithome.com/0/999/402.htm",
                        "first_collected_at": "2026-06-20T08:00:00+00:00",
                        "last_collected_at": "2026-06-20T08:00:00+00:00",
                        "seen_date": "2026-06-20",
                    },
                )
                return {
                    "sources": 1,
                    "fetched": 1,
                    "parsed": 2,
                    "inserted": 2,
                    "errors": 0,
                    "rendered": 1,
                    "render_errors": 0,
                    "fallbacks": 0,
                    "detail_fetched": 1,
                    "detail_errors": 1,
                }

            output = io.StringIO()
            with patch("phone_watch.news_service.collect_news_sources_to_db", side_effect=fake_collect):
                with redirect_stdout(output):
                    main(
                        [
                            "--db",
                            str(db_path),
                            "collect-news",
                            "--news-config",
                            str(config_path),
                            "--brand",
                            "VIVO",
                            "--source-type",
                            "ithome_brand_search",
                            "--timeout",
                            "5",
                            "--render-mode",
                            "always",
                            "--no-render-fallback",
                            "--now",
                            "2026-06-30T12:00:00+00:00",
                        ]
                    )

            with db.connect(db_path) as conn:
                rows = db.list_news_items(conn, brand="VIVO")

            self.assertIn(
                "collect-news: sources=1 fetched=1 parsed=2 inserted=2 errors=0 rendered=1 render_errors=0 fallbacks=0 detail_fetched=1 detail_errors=1",
                output.getvalue(),
            )
            self.assertIn("news_window: start=2026-06-29T12:00:00+00:00 end=2026-06-30T12:00:00+00:00", output.getvalue())
            self.assertIn("news_cleanup: deleted=1 retention_days=7", output.getvalue())
            self.assertEqual(
                captured_options,
                {
                    "brand": "VIVO",
                    "source_type": "ithome_brand_search",
                    "timeout": 5,
                    "render_mode": "always",
                    "allow_render_fallback": False,
                    "now": "2026-06-30T12:00:00+00:00",
                    "window_start": "2026-06-29T12:00:00+00:00",
                    "window_end": "2026-06-30T12:00:00+00:00",
                    "collect_run_id_is_int": True,
                },
            )
            self.assertEqual([row["title"] for row in rows], ["vivo phone news"])


if __name__ == "__main__":
    unittest.main()
