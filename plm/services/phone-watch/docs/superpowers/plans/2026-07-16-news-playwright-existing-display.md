# News Playwright Existing Display Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Use the independent Playwright IT之家 crawler as the production news collection path and make the web news module display all retained database news from the last 7 days, newest first.

**Architecture:** `scripts/ithome_playwright_today.py` remains the collection/import entry for the Baota news task. The API stops treating the news page as a "today window only" view and instead returns retained `news_items` rows filtered by category/brand and sorted newest first. Retention stays database-driven: items are deleted 7 days after `first_collected_at`.

**Tech Stack:** Python 3.10+/3.11, Playwright, pg8000/PostgreSQL, SQLite test backend, stdlib `unittest`, current single-file HTTP server/UI.

## Global Constraints

- Default web news view shows all currently retained news from the last 7 days.
- News order is descending by `COALESCE(published_at, last_collected_at, first_collected_at)`, then `seen_date`, then `id`.
- Collection uses `scripts/ithome_playwright_today.py --import-db`; `python -m phone_watch collect-news` remains available but is no longer the recommended Baota news schedule command.
- Cleanup is based on `first_collected_at`, with `retention_days=7`.
- Fallback rows with real news, such as `mobile_phone_keyword_filter`, are not red error states.
- Failure marker rows whose title ends with `当日爬取失败` are diagnostics only and must not render as news cards.
- Do not add new runtime dependencies.

---

### Task 1: Database Query for Retained News

**Files:**
- Modify: `phone_watch/db.py`
- Test: `tests/test_news_db.py`

**Interfaces:**
- Consumes: existing `news_items` schema and existing `list_news_items(...)`.
- Produces: `list_recent_news_items(conn, *, brand: str | None = None, source_type: str | None = None, limit: int | None = None) -> list[Any]`.

- [ ] **Step 1: Write failing database tests**

Add these tests to `tests/test_news_db.py` inside the existing news DB test class:

```python
    def test_list_recent_news_items_orders_by_published_then_collected_time(self) -> None:
        with db.connect(self.db_path) as conn:
            db.upsert_news_item(conn, self.news_row(
                brand="SAMSUNG",
                title="older published samsung",
                url="https://www.ithome.com/0/999/701.htm",
                seen_date="2026-07-14",
                published_at="2026-07-14T10:00:00+00:00",
                first_collected_at="2026-07-14T10:05:00+00:00",
                last_collected_at="2026-07-14T10:05:00+00:00",
            ))
            db.upsert_news_item(conn, self.news_row(
                brand="SAMSUNG",
                title="newer collected samsung",
                url="https://www.ithome.com/0/999/702.htm",
                seen_date="2026-07-16",
                published_at=None,
                first_collected_at="2026-07-16T09:00:00+00:00",
                last_collected_at="2026-07-16T09:30:00+00:00",
            ))
            db.upsert_news_item(conn, self.news_row(
                brand="OPPO",
                title="oppo hidden by brand filter",
                url="https://www.ithome.com/0/999/703.htm",
                seen_date="2026-07-16",
                published_at="2026-07-16T11:00:00+00:00",
                first_collected_at="2026-07-16T11:05:00+00:00",
                last_collected_at="2026-07-16T11:05:00+00:00",
            ))

            rows = db.list_recent_news_items(conn, brand="SAMSUNG", source_type="ithome_brand_search")

        self.assertEqual([row["title"] for row in rows], ["newer collected samsung", "older published samsung"])
```

Add a limit test:

