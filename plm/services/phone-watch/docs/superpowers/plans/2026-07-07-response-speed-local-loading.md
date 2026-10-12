# Response Speed Local Loading Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reduce OPPO/VIVO filter switching and page tab switching latency by avoiding unnecessary full-page API reloads, and reduce list payload enrichment overhead by making Tipo batch lookup use brand-grouped `IN` queries.

**Architecture:** Keep the existing lightweight Python/http.server and inline JavaScript structure. Change only the current page's data when filters change, reuse already-loaded page state on tab switches, cache low-frequency options in the browser state, and keep full refresh available through the refresh button.

**Tech Stack:** Python 3.11, unittest, existing inline HTML/CSS/JavaScript in `phone_watch/ui.py`, existing SQLite/PostgreSQL-compatible SQL helper style in `phone_watch/db.py`.

## Global Constraints

- Read `D:\Yuewei\资料\爬虫\docs\开发提示词.md` before implementation.
- Do not modify unrelated business rules.
- Do not hide real API errors as empty results.
- Do not change CSV export full-data semantics.
- Avoid pagination in this pass because it affects batch operation semantics.
- Add succinct comments near the new loading/cache logic for maintainability.
- Generate a deposit document under `D:\Yuewei\资料\爬虫\实施` after implementation.

---

### Task 1: Frontend Page-Scoped Loading

**Files:**
- Modify: `tests/test_breadcrumb_navigation.py`
- Modify: `phone_watch/ui.py`

**Interfaces:**
- Produces: `loadCurrentListOnly()`, `loadNewsOnly()`, `pageHasData(page)`.
- Preserves: `loadData()` as full refresh path for startup and refresh button.

- [x] **Step 1: Write failing tests**

Add tests asserting rendered HTML contains `loadCurrentListOnly`, `loadNewsOnly`, `pageHasData`, and that `#news-category` is split out from the global filter handler.

- [x] **Step 2: Verify RED**

Run: `py -m unittest tests.test_breadcrumb_navigation -v`

Expected: new tests fail before implementation because the functions and event split do not exist.

- [x] **Step 3: Implement page-scoped loading**

In `phone_watch/ui.py`, add:

```javascript
function currentListEndpoint(page, f) { ... }
async function loadCurrentListOnly() { ... }
async function loadNewsOnly() { ... }
function pageHasData(page) { ... }
```

Update filter and input event handlers so `#news-category` calls `loadNewsOnly()` and normal filters call `loadCurrentListOnly()`.

- [x] **Step 4: Verify GREEN**

Run: `py -m unittest tests.test_breadcrumb_navigation -v`

Expected: all breadcrumb navigation tests pass.

### Task 2: Tipo Batch Query Shape

**Files:**
- Modify: `tests/test_tipo_molding_status.py`
- Modify: `phone_watch/db.py`

**Interfaces:**
- Consumes: `molding_tipos_for_models(conn, rows)`.
- Produces: same grouped result shape, with query grouped by `brand` and `normalized_model IN (...)`.

- [x] **Step 1: Write failing test**

Add test that inspects executed SQL and asserts it uses `normalized_model IN` and not a large `OR` chain for same-brand rows.

- [x] **Step 2: Verify RED**

`pytest` is unavailable in this environment, so verify with the available runner after implementation and retain the test as part of the pytest suite.

- [x] **Step 3: Implement grouped IN query**

Replace the OR query builder in `molding_tipos_for_models()` with brand-grouped `IN` queries.

- [x] **Step 4: Verify GREEN**

Run: `py -m unittest tests.test_breadcrumb_navigation -v` and `py -m unittest discover tests -p "test_*.py"` or focused import-compatible tests where available.

### Task 3: Documentation and Verification

**Files:**
- Create: `D:\Yuewei\资料\爬虫\实施\2026-07-07-系统响应速度慢优化实施沉淀.md`

**Interfaces:**
- Consumes: final diff and verification output.
- Produces: user-facing maintenance record with changed files, code snippets, logic explanation, validation, and later maintenance advice.

- [x] **Step 1: Run focused verification**

Run the frontend static tests and Tipo tests with available commands.

- [x] **Step 2: Generate deposit document**

Document changed files, code comments, logic, verification results, and follow-up recommendations.

- [x] **Step 3: Final status**

Report files changed, verification commands, and any commands that could not run.
