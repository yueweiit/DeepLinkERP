# IT Home Playwright PG News Display Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make successful IT Home Playwright crawling write into the existing PostgreSQL-backed `news_items` flow and show tag crawl failures on the web news page.

**Architecture:** Reuse the existing `collect-news -> news_items -> /api/news -> UI` pipeline. Change IT Home brand source URLs from search pages to tag pages, cache phone-section rows during a collection run, and when a brand tag page fails or yields no rows, insert mobile-section keyword fallback rows with `last_error` so `/api/news` can report the current-day crawl failure while still showing fallback content.

**Tech Stack:** Python stdlib, existing `phone_watch.news_crawler`, existing `phone_watch.db`, existing `phone_watch.webapp`, existing native HTML/JavaScript UI, existing unittest suite, PostgreSQL via the existing DB abstraction.

## Global Constraints

- Do not use IT Home `/search/...` as the default brand source because it can trigger SoftMedia Passport.
- Prefer public `https://mobile.ithome.com/` and `https://www.ithome.com/tags/.../` pages.
- If a tag page fails or is empty, fallback to phone-section cached articles filtered by brand keywords.
- If a tag page fails or is empty, the web news page must show that the current-day crawl failed.
- Keep existing `source_type="ithome_brand_search"` for compatibility with existing UI/API filters.
- Do not introduce a new table unless existing `news_items.last_error` cannot carry the requirement.
- Do not overwrite unrelated dirty worktree changes.

---

### Task 1: Brand Tag URLs And Mobile Fallback Rows

**Files:**
- Modify: `phone_watch/news_crawler.py`
- Test: `tests/test_news_crawler.py`

**Interfaces:**
- Consumes: `NewsSource.search_keywords`, `NewsConfig.brand_keywords`, existing `parse_ithome_phone_today_html()`, existing `db.upsert_news_item()`.
- Produces: `urls_for_source(source: NewsSource) -> list[str]` that returns IT Home tag URLs for brand keyword sources, and fallback rows whose `last_error` explains the failed/empty tag page.

- [ ] **Step 1: Write failing tests**

Add tests proving:

```python
def test_ithome_brand_source_uses_keyword_tag_urls_before_start_urls(self):
    from phone_watch.news_crawler import urls_for_source

    source = NewsSource(
        brand="XIAOMI",
        source_type="ithome_brand_search",
        source_name="IT之家品牌关键词",
        start_urls=("https://www.ithome.com/search/old.html",),
        search_keywords=("小米",),
        render=False,
    )

    self.assertEqual(
        urls_for_source(source),
        ["https://www.ithome.com/tags/%E5%B0%8F%E7%B1%B3/"],
    )
```

Add a collection test where:

```python
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
```

The fake fetcher returns one OPPO article from mobile and an empty/login page from the OPPO tag URL. The test asserts:

```python
rows = db.list_news_items(self.conn, brand="OPPO", source_type="ithome_brand_search")
self.assertEqual(len(rows), 1)
self.assertEqual(rows[0]["title"], "OPPO phone from mobile")
self.assertIn("brand tag failed", rows[0]["last_error"])
self.assertEqual(counts["errors"], 1)
self.assertEqual(counts["fallbacks"], 1)
```

- [ ] **Step 2: Run tests to verify RED**

Run:

```powershell
py -m unittest tests.test_news_crawler -v
```

Expected: failures show current code still generates `/search/...` URLs and does not insert mobile fallback rows with `last_error`.

- [ ] **Step 3: Implement minimal code**

In `phone_watch/news_crawler.py`:

- Add `IT_HOME_TAG_URL = "https://www.ithome.com/tags/{keyword}/"`.
- Change `urls_for_source()` so `ithome_brand_search` with `search_keywords` returns tag URLs.
- During `collect_news_sources_to_db()`, preserve parsed `ithome_phone_today` rows in a per-run cache.
- When a brand tag URL returns no candidate/rows or is abnormal, filter cached mobile rows using `NewsConfig.brand_keywords[brand]` plus `source.search_keywords`.
- Convert matching mobile rows to `source_type="ithome_brand_search"`, `brand=<target brand>`, `source_name=<brand source_name>`, and `last_error="brand tag failed or empty; used mobile_phone_keyword_filter"`.
- Increment `counts["errors"]` and `counts["fallbacks"]` when this fallback is used.

- [ ] **Step 4: Run tests to verify GREEN**

Run:

```powershell
py -m unittest tests.test_news_crawler -v
```

Expected: all `tests.test_news_crawler` tests pass.

---

### Task 2: API Failure Metadata For Web News Page