```python
    def test_list_recent_news_items_applies_limit(self) -> None:
        with db.connect(self.db_path) as conn:
            for index in range(5):
                db.upsert_news_item(conn, self.news_row(
                    brand="VIVO",
                    title=f"vivo recent {index}",
                    url=f"https://www.ithome.com/0/999/80{index}.htm",
                    seen_date="2026-07-16",
                    first_collected_at=f"2026-07-16T0{index}:00:00+00:00",
                    last_collected_at=f"2026-07-16T0{index}:00:00+00:00",
                ))

            rows = db.list_recent_news_items(conn, brand="VIVO", limit=3)

        self.assertEqual(len(rows), 3)
        self.assertEqual([row["title"] for row in rows], ["vivo recent 4", "vivo recent 3", "vivo recent 2"])
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```powershell
py -m unittest tests.test_news_db -v
```

Expected: failure with `AttributeError: module 'phone_watch.db' has no attribute 'list_recent_news_items'`.

- [ ] **Step 3: Implement the query**

Add this function in `phone_watch/db.py` after `list_news_items`:

```python
def list_recent_news_items(
    conn: Any,
    *,
    brand: str | None = None,
    source_type: str | None = None,
    limit: int | None = None,
) -> list[Any]:
    clauses: list[str] = []
    params: list[Any] = []
    if brand:
        clauses.append("brand = ?")
        params.append(str(brand).upper())
    if source_type:
        clauses.append("source_type = ?")
        params.append(str(source_type).lower())
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    limit_clause = ""
    if limit is not None:
        limit_clause = "LIMIT ?"
        params.append(int(limit))
    return conn.execute(
        f"""
        SELECT *
        FROM news_items
        {where}
        ORDER BY COALESCE(published_at, last_collected_at, first_collected_at) DESC,
                 seen_date DESC,
                 id DESC
        {limit_clause}
        """,
        params,
    ).fetchall()
```

- [ ] **Step 4: Run tests to verify pass**

Run:

```powershell
py -m unittest tests.test_news_db -v
```

Expected: all `tests.test_news_db` tests pass.

---

### Task 2: API Returns Existing Retained News Instead of Today Window

**Files:**
- Modify: `phone_watch/webapp.py`
- Test: `tests/test_news_api.py`

**Interfaces:**
- Consumes: `db.list_recent_news_items(...)` from Task 1.
- Produces: `/api/news` response with `mode="recent_retained"`, retained rows in newest-first order, failure marker rows filtered from `items`, and no red failure for `mobile_phone_keyword_filter` rows.

- [ ] **Step 1: Write failing API tests**

Add this test to `tests/test_news_api.py`:

```python
    def test_api_news_today_returns_recent_retained_database_rows_newest_first(self) -> None:
        with db.connect(self.db_path) as conn:
            db.upsert_news_item(
                conn,
                self.news_row(
                    brand="SAMSUNG",
                    title="older samsung",
                    url="https://www.ithome.com/0/999/901.htm",
                    seen_date="2026-07-14",
                    published_at="2026-07-14T09:00:00+00:00",
                    first_collected_at="2026-07-14T09:01:00+00:00",
                    last_collected_at="2026-07-14T09:01:00+00:00",
                ),
            )
            db.upsert_news_item(
                conn,
                self.news_row(
                    brand="SAMSUNG",
                    title="newer samsung from mobile fallback",
                    url="https://www.ithome.com/0/999/902.htm",
                    seen_date="2026-07-16",
                    published_at="2026-07-16T08:00:00+00:00",
                    first_collected_at="2026-07-16T08:01:00+00:00",
                    last_collected_at="2026-07-16T08:01:00+00:00",
                    last_error="mobile_phone_keyword_filter; requested_date=2026-07-16",
                ),
            )

        status, body = self.get_json("/api/news?brand=SAMSUNG&source_type=ithome_brand_search&date=today")

        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "ok")
        self.assertEqual(body["mode"], "recent_retained")
        self.assertFalse(body["crawl_failed"])
        self.assertIsNone(body["crawl_error"])
        self.assertEqual(
            [item["title"] for item in body["items"]],
            ["newer samsung from mobile fallback", "older samsung"],
        )
