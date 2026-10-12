# News Category Keyword Search Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Update the news page to filter by news category and make IT之家 brand news use keyword search URLs.

**Architecture:** Keep the existing lightweight Python/http.server and native HTML/CSS/JavaScript structure. News brand sources are configured by `search_keywords`, crawler code generates encoded IT之家 search URLs, and the UI sends explicit `source_type` for news category requests.

**Tech Stack:** Python 3.11, standard library unittest, SQLite/PostgreSQL compatible code paths, native HTML/CSS/JavaScript.

## Global Constraints

- Do not introduce a frontend build tool or new framework.
- Do not modify `.env` or write secrets into code or documentation.
- Do not remove existing user work or unrelated dirty files.
- Keep `official` news removed.
- Keep old `/api/news?brand=...` compatibility in the backend; make the new UI pass `source_type`.

---

### Task 1: Tests First

**Files:**
- Modify: `tests/test_news_config.py`
- Modify: `tests/test_news_crawler.py`
- Modify: `tests/test_breadcrumb_navigation.py`
- Modify: `tests/test_news_static_export_and_scripts.py`

**Interfaces:**
- Consumes: existing `load_news_config()`, `urls_for_source()`, `render_app_html()`, `export_html()`
- Produces: failing tests for keyword-based config, HUAWEI category, and news category dropdown

- [ ] Update config tests to require user-confirmed keywords, no Tag `start_urls`, source name `IT之家品牌关键词搜索`, and `HUAWEI`.
- [ ] Update crawler test so `urls_for_source()` prefers `search_keywords` and returns `https://www.ithome.com/search/{encoded}.html`.
- [ ] Update UI/static tests to assert `id="news-category"`, `手机分区当日新闻`, `HUAWEI`, and category-specific API request strings.
- [ ] Run `py -m unittest tests.test_news_config tests.test_news_crawler tests.test_breadcrumb_navigation tests.test_news_static_export_and_scripts -v` and confirm failures are due to missing implementation.

### Task 2: Configuration And Crawler

**Files:**
- Modify: `config/news_sources.json`
- Modify: `phone_watch/config.py`
- Modify: `phone_watch/news_crawler.py`

**Interfaces:**
- Consumes: `NewsSource.search_keywords`
- Produces: keyword-based IT之家 source URLs and HUAWEI news config support

- [ ] Update `brand_keywords` to the confirmed mapping: `XIAOMI=小米`, `SAMSUNG=三星手机`, `OPPO=OPPO`, `HONOR=荣耀`, `VIVO=vivo`, `ZTE=中兴手机/努比亚/红魔`, `MOTOROLA=摩托罗拉`, `HUAWEI=华为手机`.
- [ ] Replace brand source names with `IT之家品牌关键词搜索` and remove brand `start_urls` so keyword generation is primary.
- [ ] Add `HUAWEI` to `REQUIRED_NEWS_BRANDS`.
- [ ] Change `IT_HOME_SEARCH_URL` to `https://www.ithome.com/search/{keyword}.html`.
- [ ] Change `urls_for_source()` so `ithome_brand_search` uses keywords before `start_urls`.
- [ ] Run focused config/crawler tests and make them pass.

### Task 3: News Category UI

**Files:**
- Modify: `phone_watch/ui.py`

**Interfaces:**
- Consumes: `/api/news?source_type=...`
- Produces: `#news-category` dropdown and category-specific news rendering

- [ ] Add a hidden-by-default `新闻分类` select next to existing filters with `手机分区当日新闻` and brand options including `HUAWEI`.
- [ ] Add `newsQuery()` that returns `source_type=ithome_phone_today` for the phone category and `brand=<BRAND>&source_type=ithome_brand_search` for brands.
- [ ] Change `loadData()` to call `/api/news` with `newsQuery()` when on the news page.
- [ ] Hide the existing `品牌` filter while on the news page and show `新闻分类`.
- [ ] Render only the active news section and change empty copy to `该分类暂无新闻`.
- [ ] Listen for `#news-category` changes and reset it from the reset button.
- [ ] Run focused UI/static tests and make them pass.

### Task 4: Full Verification And Documentation

**Files:**
- Create: `generated_docs/2026-07-01-新闻板块筛选分类与品牌关键词搜索实施沉淀.md`
- Copy to: `D:\Yuewei\资料\爬虫\实施\2026-07-01-新闻板块筛选分类与品牌关键词搜索实施沉淀.md`

**Interfaces:**
- Consumes: completed implementation and test results
- Produces: implementation sediment document

- [ ] Run `py -m json.tool config/news_sources.json`.
- [ ] Run `py -m unittest tests.test_news_config tests.test_news_crawler tests.test_news_api tests.test_breadcrumb_navigation tests.test_news_static_export_and_scripts -v`.
- [ ] Create implementation sediment document covering changed files, code logic, verification, and maintenance suggestions.
- [ ] Copy the document to the D drive target directory and verify copied content.
