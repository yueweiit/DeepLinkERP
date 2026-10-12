# IT之家 Playwright Today Script Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create a standalone Playwright script that crawls IT之家手机分区 and configured brand keyword search pages, then outputs only today's article date, title, and article URL.

**Architecture:** Keep this as an isolated debugging script under `scripts/`, with testable pure parsing helpers and Playwright only used for page fetching. The script reads `config/news_sources.json` for brand keywords and writes a JSON result to `.codex_tmp/ithome_playwright_today.json`.

**Tech Stack:** Python 3.11, Playwright sync API, optional BeautifulSoup, `unittest`.

## Global Constraints

- Do not write to the project database.
- Do not change existing `collect-news` behavior.
- Output only today's article date, title, and article URL, plus source/keyword metadata for debugging.
- Do not represent fetch failures as empty successful results; include structured `errors`.
- Article URLs must be IT之家 article detail links under `www.ithome.com` or `mobile.ithome.com`.

---

### Task 1: Parser Tests

**Files:**
- Create: `tests/test_ithome_playwright_today_script.py`
- Create later: `scripts/ithome_playwright_today.py`

**Interfaces:**
- Produces: `article_date_from_text(text: str, today: date) -> str | None`
- Produces: `extract_today_articles(html: str, base_url: str, source: str, today: date, keyword: str | None = None) -> list[dict[str, str]]`
- Produces: `dedupe_articles(items: list[dict[str, str]]) -> list[dict[str, str]]`

- [ ] Write failing tests for today's date parsing, search result extraction, mobile page extraction, and URL dedupe.
- [ ] Run `py -m unittest tests.test_ithome_playwright_today_script -v` and confirm import failure.

### Task 2: Standalone Script

**Files:**
- Create: `scripts/ithome_playwright_today.py`

**Interfaces:**
- CLI: `py scripts\ithome_playwright_today.py`
- Optional args: `--date YYYY-MM-DD`, `--news-config`, `--out`, `--timeout`, `--headed`
- Output JSON shape:

```json
{
  "status": "ok",
  "date": "2026-07-02",
  "items": [],
  "errors": [],
  "counts": {"sources": 0, "fetched": 0, "items": 0, "errors": 0}
}
```

- [ ] Implement pure parser helpers to pass Task 1 tests.
- [ ] Implement Playwright page fetching and config-driven source URL generation.
- [ ] Write JSON to stdout and `.codex_tmp/ithome_playwright_today.json`.
- [ ] Run `py -m unittest tests.test_ithome_playwright_today_script -v`.

### Task 3: Standalone Verification

**Files:**
- Runtime output: `.codex_tmp/ithome_playwright_today.json`

- [ ] Run `py scripts\ithome_playwright_today.py --timeout 20`.
- [ ] Confirm output status is `ok` or `partial_error`, with errors explicitly listed if IT之家 blocks/returns abnormal pages.
- [ ] Confirm JSON file exists.

