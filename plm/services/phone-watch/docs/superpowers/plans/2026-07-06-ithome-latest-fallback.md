# IT Home Latest Fallback Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When an IT Home source has no articles matching the requested date, collect the latest three articles from that source instead.

**Architecture:** Keep the existing "today first" extraction as the primary path. Add a separate latest-article extraction path that reuses the current URL/title parsing and marks fallback rows with `fallback="latest_when_no_today"` and `requested_date=<target date>` so older rows are never mistaken for same-day rows.

**Tech Stack:** Python 3.11, Playwright sync API, BeautifulSoup when available, `unittest`.

## Global Constraints

- Default communication and docs for this task stay in Chinese when reporting to the user.
- Do not revert unrelated dirty worktree changes.
- Use TDD: write the failing unittest first, verify it fails, then implement.
- Do not add network-dependent tests.

---

### Task 1: Latest Three Fallback For Empty Today Results

**Files:**
- Modify: `scripts/ithome_playwright_today.py`
- Modify: `tests/test_ithome_playwright_today_script.py`

**Interfaces:**
- Consumes: `extract_today_articles(html, base_url, source, today, keyword=None) -> list[dict[str, str]]`
- Produces: `extract_latest_articles(html, base_url, source, requested_date, keyword=None, limit=3) -> list[dict[str, str]]`
- Produces fallback rows with keys: `title`, `url`, `source`, optional `date`, optional `keyword`, `fallback="latest_when_no_today"`, `requested_date`.

- [ ] **Step 1: Write failing extractor test**

Add this test to `tests/test_ithome_playwright_today_script.py`:

```python
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
```

- [ ] **Step 2: Run extractor test and verify RED**

Run: `py -m unittest tests.test_ithome_playwright_today_script.IthomePlaywrightTodayScriptTests.test_extract_latest_articles_returns_three_fallback_rows_when_dates_are_not_today -v`

Expected: FAIL with `AttributeError: module 'ithome_playwright_today' has no attribute 'extract_latest_articles'`.

- [ ] **Step 3: Write failing collect-level test**

Add this test to `tests/test_ithome_playwright_today_script.py`:

```python
    def test_run_playwright_collect_uses_latest_three_fallback_when_source_has_no_today_items(self) -> None:
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

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["counts"], {"sources": 1, "fetched": 1, "items": 3, "errors": 0})
        self.assertEqual([item["title"] for item in result["items"]], ["Latest fallback 1", "Latest fallback 2", "Latest fallback 3"])
        self.assertTrue(all(item["brand"] == "VIVO" for item in result["items"]))
        self.assertTrue(all(item["fallback"] == "latest_when_no_today" for item in result["items"]))
        self.assertTrue(any("fallback source=brand_tag keyword=vivo items=3 fallback=latest_when_no_today" in line for line in logs))
```

- [ ] **Step 4: Run collect-level test and verify RED**

Run: `py -m unittest tests.test_ithome_playwright_today_script.IthomePlaywrightTodayScriptTests.test_run_playwright_collect_uses_latest_three_fallback_when_source_has_no_today_items -v`

Expected: FAIL because the existing code reports an error instead of latest fallback rows.

- [ ] **Step 5: Implement minimal latest extraction**

In `scripts/ithome_playwright_today.py`, add constants:

```python
LATEST_WHEN_NO_TODAY_FALLBACK = "latest_when_no_today"
LATEST_WHEN_NO_TODAY_LIMIT = 3
```

Add a latest item converter that accepts article URLs even when the date is not the requested date, parses real dates when present, and marks fallback metadata:

```python
def article_any_date_from_text(text: str, today: date) -> str | None:
    normalized = clean_text(text)
    if not normalized:
        return None
    if any(token in normalized for token in ("今日", "刚刚", "分钟前", "小时前")):
        return today.isoformat()
    if "昨日" in normalized:
        return (today - timedelta(days=1)).isoformat()
    full_date = re.search(r"(\d{4})[-年](\d{1,2})[-月](\d{1,2})日?", normalized)
    if full_date:
        candidate = safe_date(int(full_date.group(1)), int(full_date.group(2)), int(full_date.group(3)))
        return candidate.isoformat() if candidate else None
    month_day = re.search(r"(\d{1,2})月(\d{1,2})日", normalized)
    if month_day:
        candidate = safe_date(today.year, int(month_day.group(1)), int(month_day.group(2)))
        if candidate and candidate > today:
            candidate = date(today.year - 1, candidate.month, candidate.day)
        return candidate.isoformat() if candidate else None
    slash_date = re.search(r"(\d{1,2})[/-](\d{1,2})(?![/-]\d)", normalized)
    if slash_date:
        candidate = safe_date(today.year, int(slash_date.group(1)), int(slash_date.group(2)))
        return candidate.isoformat() if candidate else None
    return None
```

Add `latest_item_to_article`, `extract_latest_articles_bs4`, `extract_latest_articles_regex`, and `extract_latest_articles` mirroring the current today extractors but without rejecting non-today dates and with `limit=3`.

- [ ] **Step 6: Wire collect fallback**

In `run_playwright_collect`, after `extract_today_articles(...)` returns empty and before mobile keyword fallback/error handling, call:

```python
fallback_items = extract_latest_articles(
    html,
    fetch_source.url,
    source=fetch_source.source,
    requested_date=today,
    keyword=fetch_source.keyword,
    limit=LATEST_WHEN_NO_TODAY_LIMIT,
)
```

If rows exist, add brand and page URL, append them to `items`, log `fallback=latest_when_no_today`, and break without adding an error.

- [ ] **Step 7: Run focused tests and verify GREEN**

Run: `py -m unittest tests.test_ithome_playwright_today_script.IthomePlaywrightTodayScriptTests.test_extract_latest_articles_returns_three_fallback_rows_when_dates_are_not_today tests.test_ithome_playwright_today_script.IthomePlaywrightTodayScriptTests.test_run_playwright_collect_uses_latest_three_fallback_when_source_has_no_today_items -v`

Expected: both tests PASS.

- [ ] **Step 8: Run full script test module**

Run: `py -m unittest tests.test_ithome_playwright_today_script -v`

Expected: all tests PASS.
