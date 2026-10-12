# IT之家 Data-Ot 双时间标签采集 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 按实施前文档把 IT之家 Playwright 采集改为 BeautifulSoup 解析 `data-ot` + `.state` 今日标签，并用增量窗口控制本次新增文章。

**Architecture:** Playwright 只负责访问页面和拿到渲染后 HTML；BeautifulSoup/regex fallback 负责从列表块抽取标题、链接、`data-ot`、今日标签。文章日期字段统一来自 `data-ot`，增量窗口只决定是否收录，不改写发布日期；最近三条兜底保留真实日期或空日期。

**Tech Stack:** Python 3.11, Playwright sync API, BeautifulSoup, unittest, existing `phone_watch.db` news import API.

## Global Constraints

- 先读 `D:\Yuewei\资料\爬虫\docs\开发提示词.md`。
- 不清理、不改写生产 PG 历史脏数据。
- 不把正文摘要里的日期当文章发布日期。
- `published_at/date/seen_date` 优先来自 IT之家列表 `data-ot`。
- fallback 最近三条不能把 `requested_date` 或采集日期伪造成 `published_at`。
- 只修改与 IT之家新闻采集、测试、沉淀文档相关的文件。

---

### Task 1: 增加 data-ot 与今日标签规则测试

**Files:**
- Modify: `tests/test_ithome_playwright_today_script.py`

**Interfaces:**
- Consumes: `extract_today_articles(...)`, `extract_latest_articles(...)`, `item_to_news_row(...)`
- Produces: 对 `published_at`、`date`、增量窗口、fallback 入库规则的回归保护

- [ ] **Step 1: Write failing tests**

Add tests covering:

```python
def test_extract_today_articles_requires_today_state_and_data_ot_target_date(self): ...
def test_extract_today_articles_rejects_today_state_when_data_ot_is_other_date(self): ...
def test_extract_today_articles_rejects_data_ot_target_date_without_today_state(self): ...
def test_extract_today_articles_uses_data_ot_not_summary_date(self): ...
def test_extract_today_articles_applies_incremental_window(self): ...
def test_item_to_news_row_uses_item_published_at_and_does_not_fake_fallback_date(self): ...
```

- [ ] **Step 2: Verify RED**

Run:

```powershell
py -m unittest tests.test_ithome_playwright_today_script -v
```

Expected: new tests fail because current code maps “今日” directly to target date and import still fabricates fallback `published_at` from requested date.

### Task 2: 实现列表时间抽取与今日收录规则

**Files:**
- Modify: `scripts/ithome_playwright_today.py`

**Interfaces:**
- Produces:
  - `node_data_ot(node: Any) -> str`
  - `html_data_ot(block: str) -> str`
  - `normalize_data_ot(value: str | None) -> str | None`
  - `parse_data_ot_datetime(value: str | None) -> datetime | None`
  - `is_in_collect_window(published_at: str, window_start: str | None, window_end: str | None) -> bool`

- [ ] **Step 1: Add helpers**

Implement helper functions that read `data-ot` from the current `div.c[data-ot]` or a nested node, normalize the full timestamp, and compare aware datetimes for the collection window.

- [ ] **Step 2: Update item conversion**

Change `item_to_article(...)` so it accepts `state_text`, `data_ot`, `window_start`, `window_end`, and only returns a row when:

```text
"今日" in state_text
data_ot[:10] == today.isoformat()
window_start < data_ot <= window_end when a window is provided
```

The row includes:

```python
{"date": data_ot[:10], "published_at": normalized_data_ot, ...}
```

- [ ] **Step 3: Update BS4 and regex extractors**

Pass `today_state_text(...)` and `node_data_ot(...)` / `html_data_ot(...)` into `item_to_article(...)`. Keep BeautifulSoup as primary and regex as fallback.

- [ ] **Step 4: Verify GREEN for extractor tests**

Run:

```powershell
py -m unittest tests.test_ithome_playwright_today_script -v
```

Expected: extractor-related tests pass, remaining failures only if import/window result metadata still needs work.

### Task 3: 实现结果窗口元数据与入库日期规则

**Files:**
- Modify: `scripts/ithome_playwright_today.py`

**Interfaces:**
- Consumes: `run_playwright_collect(...)`, `item_to_news_row(...)`, `import_result_to_db(...)`
- Produces: result-level `window_start/window_end`; item-level date fields from `data-ot`

- [ ] **Step 1: Add optional window parameters**

Extend `run_playwright_collect(...)` with optional `window_start` and `window_end`. Default `window_end` is current local ISO time; first-run `window_start` can remain absent unless supplied by caller/tests.

- [ ] **Step 2: Pass window to extractors**

Call `extract_today_articles(..., window_start=..., window_end=...)`, and attach `collect_window_start/collect_window_end` to emitted items and result.

- [ ] **Step 3: Fix import mapping**

Update `item_to_news_row(...)`:

```text
published_at = item["published_at"] if present
else item["date"] + "T00:00:00+00:00" if date present
else None
seen_date = published_at[:10] or item["date"] or requested_date/result_date
collect_window_start/end = item/result window metadata where available
```

Do not use `requested_date` to fabricate `published_at`.

- [ ] **Step 4: Verify all script tests**

Run:

```powershell
py -m unittest tests.test_ithome_playwright_today_script -v
```

Expected: all tests in this module pass.

### Task 4: API 回归与沉淀文档

**Files:**
- Test: `tests/test_news_api.py`
- Create: `D:\Yuewei\资料\爬虫\实施\2026-07-07-IT之家data-ot双时间标签采集实施沉淀.md`

**Interfaces:**
- Consumes: existing web/news API behavior
- Produces: verification evidence and maintenance notes

- [ ] **Step 1: Run API regression**

Run:

```powershell
py -m unittest tests.test_news_api -v
```

Expected: pass, or document pre-existing failures if unrelated.

- [ ] **Step 2: Generate deposit document**

Document changed files, key code snippets, logic explanation, verification commands/results, risks, and later maintenance suggestions.

- [ ] **Step 3: Final verification**

Run the targeted tests again if code changed after documentation.

