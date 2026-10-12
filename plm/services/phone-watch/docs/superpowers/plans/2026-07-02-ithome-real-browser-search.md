# IT Home Real Browser Search Fallback Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When IT Home brand search returns an abnormal or blocked page, retry by simulating a real user entering search from the IT Home homepage.

**Architecture:** Keep the existing static request and throttling path as the first attempt. Add a Playwright helper that visits `https://www.ithome.com/`, opens the search UI, types the decoded keyword, submits, waits for the search result page, and returns `page.content()`. Wire this helper into `collect_news_sources_to_db` as an injectable fallback so unit tests can exercise the behavior without launching a browser.

**Tech Stack:** Python stdlib, `unittest`, existing `phone_watch.crawler` Playwright integration, existing `phone_watch.news_crawler` parsing and DB flow.

## Global Constraints

- Do not revert unrelated dirty work in the repository.
- Keep throttling already added for IT Home search requests: random delay `8~20` seconds per brand keyword and extra `30~60` seconds after every 3 IT Home search requests.
- Apply the real browser fallback only to `www.ithome.com/search/*.html`; do not affect `mobile.ithome.com`.
- Unit tests must not depend on live IT Home network access or a real browser.
- Preserve current success/error distinction: blocked or abnormal fallback remains `errors += 1`; valid empty search result remains no inserted rows without pretending a fetch failure.

---

### Task 1: Add Tests for Keyword Extraction and Real Browser Fallback

**Files:**
- Modify: `tests/test_news_crawler.py`

**Interfaces:**
- Consumes: `collect_news_sources_to_db(...)`, `NewsConfig`, `NewsSource`
- Produces expected APIs:
  - `ithome_search_keyword_from_url(url: str) -> str | None`
  - `collect_news_sources_to_db(..., ithome_search_browser_fetcher: Callable[[str], FetchResult] | None = None, ...)`

- [ ] **Step 1: Write the failing keyword extraction test**

Add this test method to `NewsCrawlerTests`:

```python
    def test_ithome_search_keyword_from_url_decodes_keyword(self) -> None:
        from phone_watch.news_crawler import ithome_search_keyword_from_url

        self.assertEqual(
            ithome_search_keyword_from_url("https://www.ithome.com/search/%E5%8D%8E%E4%B8%BA%E6%89%8B%E6%9C%BA.html"),
            "华为手机",
        )
        self.assertEqual(
            ithome_search_keyword_from_url("https://www.ithome.com/search/%E7%BA%A2%E9%AD%94.html"),
            "红魔",
        )
        self.assertIsNone(ithome_search_keyword_from_url("https://mobile.ithome.com/"))
```

- [ ] **Step 2: Run the keyword extraction test and verify RED**

Run:

```powershell
py -m unittest tests.test_news_crawler.NewsCrawlerTests.test_ithome_search_keyword_from_url_decodes_keyword -v
```

Expected: `ImportError` because `ithome_search_keyword_from_url` is not defined.

- [ ] **Step 3: Write the failing real browser fallback test**

Add this test method to `NewsCrawlerTests`:

```python
    def test_collect_news_sources_to_db_uses_real_browser_search_fallback_for_blocked_ithome_search(self) -> None:
        from phone_watch.news_crawler import collect_news_sources_to_db

        config = NewsConfig(
            retention_days=7,
            fallback_limit=3,
            brand_keywords={"HUAWEI": ("华为手机",)},
            sources=(
                NewsSource(
                    brand="HUAWEI",
                    source_type="ithome_brand_search",
                    source_name="IT Home brand search",
                    search_keywords=("华为手机",),
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
              <head><title>登录软媒通行证</title></head>
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
                    <span class="state">今日 09:30</span>
                  </li>
                </ul></div></div>
                """,
                {"rendered": 1, "render_errors": 0, "fallbacks": 1},
            )

        with redirect_stdout(io.StringIO()):
            counts = collect_news_sources_to_db(
                self.conn,
                config,
                brand="HUAWEI",
                timeout=5,
                render_mode="config",
                allow_render_fallback=True,
                fetcher=fetcher,
                ithome_search_browser_fetcher=browser_fetcher,
                now="2026-07-02T08:00:00+00:00",
                sleeper=lambda _seconds: None,
            )

        rows = db.list_news_items(self.conn, brand="HUAWEI")
        self.assertEqual(fetch_calls, [("https://www.ithome.com/search/%E5%8D%8E%E4%B8%BA%E6%89%8B%E6%9C%BA.html", False)])
        self.assertEqual(browser_keywords, ["华为手机"])
        self.assertEqual(counts["inserted"], 1)
        self.assertEqual(counts["rendered"], 1)
        self.assertEqual(counts["fallbacks"], 1)
        self.assertEqual(counts["errors"], 0)
        self.assertEqual(rows[0]["title"], "Huawei real browser news")
```

- [ ] **Step 4: Run the fallback test and verify RED**

Run:

```powershell
py -m unittest tests.test_news_crawler.NewsCrawlerTests.test_collect_news_sources_to_db_uses_real_browser_search_fallback_for_blocked_ithome_search -v
```

