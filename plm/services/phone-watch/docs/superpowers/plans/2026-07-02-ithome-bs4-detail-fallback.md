# IT之家 BS4 Detail Fallback Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make IT之家品牌搜索 use BS4 search-page candidate discovery as the primary path, fetch each article detail page for validation/enrichment, and keep Playwright only as search-page fallback.

**Architecture:** `phone_watch/news_crawler.py` keeps the existing source orchestration, throttling, render stats, and DB upsert flow. IT之家搜索页 parsing is split into candidate discovery, candidate-to-row fallback, detail-page enrichment, and a collector branch that fetches details one by one before window filtering/upsert.

**Tech Stack:** Python 3.11, stdlib `urllib`/`html.parser`, optional BeautifulSoup, SQLite test DB, `unittest`.

## Global Constraints

- Do not change DB schema.
- Do not change UI.
- Do not use Playwright for each article detail page.
- Do not hide search/detail fetch failures as empty results.
- Preserve existing IT之家搜索节流: random `8~20` seconds between brand search requests, plus `30~60` seconds after every 3 search requests.
- Detail-page request failures increment `detail_errors`, not source-level `errors`.
- Search source failures and search fallback abnormal pages still increment source-level `errors`.

---

### Task 1: Add Candidate Parsing Tests

**Files:**
- Modify: `tests/test_news_crawler.py`
- Modify later: `phone_watch/news_crawler.py`

**Interfaces:**
- Consumes: existing `parse_ithome_published_at()`, `is_ithome_news_url()`
- Produces: `IthomeSearchCandidate`, `parse_ithome_search_candidates()`

- [ ] **Step 1: Write the failing candidate parser test**

Add this test near the existing IT之家搜索页 parsing tests:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
py -m unittest tests.test_news_crawler.NewsCrawlerTests.test_parse_ithome_search_candidates_returns_candidates_not_rows -v
```

Expected: FAIL/ERROR because `parse_ithome_search_candidates` is not defined.

- [ ] **Step 3: Implement minimal candidate parser**

In `phone_watch/news_crawler.py`:

```python
from dataclasses import dataclass
```

Add:

```python
@dataclass(frozen=True)
class IthomeSearchCandidate:
    title: str
    url: str
    state_text: str = ""
    seen_date: str | None = None
    published_at: str | None = None
```

Add `parse_ithome_search_candidates()` and change `parse_ithome_brand_search_page()` to wrap candidates back into existing rows for compatibility.

- [ ] **Step 4: Run test to verify it passes**

Run:

```powershell
py -m unittest tests.test_news_crawler.NewsCrawlerTests.test_parse_ithome_search_candidates_returns_candidates_not_rows -v
```

Expected: PASS.

### Task 2: Add Detail Enrichment Tests

**Files:**
- Modify: `tests/test_news_crawler.py`
- Modify later: `phone_watch/news_crawler.py`

**Interfaces:**
- Consumes: `IthomeSearchCandidate`
- Produces: `enrich_ithome_candidate_from_detail()`, `row_from_ithome_candidate()`

- [ ] **Step 1: Write the failing detail enrichment tests**

Add:

```python
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
    self.assertEqual(row["title"], "Detail title wins")
    self.assertEqual(row["published_at"], "2026-07-02T08:45:00+00:00")
    self.assertEqual(row["seen_date"], "2026-07-02")
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
py -m unittest tests.test_news_crawler.NewsCrawlerTests.test_enrich_ithome_candidate_from_detail_prefers_detail_title_and_published_at -v
```

Expected: FAIL/ERROR because `enrich_ithome_candidate_from_detail` is not defined.

- [ ] **Step 3: Implement minimal detail extraction**

In `phone_watch/news_crawler.py`, add helpers for canonical URL, detail title, detail published time, degraded row, and detail enrichment. Use BeautifulSoup when available and regex fallback when not available.

- [ ] **Step 4: Run test to verify it passes**

Run:

```powershell
py -m unittest tests.test_news_crawler.NewsCrawlerTests.test_enrich_ithome_candidate_from_detail_prefers_detail_title_and_published_at -v
```

Expected: PASS.

### Task 3: Add Collector Detail Fetch Tests

**Files:**
- Modify: `tests/test_news_crawler.py`
- Modify later: `phone_watch/news_crawler.py`

**Interfaces:**
- Consumes: `collect_news_sources_to_db()`
- Produces: new parameters `detail_fetcher`, `detail_sleeper`, `detail_random_uniform`; new stats `detail_fetched`, `detail_errors`

- [ ] **Step 1: Write failing collector tests**

Add tests proving:

```python
def test_collect_news_sources_to_db_fetches_each_ithome_detail_and_counts_detail_errors(self) -> None:
    ...
