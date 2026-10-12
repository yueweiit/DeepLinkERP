# News Step 10 Full Chain Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete the news module full-chain verification requirements from step 10 in the `phone-watch-step6-api-news` project copy.

**Architecture:** Keep the news feature independent from `raw_items -> phones -> candidates`. Repair the remaining integration gaps around IT Home Tag sources, `/api/news`, static export, daily scripts, and tests without changing unrelated phone collection behavior.

**Tech Stack:** Python 3.11, unittest, SQLite/PostgreSQL-compatible DB helpers, Python `http.server`, vanilla HTML/CSS/JS, Docker Compose.

## Global Constraints

- Work in `C:\Users\JT\Desktop\备份\cst\phone_watch\phone-watch-step6-api-news`.
- Do not read or document real secrets from `.env`; use `C:\Users\JT\Desktop\备份\cst\phone_watch\python-sqlite-https-www-motorola-com\.env` only as a runtime environment source if needed.
- Do not revert existing user changes.
- News records only store title and article detail URL.
- `ithome_brand_search` and `ithome_phone_today` must remain independent sources.
- API failures must surface as errors, not fake empty results.
- Write the implementation summary to `D:\Yuewei\资料\爬虫\实施`.

---

### Task 1: Baseline Tests

**Files:**
- Read: `tests/test_news_config.py`
- Read: `tests/test_news_crawler.py`
- Read: `tests/test_news_api.py`
- Read: `tests/test_news_static_export_and_scripts.py`

**Interfaces:**
- Consumes: Existing test suite.
- Produces: Failure evidence for any remaining step 10 gaps.

- [ ] **Step 1: Run the focused news tests**

Run:

```powershell
py -m unittest tests.test_news_config tests.test_news_crawler tests.test_news_api tests.test_news_static_export_and_scripts -v
```

Expected: Either pass or fail with actionable gaps tied to step 10.

### Task 2: Repair Configuration and Crawler Gaps

**Files:**
- Modify: `config/news_sources.json`
- Modify: `phone_watch/news_crawler.py`
- Modify: `phone_watch/cli.py`
- Test: `tests/test_news_config.py`
- Test: `tests/test_news_crawler.py`

**Interfaces:**
- Consumes: `load_news_config`, `urls_for_source`, `is_ithome_news_url`, `should_render_source`, `collect-news --render-mode`.
- Produces: Valid IT Home Tag configuration and crawler behavior.

- [ ] **Step 1: If tests show config/crawler gaps, patch only the missing pieces**

Required behavior:
- IT Home brand source `source_name` should be `IT之家品牌 Tag`.
- Brand Tag `start_urls` should match the step 10 approved list.
- `ithome_brand_search` should prefer `start_urls`.
- `--render-mode playwright` should be accepted and behave like `always`.
- `is_ithome_news_url` should allow both `www.ithome.com` and `mobile.ithome.com`.

- [ ] **Step 2: Re-run targeted tests**

Run:

```powershell
py -m unittest tests.test_news_config tests.test_news_crawler -v
```

Expected: PASS.

### Task 3: Repair API, Static Export, and Daily Script Gaps

**Files:**
- Modify: `phone_watch/webapp.py`
- Modify: `phone_watch/static_export.py`
- Modify: `scripts/daily_collect.bat`
- Modify: `scripts/daily_collect.sh`
- Test: `tests/test_news_api.py`
- Test: `tests/test_news_static_export_and_scripts.py`

**Interfaces:**
- Consumes: DB news helpers in `phone_watch/db.py`.
- Produces: `/api/news`, static `news` payload, daily best-effort news collection.

- [ ] **Step 1: If tests show API/export/script gaps, patch only the missing pieces**

Required behavior:
- `/api/news?date=today` returns `status=ok`, `items`, and fallback metadata.
- Brand requests fall back to the latest 3 items when the requested day has no brand news.
- Static export includes a `news` payload.
- Daily scripts run `collect-news` after main `collect`; news failure logs but does not fail the main collection result.

- [ ] **Step 2: Re-run targeted tests**

Run:

```powershell
py -m unittest tests.test_news_api tests.test_news_static_export_and_scripts -v
```

Expected: PASS.

### Task 4: Full Local Verification

**Files:**
- Read: `config/news_sources.json`
- Read: `docker-compose.yml`
- Runtime: `data/phones.sqlite`

**Interfaces:**
- Consumes: CLI commands and Docker Compose config.
- Produces: Verification evidence for delivery document.

- [ ] **Step 1: Run JSON, DB, export, compile verification**

Run:

```powershell
py -m json.tool config/news_sources.json
py -m phone_watch init-db --db data\phones.sqlite
py -m phone_watch check-db --db data\phones.sqlite
py -m phone_watch export-html --db data\phones.sqlite --out data\phone_watch.html
py -m compileall phone_watch
```

Expected: Exit code 0 for each command.

- [ ] **Step 2: Run Docker config verification**

Run:

```powershell
docker compose config
```

Expected: Exit code 0.

### Task 5: Write Implementation Summary

**Files:**
- Create: `generated_docs/2026-07-01-新闻板块第十步全链路验证实施沉淀.md`
- Copy to: `D:\Yuewei\资料\爬虫\实施\2026-07-01-新闻板块第十步全链路验证实施沉淀.md`

**Interfaces:**
- Consumes: Final diff and verification output.
- Produces: User-requested maintenance document.

- [ ] **Step 1: Write the summary document**

Include:
- Changed files.
- Key code snippets.
- Logic explanation.
- Verification commands and results.
- Remaining risks.
- Maintenance recommendations.

- [ ] **Step 2: Copy the document to the requested D drive folder**

Run:

```powershell
Copy-Item generated_docs\2026-07-01-新闻板块第十步全链路验证实施沉淀.md D:\Yuewei\资料\爬虫\实施\2026-07-01-新闻板块第十步全链路验证实施沉淀.md
```

Expected: Target file exists.
