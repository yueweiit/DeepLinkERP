# News API Playwright Seen Date Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `/api/news?date=today` show newer Playwright-imported news rows instead of being filtered by an older `collect-news` window.

**Architecture:** Keep the existing collect-news window behavior when it is the freshest news source. When `news_items` has a newer `seen_date` than the latest collect-news window end date, query by `seen_date` and clear the window filters.

**Tech Stack:** Python 3.11, `unittest`, existing `phone_watch.db` and `phone_watch.webapp`.

## Global Constraints

- Do not change crawler behavior.
- Keep explicit `date=YYYY-MM-DD` behavior unchanged.
- Keep collect-news window behavior when there is no newer Playwright-imported `seen_date`.
- Prefer structured `seen_date` fallback over returning empty results from a stale window.

---

### Task 1: Prefer Newer Seen Date Over Stale Window

**Files:**
- Modify: `tests/test_news_api.py`
- Modify: `phone_watch/webapp.py`

**Interfaces:**
- Update: `news_payload(conn, query)` date selection for `date=today`.
- Consume: `db.latest_successful_news_run(conn)` and `db.latest_news_seen_date(conn)`.
- Produce: API response with `date=<latest seen_date>` and `window_start/window_end=None` when latest `seen_date` is newer than the latest collect-news window end date.

- [x] **Step 1: Write failing test**

Add a test that inserts an old collect-news window and a newer `ithome_phone_today` row, then calls `/api/news?source_type=ithome_phone_today&date=today`.

- [x] **Step 2: Verify RED**

Run:

```powershell
py -m unittest tests.test_news_api.NewsApiTests.test_api_news_today_prefers_newer_seen_date_over_stale_collect_news_window -v
```

Expected: fail because the stale window filters out the newer row.

- [x] **Step 3: Implement date selection**

In `news_payload`, when `date=today`, compare `db.latest_news_seen_date(conn)` with `latest_run["window_end"][:10]`. If the seen date is newer, use `seen_date` and clear window filters.

- [x] **Step 4: Verify GREEN**

Run the focused test and then `py -m unittest tests.test_news_api -v`.
