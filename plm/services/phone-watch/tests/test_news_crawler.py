from __future__ import annotations

from contextlib import redirect_stdout
import io
import tempfile
import unittest
from pathlib import Path

from phone_watch import db
from phone_watch.config import NewsConfig, NewsSource


class NewsCrawlerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmpdir.name) / "phones.sqlite"
        db.init_db(self.db_path)
        self.conn_context = db.connect(self.db_path)
        self.conn = self.conn_context.__enter__()

    def tearDown(self) -> None:
        self.conn_context.__exit__(None, None, None)
        self.tmpdir.cleanup()

    def test_parse_news_links_from_html_keeps_only_ithome_article_links(self) -> None:
        from phone_watch.news_crawler import parse_news_links_from_html

        html = """
        <nav>
          <a href="/support">Support</a>
          <a href="/privacy">Privacy Policy</a>
          <a href="/shop">Shop phones</a>
        </nav>
        <main>
          <a href="https://www.ithome.com/0/999/001.htm">Motorola phone news</a>
          <a href="https://www.ithome.com/0/999/001.htm">Motorola phone news</a>
          <a href="https://quan.ithome.com/0/999/002.htm">community post</a>
          <a href="https://www.motorola.com/news/launch-one">official copy</a>
        </main>
        """

        rows = parse_news_links_from_html(
            html,
            "https://www.ithome.com/tags/摩托罗拉/",
            brand="MOTOROLA",
            source_type="ithome_brand_search",
            source_name="IT之家品牌 Tag",
            seen_date="2026-06-30",
            collected_at="2026-06-30T08:00:00+00:00",
        )

        self.assertEqual([row["title"] for row in rows], ["Motorola phone news"])
        self.assertEqual(rows[0]["url"], "https://www.ithome.com/0/999/001.htm")
        self.assertEqual(rows[0]["brand"], "MOTOROLA")
        self.assertEqual(rows[0]["source_type"], "ithome_brand_search")
        self.assertEqual(rows[0]["seen_date"], "2026-06-30")

    def test_parse_ithome_search_links_keeps_ithome_news_and_deduplicates(self) -> None:
        from phone_watch.news_crawler import parse_news_links_from_html

        html = """
        <a href="https://www.ithome.com/0/999/001.htm">vivo new phone appears</a>
        <a href="https://www.ithome.com/0/999/001.htm">vivo new phone appears</a>
        <a href="https://quan.ithome.com/0/999/002.htm">community post</a>
        <a href="https://example.com/not-ithome.htm">external copy</a>
        """

        rows = parse_news_links_from_html(
            html,
            "https://www.ithome.com/search?keyword=vivo",
            brand="VIVO",
            source_type="ithome_brand_search",
            source_name="IT Home brand search",
            seen_date="2026-06-30",
            collected_at="2026-06-30T08:00:00+00:00",
        )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["title"], "vivo new phone appears")
        self.assertEqual(rows[0]["url"], "https://www.ithome.com/0/999/001.htm")

    def test_parse_ithome_search_page_uses_result_list_dates_and_ignores_sidebar(self) -> None:
        from phone_watch.news_crawler import parse_news_links_from_html

        html = """
        <div id="list" class="bb clearfix">
          <div class="fl">
            <ul class="bl">
              <li>
                <h2><a class="title" title="Xiaomi today news" href="https://www.ithome.com/0/999/101.htm">Xiaomi today news</a></h2>
                <div class="d"><span class="state tody">今日 10:30</span></div>
              </li>
              <li>
                <h2><a class="title" title="Xiaomi old news" href="https://www.ithome.com/0/999/102.htm">Xiaomi old news</a></h2>
                <div class="d"><span class="state other">06月30日</span></div>
              </li>
            </ul>
            <a class="more">加载更多...</a>
          </div>
          <div class="fr fx">
            <a href="https://www.ithome.com/0/999/999.htm">立即下载</a>
          </div>
        </div>
        """

        rows = parse_news_links_from_html(
            html,
            "https://www.ithome.com/search/%E5%B0%8F%E7%B1%B3.html",
            brand="XIAOMI",
            source_type="ithome_brand_search",
            source_name="IT Home brand search",
            seen_date="2026-07-01",
            collected_at="2026-07-01T08:00:00+00:00",
        )

        self.assertEqual([row["title"] for row in rows], ["Xiaomi today news", "Xiaomi old news"])
        self.assertEqual([row["seen_date"] for row in rows], ["2026-07-01", "2026-06-30"])
        self.assertNotIn("立即下载", [row["title"] for row in rows])

    def test_parse_ithome_search_candidates_returns_candidates_not_rows(self) -> None:
        from phone_watch.news_crawler import parse_ithome_search_candidates

        html = """
        <div id="list"><div class="fl"><ul class="bl">
          <li>
            <h2><a class="title" title="Xiaomi detail candidate" href="/0/999/111.htm">Xiaomi detail candidate</a></h2>
            <span class="state">\u4eca\u65e5 09:30</span>
          </li>
          <li>
            <h2><a class="title" title="Sidebar should not count" href="https://quan.ithome.com/0/999/112.htm">bad</a></h2>
          </li>
        </ul></div></div>
        """

        candidates = parse_ithome_search_candidates(
            html,
            "https://www.ithome.com/search/%E5%B0%8F%E7%B1%B3.html",
            seen_date="2026-07-02",
            window_end="2026-07-02T10:03:00+00:00",
        )

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].title, "Xiaomi detail candidate")
        self.assertEqual(candidates[0].url, "https://www.ithome.com/0/999/111.htm")
        self.assertEqual(candidates[0].state_text, "\u4eca\u65e5 09:30")
        self.assertEqual(candidates[0].seen_date, "2026-07-02")
        self.assertEqual(candidates[0].published_at, "2026-07-02T09:30:00+00:00")

    def test_ithome_search_seen_date_falls_back_for_invalid_month_day(self) -> None:
        from phone_watch.news_crawler import ithome_search_seen_date

        self.assertEqual(ithome_search_seen_date("02月31日 09:30", "2026-07-03"), "2026-07-03")
        self.assertEqual(ithome_search_seen_date("2026年02月31日", "2026-07-03"), "2026-07-03")

    def test_enrich_ithome_candidate_from_detail_prefers_detail_title_and_published_at(self) -> None:
        from phone_watch.news_crawler import IthomeSearchCandidate, enrich_ithome_candidate_from_detail

        source = NewsSource(
            brand="XIAOMI",
            source_type="ithome_brand_search",
            source_name="IT Home brand search",
        )
        detail_html = """
        <html>
          <head>
            <link rel="canonical" href="https://www.ithome.com/0/999/111.htm" />
            <meta property="article:published_time" content="2026-07-02T08:45:00+00:00" />
          </head>
          <body><h1 class="post_title">Detail title wins</h1></body>
        </html>
        """

        row = enrich_ithome_candidate_from_detail(
            IthomeSearchCandidate(
                title="List title",
                url="https://www.ithome.com/0/999/111.htm",
                state_text="\u4eca\u65e5 09:30",
                seen_date="2026-07-02",
                published_at="2026-07-02T09:30:00+00:00",
            ),
            detail_html,
            source=source,
            seen_date="2026-07-02",
            collected_at="2026-07-02T10:03:00+00:00",
            window_end="2026-07-02T10:03:00+00:00",
        )

        self.assertIsNotNone(row)
        assert row is not None
        self.assertEqual(row["title"], "Detail title wins")
        self.assertEqual(row["published_at"], "2026-07-02T08:45:00+00:00")
        self.assertEqual(row["seen_date"], "2026-07-02")

    def test_parse_ithome_published_at_supports_relative_and_month_day_labels(self) -> None:
        from phone_watch.news_crawler import parse_ithome_published_at

        window_end = "2026-07-02T10:03:00+00:00"

        self.assertEqual(parse_ithome_published_at("今日 09:30", window_end=window_end), "2026-07-02T09:30:00+00:00")
        self.assertEqual(parse_ithome_published_at("昨日 22:10", window_end=window_end), "2026-07-01T22:10:00+00:00")
        self.assertEqual(parse_ithome_published_at("07月01日 18:30", window_end=window_end), "2026-07-01T18:30:00+00:00")
        self.assertEqual(parse_ithome_published_at("07月01日", window_end=window_end), "2026-07-01T00:00:00+00:00")
        self.assertIsNone(parse_ithome_published_at("来源：IT之家", window_end=window_end))

    def test_ithome_blocked_detection_distinguishes_login_page_from_result_list(self) -> None:
        from phone_watch.news_crawler import is_ithome_blocked_or_error

        login_html = """
        <html>
          <head><title>\u767b\u5f55\u8f6f\u5a92\u901a\u884c\u8bc1</title></head>
          <body><main>\u8bf7\u767b\u5f55\u540e\u7ee7\u7eed\u8bbf\u95ee</main></body>
        </html>
        """
        result_html = """
        <html>
          <head><title>IT\u4e4b\u5bb6\u641c\u7d22</title></head>
          <body>
            <div id="list"><div class="fl"><ul class="bl">
              <li>
                <a class="title" href="https://www.ithome.com/0/999/105.htm" title="vivo phone news">vivo phone news</a>
                <span class="state">\u4eca\u65e5 09:30</span>
              </li>
            </ul></div></div>
          </body>
        </html>
        """

        self.assertTrue(is_ithome_blocked_or_error(login_html))
        self.assertFalse(is_ithome_blocked_or_error(result_html))

    def test_ithome_search_keyword_from_url_decodes_keyword(self) -> None:
        from phone_watch.news_crawler import ithome_search_keyword_from_url

        self.assertEqual(
            ithome_search_keyword_from_url("https://www.ithome.com/search/%E5%8D%8E%E4%B8%BA%E6%89%8B%E6%9C%BA.html"),
            "\u534e\u4e3a\u624b\u673a",
        )
        self.assertEqual(
            ithome_search_keyword_from_url("https://www.ithome.com/search/%E7%BA%A2%E9%AD%94.html"),
            "\u7ea2\u9b54",
        )
        self.assertIsNone(ithome_search_keyword_from_url("https://mobile.ithome.com/"))

    def test_collect_news_sources_to_db_uses_real_browser_search_fallback_for_blocked_ithome_search(self) -> None:
        from phone_watch.news_crawler import collect_news_sources_to_db

        keyword = "\u534e\u4e3a\u624b\u673a"
        config = NewsConfig(
            retention_days=7,
            fallback_limit=3,
            brand_keywords={"HUAWEI": (keyword,)},
            sources=(
                NewsSource(
                    brand="HUAWEI",
                    source_type="ithome_brand_search",
                    source_name="IT Home brand search",
                    start_urls=("https://www.ithome.com/search/%E5%8D%8E%E4%B8%BA%E6%89%8B%E6%9C%BA.html",),
                    render=False,
                ),
            ),
        )
        fetch_calls: list[tuple[str, bool]] = []
        browser_keywords: list[str] = []

        def fetcher(url: str, *, render: bool, timeout: int, allow_render_fallback: bool) -> str:
            fetch_calls.append((url, render))
            return """
            <html>
              <head><title>\u767b\u5f55\u8f6f\u5a92\u901a\u884c\u8bc1</title></head>
              <body>login required</body>
            </html>
            """

        def browser_fetcher(keyword: str, *, timeout: int) -> tuple[str, dict[str, int]]:
            browser_keywords.append(keyword)
            return (
                """
                <div id="list"><div class="fl"><ul class="bl">
                  <li>
                    <h2><a class="title" title="Huawei real browser news" href="https://www.ithome.com/0/999/801.htm">Huawei real browser news</a></h2>
                    <span class="state">\u4eca\u65e5 09:30</span>
                  </li>
                </ul></div></div>
                """,
                {"rendered": 1, "render_errors": 0, "fallbacks": 1},
            )

        def detail_fetcher(url: str, *, render: bool, timeout: int, allow_render_fallback: bool) -> str:
            return "<html><body><h1>Huawei real browser news</h1></body></html>"

        with redirect_stdout(io.StringIO()):
            counts = collect_news_sources_to_db(
                self.conn,
                config,
                brand="HUAWEI",
                timeout=5,
                render_mode="config",
                allow_render_fallback=True,
                fetcher=fetcher,
                detail_fetcher=detail_fetcher,
                ithome_search_browser_fetcher=browser_fetcher,
                now="2026-07-02T08:00:00+00:00",
                sleeper=lambda _seconds: None,
            )

        rows = db.list_news_items(self.conn, brand="HUAWEI")
        self.assertEqual(
            fetch_calls,
            [("https://www.ithome.com/search/%E5%8D%8E%E4%B8%BA%E6%89%8B%E6%9C%BA.html", False)],
        )
        self.assertEqual(browser_keywords, [keyword])
        self.assertEqual(counts["inserted"], 1)
        self.assertEqual(counts["rendered"], 1)
        self.assertEqual(counts["fallbacks"], 1)
        self.assertEqual(counts["errors"], 0)
        self.assertEqual(rows[0]["title"], "Huawei real browser news")

    def test_collect_news_sources_to_db_uses_playwright_fallback_for_blocked_ithome_search(self) -> None:
        from phone_watch.news_crawler import collect_news_sources_to_db

        config = NewsConfig(
            retention_days=7,
            fallback_limit=3,
            brand_keywords={"VIVO": ("vivo",)},
            sources=(
                NewsSource(
                    brand="VIVO",
                    source_type="ithome_brand_search",
                    source_name="IT Home brand search",
                    start_urls=("https://www.ithome.com/search/vivo.html",),
                    render=False,
                ),
            ),
        )
        calls: list[bool] = []

        def fetcher(url: str, *, render: bool, timeout: int, allow_render_fallback: bool):
            calls.append(render)
            if not render:
                return """
                <html>
                  <head><title>\u767b\u5f55\u8f6f\u5a92\u901a\u884c\u8bc1</title></head>
                  <body>login required</body>
                </html>
                """
            return (
                """
                <div id="list"><div class="fl"><ul class="bl">
                  <li>
                    <h2><a class="title" title="vivo fallback news" href="https://www.ithome.com/0/999/701.htm">vivo fallback news</a></h2>
                    <span class="state">\u4eca\u65e5 09:30</span>
                  </li>
                </ul></div></div>
                """,
                {"rendered": 1, "render_errors": 0, "fallbacks": 1},
            )

        def detail_fetcher(url: str, *, render: bool, timeout: int, allow_render_fallback: bool) -> str:
            return "<html><body><h1>vivo fallback news</h1></body></html>"

        with redirect_stdout(io.StringIO()):
            counts = collect_news_sources_to_db(
                self.conn,
                config,
                brand="VIVO",
                timeout=5,
                render_mode="config",
                allow_render_fallback=True,
                fetcher=fetcher,
                detail_fetcher=detail_fetcher,
                now="2026-07-02T08:00:00+00:00",
                sleeper=lambda _seconds: None,
            )

        rows = db.list_news_items(self.conn, brand="VIVO")
        self.assertEqual(calls, [False, True])
        self.assertEqual(counts["inserted"], 1)
        self.assertEqual(counts["rendered"], 1)
        self.assertEqual(counts["fallbacks"], 1)
        self.assertEqual(counts["errors"], 0)
        self.assertEqual(rows[0]["title"], "vivo fallback news")

    def test_collect_news_sources_to_db_fetches_each_ithome_detail_and_counts_detail_errors(self) -> None:
        from phone_watch.news_crawler import collect_news_sources_to_db

        config = NewsConfig(
            retention_days=7,
            fallback_limit=3,
            brand_keywords={"XIAOMI": ("xiaomi",)},
            sources=(
                NewsSource(
                    brand="XIAOMI",
                    source_type="ithome_brand_search",
                    source_name="IT Home brand search",
                    search_keywords=("xiaomi",),
                    render=False,
                ),
            ),
        )
        detail_calls: list[str] = []

        def fetcher(url: str, *, render: bool, timeout: int, allow_render_fallback: bool) -> str:
            return """
            <div id="list"><div class="fl"><ul class="bl">
              <li><h2><a class="title" title="list one" href="https://www.ithome.com/0/999/111.htm">list one</a></h2><span class="state">\u4eca\u65e5 09:30</span></li>
              <li><h2><a class="title" title="list two" href="https://www.ithome.com/0/999/112.htm">list two</a></h2><span class="state">\u4eca\u65e5 09:20</span></li>
            </ul></div></div>
            """

        def detail_fetcher(url: str, *, render: bool, timeout: int, allow_render_fallback: bool) -> str:
            detail_calls.append(url)
            if url.endswith("/112.htm"):
                raise TimeoutError("detail timeout")
            return """
            <html>
              <head><meta property="article:published_time" content="2026-07-02T09:11:00+00:00" /></head>
              <body><h1>detail one title</h1></body>
            </html>
            """

        with redirect_stdout(io.StringIO()):
            counts = collect_news_sources_to_db(
                self.conn,
                config,
                brand="XIAOMI",
                timeout=5,
                fetcher=fetcher,
                detail_fetcher=detail_fetcher,
                now="2026-07-02T10:03:00+00:00",
                detail_sleeper=lambda _seconds: None,
                detail_random_uniform=lambda start, _end: start,
                sleeper=lambda _seconds: None,
            )

        rows = db.list_news_items(self.conn, brand="XIAOMI")

        self.assertEqual(detail_calls, ["https://www.ithome.com/0/999/111.htm", "https://www.ithome.com/0/999/112.htm"])
        self.assertEqual(counts["detail_fetched"], 1)
        self.assertEqual(counts["detail_errors"], 1)
        self.assertEqual(counts["errors"], 0)
        self.assertEqual(counts["inserted"], 2)
        self.assertEqual({row["title"] for row in rows}, {"detail one title", "list two"})

    def test_collect_news_sources_to_db_uses_browser_search_fallback_then_fetches_details(self) -> None:
        from phone_watch.news_crawler import collect_news_sources_to_db

        keyword = "\u534e\u4e3a\u624b\u673a"
        config = NewsConfig(
            retention_days=7,
            fallback_limit=3,
            brand_keywords={"HUAWEI": (keyword,)},
            sources=(
                NewsSource(
                    brand="HUAWEI",
                    source_type="ithome_brand_search",
                    source_name="IT Home brand search",
                    start_urls=("https://www.ithome.com/search/%E5%8D%8E%E4%B8%BA%E6%89%8B%E6%9C%BA.html",),
                    render=False,
                ),
            ),
        )
        browser_keywords: list[str] = []
        detail_calls: list[str] = []

        def fetcher(url: str, *, render: bool, timeout: int, allow_render_fallback: bool) -> str:
            return """
            <html>
              <head><title>\u767b\u5f55\u8f6f\u5a92\u901a\u884c\u8bc1</title></head>
              <body>login required</body>
            </html>
            """

        def browser_fetcher(keyword: str, *, timeout: int) -> tuple[str, dict[str, int]]:
            browser_keywords.append(keyword)
            return (
                """
                <div id="list"><div class="fl"><ul class="bl">
                  <li>
                    <h2><a class="title" title="Huawei fallback list" href="https://www.ithome.com/0/999/801.htm">Huawei fallback list</a></h2>
                    <span class="state">\u4eca\u65e5 09:30</span>
                  </li>
                </ul></div></div>
                """,
                {"rendered": 1, "render_errors": 0, "fallbacks": 1},
            )

        def detail_fetcher(url: str, *, render: bool, timeout: int, allow_render_fallback: bool) -> str:
            detail_calls.append(url)
            return "<html><body><h1>Huawei detail title</h1></body></html>"

        with redirect_stdout(io.StringIO()):
            counts = collect_news_sources_to_db(
                self.conn,
                config,
                brand="HUAWEI",
                timeout=5,
                render_mode="config",
                allow_render_fallback=True,
                fetcher=fetcher,
                detail_fetcher=detail_fetcher,
                ithome_search_browser_fetcher=browser_fetcher,
                now="2026-07-02T08:00:00+00:00",
                detail_sleeper=lambda _seconds: None,
                sleeper=lambda _seconds: None,
            )

        rows = db.list_news_items(self.conn, brand="HUAWEI")

        self.assertEqual(browser_keywords, [keyword])
        self.assertEqual(detail_calls, ["https://www.ithome.com/0/999/801.htm"])
        self.assertEqual(counts["detail_fetched"], 1)
        self.assertEqual(counts["detail_errors"], 0)
        self.assertEqual(counts["inserted"], 1)
        self.assertEqual(rows[0]["title"], "Huawei detail title")

    def test_parse_ithome_phone_today_html_maps_brand_and_keeps_unknown_as_all(self) -> None:
        from phone_watch.news_crawler import parse_ithome_phone_today_html

        vivo_title = "\u5168\u65b0 vivo X \u624b\u673a\u4eca\u65e5\u53d1\u5e03"
        honor_title = "\u8363\u8000\u624b\u673a\u65b0\u54c1\u516c\u5e03"
        unknown_title = "\u624b\u673a\u884c\u4e1a\u4eca\u65e5\u65b0\u54c1\u6c47\u603b"
        html = f"""
        <article><span>2026-06-30</span><a href="/0/999/101.htm">{vivo_title}</a></article>
        <article><span>2026-06-29</span><a href="/0/999/102.htm">{honor_title}</a></article>
        <article><span>2026-06-30</span><a href="/0/999/103.htm">{unknown_title}</a></article>
        """

        rows = parse_ithome_phone_today_html(
            html,
            "https://www.ithome.com/category/phone",
            source_name="IT Home phone today",
            seen_date="2026-06-30",
            collected_at="2026-06-30T08:00:00+00:00",
        )

        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["brand"], "VIVO")
        self.assertEqual(rows[0]["title"], vivo_title)
        self.assertEqual(rows[0]["source_type"], "ithome_phone_today")
        self.assertEqual(rows[0]["url"], "https://www.ithome.com/0/999/101.htm")
        self.assertEqual(rows[1]["brand"], "ALL")
        self.assertEqual(rows[1]["title"], unknown_title)
        self.assertEqual(rows[1]["url"], "https://www.ithome.com/0/999/103.htm")

    def test_ithome_phone_today_accepts_mobile_ithome_article_links(self) -> None:
        from phone_watch.news_crawler import parse_ithome_phone_today_html

        title = "\u5c0f\u7c73\u624b\u673a\u65b0\u54c1\u4eca\u65e5\u53d1\u5e03"
        html = f"""
        <article><span>2026-06-30</span><a href="https://mobile.ithome.com/0/999/104.htm">{title}</a></article>
        """

        rows = parse_ithome_phone_today_html(
            html,
            "https://mobile.ithome.com/",
            source_name="IT Home phone today",
            seen_date="2026-06-30",
            collected_at="2026-06-30T08:00:00+00:00",
        )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["brand"], "XIAOMI")
        self.assertEqual(rows[0]["url"], "https://mobile.ithome.com/0/999/104.htm")

    def test_collect_news_sources_to_db_writes_rows_and_counts_source_errors(self) -> None:
        from phone_watch.news_crawler import collect_news_sources_to_db

        config = NewsConfig(
            retention_days=7,
            fallback_limit=3,
            brand_keywords={"VIVO": ("vivo phone",)},
            sources=(
                NewsSource(
                    brand="VIVO",
                    source_type="ithome_brand_search",
                    source_name="IT Home brand tag timeout",
                    start_urls=("https://www.ithome.com/tags/vivo-timeout/",),
                ),
                NewsSource(
                    brand="VIVO",
                    source_type="ithome_brand_search",
                    source_name="IT Home brand search",
                    start_urls=("https://www.ithome.com/tags/vivo/",),
                ),
            ),
        )

        def fetcher(url: str, *, render: bool, timeout: int) -> str:
            if "vivo-timeout" in url:
                raise TimeoutError("source timeout")
            return '<a href="https://www.ithome.com/0/999/201.htm">vivo phone news</a>'

        def detail_fetcher(url: str, *, render: bool, timeout: int, allow_render_fallback: bool) -> str:
            return "<html><body><h1>vivo phone news</h1></body></html>"

        with redirect_stdout(io.StringIO()):
            counts = collect_news_sources_to_db(
                self.conn,
                config,
                brand="VIVO",
                timeout=5,
                fetcher=fetcher,
                detail_fetcher=detail_fetcher,
                now="2026-06-30T08:00:00+00:00",
            )
        rows = db.list_news_items(self.conn, brand="VIVO")

        self.assertEqual(counts["sources"], 2)
        self.assertEqual(counts["inserted"], 2)
        self.assertEqual(counts["errors"], 1)
        self.assertEqual({row["title"] for row in rows}, {"vivo phone news", "IT Home brand tag timeout 当日爬取失败"})
        failure_row = [row for row in rows if row["title"].endswith("当日爬取失败")][0]
        self.assertIn("brand tag failed", failure_row["last_error"])

    def test_collect_news_sources_to_db_filters_window_and_skips_existing_fallback_rows(self) -> None:
        from phone_watch.news_crawler import collect_news_sources_to_db

        config = NewsConfig(
            retention_days=7,
            fallback_limit=3,
            brand_keywords={"VIVO": ("vivo phone",)},
            sources=(
                NewsSource(
                    brand="VIVO",
                    source_type="ithome_brand_search",
                    source_name="IT Home brand search",
                    start_urls=("https://www.ithome.com/search/vivo.html",),
                ),
            ),
        )
        db.upsert_news_item(
            self.conn,
            {
                "brand": "VIVO",
                "source_type": "ithome_brand_search",
                "source_name": "IT Home brand search",
                "title": "existing old vivo",
                "url": "https://www.ithome.com/0/999/601.htm",
                "first_collected_at": "2026-07-01T08:00:00+00:00",
                "last_collected_at": "2026-07-01T08:00:00+00:00",
                "seen_date": "2026-07-01",
                "published_at": "2026-07-01T08:00:00+00:00",
            },
        )

        def fetcher(url: str, *, render: bool, timeout: int, allow_render_fallback: bool) -> str:
            return """
            <div id="list"><div class="fl"><ul class="bl">
              <li>
                <h2><a class="title" title="existing old vivo" href="https://www.ithome.com/0/999/601.htm">existing old vivo</a></h2>
                <span class="state">07月01日 08:00</span>
              </li>
              <li>
                <h2><a class="title" title="new window vivo" href="https://www.ithome.com/0/999/602.htm">new window vivo</a></h2>
                <span class="state">今日 09:30</span>
              </li>
            </ul></div></div>
            """

        counts = collect_news_sources_to_db(
            self.conn,
            config,
            brand="VIVO",
            timeout=5,
            fetcher=fetcher,
            now="2026-07-02T10:03:00+00:00",
            window_start="2026-07-01T10:05:00+00:00",
            window_end="2026-07-02T10:03:00+00:00",
            collect_run_id=7,
            sleeper=lambda _seconds: None,
        )
        rows = db.list_news_items(self.conn, brand="VIVO")

        self.assertEqual(counts["inserted"], 1)
        self.assertEqual([row["title"] for row in rows], ["new window vivo", "existing old vivo"])
        old_row = [row for row in rows if row["title"] == "existing old vivo"][0]
        self.assertEqual(old_row["last_collected_at"], "2026-07-01T08:00:00+00:00")
        new_row = [row for row in rows if row["title"] == "new window vivo"][0]
        self.assertEqual(new_row["published_at"], "2026-07-02T09:30:00+00:00")
        self.assertEqual(new_row["collect_run_id"], 7)

    def test_collect_news_sources_to_db_backfills_recent_rows_only_until_fallback_limit(self) -> None:
        from phone_watch.news_crawler import collect_news_sources_to_db

        config = NewsConfig(
            retention_days=7,
            fallback_limit=3,
            brand_keywords={"VIVO": ("vivo phone",)},
            sources=(
                NewsSource(
                    brand="VIVO",
                    source_type="ithome_brand_search",
                    source_name="IT Home brand search",
                    start_urls=("https://www.ithome.com/search/vivo.html",),
                ),
            ),
        )
        db.upsert_news_item(
            self.conn,
            {
                "brand": "VIVO",
                "source_type": "ithome_brand_search",
                "source_name": "IT Home brand search",
                "title": "existing recent vivo",
                "url": "https://www.ithome.com/0/999/701.htm",
                "first_collected_at": "2026-07-01T08:00:00+00:00",
                "last_collected_at": "2026-07-01T08:00:00+00:00",
                "seen_date": "2026-07-01",
                "published_at": "2026-07-01T08:00:00+00:00",
            },
        )

        def fetcher(url: str, *, render: bool, timeout: int, allow_render_fallback: bool) -> str:
            return """
            <div id="list"><div class="fl"><ul class="bl">
              <li><h2><a class="title" title="outside vivo 1" href="https://www.ithome.com/0/999/702.htm">outside vivo 1</a></h2><span class="state">07月01日 08:30</span></li>
              <li><h2><a class="title" title="outside vivo 2" href="https://www.ithome.com/0/999/703.htm">outside vivo 2</a></h2><span class="state">07月01日 08:20</span></li>
              <li><h2><a class="title" title="outside vivo 3" href="https://www.ithome.com/0/999/704.htm">outside vivo 3</a></h2><span class="state">07月01日 08:10</span></li>
            </ul></div></div>
            """

        counts = collect_news_sources_to_db(
            self.conn,
            config,
            brand="VIVO",
            timeout=5,
            fetcher=fetcher,
            now="2026-07-02T10:03:00+00:00",
            window_start="2026-07-01T10:05:00+00:00",
            window_end="2026-07-02T10:03:00+00:00",
            sleeper=lambda _seconds: None,
        )
        rows = db.list_news_items(self.conn, brand="VIVO")

        self.assertEqual(counts["inserted"], 2)
        self.assertEqual(len(rows), 3)
        self.assertEqual(
            {row["title"] for row in rows},
            {"existing recent vivo", "outside vivo 1", "outside vivo 2"},
        )

    def test_collect_news_sources_to_db_honors_render_modes_and_reports_fetch_stats(self) -> None:
        from phone_watch.news_crawler import collect_news_sources_to_db

        config = NewsConfig(
            retention_days=7,
            fallback_limit=3,
            brand_keywords={"VIVO": ("vivo phone",)},
            sources=(
                NewsSource(
                    brand="VIVO",
                    source_type="ithome_brand_search",
                    source_name="IT Home brand tag",
                    start_urls=("https://www.ithome.com/tags/vivo/",),
                    render=True,
                ),
                NewsSource(
                    brand="ALL",
                    source_type="ithome_phone_today",
                    source_name="IT Home phone today",
                    start_urls=("https://mobile.ithome.com/",),
                    render=False,
                ),
            ),
        )

        def run_mode(render_mode: str) -> tuple[dict[str, int], list[bool]]:
            render_flags: list[bool] = []

            def fetcher(url: str, *, render: bool, timeout: int, allow_render_fallback: bool):
                render_flags.append(render)
                if "tags/vivo" in url:
                    return (
                        '<a href="https://www.ithome.com/0/999/501.htm">vivo phone news</a>',
                        {"rendered": int(render), "render_errors": 0, "fallbacks": 0},
                    )
                return (
                    '<article><span>2026-06-30</span><a href="https://mobile.ithome.com/0/999/502.htm">vivo phone today</a></article>',
                    {"rendered": int(render), "render_errors": 0, "fallbacks": 0},
                )

            def detail_fetcher(url: str, *, render: bool, timeout: int, allow_render_fallback: bool) -> str:
                return "<html><body><h1>vivo phone news</h1></body></html>"

            counts = collect_news_sources_to_db(
                self.conn,
                config,
                brand="VIVO",
                timeout=5,
                render_mode=render_mode,
                fetcher=fetcher,
                detail_fetcher=detail_fetcher,
                now="2026-06-30T08:00:00+00:00",
            )
            return counts, render_flags

        config_counts, config_flags = run_mode("config")
        always_counts, always_flags = run_mode("always")
        playwright_counts, playwright_flags = run_mode("playwright")
        never_counts, never_flags = run_mode("never")

        self.assertEqual(config_flags, [False, True])
        self.assertEqual(always_flags, [True, True])
        self.assertEqual(playwright_flags, [True, True])
        self.assertEqual(never_flags, [False, False])
        self.assertEqual(config_counts["rendered"], 1)
        self.assertEqual(always_counts["rendered"], 2)
        self.assertEqual(playwright_counts["rendered"], 2)
        self.assertEqual(never_counts["rendered"], 0)

    def test_collect_news_sources_to_db_throttles_ithome_search_requests(self) -> None:
        from phone_watch.news_crawler import collect_news_sources_to_db

        config = NewsConfig(
            retention_days=7,
            fallback_limit=3,
            brand_keywords={"VIVO": ("vivo",)},
            sources=(
                NewsSource(
                    brand="VIVO",
                    source_type="ithome_brand_search",
                    source_name="IT Home brand search",
                    start_urls=(
                        "https://www.ithome.com/search/vivo.html",
                        "https://www.ithome.com/search/oppo.html",
                        "https://www.ithome.com/search/xiaomi.html",
                        "https://www.ithome.com/search/zte.html",
                    ),
                    render=False,
                ),
                NewsSource(
                    brand="ALL",
                    source_type="ithome_phone_today",
                    source_name="IT Home phone today",
                    start_urls=("https://mobile.ithome.com/",),
                    render=False,
                ),
            ),
        )
        delay_ranges: list[tuple[int, int]] = []
        sleep_calls: list[float] = []

        def fake_random_uniform(start: float, end: float) -> float:
            delay_ranges.append((int(start), int(end)))
            return start + 0.5

        def fake_sleep(seconds: float) -> None:
            sleep_calls.append(seconds)

        def fetcher(url: str, *, render: bool, timeout: int, allow_render_fallback: bool) -> str:
            if "mobile.ithome.com" in url:
                return '<article><span>2026-07-02</span><a href="https://mobile.ithome.com/0/999/900.htm">phone today</a></article>'
            return '<a href="https://www.ithome.com/0/999/901.htm">brand phone news</a>'

        with redirect_stdout(io.StringIO()):
            counts = collect_news_sources_to_db(
                self.conn,
                config,
                brand="VIVO",
                timeout=5,
                fetcher=fetcher,
                now="2026-07-02T08:00:00+00:00",
                sleeper=fake_sleep,
                random_uniform=fake_random_uniform,
            )

        self.assertEqual(delay_ranges, [(8, 20), (8, 20), (8, 20), (30, 60), (8, 20)])
        self.assertEqual(sleep_calls, [8.5, 8.5, 8.5, 30.5, 8.5])
        self.assertEqual(counts["fetched"], 5)

    def test_ithome_brand_source_uses_keyword_tag_urls_before_start_urls(self) -> None:
        from phone_watch.news_crawler import urls_for_source

        source = NewsSource(
            brand="XIAOMI",
            source_type="ithome_brand_search",
            source_name="IT之家品牌关键词搜索",
            start_urls=("https://www.ithome.com/tags/小米/",),
            search_keywords=("小米",),
            render=True,
        )

        self.assertEqual(
            urls_for_source(source),
            ["https://www.ithome.com/tags/%E5%B0%8F%E7%B1%B3/"],
        )

    def test_ithome_brand_source_generates_multiple_keyword_tag_urls(self) -> None:
        from phone_watch.news_crawler import urls_for_source

        source = NewsSource(
            brand="ZTE",
            source_type="ithome_brand_search",
            source_name="IT之家品牌关键词搜索",
            search_keywords=("中兴手机", "努比亚", "红魔"),
            render=True,
        )

        self.assertEqual(
            urls_for_source(source),
            [
                "https://www.ithome.com/tags/%E4%B8%AD%E5%85%B4%E6%89%8B%E6%9C%BA/",
                "https://www.ithome.com/tags/%E5%8A%AA%E6%AF%94%E4%BA%9A/",
                "https://www.ithome.com/tags/%E7%BA%A2%E9%AD%94/",
            ],
        )

    def test_collect_news_sources_to_db_uses_mobile_cache_when_brand_tag_empty_and_records_error(self) -> None:
        from phone_watch.news_crawler import collect_news_sources_to_db

        config = NewsConfig(
            retention_days=7,
            fallback_limit=3,
            brand_keywords={"OPPO": ("OPPO",)},
            sources=(
                NewsSource(
                    brand="ALL",
                    source_type="ithome_phone_today",
                    source_name="IT Home phone today",
                    start_urls=("https://mobile.ithome.com/",),
                    render=False,
                ),
                NewsSource(
                    brand="OPPO",
                    source_type="ithome_brand_search",
                    source_name="IT Home brand tag",
                    search_keywords=("OPPO",),
                    render=False,
                ),
            ),
        )

        def fetcher(url: str, *, render: bool, timeout: int, allow_render_fallback: bool) -> str:
            if "mobile.ithome.com" in url:
                return """
                <article><span>2026-07-03</span><a href="https://mobile.ithome.com/0/999/801.htm">OPPO phone from mobile</a></article>
                <article><span>2026-07-03</span><a href="https://mobile.ithome.com/0/999/802.htm">Samsung phone from mobile</a></article>
                """
            return "<html><body>登录软媒通行证</body></html>"

        with redirect_stdout(io.StringIO()):
            counts = collect_news_sources_to_db(
                self.conn,
                config,
                brand="OPPO",
                timeout=5,
                render_mode="never",
                allow_render_fallback=True,
                fetcher=fetcher,
                now="2026-07-03T08:00:00+00:00",
            )

        rows = db.list_news_items(self.conn, brand="OPPO", source_type="ithome_brand_search")

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["title"], "OPPO phone from mobile")
        self.assertIn("brand tag failed", rows[0]["last_error"])
        self.assertEqual(counts["errors"], 1)
        self.assertEqual(counts["fallbacks"], 1)

    def test_collect_news_sources_to_db_prefetches_mobile_cache_when_brand_source_comes_first(self) -> None:
        from phone_watch.news_crawler import collect_news_sources_to_db

        config = NewsConfig(
            retention_days=7,
            fallback_limit=3,
            brand_keywords={"OPPO": ("OPPO",)},
            sources=(
                NewsSource(
                    brand="OPPO",
                    source_type="ithome_brand_search",
                    source_name="IT Home brand tag",
                    search_keywords=("OPPO",),
                    render=False,
                ),
                NewsSource(
                    brand="ALL",
                    source_type="ithome_phone_today",
                    source_name="IT Home phone today",
                    start_urls=("https://mobile.ithome.com/",),
                    render=False,
                ),
            ),
        )
        fetched_urls: list[str] = []

        def fetcher(url: str, *, render: bool, timeout: int, allow_render_fallback: bool) -> str:
            fetched_urls.append(url)
            if "mobile.ithome.com" in url:
                return """
                <article><span>2026-07-03</span><a href="https://mobile.ithome.com/0/999/811.htm">OPPO phone from mobile cache</a></article>
                """
            return "<html><body>登录软媒通行证</body></html>"

        with redirect_stdout(io.StringIO()):
            counts = collect_news_sources_to_db(
                self.conn,
                config,
                brand="OPPO",
                timeout=5,
                render_mode="never",
                allow_render_fallback=True,
                fetcher=fetcher,
                now="2026-07-03T08:00:00+00:00",
            )

        rows = db.list_news_items(self.conn, brand="OPPO", source_type="ithome_brand_search")

        self.assertEqual(fetched_urls[0], "https://mobile.ithome.com/")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["title"], "OPPO phone from mobile cache")
        self.assertIn("brand tag failed", rows[0]["last_error"])
        self.assertEqual(counts["errors"], 1)
        self.assertEqual(counts["fallbacks"], 1)

    def test_collect_news_sources_to_db_uses_mobile_cache_when_brand_tag_fetch_fails(self) -> None:
        from phone_watch.news_crawler import collect_news_sources_to_db

        config = NewsConfig(
            retention_days=7,
            fallback_limit=3,
            brand_keywords={"SAMSUNG": ("三星手机",)},
            sources=(
                NewsSource(
                    brand="ALL",
                    source_type="ithome_phone_today",
                    source_name="IT Home phone today",
                    start_urls=("https://mobile.ithome.com/",),
                    render=False,
                ),
                NewsSource(
                    brand="SAMSUNG",
                    source_type="ithome_brand_search",
                    source_name="IT Home brand tag",
                    search_keywords=("三星手机",),
                    render=False,
                ),
            ),
        )

        def fetcher(url: str, *, render: bool, timeout: int, allow_render_fallback: bool) -> str:
            if "mobile.ithome.com" in url:
                return """
                <article><span>2026-07-03</span><a href="https://mobile.ithome.com/0/999/821.htm">三星手机 from mobile cache</a></article>
                """
            raise TimeoutError("tag fetch failed")

        with redirect_stdout(io.StringIO()):
            counts = collect_news_sources_to_db(
                self.conn,
                config,
                brand="SAMSUNG",
                timeout=5,
                render_mode="never",
                allow_render_fallback=True,
                fetcher=fetcher,
                now="2026-07-03T08:00:00+00:00",
            )

        rows = db.list_news_items(self.conn, brand="SAMSUNG", source_type="ithome_brand_search")

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["title"], "三星手机 from mobile cache")
        self.assertIn("brand tag failed", rows[0]["last_error"])
        self.assertEqual(counts["errors"], 1)
        self.assertEqual(counts["fallbacks"], 1)

    def test_collect_news_sources_to_db_records_brand_tag_failure_when_no_mobile_match(self) -> None:
        from phone_watch.news_crawler import collect_news_sources_to_db

        config = NewsConfig(
            retention_days=7,
            fallback_limit=3,
            brand_keywords={"HUAWEI": ("华为手机",)},
            sources=(
                NewsSource(
                    brand="ALL",
                    source_type="ithome_phone_today",
                    source_name="IT Home phone today",
                    start_urls=("https://mobile.ithome.com/",),
                    render=False,
                ),
                NewsSource(
                    brand="HUAWEI",
                    source_type="ithome_brand_search",
                    source_name="IT Home brand tag",
                    search_keywords=("华为手机",),
                    render=False,
                ),
            ),
        )

        def fetcher(url: str, *, render: bool, timeout: int, allow_render_fallback: bool) -> str:
            if "mobile.ithome.com" in url:
                return """
                <article><span>2026-07-03</span><a href="https://mobile.ithome.com/0/999/831.htm">OPPO phone from mobile cache</a></article>
                """
            raise TimeoutError("tag fetch failed")

        with redirect_stdout(io.StringIO()):
            counts = collect_news_sources_to_db(
                self.conn,
                config,
                brand="HUAWEI",
                timeout=5,
                render_mode="never",
                allow_render_fallback=True,
                fetcher=fetcher,
                now="2026-07-03T08:00:00+00:00",
            )

        rows = db.list_news_items(self.conn, brand="HUAWEI", source_type="ithome_brand_search")

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["title"], "IT Home brand tag 当日爬取失败")
        self.assertEqual(rows[0]["url"], "https://www.ithome.com/tags/%E5%8D%8E%E4%B8%BA%E6%89%8B%E6%9C%BA/")
        self.assertIn("brand tag failed", rows[0]["last_error"])
        self.assertEqual(counts["errors"], 1)
        self.assertEqual(counts["fallbacks"], 0)

    def test_collect_news_sources_to_db_counts_render_fallbacks_and_nonfallback_errors(self) -> None:
        from phone_watch.news_crawler import collect_news_sources_to_db

        config = NewsConfig(
            retention_days=7,
            fallback_limit=3,
            brand_keywords={"VIVO": ("vivo phone",)},
            sources=(
                NewsSource(
                    brand="VIVO",
                    source_type="ithome_brand_search",
                    source_name="IT Home brand tag",
                    start_urls=("https://www.ithome.com/tags/vivo/",),
                    render=True,
                ),
            ),
        )

        def fallback_fetcher(url: str, *, render: bool, timeout: int, allow_render_fallback: bool):
            self.assertTrue(render)
            self.assertTrue(allow_render_fallback)
            return (
                '<a href="https://www.ithome.com/0/999/601.htm">vivo launch news</a>',
                {"rendered": 0, "render_errors": 1, "fallbacks": 1},
            )

        def detail_fetcher(url: str, *, render: bool, timeout: int, allow_render_fallback: bool) -> str:
            return "<html><body><h1>vivo launch news</h1></body></html>"

        fallback_counts = collect_news_sources_to_db(
            self.conn,
            config,
            brand="VIVO",
            timeout=5,
            render_mode="config",
            allow_render_fallback=True,
            fetcher=fallback_fetcher,
            detail_fetcher=detail_fetcher,
            now="2026-06-30T08:00:00+00:00",
        )

        def failing_fetcher(url: str, *, render: bool, timeout: int, allow_render_fallback: bool):
            self.assertTrue(render)
            self.assertFalse(allow_render_fallback)
            raise RuntimeError("Playwright render failed")

        with redirect_stdout(io.StringIO()):
            failing_counts = collect_news_sources_to_db(
                self.conn,
                config,
                brand="VIVO",
                timeout=5,
                render_mode="config",
                allow_render_fallback=False,
                fetcher=failing_fetcher,
                now="2026-06-30T08:00:00+00:00",
            )

        self.assertEqual(fallback_counts["render_errors"], 1)
        self.assertEqual(fallback_counts["fallbacks"], 1)
        self.assertEqual(fallback_counts["errors"], 0)
        self.assertEqual(failing_counts["errors"], 1)
        self.assertEqual(failing_counts["fetched"], 0)


if __name__ == "__main__":
    unittest.main()