```

The test search fetcher returns two candidates. The detail fetcher returns detail HTML for one URL and raises `TimeoutError` for the other. Expected counts: `detail_fetched == 1`, `detail_errors == 1`, `errors == 0`, `inserted == 2`; the failed detail keeps list-row fallback.

Add:

```python
def test_collect_news_sources_to_db_uses_browser_search_fallback_then_fetches_details(self) -> None:
    ...
```

The test search fetcher returns an IT之家 login/blocked page. The browser fallback returns a normal search page. Expected: browser fallback called once, detail fetcher called once, inserted row uses detail title.

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
py -m unittest tests.test_news_crawler.NewsCrawlerTests.test_collect_news_sources_to_db_fetches_each_ithome_detail_and_counts_detail_errors tests.test_news_crawler.NewsCrawlerTests.test_collect_news_sources_to_db_uses_browser_search_fallback_then_fetches_details -v
```

Expected: FAIL/ERROR because detail fetcher parameters and detail stats do not exist.

- [ ] **Step 3: Implement IT之家 detail branch in collector**

In `collect_news_sources_to_db()`:

```python
detail_fetcher: Fetcher | None = None
detail_sleeper: Callable[[float], None] = time.sleep
detail_random_uniform: Callable[[float, float], float] = random.uniform
```

Initialize:

```python
active_detail_fetcher = detail_fetcher or active_fetcher
counts["detail_fetched"] = 0
counts["detail_errors"] = 0
```

For `ithome_brand_search`, parse candidates from the search page/fallback page, then request every candidate URL with `render=False`, enrich rows, log detail failures as warnings, and keep degraded candidate rows when available.

- [ ] **Step 4: Run tests to verify they pass**

Run the two targeted tests again.

Expected: PASS.

### Task 4: Regression Verification

**Files:**
- Test only

- [ ] **Step 1: Run news crawler tests**

Run:

```powershell
py -m unittest tests.test_news_crawler -v
```

Expected: all tests pass.

- [ ] **Step 2: Run CLI news tests**

Run:

```powershell
py -m unittest tests.test_cli_collect_news -v
```

Expected: all tests pass.

- [ ] **Step 3: Run live temporary collection**

Run:

```powershell
py -m phone_watch collect-news --db .codex_tmp\news_bs4_detail_live.sqlite --timeout 20
```

Expected: command exits successfully or reports external network/site failures distinctly with `[WARN]`/`[ERROR]`; output includes `detail_fetched`/`detail_errors`.

### Task 5: Implementation Deposition Document

**Files:**
- Create outside repo: `D:\Yuewei\资料\爬虫\实施\2026-07-02-IT之家BS4搜索页主抓详情页校验与Playwright兜底实施沉淀.md`

**Interfaces:**
- Consumes: final diff and verification outputs.
- Produces: maintenance document requested by the user.

- [ ] **Step 1: Write the document**

Document must include changed files, key code/logic summary, test commands/results, live collection result, and later maintenance advice.

- [ ] **Step 2: Verify the document exists**

Run:

```powershell
Test-Path "D:\Yuewei\资料\爬虫\实施\2026-07-02-IT之家BS4搜索页主抓详情页校验与Playwright兜底实施沉淀.md"
```

Expected: `True`.

