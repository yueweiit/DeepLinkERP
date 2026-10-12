# IT之家 Playwright 登录态搜索优先 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 IT之家 Playwright 新闻采集在复用登录态的前提下优先访问搜索页，搜索页异常时再回退到 tag 页。

**Architecture:** 保持 `scripts/ithome_playwright_today.py` 作为唯一业务入口，复用现有 `--user-data-dir` 持久化 Chromium profile。只调整 `load_sources()` 构造品牌来源的顺序：品牌关键词先生成 `brand_search`，并把 tag 页作为 `fallback_url`。

**Tech Stack:** Python 3.11, Playwright sync API, unittest, existing fake Playwright test doubles.

## Global Constraints

- 不修改数据库写入逻辑。
- 不删除 tag 页能力，tag 仅作为搜索失败/404 后兜底。
- 保持现有命令参数兼容：`--user-data-dir`、`--login-wait-seconds`、`--import-db` 继续可用。
- 先写失败测试，再改业务代码。

---

### Task 1: 将 Playwright 品牌来源改为搜索优先

**Files:**
- Modify: `tests/test_ithome_playwright_today_script.py`
- Modify: `scripts/ithome_playwright_today.py`

**Interfaces:**
- Consumes: `load_sources(config_path: Path) -> list[FetchSource]`
- Produces: `FetchSource(source="brand_search", url=ITHOME_SEARCH_URL, fallback_url=ITHOME_TAG_URL, fallback_source="brand_tag")`

- [ ] **Step 1: Write the failing tests**

Update the existing load-source assertions:

```python
def test_load_sources_uses_search_pages_for_brand_keywords(self) -> None:
    ...
    self.assertEqual(sources[1].source, "brand_search")
    self.assertEqual(sources[1].url, "https://www.ithome.com/search/OPPO.html")
    self.assertEqual(sources[2].source, "brand_search")
    self.assertEqual(sources[2].url, "https://www.ithome.com/search/%E4%B8%AD%E5%85%B4%E6%89%8B%E6%9C%BA.html")
```

Update fallback assertions:

```python
def test_load_sources_adds_tag_fallback_for_brand_search(self) -> None:
    ...
    self.assertEqual(sources[1].source, "brand_search")
    self.assertEqual(sources[1].url, "https://www.ithome.com/search/%E7%BA%A2%E9%AD%94.html")
    self.assertEqual(sources[1].fallback_source, "brand_tag")
    self.assertEqual(sources[1].fallback_url, "https://www.ithome.com/tags/%E7%BA%A2%E9%AD%94/")
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
py -m unittest tests.test_ithome_playwright_today_script.IthomePlaywrightTodayScriptTests.test_load_sources_uses_search_pages_for_brand_keywords tests.test_ithome_playwright_today_script.IthomePlaywrightTodayScriptTests.test_load_sources_adds_tag_fallback_for_brand_search -v
```

Expected: FAIL because current code still returns `brand_tag` first.

- [ ] **Step 3: Write minimal implementation**

Change `load_sources()` so each brand keyword builds:

```python
FetchSource(
    source="brand_search",
    url=ITHOME_SEARCH_URL.format(keyword=quote(keyword_text)),
    keyword=keyword_text,
    brand=brand,
    fallback_url=ITHOME_TAG_URL.format(keyword=quote(keyword_text)),
    fallback_source="brand_tag",
)
```

- [ ] **Step 4: Run focused tests**

Run the same unittest command. Expected: both tests pass.

---

### Task 2: 保留并验证登录态采集命令

**Files:**
- Modify: `tests/test_ithome_playwright_today_script.py`

**Interfaces:**
- Consumes: `run_playwright_collect(..., user_data_dir: str | None)`
- Produces: persistent context with `launch_persistent_context(user_data_dir, headless=not headed, user_agent=USER_AGENT, viewport=..., locale="zh-CN")`

- [ ] **Step 1: Confirm existing login-state test still covers requirement**

Keep `test_run_playwright_collect_uses_persistent_context_when_user_data_dir_is_set` and `test_run_login_session_opens_homepage_with_persistent_context`.

- [ ] **Step 2: Run login-state tests**

Run:

```powershell
py -m unittest tests.test_ithome_playwright_today_script.IthomePlaywrightTodayScriptTests.test_run_playwright_collect_uses_persistent_context_when_user_data_dir_is_set tests.test_ithome_playwright_today_script.IthomePlaywrightTodayScriptTests.test_run_login_session_opens_homepage_with_persistent_context -v
```

Expected: both pass.

---

### Task 3: Final verification

**Files:**
- Test: `tests/test_ithome_playwright_today_script.py`
- Test: `scripts/ithome_playwright_today.py`

- [ ] **Step 1: Run broader script tests**

Run:

```powershell
py -m unittest tests.test_ithome_playwright_today_script -v
```

Expected: all tests in the module pass.

- [ ] **Step 2: Compile touched files**

Run:

```powershell
py -m compileall scripts\ithome_playwright_today.py tests\test_ithome_playwright_today_script.py
```

Expected: exit code 0.

- [ ] **Step 3: Report commands**

Login once:

```powershell
py scripts\ithome_playwright_today.py --user-data-dir .codex_tmp\ithome-profile --login-wait-seconds 120
```

Collect with login state and search priority:

```powershell
cmd /c "call scripts\local_pg_env.bat && set PHONE_WATCH_PG_CONNECT_TIMEOUT=120 && py scripts\ithome_playwright_today.py --user-data-dir .codex_tmp\ithome-profile --import-db --timeout 20"
```