```

Add this test to keep diagnostic markers hidden:

```python
    def test_api_news_recent_retained_filters_failure_marker_rows(self) -> None:
        with db.connect(self.db_path) as conn:
            db.upsert_news_item(
                conn,
                self.news_row(
                    brand="HUAWEI",
                    title="IT之家品牌关键词搜索 当日爬取失败",
                    url="https://www.ithome.com/tags/%E5%8D%8E%E4%B8%BA/",
                    seen_date="2026-07-16",
                    last_error="brand tag failed or empty; used mobile_phone_keyword_filter",
                ),
            )
            db.upsert_news_item(
                conn,
                self.news_row(
                    brand="HUAWEI",
                    title="Huawei real news",
                    url="https://www.ithome.com/0/999/903.htm",
                    seen_date="2026-07-16",
                    published_at="2026-07-16T10:00:00+00:00",
                ),
            )

        status, body = self.get_json("/api/news?brand=HUAWEI&source_type=ithome_brand_search&date=today")

        self.assertEqual(status, 200)
        self.assertFalse(body["crawl_failed"])
        self.assertEqual([item["title"] for item in body["items"]], ["Huawei real news"])
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```powershell
py -m unittest tests.test_news_api -v
```

Expected: new tests fail because `/api/news` still uses today/window fallback and classifies `mobile_phone_keyword_filter` as crawl failure.

- [ ] **Step 3: Add fallback classification helper**

In `phone_watch/webapp.py`, add this helper near `is_no_today_news_error`:

```python
def is_successful_news_fallback(error: object) -> bool:
    text = str(error or "")
    return "mobile_phone_keyword_filter" in text
```

Update `classify_news_status(rows)` so successful fallback errors are not crawl failures:

```python
def classify_news_status(rows) -> dict[str, object]:
    errors = []
    no_today = False
    fallback_note = False
    for row in rows:
        error = row["last_error"] if "last_error" in row.keys() else None
        if not error:
            continue
        if is_no_today_news_error(error):
            no_today = True
            continue
        if is_successful_news_fallback(error) and not is_news_failure_marker(row):
            fallback_note = True
            continue
        if is_news_failure_marker(row):
            errors.append(str(error))
    crawl_error = errors[0] if errors else None
    empty_today = no_today and not crawl_error
    return {
        "crawl_failed": bool(crawl_error),
        "crawl_error": crawl_error,
        "empty_today": empty_today,
        "empty_message": "今日暂无相关新闻" if empty_today else "",
        "fallback_note": fallback_note,
        "fallback_message": "部分品牌页未命中，已展示手机分区匹配到的新闻" if fallback_note else "",
    }
```

- [ ] **Step 4: Replace `/api/news` selection with retained-news query**

In `news_payload(conn, query)`, replace the current `requested_date`/window selection block with:

```python
    brand = (query.get("brand") or "").strip().upper() or None
    source_type = (query.get("source_type") or "").strip().lower() or None
    fallback_limit = 3
    rows = db.list_recent_news_items(
        conn,
        brand=brand,
        source_type=source_type,
    )
    news_status = classify_news_status(rows)
    visible_rows = [row for row in rows if not is_news_failure_marker(row)]
    return {
        "status": "ok",
        "mode": "recent_retained",
        "date": query.get("date") or "today",
        "window_start": None,
        "window_end": None,
        "fallback_used": False,
        "fallback_limit": fallback_limit,
        "retention_days": 7,
        **news_status,
        "items": news_rows_to_payload(visible_rows),
    }
```

Keep the existing function signature and `news_rows_to_payload(...)` unchanged.

- [ ] **Step 5: Run API tests**

Run:

```powershell
py -m unittest tests.test_news_api -v
```

Expected: all `tests.test_news_api` tests pass after updating old assertions that depended on `fallback_used=true` for empty today views. For old tests, expected behavior is now retained-news mode and newest-first rows.

---

### Task 3: Playwright Script Cleanup After Import

**Files:**
- Modify: `scripts/ithome_playwright_today.py`
- Test: `tests/test_ithome_playwright_today_script.py`

**Interfaces:**
- Consumes: existing `import_result_to_db(...)`.
- Produces: `import_result_to_db(...)` also calls `db_module.cleanup_old_news_items(conn, retention_days=7, now=imported_at)` when available and returns `cleanup_deleted`.

- [ ] **Step 1: Write failing import cleanup test**

