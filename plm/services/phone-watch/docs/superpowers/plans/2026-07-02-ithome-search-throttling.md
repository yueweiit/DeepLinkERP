# IT之家搜索节流 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reduce IT之家品牌搜索页异常/拦截概率 by adding slower randomized throttling for brand search requests.

**Architecture:** Keep throttling inside `phone_watch/news_crawler.py` near the URL fetch loop so it applies to both static fetch and Playwright fallback for IT之家搜索页. Inject sleeper/randomizer dependencies for tests so unit tests do not actually sleep.

**Tech Stack:** Python standard library, `unittest`, existing `NewsConfig`/`NewsSource` crawler code.

## Global Constraints

- Only IT之家 search URLs should use this slow throttling.
- Each IT之家品牌搜索 request waits a random `8` to `20` seconds before fetching.
- After every `3` IT之家品牌搜索 requests, wait one additional random `30` to `60` seconds.
- `mobile.ithome.com` phone channel must not use this slow brand-search throttling.
- Do not change database schema or UI.

---

### Task 1: Add Tests For Search Throttling

**Files:**
- Modify: `tests/test_news_crawler.py`

**Interfaces:**
- Consumes: `collect_news_sources_to_db(..., sleeper=..., random_uniform=...)`
- Produces: tests that verify sleep ranges and request counting without real sleeping.

- [ ] **Step 1: Write the failing test**

Add a test that configures four brand search URLs plus one mobile channel URL, records calls to injected `sleeper`, and asserts:

```python
self.assertEqual(delay_ranges[:4], [(8, 20), (8, 20), (8, 20), (30, 60)])
self.assertEqual(delay_ranges[4:], [(8, 20)])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `py -m unittest tests.test_news_crawler.NewsCrawlerTests.test_collect_news_sources_to_db_throttles_ithome_search_requests -v`

Expected: FAIL because `collect_news_sources_to_db` does not yet accept `sleeper` / `random_uniform`.

### Task 2: Implement Search Throttling

**Files:**
- Modify: `phone_watch/news_crawler.py`

**Interfaces:**
- Produces: `throttle_ithome_search_request(request_count, sleeper=time.sleep, random_uniform=random.uniform) -> None`
- Produces: optional keyword args on `collect_news_sources_to_db`: `sleeper` and `random_uniform`

- [ ] **Step 1: Add throttling constants and helper**

Add constants for `(8, 20)`, every `3` requests, and `(30, 60)`.

- [ ] **Step 2: Call helper before each IT之家 search fetch**

Inside the `for url in urls_for_source(source)` loop, increment a search request count when `is_ithome_search_url(url)` is true, then call the helper before `call_fetcher`.

- [ ] **Step 3: Remove duplicate 5-10 second sleep from `default_fetcher`**

Keep `fetch_ithome_search_html` but remove its old `time.sleep(random.uniform(5, 10))` so there is only one throttling layer.

- [ ] **Step 4: Run targeted test**

Run: `py -m unittest tests.test_news_crawler.NewsCrawlerTests.test_collect_news_sources_to_db_throttles_ithome_search_requests -v`

Expected: PASS.

### Task 3: Verify Existing News Tests And Live Sampling

**Files:**
- Test only.

- [ ] **Step 1: Run news crawler tests**

Run: `py -m unittest tests.test_news_crawler -v`

Expected: all tests pass.

- [ ] **Step 2: Run collect-news against temporary SQLite**

Run: `py -m phone_watch collect-news --db .codex_tmp\news_throttle_live.sqlite --timeout 20`

Expected: command completes and logs `[THROTTLE]` delays for IT之家 search URLs.
