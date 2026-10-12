# IT Home Tag Search Fallback Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** For each IT Home brand keyword, try the tag URL first; if it returns the temporary 404 redirect page, wait 8 seconds and try the search URL for that same keyword.

**Architecture:** Extend `FetchSource` with an optional fallback URL and source label. `load_sources()` will generate one `brand_tag` source per keyword with `fallback_url=https://www.ithome.com/search/{keyword}.html`. `run_playwright_collect()` will switch to the fallback URL only for the current source after detecting the 404 redirect page, while the next keyword still starts with tag.

**Tech Stack:** Python 3.11, Playwright sync API, `unittest`.

## Global Constraints

- Keep this behavior inside `scripts/ithome_playwright_today.py`; do not modify the main `collect-news` crawler.
- Per keyword, start from tag every time.
- On IT Home 404 redirect page, wait 8000 ms and try search once.
- Do not retry forever; if search also fails or has no rows, continue with existing empty/latest fallback behavior.
- Preserve `keyword`, `brand`, and `page_url` metadata for whichever URL produced rows.

---

### Task 1: Add Tag-To-Search Fallback

**Files:**
- Modify: `scripts/ithome_playwright_today.py`
- Modify: `tests/test_ithome_playwright_today_script.py`

**Interfaces:**
- Modify: `FetchSource(source, url, keyword=None, brand=None, fallback_url=None, fallback_source=None)`
- Add: tag sources from `load_sources()` carry `fallback_url=ITHOME_SEARCH_URL.format(keyword=quote(keyword_text))` and `fallback_source="brand_search"`.
- Update: `run_playwright_collect()` switches `fetch_source.url` to the fallback URL after `is_ithome_404_redirect_page(html)` and logs `next=brand_search`.

- [x] **Step 1: Write failing tests**

Add tests that verify `load_sources()` attaches the search fallback and `run_playwright_collect()` waits 8 seconds, fetches tag then search, and uses the search URL in `page_url`.

- [x] **Step 2: Verify RED**

Run:

```powershell
py -m unittest tests.test_ithome_playwright_today_script.IthomePlaywrightTodayScriptTests.test_load_sources_adds_search_fallback_for_brand_tag tests.test_ithome_playwright_today_script.IthomePlaywrightTodayScriptTests.test_run_playwright_collect_switches_from_tag_to_search_after_404_redirect -v
```

Expected: tests fail because `fallback_url` and tag-to-search switch do not exist yet.

- [x] **Step 3: Implement fallback fields and load_sources mapping**

Add fields to `FetchSource` and set them in `load_sources()`.

- [x] **Step 4: Implement source switch after 404 redirect**

When the tag URL returns an IT Home 404 redirect page and `fallback_url` is present:

1. Log `retry_404_redirect ... next=brand_search`.
2. Wait `ITHOME_404_REDIRECT_WAIT_MS`.
3. Fetch a replacement `FetchSource` using the fallback URL/source.
4. Parse and record rows against that fallback URL.

- [x] **Step 5: Verify GREEN**

Run the two focused tests and then:

```powershell
py -m unittest tests.test_ithome_playwright_today_script -v
```

Expected: all tests pass.