Add this test to `tests/test_ithome_playwright_today_script.py`:

```python
    def test_import_result_to_db_cleans_old_news_items_after_import(self) -> None:
        result = {
            "date": "2026-07-16",
            "items": [
                {
                    "date": "2026-07-16",
                    "title": "Today samsung",
                    "url": "https://www.ithome.com/0/999/950.htm",
                    "source": "brand_search",
                    "brand": "SAMSUNG",
                }
            ],
        }
        cleanup_calls: list[dict[str, object]] = []

        class FakeDb:
            DEFAULT_DB = self.module.Path("data/phones.sqlite")

            def init_db(self, db_path: object = DEFAULT_DB) -> None:
                pass

            def connect(self, db_path: object = DEFAULT_DB) -> object:
                class Conn:
                    def __enter__(inner_self) -> object:
                        return inner_self

                    def __exit__(inner_self, exc_type: object, exc: object, tb: object) -> None:
                        pass

                return Conn()

            def upsert_news_item(self, conn: object, row: dict[str, object]) -> int:
                return 1

            def cleanup_old_news_items(self, conn: object, *, retention_days: int, now: str | None = None) -> int:
                cleanup_calls.append({"retention_days": retention_days, "now": now})
                return 4

        counts = self.module.import_result_to_db(
            result,
            db_path="postgres",
            db_module=FakeDb(),
            imported_at="2026-07-16T10:00:00+00:00",
        )

        self.assertEqual(counts["cleanup_deleted"], 4)
        self.assertEqual(cleanup_calls, [{"retention_days": 7, "now": "2026-07-16T10:00:00+00:00"}])
```

- [ ] **Step 2: Run test to verify failure**

Run:

```powershell
py -m unittest tests.test_ithome_playwright_today_script.IthomePlaywrightTodayScriptTests.test_import_result_to_db_cleans_old_news_items_after_import -v
```

Expected: failure because `cleanup_deleted` is missing and cleanup is not called.

- [ ] **Step 3: Implement cleanup in import**

In `scripts/ithome_playwright_today.py`, change the `counts` initialization in `import_result_to_db(...)`:

```python
    counts = {"items": len(result.get("items") or []), "upserted": 0, "skipped": 0, "cleanup_deleted": 0}
```

After the import loop and before leaving the `with db_module.connect(...)` block, add:

```python
        cleanup = getattr(db_module, "cleanup_old_news_items", None)
        if cleanup is not None:
            counts["cleanup_deleted"] = int(cleanup(conn, retention_days=7, now=timestamp))
```

- [ ] **Step 4: Run Playwright script tests**

Run:

```powershell
py -m unittest tests.test_ithome_playwright_today_script -v
```

Expected: all script tests pass after updating existing expected import counts to include `"cleanup_deleted": 0` where fake DBs do not implement cleanup.

---

### Task 4: UI Status Text for Retained-News Mode

**Files:**
- Modify: `phone_watch/ui.py`
- Test: `tests/test_news_api.py` covers API contract; no browser test required for this copy-only change.

**Interfaces:**
- Consumes: `/api/news` fields `mode`, `retention_days`, `fallback_note`, and `fallback_message`.
- Produces: status bar text that describes retained-news display and avoids red failure for successful fallback rows.

- [ ] **Step 1: Update UI status decision**

In `phone_watch/ui.py`, update `renderNews()` status logic. Keep the existing `news.status !== "ok"` and `news.empty_today` branches, but insert retained-news handling before the old `news.crawl_failed` branch:

```javascript
        } else if (news.mode === "recent_retained") {
          status.className = "news-status-note";
          const retentionDays = news.retention_days || 7;
          status.textContent = news.fallback_note && news.fallback_message
            ? `${news.fallback_message}。当前展示最近 ${retentionDays} 天已采集新闻，按时间倒序`
            : `当前展示最近 ${retentionDays} 天已采集新闻，按时间倒序`;
```

Leave the old `crawl_failed` branch after this for legacy responses and explicit failures.

- [ ] **Step 2: Run API/UI-adjacent tests**

