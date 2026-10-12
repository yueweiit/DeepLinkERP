# IT Home 404 Redirect Retry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When the Playwright IT Home crawler receives the temporary 404 redirect page, wait 8 seconds and retry the same URL once before treating the source as empty.

**Architecture:** Add a focused detector for the IT Home 404 redirect page and wire it into `run_playwright_collect` immediately after page fetch, before parsing. This keeps ordinary no-result pages and network errors unchanged while giving transient redirect pages one recovery attempt.

**Tech Stack:** Python 3.11, Playwright sync API, `unittest`.

## Global Constraints

- Do not modify the main `collect-news` crawler for this task.
- Do not retry forever: exactly one 8-second retry per source when the 404 redirect page is detected.
- Keep the retry visible in logs as `retry_404_redirect`.
- Use TDD and run the script test module before completion.

---

### Task 1: Retry IT Home 404 Redirect Page Once

**Files:**
- Modify: `scripts/ithome_playwright_today.py`
- Modify: `tests/test_ithome_playwright_today_script.py`

**Interfaces:**
- Produces: `is_ithome_404_redirect_page(html: str) -> bool`
- Updates: `run_playwright_collect(...)` to wait `8000` ms and refetch once when the detector is true.

- [ ] **Step 1: Add failing detector and collect-level tests**

Add tests for the detector and for one retry inside `run_playwright_collect`.

- [ ] **Step 2: Verify RED**

Run:

```powershell
py -m unittest tests.test_ithome_playwright_today_script.IthomePlaywrightTodayScriptTests.test_is_ithome_404_redirect_page_detects_redirect_prompt tests.test_ithome_playwright_today_script.IthomePlaywrightTodayScriptTests.test_run_playwright_collect_waits_8_seconds_and_retries_ithome_404_redirect_page -v
```

Expected: tests fail because `is_ithome_404_redirect_page` and retry behavior do not exist yet.

- [ ] **Step 3: Implement detector and retry**

Add constants:

```python
ITHOME_404_REDIRECT_WAIT_MS = 8000
ITHOME_404_REDIRECT_MARKERS = ("404错误", "没有找到页面", "自动返回IT之家首页")
```

Add `is_ithome_404_redirect_page` using `body_preview_from_html`/`html_fragment_text`, then in `run_playwright_collect` after `fetch_page_html`:

```python
if is_ithome_404_redirect_page(html):
    logger(...)
    page.wait_for_timeout(ITHOME_404_REDIRECT_WAIT_MS)
    html, text_len = fetch_page_html(page, fetch_source, timeout=timeout)
    fetched += 1
```

- [ ] **Step 4: Verify GREEN**

Run the two focused tests, then:

```powershell
py -m unittest tests.test_ithome_playwright_today_script -v
```

Expected: all tests pass.