Expected: `TypeError` because `collect_news_sources_to_db` does not accept `ithome_search_browser_fetcher`.

### Task 2: Implement Browser Search Helper and Wire Fallback

**Files:**
- Modify: `phone_watch/crawler.py`
- Modify: `phone_watch/news_crawler.py`

**Interfaces:**
- Produces:
  - `fetch_ithome_search_html_like_user(keyword: str, *, timeout: int = 25) -> str | None`
  - `ithome_search_keyword_from_url(url: str) -> str | None`
  - `collect_news_sources_to_db(..., ithome_search_browser_fetcher: Callable[..., FetchResult] | None = None, ...)`

- [ ] **Step 1: Add Playwright helper in `phone_watch/crawler.py`**

Add `fetch_ithome_search_html_like_user`. It must:
- import Playwright inside the function, matching `fetch_rendered_html`
- open `ITHOME_HOME_URL`
- click the search trigger if one exists
- fill the keyword into a visible search input
- press Enter
- wait for `/search/` in the URL or `#list`
- scroll lightly
- print `[RENDER] ithome search-like-user start keyword=...` and `done keyword=... html_len=... text_len=...`
- return `None` and print `[WARN] ithome search-like-user failed: ...` on failure

- [ ] **Step 2: Add keyword extraction in `phone_watch/news_crawler.py`**

Implement:

```python
def ithome_search_keyword_from_url(url: str) -> str | None:
    parsed = urlparse(url)
    if parsed.netloc.lower() != "www.ithome.com":
        return None
    match = re.match(r"^/search/(.+)\.html$", parsed.path)
    if not match:
        return None
    keyword = unquote(match.group(1)).strip()
    return keyword or None
```

- [ ] **Step 3: Wire browser fallback before the old direct render fallback**

In `collect_news_sources_to_db`, add an optional `ithome_search_browser_fetcher` parameter. When a non-rendered `ithome_brand_search` URL returns blocked/abnormal HTML and has no parsed rows:
- decode the keyword with `ithome_search_keyword_from_url`
- call `ithome_search_browser_fetcher(keyword, timeout=timeout)` if provided, otherwise `fetch_ithome_search_html_like_user(keyword, timeout=timeout)`
- count returned stats using existing `rendered`, `render_errors`, `fallbacks` keys
- parse returned HTML through `rows_from_source_html`
- only fall back to old `render=True` direct URL render if the real browser fallback fails to return usable rows

- [ ] **Step 4: Run the two new tests and verify GREEN**

Run:

```powershell
py -m unittest tests.test_news_crawler.NewsCrawlerTests.test_ithome_search_keyword_from_url_decodes_keyword -v
py -m unittest tests.test_news_crawler.NewsCrawlerTests.test_collect_news_sources_to_db_uses_real_browser_search_fallback_for_blocked_ithome_search -v
```

Expected: both pass.

### Task 3: Regression Verification

**Files:**
- Read: `tests/test_news_crawler.py`
- Read: `tests/test_cli_collect_news.py`

**Interfaces:**
- Consumes: all behavior from Tasks 1 and 2
- Produces: evidence that the change did not break existing news collection behavior

- [ ] **Step 1: Run news crawler tests**

Run:

```powershell
py -m unittest tests.test_news_crawler -v
```

Expected: all tests pass.

- [ ] **Step 2: Run CLI news collection tests**

Run:

```powershell
py -m unittest tests.test_cli_collect_news -v
```

Expected: all tests pass.

- [ ] **Step 3: Run live collection with a temp database**

Run:

```powershell
py -m phone_watch collect-news --db .codex_tmp\news_real_browser_live.sqlite --timeout 20
```

Expected: fewer IT Home search abnormal errors than the previous throttling-only run (`errors=3`). If live network or anti-bot still blocks, report the exact remaining failed URLs and warning messages.

## Self-Review

- Spec coverage: The plan covers homepage-first Playwright browsing, search keyword typing, result page capture, injection for tests, preservation of throttling, and regression/live verification.
- Placeholder scan: No `TBD`, `TODO`, or unspecified implementation steps remain.
- Type consistency: The same function names and signatures are used in tests and implementation tasks.

## Execution Notes

- Added `ithome_search_keyword_from_url()` and injectable `ithome_search_browser_fetcher` coverage.
- Added `fetch_ithome_search_html_like_user()` to visit the IT Home homepage, attempt search UI input, then capture the result page HTML.
- Unit verification passed:
  - `py -m unittest tests.test_news_crawler -v` -> 18 tests OK
  - `py -m unittest tests.test_cli_collect_news -v` -> 3 tests OK
- Live verification command:
  - `py -m phone_watch collect-news --db .codex_tmp\news_real_browser_live.sqlite --timeout 20`
- Live result:
  - `sources=9 fetched=11 parsed=93 inserted=25 errors=6 rendered=12 render_errors=0 fallbacks=12`
- Live finding:
  - The real browser fallback executed, but IT Home still returned short abnormal pages such as `html_len=2842 text_len=9` for several keywords.
  - Remaining abnormal search URLs included Motorola, OPPO, ZTE/中兴手机, 努比亚, 三星手机, and 华为手机 in this run.