Run:

```powershell
py -m unittest tests.test_news_api tests.test_news_static_export_and_scripts -v
```

Expected: tests pass. If static export tests assert exact default news payload, update expected payload to include `mode="recent_retained"` and `retention_days=7`.

---

### Task 5: Documentation and Baota Command

**Files:**
- Modify: `DEPLOY_BAOTA.md`
- Modify: `DOCKER_DEPLOY.md`

**Interfaces:**
- Consumes: working independent Playwright script and profile path.
- Produces: clear Baota schedule commands for login bootstrap, collection, and log viewing.

- [ ] **Step 1: Update Baota deployment docs**

Add this section to `DEPLOY_BAOTA.md` under the news collection section:

```markdown
### 使用独立 Playwright 新闻脚本

新闻计划任务推荐使用独立 Playwright 脚本，复用服务器上的 IT之家登录态：

首次登录：

```bash
cd /www/wwwroot/YUEWEI/phone-watch-step6-api-news
set -a
source .env
set +a
mkdir -p logs .codex_tmp /www/wwwroot/YUEWEI/ithome-playwright-profile
python3 scripts/ithome_playwright_today.py \
  --user-data-dir /www/wwwroot/YUEWEI/ithome-playwright-profile \
  --login-wait-seconds 180
```

每日新闻采集：

```bash
cd /www/wwwroot/YUEWEI/phone-watch-step6-api-news
set -a
source .env
set +a
mkdir -p logs .codex_tmp /www/wwwroot/YUEWEI/ithome-playwright-profile
python3 scripts/ithome_playwright_today.py \
  --timeout 60 \
  --user-data-dir /www/wwwroot/YUEWEI/ithome-playwright-profile \
  --import-db \
  --out .codex_tmp/ithome_playwright_today.json \
  2>&1 | tee -a logs/ithome_playwright_today.log
tail -n 120 logs/ithome_playwright_today.log
```

页面新闻模块展示数据库中尚未过 7 天保留期的新闻，按发布时间或采集时间倒序。
```

- [ ] **Step 2: Update Docker docs**

In `DOCKER_DEPLOY.md`, add equivalent guidance using container commands only if Playwright persistent profile is mounted. Otherwise state that Baota host script is the recommended production path for the logged-in IT之家 workflow.

- [ ] **Step 3: Run doc grep check**

Run:

```powershell
rg -n "ithome_playwright_today|recent_retained|最近 7 天|user-data-dir" DEPLOY_BAOTA.md DOCKER_DEPLOY.md
```

Expected: commands and behavior are documented.

---

### Task 6: Final Verification

**Files:**
- No code changes.

**Interfaces:**
- Consumes all previous tasks.
- Produces verified behavior evidence.

- [ ] **Step 1: Run focused tests**

Run:

```powershell
py -m unittest tests.test_news_db tests.test_news_api tests.test_ithome_playwright_today_script tests.test_news_static_export_and_scripts -v
```

Expected: all tests pass.

- [ ] **Step 2: Run local SQLite smoke collection with independent script**

Run:

```powershell
$env:PHONE_WATCH_DB_BACKEND="sqlite"
py scripts\ithome_playwright_today.py --date 2026-07-08 --timeout 60 --user-data-dir C:\Users\JT\ithome-playwright-profile --import-db --db .codex_tmp\ithome_news_debug.sqlite --out .codex_tmp\ithome_playwright_today.json
```

Expected: script exits `0`, writes `.codex_tmp\ithome_playwright_today.json`, and reports import counts with `cleanup_deleted`.

- [ ] **Step 3: Run local API smoke against retained data**

Run:

```powershell
$env:PHONE_WATCH_DB_BACKEND="sqlite"
py -m phone_watch export-html --db .codex_tmp\ithome_news_debug.sqlite --out .codex_tmp\news_debug.html
```

Expected: export succeeds, and the embedded news payload contains `mode` or retained items sorted newest first depending on static export implementation. If static export does not use `/api/news`, rely on Task 2 API unit coverage.

