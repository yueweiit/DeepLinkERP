from __future__ import annotations

from datetime import date
import importlib.util
from pathlib import Path
import sys
import tempfile
from types import ModuleType
import unittest
from unittest.mock import patch


def load_script_module():
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "ithome_playwright_today.py"
    spec = importlib.util.spec_from_file_location("ithome_playwright_today", script_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load script: {script_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class IthomePlaywrightTodayScriptTests(unittest.TestCase):
    def setUp(self) -> None:
        self.module = load_script_module()
        self.today = date(2026, 7, 2)

    def test_article_date_from_text_maps_today_labels_only(self) -> None:
        article_date_from_text = self.module.article_date_from_text

        self.assertEqual(article_date_from_text("\u4eca\u65e5 09:30", self.today), "2026-07-02")
        self.assertEqual(article_date_from_text("2\u5c0f\u65f6\u524d", self.today), "2026-07-02")
        self.assertEqual(article_date_from_text("2026-07-02 08:20", self.today), "2026-07-02")
        self.assertEqual(article_date_from_text("07\u670802\u65e5 08:20", self.today), "2026-07-02")
        self.assertIsNone(article_date_from_text("\u6628\u65e5 23:50", self.today))
        self.assertIsNone(article_date_from_text("2026-07-01 23:50", self.today))

    def test_article_date_from_text_ignores_invalid_date_like_fragments(self) -> None:
        article_date_from_text = self.module.article_date_from_text

        self.assertIsNone(article_date_from_text("2026-13-40", self.today))
        self.assertIsNone(article_date_from_text("13/40", self.today))

    def test_extract_today_articles_from_search_page(self) -> None:
        html = """
        <div id="list"><div class="fl"><ul class="bl">
          <li>
            <h2><a class="title" title="Today search phone" href="/0/999/101.htm">Today search phone</a></h2>
            <div class="c" data-ot="2026-07-02T09:30:00+08:00"></div>
            <span class="state">\u4eca\u65e5 09:30</span>
          </li>
          <li>
            <h2><a class="title" title="Yesterday phone" href="/0/999/102.htm">Yesterday phone</a></h2>
            <span class="state">\u6628\u65e5 22:10</span>
          </li>
        </ul></div></div>
        """

        items = self.module.extract_today_articles(
            html,
            "https://www.ithome.com/search/vivo.html",
            source="brand_keyword",
            today=self.today,
            keyword="vivo",
        )

        self.assertEqual(
            items,
            [
                {
                    "date": "2026-07-02",
                    "published_at": "2026-07-02T09:30:00+08:00",
                    "title": "Today search phone",
                    "url": "https://www.ithome.com/0/999/101.htm",
                    "source": "brand_keyword",
                    "keyword": "vivo",
                }
            ],
        )

    def test_extract_today_articles_from_mobile_page_and_dedupes(self) -> None:
        html = """
        <article>
          <div class="c" data-ot="2026-07-02T09:30:00+08:00"></div>
          <span class="state">\u4eca\u65e5 09:30</span>
          <a href="https://mobile.ithome.com/0/999/201.htm">\u5c0f\u7c73\u4eca\u65e5\u65b0\u673a</a>
        </article>
        <article>
          <div class="c" data-ot="2026-07-02T09:30:00+08:00"></div>
          <span class="state">\u4eca\u65e5 09:30</span>
          <a href="https://mobile.ithome.com/0/999/201.htm">\u5c0f\u7c73\u4eca\u65e5\u65b0\u673a</a>
        </article>
        <article>
          <span class="state">\u6628\u65e5 18:20</span>
          <a href="https://mobile.ithome.com/0/999/202.htm">\u65e7\u95fb</a>
        </article>
        """

        items = self.module.extract_today_articles(
            html,
            "https://mobile.ithome.com/",
            source="mobile_phone",
            today=self.today,
        )

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["date"], "2026-07-02")
        self.assertEqual(items[0]["title"], "\u5c0f\u7c73\u4eca\u65e5\u65b0\u673a")
        self.assertEqual(items[0]["url"], "https://mobile.ithome.com/0/999/201.htm")

    def test_extract_today_articles_from_real_ithome_nested_list_item(self) -> None:
        html = """
        <div id="list" class="bb clearfix">
          <div class="fl">
            <ul class="bl">
              <li>
                <a href="https://www.ithome.com/0/972/035.htm" target="_blank" class="img">
                  <img alt="OPPO Reno16 全新配色“半夏青”今日开售，3299 元起">
                </a>
                <div class="c" data-ot="2026-07-02T10:29:19.0770000+08:00">
                  <h2>
                    <a title="OPPO Reno16 全新配色“半夏青”今日开售，3299 元起"
                       target="_blank"
                       href="https://www.ithome.com/0/972/035.htm"
                       class="title">OPPO Reno16 全新配色“半夏青”今日开售，3299 元起</a>
                  </h2>
                  <div class="m">该机配备 6.32 英寸 OLED 直屏。</div>
                  <div class="o">
                    <div class="tags"><strong>Tags：</strong><a href="//www.ithome.com/tags/OPPO%20Reno16/">OPPO Reno16</a></div>
                    <div class="d"><span class="state tody">今日 10:29</span></div>
                  </div>
                </div>
              </li>
            </ul>
          </div>
        </div>
        """

        items = self.module.extract_today_articles(
            html,
            "https://mobile.ithome.com/",
            source="mobile_phone",
            today=self.today,
        )

        self.assertEqual(
            items,
            [
                {
                    "date": "2026-07-02",
                    "published_at": "2026-07-02T10:29:19.0770000+08:00",
                    "title": "OPPO Reno16 全新配色“半夏青”今日开售，3299 元起",
                    "url": "https://www.ithome.com/0/972/035.htm",
                    "source": "mobile_phone",
                }
            ],
        )

    def test_extract_today_articles_regex_handles_nested_ithome_list_item_without_bs4(self) -> None:
        html = """
        <div id="list" class="bb clearfix">
          <div class="fl">
            <ul class="bl">
              <li>
                <a href="https://www.ithome.com/0/972/035.htm" target="_blank" class="img">
                  <img alt="OPPO Reno16 全新配色“半夏青”今日开售，3299 元起">
                </a>
                <div class="c" data-ot="2026-07-02T10:29:19.0770000+08:00">
                  <h2>
                    <a title="OPPO Reno16 全新配色“半夏青”今日开售，3299 元起"
                       target="_blank"
                       href="https://www.ithome.com/0/972/035.htm"
                       class="title">OPPO Reno16 全新配色“半夏青”今日开售，3299 元起</a>
                  </h2>
                  <div class="m">该机配备 6.32 英寸 OLED 直屏。</div>
                  <div class="o">
                    <div class="tags"><strong>Tags：</strong><a href="//www.ithome.com/tags/OPPO%20Reno16/">OPPO Reno16</a></div>
                    <div class="d"><span class="state tody">今日 10:29</span></div>
                  </div>
                </div>
              </li>
            </ul>
          </div>
        </div>
        """

        with patch.object(self.module, "BeautifulSoup", None):
            items = self.module.extract_today_articles(
                html,
                "https://mobile.ithome.com/",
                source="mobile_phone",
                today=self.today,
            )

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["title"], "OPPO Reno16 全新配色“半夏青”今日开售，3299 元起")
        self.assertEqual(items[0]["url"], "https://www.ithome.com/0/972/035.htm")

    def test_extract_today_articles_regex_handles_multiple_nested_ithome_list_items_without_bs4(self) -> None:
        html = """
        <div id="list" class="bb clearfix"><div class="fl"><ul class="bl">
          <li>
            <a href="https://www.ithome.com/0/972/035.htm" class="img"><img></a>
            <div class="c" data-ot="2026-07-02T10:29:19+08:00">
              <h2><a title="First phone" href="https://www.ithome.com/0/972/035.htm" class="title">First phone</a></h2>
              <div class="m">desc</div>
              <div class="o"><div class="tags"><a href="//www.ithome.com/tags/OPPO/">OPPO</a></div><div class="d"><span class="state tody">今日 10:29</span></div></div>
            </div>
          </li>
          <li>
            <a href="https://www.ithome.com/0/972/034.htm" class="img"><img></a>
            <div class="c" data-ot="2026-07-02T10:25:20+08:00">
              <h2><a title="Second phone" href="https://www.ithome.com/0/972/034.htm" class="title">Second phone</a></h2>
              <div class="m">desc</div>
              <div class="o"><div class="tags"><a href="//www.ithome.com/tags/Samsung/">Samsung</a></div><div class="d"><span class="state tody">今日 10:25</span></div></div>
            </div>
          </li>
        </ul></div></div>
        """

        with patch.object(self.module, "BeautifulSoup", None):
            items = self.module.extract_today_articles(
                html,
                "https://mobile.ithome.com/",
                source="mobile_phone",
                today=self.today,
            )

        self.assertEqual([item["title"] for item in items], ["First phone", "Second phone"])

    def test_extract_today_articles_prefers_title_anchor_when_image_anchor_comes_first(self) -> None:
        html = """
        <li>
          <a class="img" href="https://www.ithome.com/0/972/005.htm"></a>
          <div class="c" data-ot="2026-07-02T09:39:00+08:00"></div>
          <h2>
            <a class="title" title="\u4e09\u661f\u6298\u53e0\u624b\u673a\u65b0\u95fb" href="https://www.ithome.com/0/972/005.htm">
              \u4e09\u661f\u6298\u53e0\u624b\u673a\u65b0\u95fb
            </a>
          </h2>
          <span class="state">\u4eca\u65e5 9:39</span>
        </li>
        """

        items = self.module.extract_today_articles(
            html,
            "https://mobile.ithome.com/",
            source="mobile_phone",
            today=self.today,
        )

        self.assertEqual(
            items,
            [
                {
                    "date": "2026-07-02",
                    "published_at": "2026-07-02T09:39:00+08:00",
                    "title": "\u4e09\u661f\u6298\u53e0\u624b\u673a\u65b0\u95fb",
                    "url": "https://www.ithome.com/0/972/005.htm",
                    "source": "mobile_phone",
                }
            ],
        )

    def test_extract_today_articles_uses_time_tag_today_not_title_text(self) -> None:
        html = """
        <div id="list"><div class="fl"><ul class="bl">
          <li>
            <div class="c" data-ot="2026-07-02T09:55:00+08:00"></div>
            <h2>
              <a class="title" title="\u65b0\u673a\u4eca\u65e5\u5f00\u552e" href="/0/999/111.htm">
                \u65b0\u673a\u4eca\u65e5\u5f00\u552e
              </a>
            </h2>
            <div class="d"><span class="state tody">\u4eca\u65e5 9:55</span></div>
          </li>
        </ul></div></div>
        """

        items = self.module.extract_today_articles(
            html,
            "https://mobile.ithome.com/",
            source="mobile_phone",
            today=self.today,
        )

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["date"], "2026-07-02")
        self.assertEqual(items[0]["title"], "\u65b0\u673a\u4eca\u65e5\u5f00\u552e")

    def test_extract_today_articles_uses_state_today_label_and_data_ot(self) -> None:
        html = """
        <div id="list"><div class="fl"><ul class="bl">
          <li>
            <div class="c" data-ot="2026-07-02T08:16:16.7570000+08:00">
              <h2><a class="title" title="Today phone news" href="https://www.ithome.com/0/973/331.htm">Today phone news</a></h2>
              <div class="m">Summary mentions July 4, but that is not publish time.</div>
              <div class="d"><span class="state tody">\u4eca\u65e5 8:16</span></div>
            </div>
          </li>
        </ul></div></div>
        """

        items = self.module.extract_today_articles(
            html,
            "https://mobile.ithome.com/",
            source="mobile_phone",
            today=self.today,
        )

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["date"], self.today.isoformat())
        self.assertEqual(items[0]["published_at"], "2026-07-02T08:16:16.7570000+08:00")
        self.assertEqual(items[0]["url"], "https://www.ithome.com/0/973/331.htm")

    def test_extract_today_articles_rejects_today_state_when_data_ot_is_other_date(self) -> None:
        html = """
        <div id="list"><div class="fl"><ul class="bl">
          <li>
            <div class="c" data-ot="2026-07-01T23:59:00+08:00">
              <h2><a class="title" title="Old article with today label" href="/0/973/333.htm">Old article with today label</a></h2>
              <div class="d"><span class="state tody">\u4eca\u65e5 9:26</span></div>
            </div>
          </li>
        </ul></div></div>
        """

        items = self.module.extract_today_articles(
            html,
            "https://mobile.ithome.com/",
            source="mobile_phone",
            today=self.today,
        )

        self.assertEqual(items, [])

    def test_extract_today_articles_uses_data_ot_not_summary_date(self) -> None:
        html = """
        <div id="list"><div class="fl"><ul class="bl">
          <li>
            <div class="c" data-ot="2026-07-02T08:16:16.7570000+08:00">
              <h2><a class="title" title="Wired iPhone child mode" href="https://www.ithome.com/0/973/331.htm">Wired iPhone child mode</a></h2>
              <div class="m">Wired posted this story on July 4, but that text is article body context.</div>
              <div class="d"><span class="state tody">\u4eca\u65e5 8:16</span></div>
            </div>
          </li>
        </ul></div></div>
        """

        items = self.module.extract_today_articles(
            html,
            "https://mobile.ithome.com/",
            source="mobile_phone",
            today=self.today,
        )

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["date"], "2026-07-02")
        self.assertEqual(items[0]["published_at"], "2026-07-02T08:16:16.7570000+08:00")

    def test_extract_today_articles_applies_incremental_window(self) -> None:
        html = """
        <div id="list"><div class="fl"><ul class="bl">
          <li>
            <div class="c" data-ot="2026-07-02T08:00:00+08:00">
              <h2><a class="title" title="Already collected" href="/0/973/340.htm">Already collected</a></h2>
              <div class="d"><span class="state tody">\u4eca\u65e5 8:00</span></div>
            </div>
          </li>
          <li>
            <div class="c" data-ot="2026-07-02T08:30:00+08:00">
              <h2><a class="title" title="New in window" href="/0/973/341.htm">New in window</a></h2>
              <div class="d"><span class="state tody">\u4eca\u65e5 8:30</span></div>
            </div>
          </li>
          <li>
            <div class="c" data-ot="2026-07-02T09:30:00+08:00">
              <h2><a class="title" title="Future for this run" href="/0/973/342.htm">Future for this run</a></h2>
              <div class="d"><span class="state tody">\u4eca\u65e5 9:30</span></div>
            </div>
          </li>
        </ul></div></div>
        """

        items = self.module.extract_today_articles(
            html,
            "https://mobile.ithome.com/",
            source="mobile_phone",
            today=self.today,
            window_start="2026-07-02T08:00:00+08:00",
            window_end="2026-07-02T09:00:00+08:00",
        )

        self.assertEqual([item["title"] for item in items], ["New in window"])
        self.assertEqual(items[0]["published_at"], "2026-07-02T08:30:00+08:00")

    def test_extract_today_articles_ignores_data_ot_without_state_today_label(self) -> None:
        html = """
        <div id="list"><div class="fl"><ul class="bl">
          <li data-ot="2026-07-02T08:16:16+08:00">
            <h2><a class="title" title="data ot today" href="/0/973/332.htm">data ot today</a></h2>
            <div class="m">No blue today state label here.</div>
          </li>
        </ul></div></div>
        """

        items = self.module.extract_today_articles(
            html,
            "https://mobile.ithome.com/",
            source="mobile_phone",
            today=self.today,
        )

        self.assertEqual(items, [])

    def test_extract_today_articles_ignores_title_today_when_time_tag_is_not_today(self) -> None:
        html = """
        <div id="list"><div class="fl"><ul class="bl">
          <li>
            <h2>
              <a class="title" title="OPPO \u4eca\u65e5\u5f00\u552e" href="/0/999/112.htm">
                OPPO \u4eca\u65e5\u5f00\u552e
              </a>
            </h2>
            <div class="m">\u6807\u9898\u548c\u6458\u8981\u90fd\u53ef\u80fd\u6709\u4eca\u65e5\u7b49\u4e1a\u52a1\u8bcd</div>
            <div class="d"><span class="state">7\u67081\u65e5 18:20</span></div>
          </li>
        </ul></div></div>
        """

        items = self.module.extract_today_articles(
            html,
            "https://www.ithome.com/tags/OPPO/",
            source="brand_tag",
            today=self.today,
            keyword="OPPO",
        )

        self.assertEqual(items, [])

    def test_extract_latest_articles_returns_three_fallback_rows_when_dates_are_not_today(self) -> None:
        html = """
        <div id="list"><div class="fl"><ul class="bl">
          <li><h2><a class="title" title="Old vivo 1" href="/0/999/701.htm">Old vivo 1</a></h2><span>2026-07-01</span></li>
          <li><h2><a class="title" title="Old vivo 2" href="/0/999/702.htm">Old vivo 2</a></h2><span>2026-06-30</span></li>
          <li><h2><a class="title" title="Old vivo 3" href="/0/999/703.htm">Old vivo 3</a></h2><span>06月29日</span></li>
          <li><h2><a class="title" title="Old vivo 4" href="/0/999/704.htm">Old vivo 4</a></h2><span>06月28日</span></li>
        </ul></div></div>
        """

        items = self.module.extract_latest_articles(
            html,
            "https://www.ithome.com/tags/vivo/",
            source="brand_tag",
            requested_date=self.today,
            keyword="vivo",
            limit=3,
        )

        self.assertEqual([item["title"] for item in items], ["Old vivo 1", "Old vivo 2", "Old vivo 3"])
        self.assertEqual(items[0]["date"], "2026-07-01")
        self.assertEqual(items[2]["date"], "2026-06-29")
        self.assertTrue(all(item["fallback"] == "latest_when_no_today" for item in items))
        self.assertTrue(all(item["requested_date"] == "2026-07-02" for item in items))
        self.assertTrue(all(item["keyword"] == "vivo" for item in items))

    def test_fetch_page_html_uses_playwright_page_content_only(self) -> None:
        class FakeMouse:
            def __init__(self) -> None:
                self.wheels: list[tuple[int, int]] = []

            def wheel(self, x: int, y: int) -> None:
                self.wheels.append((x, y))

        class FakeLocator:
            def inner_text(self, *, timeout: int) -> str:
                self.timeout = timeout
                return "loaded body text"

        class FakePage:
            def __init__(self) -> None:
                self.goto_calls: list[dict[str, object]] = []
                self.load_states: list[dict[str, object]] = []
                self.timeouts: list[int] = []
                self.mouse = FakeMouse()
                self.locator_obj = FakeLocator()

            def goto(self, url: str, *, wait_until: str, timeout: int) -> None:
                self.goto_calls.append({"url": url, "wait_until": wait_until, "timeout": timeout})

            def wait_for_load_state(self, state: str, *, timeout: int) -> None:
                self.load_states.append({"state": state, "timeout": timeout})

            def wait_for_timeout(self, timeout: int) -> None:
                self.timeouts.append(timeout)

            def content(self) -> str:
                return "<html><body>loaded</body></html>"

            def locator(self, selector: str) -> FakeLocator:
                self.selector = selector
                return self.locator_obj

        source = self.module.FetchSource(source="brand_keyword", url="https://www.ithome.com/search/vivo.html")
        page = FakePage()

        html, text_len = self.module.fetch_page_html(page, source, timeout=20)

        self.assertEqual(html, "<html><body>loaded</body></html>")
        self.assertEqual(text_len, len("loaded body text"))
        self.assertEqual(
            page.goto_calls,
            [{"url": source.url, "wait_until": "domcontentloaded", "timeout": 20000}],
        )
        self.assertEqual(page.load_states, [{"state": "networkidle", "timeout": 12000}])
        self.assertEqual(page.mouse.wheels, [(0, 1000), (0, 1000)])
        self.assertEqual(page.timeouts, [700, 700])
        self.assertEqual(page.selector, "body")

    def test_is_ithome_404_redirect_page_detects_redirect_prompt(self) -> None:
        html = """
        <html><body>
          <h1>404错误，没有找到页面, IT之家</h1>
          <p>不要慌！ 3 秒后将自动返回IT之家首页，请稍候...</p>
          <script>function jump() { window.location = "/" }</script>
        </body></html>
        """

        self.assertTrue(self.module.is_ithome_404_redirect_page(html))
        self.assertFalse(self.module.is_ithome_404_redirect_page("<html><body>普通空页面</body></html>"))

    def test_run_playwright_collect_reports_missing_playwright_as_error(self) -> None:
        real_import = __import__

        def fake_import(name: str, *args: object, **kwargs: object) -> ModuleType:
            if name == "playwright.sync_api":
                raise ImportError("missing playwright")
            return real_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=fake_import):
            result = self.module.run_playwright_collect(
                sources=[self.module.FetchSource(source="mobile_phone", url="https://mobile.ithome.com/")],
                today=self.today,
                timeout=20,
                headed=False,
            )

        self.assertEqual(result["status"], "error")
        self.assertEqual(result["items"], [])
        self.assertEqual(result["counts"], {"sources": 1, "fetched": 0, "items": 0, "errors": 1})
        self.assertEqual(result["errors"][0]["source"], "playwright")
        self.assertIn("playwright not installed", result["errors"][0]["error"])

    def test_run_playwright_collect_can_use_injected_playwright_factory(self) -> None:
        html = """
        <div id="list"><div class="fl"><ul class="bl">
          <li>
            <div class="c" data-ot="2026-07-02T10:30:00+08:00"></div>
            <h2><a class="title" title="Injected Playwright phone" href="/0/999/301.htm">Injected Playwright phone</a></h2>
            <span class="state">\u4eca\u65e5 10:30</span>
          </li>
        </ul></div></div>
        """

        class FakePage:
            def __init__(self) -> None:
                self.mouse = self

            def goto(self, url: str, *, wait_until: str, timeout: int) -> None:
                self.url = url
                self.wait_until = wait_until
                self.timeout = timeout

            def wait_for_load_state(self, state: str, *, timeout: int) -> None:
                self.state = state
                self.state_timeout = timeout

            def wheel(self, x: int, y: int) -> None:
                pass

            def wait_for_timeout(self, timeout: int) -> None:
                pass

            def content(self) -> str:
                return html

            def locator(self, selector: str) -> object:
                class Body:
                    def inner_text(self, *, timeout: int) -> str:
                        return "body text"

                return Body()

        class FakeBrowser:
            def __init__(self) -> None:
                self.closed = False
                self.page = FakePage()

            def new_page(self, **kwargs: object) -> FakePage:
                self.new_page_kwargs = kwargs
                return self.page

            def close(self) -> None:
                self.closed = True

        class FakeChromium:
            def __init__(self) -> None:
                self.browser = FakeBrowser()

            def launch(self, *, headless: bool) -> FakeBrowser:
                self.headless = headless
                return self.browser

        class FakePlaywright:
            def __init__(self) -> None:
                self.chromium = FakeChromium()

        class FakePlaywrightContext:
            def __init__(self) -> None:
                self.playwright = FakePlaywright()

            def __enter__(self) -> FakePlaywright:
                return self.playwright

            def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
                self.exited = True

        context = FakePlaywrightContext()
        logs: list[str] = []

        result = self.module.run_playwright_collect(
            sources=[self.module.FetchSource(source="brand_keyword", url="https://www.ithome.com/search/vivo.html", keyword="vivo", brand="VIVO")],
            today=self.today,
            timeout=20,
            headed=False,
            playwright_factory=lambda: context,
            logger=logs.append,
        )

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["counts"], {"sources": 1, "fetched": 1, "items": 1, "errors": 0})
        self.assertEqual(
            result["items"],
            [
                {
                    "date": "2026-07-02",
                    "published_at": "2026-07-02T10:30:00+08:00",
                    "title": "Injected Playwright phone",
                    "url": "https://www.ithome.com/0/999/301.htm",
                    "source": "brand_keyword",
                    "keyword": "vivo",
                    "brand": "VIVO",
                    "page_url": "https://www.ithome.com/search/vivo.html",
                    "collect_window_start": None,
                    "collect_window_end": result["window_end"],
                }
            ],
        )
        self.assertTrue(context.playwright.chromium.browser.closed)
        self.assertTrue(any("start date=2026-07-02 sources=1 headed=False" in line for line in logs))
        self.assertTrue(any("fetch source=brand_keyword keyword=vivo" in line for line in logs))
        self.assertTrue(any("fetched source=brand_keyword html_len=" in line and "items=1" in line for line in logs))
        self.assertTrue(any("done status=ok sources=1 fetched=1 items=1 errors=0" in line for line in logs))

    def test_run_playwright_collect_uses_persistent_context_when_user_data_dir_is_set(self) -> None:
        html = """
        <div id="list"><div class="fl"><ul class="bl">
          <li>
            <div class="c" data-ot="2026-07-02T10:40:00+08:00"></div>
            <h2><a class="title" title="Persistent profile phone" href="/0/999/401.htm">Persistent profile phone</a></h2>
            <span class="state">\u4eca\u65e5 10:40</span>
          </li>
        </ul></div></div>
        """

        class FakePage:
            def __init__(self) -> None:
                self.mouse = self

            def goto(self, url: str, *, wait_until: str, timeout: int) -> None:
                pass

            def wait_for_load_state(self, state: str, *, timeout: int) -> None:
                pass

            def wheel(self, x: int, y: int) -> None:
                pass

            def wait_for_timeout(self, timeout: int) -> None:
                pass

            def content(self) -> str:
                return html

            def locator(self, selector: str) -> object:
                class Body:
                    def inner_text(self, *, timeout: int) -> str:
                        return "body text"

                return Body()

        class FakePersistentContext:
            def __init__(self) -> None:
                self.closed = False
                self.page = FakePage()

            def new_page(self) -> FakePage:
                return self.page

            def close(self) -> None:
                self.closed = True

        class FakeChromium:
            def __init__(self) -> None:
                self.context = FakePersistentContext()
                self.launch_calls = 0
                self.persistent_kwargs: dict[str, object] | None = None

            def launch(self, *, headless: bool) -> object:
                self.launch_calls += 1
                raise AssertionError("ephemeral launch should not be used with user_data_dir")

            def launch_persistent_context(self, user_data_dir: str, **kwargs: object) -> FakePersistentContext:
                self.persistent_user_data_dir = user_data_dir
                self.persistent_kwargs = kwargs
                return self.context

        class FakePlaywright:
            def __init__(self) -> None:
                self.chromium = FakeChromium()

        class FakePlaywrightContext:
            def __init__(self) -> None:
                self.playwright = FakePlaywright()

            def __enter__(self) -> FakePlaywright:
                return self.playwright

            def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
                pass

        context = FakePlaywrightContext()

        result = self.module.run_playwright_collect(
            sources=[self.module.FetchSource(source="brand_keyword", url="https://www.ithome.com/search/oppo.html", keyword="oppo", brand="OPPO")],
            today=self.today,
            timeout=20,
            headed=True,
            user_data_dir=".codex_tmp/ithome-profile",
            playwright_factory=lambda: context,
        )

        chromium = context.playwright.chromium
        self.assertEqual(chromium.launch_calls, 0)
        self.assertEqual(chromium.persistent_user_data_dir, ".codex_tmp/ithome-profile")
        self.assertEqual(chromium.persistent_kwargs["headless"], False)
        self.assertEqual(chromium.persistent_kwargs["user_agent"], self.module.USER_AGENT)
        self.assertEqual(chromium.persistent_kwargs["viewport"], {"width": 1440, "height": 1200})
        self.assertEqual(chromium.persistent_kwargs["locale"], "zh-CN")
        self.assertTrue(chromium.context.closed)
        self.assertEqual(result["status"], "ok")

    def test_run_login_session_opens_homepage_with_persistent_context(self) -> None:
        class FakePage:
            def goto(self, url: str, *, wait_until: str, timeout: int) -> None:
                self.goto_call = {"url": url, "wait_until": wait_until, "timeout": timeout}

            def wait_for_timeout(self, timeout: int) -> None:
                self.wait_timeout = timeout

        class FakePersistentContext:
            def __init__(self) -> None:
                self.closed = False
                self.page = FakePage()

            def new_page(self) -> FakePage:
                return self.page

            def close(self) -> None:
                self.closed = True

        class FakeChromium:
            def __init__(self) -> None:
                self.context = FakePersistentContext()

            def launch_persistent_context(self, user_data_dir: str, **kwargs: object) -> FakePersistentContext:
                self.user_data_dir = user_data_dir
                self.kwargs = kwargs
                return self.context

        class FakePlaywright:
            def __init__(self) -> None:
                self.chromium = FakeChromium()

        class FakePlaywrightContext:
            def __init__(self) -> None:
                self.playwright = FakePlaywright()

            def __enter__(self) -> FakePlaywright:
                return self.playwright

            def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
                pass

        context = FakePlaywrightContext()

        self.module.run_login_session(
            user_data_dir=".codex_tmp/ithome-profile",
            wait_seconds=60,
            playwright_factory=lambda: context,
        )

        chromium = context.playwright.chromium
        self.assertEqual(chromium.user_data_dir, ".codex_tmp/ithome-profile")
        self.assertEqual(chromium.kwargs["headless"], False)
        self.assertEqual(chromium.kwargs["locale"], "zh-CN")
        self.assertEqual(chromium.context.page.goto_call, {"url": "https://www.ithome.com/", "wait_until": "domcontentloaded", "timeout": 20000})
        self.assertEqual(chromium.context.page.wait_timeout, 60000)
        self.assertTrue(chromium.context.closed)

    def test_run_playwright_collect_retries_short_brand_search_page(self) -> None:
        short_html = "<html><body>请稍候</body></html>"
        article_html = """
        <div id="list"><div class="fl"><ul class="bl">
          <li>
            <div class="c" data-ot="2026-07-02T11:30:00+08:00"></div>
            <h2><a class="title" title="Retried phone" href="/0/999/901.htm">Retried phone</a></h2>
            <span class="state">\u4eca\u65e5 11:30</span>
          </li>
        </ul></div></div>
        """

        class FakePage:
            def __init__(self) -> None:
                self.mouse = self
                self.goto_calls: list[str] = []
                self.html_responses = [short_html, article_html]
                self.text_responses = ["请稍候", "Retried phone 今日 11:30"]

            def goto(self, url: str, *, wait_until: str, timeout: int) -> None:
                self.goto_calls.append(url)

            def wait_for_load_state(self, state: str, *, timeout: int) -> None:
                pass

            def wheel(self, x: int, y: int) -> None:
                pass

            def wait_for_timeout(self, timeout: int) -> None:
                pass

            def content(self) -> str:
                return self.html_responses.pop(0)

            def locator(self, selector: str) -> object:
                page = self

                class Body:
                    def inner_text(self, *, timeout: int) -> str:
                        return page.text_responses.pop(0)

                return Body()

        class FakeBrowser:
            def __init__(self) -> None:
                self.page = FakePage()

            def new_page(self, **kwargs: object) -> FakePage:
                return self.page

            def close(self) -> None:
                pass

        class FakeChromium:
            def __init__(self) -> None:
                self.browser = FakeBrowser()

            def launch(self, *, headless: bool) -> FakeBrowser:
                return self.browser

        class FakePlaywright:
            def __init__(self) -> None:
                self.chromium = FakeChromium()

        class FakePlaywrightContext:
            def __init__(self) -> None:
                self.playwright = FakePlaywright()

            def __enter__(self) -> FakePlaywright:
                return self.playwright

            def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
                pass

        context = FakePlaywrightContext()
        logs: list[str] = []

        result = self.module.run_playwright_collect(
            sources=[self.module.FetchSource(source="brand_keyword", url="https://www.ithome.com/search/vivo.html", keyword="vivo", brand="VIVO")],
            today=self.today,
            timeout=20,
            headed=False,
            playwright_factory=lambda: context,
            logger=logs.append,
        )

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["counts"], {"sources": 1, "fetched": 2, "items": 1, "errors": 0})
        self.assertEqual(result["items"][0]["title"], "Retried phone")
        self.assertEqual(len(context.playwright.chromium.browser.page.goto_calls), 2)
        self.assertTrue(any("retry source=brand_keyword" in line and "body_preview=请稍候" in line for line in logs))

    def test_run_playwright_collect_reports_body_preview_after_short_page_retries(self) -> None:
        short_html = "<html><body>请稍候</body></html>"

        class FakePage:
            def __init__(self) -> None:
                self.mouse = self

            def goto(self, url: str, *, wait_until: str, timeout: int) -> None:
                pass

            def wait_for_load_state(self, state: str, *, timeout: int) -> None:
                pass

            def wheel(self, x: int, y: int) -> None:
                pass

            def wait_for_timeout(self, timeout: int) -> None:
                pass

            def content(self) -> str:
                return short_html

            def locator(self, selector: str) -> object:
                class Body:
                    def inner_text(self, *, timeout: int) -> str:
                        return "请稍候"

                return Body()

        class FakeBrowser:
            def new_page(self, **kwargs: object) -> FakePage:
                return FakePage()

            def close(self) -> None:
                pass

        class FakeChromium:
            def launch(self, *, headless: bool) -> FakeBrowser:
                return FakeBrowser()

        class FakePlaywright:
            def __init__(self) -> None:
                self.chromium = FakeChromium()

        class FakePlaywrightContext:
            def __enter__(self) -> FakePlaywright:
                return FakePlaywright()

            def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
                pass

        logs: list[str] = []

        result = self.module.run_playwright_collect(
            sources=[self.module.FetchSource(source="brand_keyword", url="https://www.ithome.com/search/vivo.html", keyword="vivo", brand="VIVO")],
            today=self.today,
            timeout=20,
            headed=False,
            playwright_factory=lambda: FakePlaywrightContext(),
            logger=logs.append,
        )

        self.assertEqual(result["status"], "error")
        self.assertEqual(result["counts"], {"sources": 1, "fetched": 3, "items": 0, "errors": 1})
        self.assertEqual(result["errors"][0]["body_preview"], "请稍候")
        self.assertTrue(any("empty source=brand_keyword" in line and "body_preview=请稍候" in line for line in logs))

    def test_run_playwright_collect_waits_8_seconds_and_retries_ithome_404_redirect_page(self) -> None:
        redirect_html = """
        <html><body>
          404错误，没有找到页面, IT之家 不要慌！ 3 秒后将自动返回IT之家首页，请稍候...
          <script>function jump() { window.location = "/" }</script>
        </body></html>
        """
        article_html = """
        <div id="list"><div class="fl"><ul class="bl">
          <li>
            <div class="c" data-ot="2026-07-02T12:05:00+08:00"></div>
            <h2><a class="title" title="Retried red magic phone" href="/0/999/905.htm">Retried red magic phone</a></h2>
            <span class="state">今日 12:05</span>
          </li>
        </ul></div></div>
        """

        class FakePage:
            def __init__(self) -> None:
                self.timeouts: list[int] = []

            def wait_for_timeout(self, timeout: int) -> None:
                self.timeouts.append(timeout)

        class FakeBrowser:
            def __init__(self) -> None:
                self.page = FakePage()

            def new_page(self, **kwargs: object) -> FakePage:
                return self.page

            def close(self) -> None:
                pass

        class FakeChromium:
            def __init__(self) -> None:
                self.browser = FakeBrowser()

            def launch(self, *, headless: bool) -> FakeBrowser:
                return self.browser

        class FakePlaywright:
            def __init__(self) -> None:
                self.chromium = FakeChromium()

        class FakePlaywrightContext:
            def __init__(self) -> None:
                self.playwright = FakePlaywright()

            def __enter__(self) -> FakePlaywright:
                return self.playwright

            def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
                pass

        context = FakePlaywrightContext()
        responses = [(redirect_html, 26), (article_html, len("Retried red magic phone 今日 12:05"))]

        def fake_fetch_page_html(page: object, source: object, *, timeout: int) -> tuple[str, int]:
            return responses.pop(0)

        logs: list[str] = []

        with patch.object(self.module, "fetch_page_html", side_effect=fake_fetch_page_html):
            result = self.module.run_playwright_collect(
                sources=[
                    self.module.FetchSource(
                        source="brand_tag",
                        url="https://www.ithome.com/tags/%E7%BA%A2%E9%AD%94/",
                        keyword="红魔",
                        brand="ZTE",
                    )
                ],
                today=self.today,
                timeout=20,
                headed=False,
                playwright_factory=lambda: context,
                logger=logs.append,
            )

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["counts"], {"sources": 1, "fetched": 2, "items": 1, "errors": 0})
        self.assertEqual(result["items"][0]["title"], "Retried red magic phone")
        self.assertEqual(context.playwright.chromium.browser.page.timeouts, [8000])
        self.assertTrue(any("retry_404_redirect source=brand_tag keyword=红魔 wait=8000ms" in line for line in logs))

    def test_run_playwright_collect_switches_from_tag_to_search_after_404_redirect(self) -> None:
        redirect_html = """
        <html><body>
          404错误，没有找到页面, IT之家 不要慌！ 3 秒后将自动返回IT之家首页，请稍候...
        </body></html>
        """
        search_html = """
        <div id="list"><div class="fl"><ul class="bl">
          <li>
            <div class="c" data-ot="2026-07-02T12:20:00+08:00"></div>
            <h2><a class="title" title="Search red magic phone" href="/0/999/906.htm">Search red magic phone</a></h2>
            <span class="state">今日 12:20</span>
          </li>
        </ul></div></div>
        """

        class FakePage:
            def __init__(self) -> None:
                self.timeouts: list[int] = []

            def wait_for_timeout(self, timeout: int) -> None:
                self.timeouts.append(timeout)

        class FakeBrowser:
            def __init__(self) -> None:
                self.page = FakePage()

            def new_page(self, **kwargs: object) -> FakePage:
                return self.page

            def close(self) -> None:
                pass

        class FakeChromium:
            def __init__(self) -> None:
                self.browser = FakeBrowser()

            def launch(self, *, headless: bool) -> FakeBrowser:
                return self.browser

        class FakePlaywright:
            def __init__(self) -> None:
                self.chromium = FakeChromium()

        class FakePlaywrightContext:
            def __init__(self) -> None:
                self.playwright = FakePlaywright()

            def __enter__(self) -> FakePlaywright:
                return self.playwright

            def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
                pass

        context = FakePlaywrightContext()
        fetched_urls: list[str] = []
        responses = [(redirect_html, 26), (search_html, len("Search red magic phone 今日 12:20"))]

        def fake_fetch_page_html(page: object, source: object, *, timeout: int) -> tuple[str, int]:
            fetched_urls.append(source.url)
            return responses.pop(0)

        logs: list[str] = []

        with patch.object(self.module, "fetch_page_html", side_effect=fake_fetch_page_html):
            result = self.module.run_playwright_collect(
                sources=[
                    self.module.FetchSource(
                        source="brand_tag",
                        url="https://www.ithome.com/tags/%E7%BA%A2%E9%AD%94/",
                        keyword="红魔",
                        brand="ZTE",
                        fallback_url="https://www.ithome.com/search/%E7%BA%A2%E9%AD%94.html",
                        fallback_source="brand_search",
                    )
                ],
                today=self.today,
                timeout=20,
                headed=False,
                playwright_factory=lambda: context,
                logger=logs.append,
            )

        self.assertEqual(
            fetched_urls,
            [
                "https://www.ithome.com/tags/%E7%BA%A2%E9%AD%94/",
                "https://www.ithome.com/search/%E7%BA%A2%E9%AD%94.html",
            ],
        )
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["counts"], {"sources": 1, "fetched": 2, "items": 1, "errors": 0})
        self.assertEqual(result["items"][0]["source"], "brand_search")
        self.assertEqual(result["items"][0]["page_url"], "https://www.ithome.com/search/%E7%BA%A2%E9%AD%94.html")
        self.assertTrue(any("retry_404_redirect source=brand_tag keyword=红魔 wait=8000ms next=brand_search" in line for line in logs))

    def test_load_sources_uses_search_pages_for_brand_keywords(self) -> None:
        config = {
            "sources": [
                {
                    "brand": "OPPO",
                    "source_type": "ithome_brand_search",
                    "search_keywords": ["OPPO"],
                },
                {
                    "brand": "ZTE",
                    "source_type": "ithome_brand_search",
                    "search_keywords": ["中兴手机"],
                },
            ]
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "news_sources.json"
            config_path.write_text(__import__("json").dumps(config, ensure_ascii=False), encoding="utf-8")

            sources = self.module.load_sources(config_path)

        self.assertEqual(sources[0].source, "mobile_phone")
        self.assertEqual(sources[1].source, "brand_search")
        self.assertEqual(sources[1].url, "https://www.ithome.com/search/OPPO.html")
        self.assertEqual(sources[1].keyword, "OPPO")
        self.assertEqual(sources[2].source, "brand_search")
        self.assertEqual(sources[2].url, "https://www.ithome.com/search/%E4%B8%AD%E5%85%B4%E6%89%8B%E6%9C%BA.html")

    def test_load_sources_adds_tag_fallback_for_brand_search(self) -> None:
        config = {
            "sources": [
                {
                    "brand": "ZTE",
                    "source_type": "ithome_brand_search",
                    "search_keywords": ["红魔"],
                }
            ]
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "news_sources.json"
            config_path.write_text(__import__("json").dumps(config, ensure_ascii=False), encoding="utf-8")

            sources = self.module.load_sources(config_path)

        self.assertEqual(sources[1].source, "brand_search")
        self.assertEqual(sources[1].url, "https://www.ithome.com/search/%E7%BA%A2%E9%AD%94.html")
        self.assertEqual(sources[1].fallback_source, "brand_tag")
        self.assertEqual(sources[1].fallback_url, "https://www.ithome.com/tags/%E7%BA%A2%E9%AD%94/")

    def test_run_playwright_collect_falls_back_to_mobile_items_when_brand_tag_is_empty(self) -> None:
        mobile_html = """
        <article>
          <span class="state">\u4eca\u65e5 09:30</span>
          <div class="c" data-ot="2026-07-02T09:30:00+08:00"></div>
          <a href="https://mobile.ithome.com/0/999/501.htm">OPPO Find X 今日发布</a>
        </article>
        <article>
          <span class="state">\u4eca\u65e5 09:20</span>
          <div class="c" data-ot="2026-07-02T09:20:00+08:00"></div>
          <a href="https://mobile.ithome.com/0/999/502.htm">三星折叠屏消息</a>
        </article>
        """
        passport_html = "<html><body>登录软媒通行证</body></html>"

        class FakeBrowser:
            def new_page(self, **kwargs: object) -> object:
                return object()

            def close(self) -> None:
                pass

        class FakeChromium:
            def launch(self, *, headless: bool) -> FakeBrowser:
                return FakeBrowser()

        class FakePlaywright:
            def __init__(self) -> None:
                self.chromium = FakeChromium()

        class FakePlaywrightContext:
            def __enter__(self) -> FakePlaywright:
                return FakePlaywright()

            def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
                pass

        def fake_fetch_page_html(page: object, source: object, *, timeout: int) -> tuple[str, int]:
            if source.source == "mobile_phone":
                return mobile_html, len("OPPO Find X 今日发布 三星折叠屏消息")
            return passport_html, len("登录软媒通行证")

        logs: list[str] = []

        with patch.object(self.module, "fetch_page_html", side_effect=fake_fetch_page_html):
            result = self.module.run_playwright_collect(
                sources=[
                    self.module.FetchSource(source="mobile_phone", url="https://mobile.ithome.com/"),
                    self.module.FetchSource(
                        source="brand_tag",
                        url="https://www.ithome.com/tags/OPPO/",
                        keyword="OPPO",
                        brand="OPPO",
                    ),
                ],
                today=self.today,
                timeout=20,
                headed=False,
                playwright_factory=lambda: FakePlaywrightContext(),
                logger=logs.append,
            )

        self.assertEqual(result["status"], "partial_error")
        self.assertEqual(result["counts"], {"sources": 2, "fetched": 2, "items": 2, "errors": 1})
        self.assertEqual(result["items"][0]["title"], "OPPO Find X 今日发布")
        self.assertEqual(result["items"][0]["source"], "brand_tag")
        self.assertEqual(result["items"][0]["fallback"], "mobile_phone_keyword_filter")
        self.assertEqual(result["items"][0]["page_url"], "https://mobile.ithome.com/")
        self.assertEqual(result["items"][1]["title"], "三星折叠屏消息")
        self.assertEqual(result["items"][1]["source"], "mobile_phone")
        self.assertEqual(result["errors"][0]["fallback"], "mobile_phone_keyword_filter")
        self.assertTrue(any("fallback source=brand_tag keyword=OPPO items=1" in line for line in logs))

    def test_run_playwright_collect_prefers_mobile_today_items_before_latest_three_fallback(self) -> None:
        mobile_html = """
        <article>
          <span class="state">\u4eca\u65e5 09:30</span>
          <div class="c" data-ot="2026-07-02T09:30:00+08:00"></div>
          <a href="https://mobile.ithome.com/0/999/601.htm">vivo \u4eca\u65e5\u65b0\u95fb</a>
        </article>
        """
        brand_old_html = """
        <div id="list"><div class="fl"><ul class="bl">
          <li><h2><a class="title" title="Old vivo 1" href="/0/999/701.htm">Old vivo 1</a></h2><span>2026-07-01</span></li>
          <li><h2><a class="title" title="Old vivo 2" href="/0/999/702.htm">Old vivo 2</a></h2><span>2026-06-30</span></li>
          <li><h2><a class="title" title="Old vivo 3" href="/0/999/703.htm">Old vivo 3</a></h2><span>2026-06-29</span></li>
        </ul></div></div>
        """

        class FakeBrowser:
            def new_page(self, **kwargs: object) -> object:
                return object()

            def close(self) -> None:
                pass

        class FakeChromium:
            def launch(self, *, headless: bool) -> FakeBrowser:
                return FakeBrowser()

        class FakePlaywright:
            def __init__(self) -> None:
                self.chromium = FakeChromium()

        class FakePlaywrightContext:
            def __enter__(self) -> FakePlaywright:
                return FakePlaywright()

            def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
                pass

        def fake_fetch_page_html(page: object, source: object, *, timeout: int) -> tuple[str, int]:
            if source.source == "mobile_phone":
                return mobile_html, len("vivo 今日新闻")
            return brand_old_html, len("Old vivo")

        logs: list[str] = []

        with patch.object(self.module, "fetch_page_html", side_effect=fake_fetch_page_html):
            result = self.module.run_playwright_collect(
                sources=[
                    self.module.FetchSource(source="mobile_phone", url="https://mobile.ithome.com/"),
                    self.module.FetchSource(
                        source="brand_tag",
                        url="https://www.ithome.com/tags/vivo/",
                        keyword="vivo",
                        brand="VIVO",
                    ),
                ],
                today=self.today,
                timeout=20,
                headed=False,
                playwright_factory=lambda: FakePlaywrightContext(),
                logger=logs.append,
            )

        self.assertEqual(result["status"], "partial_error")
        self.assertEqual([item["title"] for item in result["items"]], ["vivo \u4eca\u65e5\u65b0\u95fb"])
        self.assertEqual(result["items"][0]["fallback"], "mobile_phone_keyword_filter")
        self.assertEqual(result["items"][0]["brand"], "VIVO")
        self.assertFalse(any(item.get("fallback") == "latest_when_no_today" for item in result["items"]))
        self.assertTrue(any("fallback source=brand_tag keyword=vivo items=1 fallback=mobile_phone_keyword_filter" in line for line in logs))

    def test_run_playwright_collect_reports_error_when_source_has_no_today_items(self) -> None:
        old_html = """
        <div id="list"><div class="fl"><ul class="bl">
          <li><h2><a class="title" title="Latest fallback 1" href="/0/999/801.htm">Latest fallback 1</a></h2><span>2026-07-01</span></li>
          <li><h2><a class="title" title="Latest fallback 2" href="/0/999/802.htm">Latest fallback 2</a></h2><span>2026-06-30</span></li>
          <li><h2><a class="title" title="Latest fallback 3" href="/0/999/803.htm">Latest fallback 3</a></h2><span>2026-06-29</span></li>
          <li><h2><a class="title" title="Latest fallback 4" href="/0/999/804.htm">Latest fallback 4</a></h2><span>2026-06-28</span></li>
        </ul></div></div>
        """

        class FakeBrowser:
            def new_page(self, **kwargs: object) -> object:
                return object()

            def close(self) -> None:
                pass

        class FakeChromium:
            def launch(self, *, headless: bool) -> FakeBrowser:
                return FakeBrowser()

        class FakePlaywright:
            def __init__(self) -> None:
                self.chromium = FakeChromium()

        class FakePlaywrightContext:
            def __enter__(self) -> FakePlaywright:
                return FakePlaywright()

            def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
                pass

        def fake_fetch_page_html(page: object, source: object, *, timeout: int) -> tuple[str, int]:
            return old_html, len("Latest fallback")

        logs: list[str] = []

        with patch.object(self.module, "fetch_page_html", side_effect=fake_fetch_page_html):
            result = self.module.run_playwright_collect(
                sources=[
                    self.module.FetchSource(
                        source="brand_tag",
                        url="https://www.ithome.com/tags/vivo/",
                        keyword="vivo",
                        brand="VIVO",
                    ),
                ],
                today=self.today,
                timeout=20,
                headed=False,
                playwright_factory=lambda: FakePlaywrightContext(),
                logger=logs.append,
            )

        self.assertEqual(result["status"], "error")
        self.assertEqual(result["counts"], {"sources": 1, "fetched": 1, "items": 0, "errors": 1})
        self.assertEqual(result["items"], [])
        self.assertEqual(result["errors"][0]["source"], "brand_tag")
        self.assertIn("no today articles parsed", result["errors"][0]["error"])
        self.assertTrue(any("empty source=brand_tag keyword=vivo error=no today articles parsed" in line for line in logs))
        self.assertFalse(any("fallback=latest_when_no_today" in line for line in logs))

    def test_import_result_to_db_upserts_playwright_items_as_news_rows(self) -> None:
        result = {
            "date": "2026-07-02",
            "items": [
                {
                    "date": "2026-07-01",
                    "requested_date": "2026-07-02",
                    "title": "Latest vivo fallback",
                    "url": "https://www.ithome.com/0/999/901.htm",
                    "source": "brand_tag",
                    "keyword": "vivo",
                    "brand": "VIVO",
                    "page_url": "https://www.ithome.com/tags/vivo/",
                    "fallback": "latest_when_no_today",
                },
                {
                    "date": "2026-07-02",
                    "title": "General phone news",
                    "url": "https://www.ithome.com/0/999/902.htm",
                    "source": "mobile_phone",
                    "page_url": "https://mobile.ithome.com/",
                },
            ],
        }
        upserted_rows: list[dict[str, object]] = []

        class FakeDb:
            DEFAULT_DB = self.module.Path("data/phones.sqlite")

            def init_db(self, db_path: object = DEFAULT_DB) -> None:
                self.db_path = db_path

            def connect(self, db_path: object = DEFAULT_DB) -> object:
                class Conn:
                    def __enter__(inner_self) -> object:
                        return inner_self

                    def __exit__(inner_self, exc_type: object, exc: object, tb: object) -> None:
                        pass

                return Conn()

            def upsert_news_item(self, conn: object, row: dict[str, object]) -> int:
                upserted_rows.append(row)
                return len(upserted_rows)

        counts = self.module.import_result_to_db(
            result,
            db_path="postgres",
            db_module=FakeDb(),
            imported_at="2026-07-02T10:00:00+00:00",
        )

        self.assertEqual(counts, {"items": 2, "upserted": 2, "skipped": 0, "cleanup_deleted": 0})
        self.assertEqual(upserted_rows[0]["brand"], "VIVO")
        self.assertEqual(upserted_rows[0]["source_type"], "ithome_brand_search")
        self.assertEqual(upserted_rows[0]["source_name"], "IT之家品牌关键词搜索")
        self.assertEqual(upserted_rows[0]["seen_date"], "2026-07-01")
        self.assertEqual(upserted_rows[0]["published_at"], "2026-07-01T00:00:00+00:00")
        self.assertEqual(upserted_rows[0]["last_error"], "latest_when_no_today; requested_date=2026-07-02")
        self.assertEqual(upserted_rows[1]["brand"], "ALL")
        self.assertEqual(upserted_rows[1]["source_type"], "ithome_phone_today")
        self.assertEqual(upserted_rows[1]["source_name"], "IT之家手机分区当日新闻")
        self.assertEqual(upserted_rows[1]["seen_date"], "2026-07-02")
        self.assertEqual(upserted_rows[1]["published_at"], "2026-07-02T00:00:00+00:00")

    def test_import_result_to_db_cleans_old_news_items_after_import(self) -> None:
        result = {
            "date": "2026-07-16",
            "items": [
                {
                    "date": "2026-07-16",
                    "title": "Today samsung",
                    "url": "https://www.ithome.com/0/999/950.htm",
                    "source": "brand_search",
                    "brand": "SAMSUNG",
                }
            ],
        }
        cleanup_calls: list[dict[str, object]] = []

        class FakeDb:
            DEFAULT_DB = self.module.Path("data/phones.sqlite")

            def init_db(self, db_path: object = DEFAULT_DB) -> None:
                pass

            def connect(self, db_path: object = DEFAULT_DB) -> object:
                class Conn:
                    def __enter__(inner_self) -> object:
                        return inner_self

                    def __exit__(inner_self, exc_type: object, exc: object, tb: object) -> None:
                        pass

                return Conn()

            def upsert_news_item(self, conn: object, row: dict[str, object]) -> int:
                return 1

            def cleanup_old_news_items(self, conn: object, *, retention_days: int, now: str | None = None) -> int:
                cleanup_calls.append({"retention_days": retention_days, "now": now})
                return 4

        counts = self.module.import_result_to_db(
            result,
            db_path="postgres",
            db_module=FakeDb(),
            imported_at="2026-07-16T10:00:00+00:00",
        )

        self.assertEqual(counts["cleanup_deleted"], 4)
        self.assertEqual(cleanup_calls, [{"retention_days": 7, "now": "2026-07-16T10:00:00+00:00"}])

    def test_item_to_news_row_uses_item_published_at_and_does_not_fake_fallback_date(self) -> None:
        row = self.module.item_to_news_row(
            {
                "title": "Fallback without real publish date",
                "url": "https://www.ithome.com/0/999/990.htm",
                "source": "brand_tag",
                "brand": "VIVO",
                "requested_date": "2026-07-02",
                "fallback": "latest_when_no_today",
            },
            imported_at="2026-07-02T10:00:00+00:00",
            result_date="2026-07-02",
        )

        self.assertIsNotNone(row)
        self.assertEqual(row["seen_date"], "2026-07-02")
        self.assertIsNone(row["published_at"])
        self.assertEqual(row["last_error"], "latest_when_no_today; requested_date=2026-07-02")

        row_with_published_at = self.module.item_to_news_row(
            {
                "date": "2026-07-01",
                "published_at": "2026-07-01T18:20:00+08:00",
                "title": "Fallback with real publish date",
                "url": "https://www.ithome.com/0/999/991.htm",
                "source": "brand_tag",
                "brand": "VIVO",
                "requested_date": "2026-07-02",
                "fallback": "latest_when_no_today",
            },
            imported_at="2026-07-02T10:00:00+00:00",
            result_date="2026-07-02",
        )

        self.assertEqual(row_with_published_at["published_at"], "2026-07-01T18:20:00+08:00")
        self.assertEqual(row_with_published_at["seen_date"], "2026-07-01")

    def test_write_result_also_writes_ascii_safe_companion_json(self) -> None:
        result = {
            "status": "partial_error",
            "items": [{"title": "中兴手机", "keyword": "红魔"}],
            "errors": [{"body_preview": "登录软媒通行证"}],
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            out_path = Path(tmpdir) / "ithome_playwright_today.json"

            self.module.write_result(result, out_path)

            utf8_text = out_path.read_text(encoding="utf-8")
            ascii_text = out_path.with_name("ithome_playwright_today.ascii.json").read_text(encoding="utf-8")

        self.assertIn("中兴手机", utf8_text)
        self.assertNotIn("中兴手机", ascii_text)
        self.assertIn("\\u4e2d\\u5174\\u624b\\u673a", ascii_text)
        self.assertIn("\\u767b\\u5f55\\u8f6f\\u5a92\\u901a\\u884c\\u8bc1", ascii_text)

    def test_result_to_stdout_json_is_ascii_safe(self) -> None:
        result = {"title": "中兴手机", "body_preview": "登录软媒通行证"}

        text = self.module.result_to_stdout_json(result)

        self.assertNotIn("中兴手机", text)
        self.assertIn("\\u4e2d\\u5174\\u624b\\u673a", text)
        self.assertIn("\\u767b\\u5f55\\u8f6f\\u5a92\\u901a\\u884c\\u8bc1", text)


if __name__ == "__main__":
    unittest.main()
