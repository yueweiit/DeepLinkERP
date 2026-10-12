# PG Primary Display Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make PostgreSQL the primary runtime database for the phone watch app, while keeping SQLite compatibility and ensuring the web UI displays existing PG data through the current API layer.

**Architecture:** Keep all database access centralized in `phone_watch/db.py`; do not add direct SQL to the UI. Update CLI/help/docs/scripts so production and Windows startup paths default to PostgreSQL and clearly explain that `--db` is only meaningful for SQLite mode.

**Tech Stack:** Python 3.11, pg8000/PostgreSQL, SQLite compatibility, Python http.server, Windows batch scripts.

## Global Constraints

- Do not delete, truncate, or overwrite existing PG data.
- Do not write database passwords into code or documentation.
- Keep SQLite as a fallback for local development.
- Web pages must read PG data through existing APIs: `webapp.py -> db.connect() -> db.list_*()`.
- Any schema change must support both SQLite and PostgreSQL.
- Generate final implementation notes under `D:\Yuewei\资料\爬虫\实施`.

---

### Task 1: Align CLI Wording With PostgreSQL Primary Mode

**Files:**
- Modify: `phone_watch/cli.py`
- Test: `tests/test_cli_pg_help.py`

**Interfaces:**
- Consumes: `db.db_backend()`, `db.DEFAULT_DB`
- Produces: clearer CLI help text without changing command behavior.

- [ ] **Step 1: Add tests for help text**

Create `tests/test_cli_pg_help.py` with assertions that top-level help no longer says this is SQLite-only and that `--db` is described as SQLite-only.

- [ ] **Step 2: Run the focused test**

Run: `python -m pytest tests/test_cli_pg_help.py -q`

Expected: FAIL before implementation if help text is still SQLite-only.

- [ ] **Step 3: Update CLI descriptions**

In `phone_watch/cli.py`, change:
- parser description from SQLite-only wording to SQLite/PostgreSQL wording.
- `--db` help text to say it is used only in SQLite mode.
- `init-db` help text to say it initializes current backend schema.

- [ ] **Step 4: Run focused test again**

Run: `python -m pytest tests/test_cli_pg_help.py -q`

Expected: PASS.

### Task 2: Add PG Startup Documentation for Existing Data Display

**Files:**
- Modify: `README.md`

**Interfaces:**
- Consumes: current scripts `scripts\run_server_windows.bat`, `scripts\daily_collect.bat`
- Produces: user-facing commands that start the web app against PG.

- [ ] **Step 1: Rewrite README database section**

Document:
- Default recommended backend is PostgreSQL for production.
- Existing PG data appears in the web UI after `init-db`/`serve`.
- Password must be provided via `PHONE_WATCH_PG_PASSWORD`.
- SQLite command remains available for local fallback.

- [ ] **Step 2: Check README for old status/database wording**

Run: `rg -n "SQLite|待打样|已打样|待开模" README.md`

Expected: SQLite appears only in fallback/context; old status wording should not appear as current behavior.

### Task 3: Verify PG Scripts Are Safe and Clear

**Files:**
- Modify if needed: `scripts/run_server_windows.bat`
- Modify if needed: `scripts/start_server_windows_background.bat`
- Modify if needed: `scripts/daily_collect.bat`

**Interfaces:**
- Consumes: PG environment variables.
- Produces: startup paths that default to PG without requiring `--db data/phones.sqlite`.

- [ ] **Step 1: Inspect scripts for SQLite db arguments**

Run: `rg -n "data\\\\phones.sqlite|data/phones.sqlite|--db" scripts`

Expected: production PG scripts should not pass `--db`; static export/local-only scripts may still pass SQLite.

- [ ] **Step 2: Patch only PG startup scripts if they still pass SQLite**

Remove `--db data\phones.sqlite` only from PG-oriented Windows scripts.

- [ ] **Step 3: Re-run script search**

Run: `rg -n "data\\\\phones.sqlite|data/phones.sqlite|--db" scripts`

Expected: no SQLite argument in `run_server_windows.bat`, `start_server_windows_background.bat`, or `daily_collect.bat`.

### Task 4: Verify Database Layer and Web API Against PG

**Files:**
- No code changes expected unless verification exposes a bug.

**Interfaces:**
- Consumes: environment variables `PHONE_WATCH_DB_BACKEND=postgres`, `PHONE_WATCH_PG_*`.
- Produces: evidence that PG connection, schema init, and API data display path work.

- [ ] **Step 1: Run unit tests covering DB behavior**

Run: `python -m pytest tests/test_tipo_molding_status.py tests/test_price_filtering.py tests/test_manual_model.py -q`

Expected: PASS.

- [ ] **Step 2: Check PG connection**

Run with PG env loaded: `python -m phone_watch check-db`

Expected: `数据库连接正常: backend=postgres ok=1`

- [ ] **Step 3: Initialize PG schema**

Run with PG env loaded: `python -m phone_watch init-db`

Expected: `PostgreSQL 表结构已初始化`

- [ ] **Step 4: Start web server and query API**

Run server against PG, then request:
- `http://127.0.0.1:8000/api/summary`
- `http://127.0.0.1:8000/api/phones`
- `http://127.0.0.1:8000/api/candidates`

Expected: JSON responses come from PG-backed APIs. Empty arrays are acceptable only if PG truly has no matching data; connection or SQL errors are not acceptable.

### Task 5: Generate Implementation Notes

**Files:**
- Create: `D:\Yuewei\资料\爬虫\实施\2026-06-26-PG数据库接入与已有数据展示实施沉淀.md`

**Interfaces:**
- Consumes: final diff and verification results.
- Produces: Chinese implementation notes for future maintenance.

- [ ] **Step 1: Write notes**

Include:
- modified files
- key code changes
- PG read/write/display logic
- startup commands
- verification results
- maintenance suggestions

- [ ] **Step 2: Confirm document exists**

Run: `Test-Path "D:\Yuewei\资料\爬虫\实施\2026-06-26-PG数据库接入与已有数据展示实施沉淀.md"`

Expected: `True`
