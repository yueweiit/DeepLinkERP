# IT之家今日新闻脚本 Playwright 获取层 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 按实施前文档把 `scripts/ithome_playwright_today.py` 收敛为 Playwright 获取页面 HTML，保留现有关键词、解析、输出结构和展示链路不变。

**Architecture:** Playwright 只负责打开 URL、等待、轻量滚动和返回 HTML；文章日期、标题、链接、去重、品牌关键词和 JSON 输出继续走脚本现有函数。正式采集链路 `phone_watch/news_crawler.py`、数据库、API、UI 不纳入本次变更。

**Tech Stack:** Python 3.11, Playwright sync API, optional BeautifulSoup, unittest.

## Global Constraints

- 只允许修改 `scripts/ithome_playwright_today.py` 和必要测试。
- 不修改 `config/news_sources.json`。
- 不修改 `phone_watch/news_crawler.py`、数据库、接口、页面展示。
- 不把失败伪装成空结果；失败要进入结构化 `errors`。
- 输出 JSON 字段结构保持兼容。

---

### Task 1: 获取层单元测试

**Files:**
- Modify: `tests/test_ithome_playwright_today_script.py`

**Interfaces:**
- Consumes: `fetch_page_html(page, source, timeout=int) -> tuple[str, int]`
- Consumes: `run_playwright_collect(sources, today, timeout, headed) -> dict[str, Any]`

- [ ] 增加测试：`fetch_page_html()` 必须调用 `page.goto(..., wait_until="domcontentloaded")`，尝试等待 `networkidle`，滚动两次，然后返回 `page.content()` 和 body 文本长度。
- [ ] 增加测试：`run_playwright_collect()` 在无法导入 Playwright 时返回 `status=error` 和结构化 `errors`。
- [ ] 运行 `py -m unittest tests.test_ithome_playwright_today_script -v`，确认新增测试先失败或暴露现有脚本问题。

### Task 2: 目标脚本修复

**Files:**
- Modify: `scripts/ithome_playwright_today.py`

**Interfaces:**
- Produces: `fetch_page_html(page, source, timeout=int) -> tuple[str, int]`
- Produces: `run_playwright_collect(...) -> dict[str, Any]`

- [ ] 修正脚本中乱码导致的日期识别和 argparse 字符串语法问题。
- [ ] 保留 `load_sources()`、`extract_today_articles()`、`dedupe_articles()` 的业务职责。
- [ ] 保持 Playwright 获取层只返回 HTML 和 body 文本长度。
- [ ] 保持 `no today articles parsed html_len=... text_len=...` 的可排查错误信息。

### Task 3: 验证与沉淀

**Files:**
- Runtime: `.codex_tmp/ithome_playwright_today.json`
- Create outside repo: `D:\Yuewei\资料\爬虫\实施\2026-07-03-IT之家今日新闻脚本改用Playwright获取数据实施沉淀.md`

- [ ] 运行 `py -m unittest tests.test_ithome_playwright_today_script -v`。
- [ ] 运行 `py scripts\ithome_playwright_today.py --timeout 20`；如果网络或 Playwright 浏览器不可用，记录真实错误，不伪装成功。
- [ ] 生成实施沉淀文档，包含改动文件、关键代码、逻辑说明、验证结果、后期维护建议。
