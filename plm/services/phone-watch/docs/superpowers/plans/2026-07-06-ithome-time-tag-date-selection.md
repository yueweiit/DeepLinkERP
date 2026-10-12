# IT之家时间标签日期选择 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** IT之家新闻抓取只用列表时间标签判断“今日”，当天没有结果时才取最近三条，并在页面显示文章真实发布时间。

**Architecture:** 在 `scripts/ithome_playwright_today.py` 中把日期来源限制到时间标签或日期属性，避免标题/摘要里的“今日开售”等业务词干扰。品牌页当天为空时先复用手机分区当天新闻按品牌过滤，再取最近三条兜底。入库时区分归档日 `seen_date` 和真实发布时间 `published_at`，前端优先显示 `published_at`。

**Tech Stack:** Python unittest、BeautifulSoup/正则 HTML 解析、现有 `news_items` 数据模型、内嵌前端 JavaScript。

## Global Constraints

- 默认中文沟通。
- 遵循 TDD：生产代码改动前先写失败测试并确认失败。
- 不清理或回退无关脏工作区改动。
- 不引入新依赖。

---

### Task 1: 时间标签日期提取

**Files:**
- Modify: `tests/test_ithome_playwright_today_script.py`
- Modify: `scripts/ithome_playwright_today.py`

**Interfaces:**
- Produces: `context_date_text(node: Any) -> str` 只返回时间标签/日期属性文本，供 `item_to_article()` 和 `latest_item_to_article()` 使用。

- [ ] **Step 1: Write the failing tests**

Add tests proving title text containing `今日` cannot override the time tag, while a `.state` time tag containing `今日 9:55` is accepted as today.

- [ ] **Step 2: Run tests to verify RED**

Run: `py -m unittest tests.test_ithome_playwright_today_script -v`
Expected: at least one new test fails because current `context_date_text()` reads the full card text.

- [ ] **Step 3: Implement minimal extraction**

Update `context_date_text()` to prefer `data-ot`, `datetime`, `.state`, `.d`, `time`, and descendant non-link date-like text. Do not use title or summary text for date inference unless it is a date-like standalone tag.

- [ ] **Step 4: Run tests to verify GREEN**

Run: `py -m unittest tests.test_ithome_playwright_today_script -v`
Expected: pass.

### Task 2: 今日优先，最近三条兜底

**Files:**
- Modify: `tests/test_ithome_playwright_today_script.py`
- Modify: `scripts/ithome_playwright_today.py`

**Interfaces:**
- Consumes: `filter_mobile_items_for_brand(mobile_items, source)`
- Produces: brand pages use mobile-phone today items before `latest_when_no_today`.

- [ ] **Step 1: Write the failing test**

Add a collector test where a brand page has no today items but `mobile_phone` contains a matching today item. Expected result uses `mobile_phone_keyword_filter` instead of `latest_when_no_today`.

- [ ] **Step 2: Run tests to verify RED**

Run: `py -m unittest tests.test_ithome_playwright_today_script -v`
Expected: new fallback-order test fails.

- [ ] **Step 3: Implement minimal fallback reorder**

Move `filter_mobile_items_for_brand()` before `extract_latest_articles()` in the no-today branch.

- [ ] **Step 4: Run tests to verify GREEN**

Run: `py -m unittest tests.test_ithome_playwright_today_script -v`
Expected: pass.

### Task 3: 入库和页面显示真实发布时间

**Files:**
- Modify: `tests/test_ithome_playwright_today_script.py`
- Modify: `scripts/ithome_playwright_today.py`
- Modify: `phone_watch/ui.py`

**Interfaces:**
- Produces: `item_to_news_row()` keeps `seen_date` as requested/import result date for fallback rows and sets `published_at` from `item["date"]`.
- Produces: `newsDate(item)` returns `published_at.slice(0, 10)` before `seen_date`.

- [ ] **Step 1: Write the failing tests**

Update import tests so fallback row `seen_date` is the requested date and `published_at` is the article date.

- [ ] **Step 2: Run tests to verify RED**

Run: `py -m unittest tests.test_ithome_playwright_today_script -v`
Expected: import date semantics test fails.

- [ ] **Step 3: Implement minimal date split**

Update `item_to_news_row()` and `newsDate()`.

- [ ] **Step 4: Run focused verification**

Run:
`py -m unittest tests.test_ithome_playwright_today_script -v`
`py -m unittest tests.test_news_api -v`

Expected: both pass.
