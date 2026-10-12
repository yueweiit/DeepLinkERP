# IT Home Playwright Persistent Login Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Allow the IT Home Playwright script to reuse a manually logged-in browser profile.

**Architecture:** Add an optional `--user-data-dir` argument to `scripts/ithome_playwright_today.py`. When provided, launch Chromium with `launch_persistent_context`; otherwise keep the existing ephemeral browser launch behavior.

**Tech Stack:** Python 3.11, unittest, Playwright sync API.

## Global Constraints

- Do not store account passwords or login tokens in source code.
- Keep the default behavior unchanged when `--user-data-dir` is omitted.
- Store local login profiles under `.codex_tmp` or another git-ignored private directory.

---

### Task 1: Persistent Browser Profile

**Files:**
- Modify: `scripts/ithome_playwright_today.py`
- Modify: `tests/test_ithome_playwright_today_script.py`

**Interfaces:**
- Consumes: `run_playwright_collect(..., headed: bool, playwright_factory: Callable | None, logger: Callable | None)`
- Produces: `run_playwright_collect(..., user_data_dir: str | None = None)`

- [ ] **Step 1: Write failing test**

Add a unittest proving `user_data_dir` calls `chromium.launch_persistent_context(...)` and closes the returned context.

- [ ] **Step 2: Run failing test**

Run: `py -m unittest tests.test_ithome_playwright_today_script.IthomePlaywrightTodayScriptTests.test_run_playwright_collect_uses_persistent_context_when_user_data_dir_is_set -v`

- [ ] **Step 3: Implement minimal support**

Add `user_data_dir` to `run_playwright_collect`, the parser, and `main`.

- [ ] **Step 4: Run focused tests**

Run: `py -m unittest tests.test_ithome_playwright_today_script -v`

- [ ] **Step 5: Try headed profile launch**

Run: `py scripts\ithome_playwright_today.py --headed --user-data-dir .codex_tmp\ithome-profile --timeout 20`