**Files:**
- Modify: `phone_watch/webapp.py`
- Test: `tests/test_news_api.py`

**Interfaces:**
- Consumes: `news_items.last_error` from rows returned by `db.list_news_items()` and `db.list_news_for_brand_with_fallback()`.
- Produces: `/api/news` payload fields `crawl_failed: bool` and `crawl_error: str | None`.

- [ ] **Step 1: Write failing tests**

Add an API test that inserts an OPPO `news_items` row with `last_error="brand tag failed or empty; used mobile_phone_keyword_filter"` and requests:

```python
payload = news_payload(self.conn, {"brand": "OPPO", "source_type": "ithome_brand_search", "date": "2026-07-03"})
self.assertEqual(payload["status"], "ok")
self.assertTrue(payload["crawl_failed"])
self.assertIn("brand tag failed", payload["crawl_error"])
self.assertEqual(payload["items"][0]["last_error"], "brand tag failed or empty; used mobile_phone_keyword_filter")
```

- [ ] **Step 2: Run tests to verify RED**

Run:

```powershell
py -m unittest tests.test_news_api -v
```

Expected: payload has no `crawl_failed` or `crawl_error`.

- [ ] **Step 3: Implement minimal code**

In `phone_watch/webapp.py`:

- Add a helper that scans selected news rows for non-empty `last_error`.
- Return `crawl_failed=True` and the first error text when selected rows contain `last_error`.
- Keep `status="ok"` because fallback rows are still valid displayable content.

- [ ] **Step 4: Run tests to verify GREEN**

Run:

```powershell
py -m unittest tests.test_news_api -v
```

Expected: all `tests.test_news_api` tests pass.

---

### Task 3: Web Status Message

**Files:**
- Modify: `phone_watch/ui.py`
- Test: `tests/test_news_static_export_and_scripts.py` or `tests/test_breadcrumb_navigation.py`

**Interfaces:**
- Consumes: `/api/news` payload fields `crawl_failed` and `crawl_error`.
- Produces: existing `#news-status` area showing `当日爬取失败：<error>` when the current category has a crawl failure.

- [ ] **Step 1: Write failing test**

Add a static UI string test asserting `render_app_html(api_mode=True)` contains both:

```python
"crawl_failed"
"当日爬取失败"
```

- [ ] **Step 2: Run test to verify RED**

Run:

```powershell
py -m unittest tests.test_breadcrumb_navigation tests.test_news_static_export_and_scripts -v
```

Expected: failure because the UI does not yet handle `crawl_failed`.

- [ ] **Step 3: Implement minimal code**

In `phone_watch/ui.py`, in `renderNews()` before the existing `fallback_used` branch:

```javascript
} else if (news.crawl_failed) {
  status.className = "empty news-error";
  status.textContent = `当日爬取失败：${news.crawl_error || "品牌 tag 页无数据，已使用手机分区关键词结果"}`;
}
```

- [ ] **Step 4: Run test to verify GREEN**

Run:

```powershell
py -m unittest tests.test_breadcrumb_navigation tests.test_news_static_export_and_scripts -v
```

Expected: all focused UI/static tests pass.

---

### Task 4: End-To-End Verification

**Files:**
- Read: `config/news_sources.json`
- Read: `scripts/local_pg_env.ps1`

**Interfaces:**
- Consumes: existing CLI command `py -m phone_watch collect-news`.
- Produces: PG-backed `news_items` rows and web display through `/api/news`.

- [ ] **Step 1: Run full focused tests**

Run:

```powershell
py -m unittest tests.test_news_crawler tests.test_news_api tests.test_cli_collect_news tests.test_breadcrumb_navigation tests.test_news_static_export_and_scripts -v
```

Expected: all pass.

- [ ] **Step 2: Run Playwright debug script**

Run:

```powershell
py scripts\ithome_playwright_today.py --timeout 20 --out .codex_tmp\ithome_playwright_today.json
```

Expected: `status=ok` or structured fallback errors, and no `/search/...` fetch logs.

- [ ] **Step 3: Run formal news collection**

Run with the user's PG environment loaded:

```powershell
. .\scripts\local_pg_env.ps1
py -m phone_watch collect-news --timeout 20 --render-mode never
```

Expected: `collect-news` prints counts with inserted news rows. If tag pages fail, `errors` and `fallbacks` are non-zero and fallback rows have `last_error`.

- [ ] **Step 4: Run web server**

Run:

```powershell
py -m phone_watch serve --host 127.0.0.1 --port 8000
```

Expected: opening `http://127.0.0.1:8000` and selecting 新闻板块 shows PG-backed news. Categories with tag failure show `当日爬取失败`.

