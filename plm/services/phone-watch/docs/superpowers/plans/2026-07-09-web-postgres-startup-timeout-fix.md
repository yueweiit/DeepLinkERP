# Web PostgreSQL Startup Timeout Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep Windows web startup scripts on PostgreSQL defaults for deployment while fixing the bad connect-timeout guard.

**Architecture:** Database selection stays explicit in startup scripts. The web scripts default to PostgreSQL because the target deployment uses PGSQL; failures to reach PostgreSQL remain visible instead of falling back to SQLite. The only behavior fix is correcting `PHONE_WATCH_PG_CONNECT_TIMEOUT` initialization.

**Tech Stack:** Windows batch scripts, Python `unittest`, existing `phone_watch` CLI and PostgreSQL environment variables.

## Global Constraints

- Keep deployment/startup scripts connected to PostgreSQL by default.
- Do not add automatic SQLite fallback for PostgreSQL connection failures.
- Do not write real passwords or secrets into code or documentation.
- Keep errors distinguishable from empty results.

---

### Task 1: Add Startup Script Regression Tests

**Files:**
- Modify: `tests/test_news_static_export_and_scripts.py`

**Interfaces:**
- Consumes: Script text from `scripts/start_web.bat`, `scripts/start_web_background.bat`, and `scripts/run_server_windows.bat`.
- Produces: Regression coverage proving web startup scripts default to PostgreSQL and timeout initialization is correct.

- [x] **Step 1: Write the failing tests**

Add a test that checks both local Windows web scripts:

```python
def test_local_windows_web_scripts_default_to_postgres_with_timeout_guard(self) -> None:
    for script_name in ("start_web.bat", "start_web_background.bat"):
        with self.subTest(script=script_name):
            script = Path("scripts", script_name).read_text(encoding="utf-8")

            self.assertIn('if "%PHONE_WATCH_DB_BACKEND%"=="" set PHONE_WATCH_DB_BACKEND=postgres', script)
            self.assertIn('if "%PHONE_WATCH_PG_HOST%"=="" set PHONE_WATCH_PG_HOST=127.0.0.1', script)
            self.assertIn('if "%PHONE_WATCH_PG_CONNECT_TIMEOUT%"=="" set PHONE_WATCH_PG_CONNECT_TIMEOUT=10', script)
            self.assertIn('if "%PHONE_WATCH_PG_PASSWORD%"==""', script)
            self.assertNotIn('if "%PHONE_WATCH_PG_CONNECT_TIMEOUT%"==replace_with_local_password', script)
```

- [x] **Step 2: Run tests to verify they fail before script correction**

Run:

```powershell
py -m unittest tests.test_news_static_export_and_scripts -v
```

Expected before correction: the test fails while scripts still default to SQLite or contain the bad timeout comparison.

### Task 2: Restore PostgreSQL Defaults And Fix Timeout Guard

**Files:**
- Modify: `scripts/start_web.bat`
- Modify: `scripts/start_web_background.bat`

**Interfaces:**
- Consumes: Existing `py -m phone_watch serve` and `py -m phone_watch start-server` commands.
- Produces: Startup scripts that require PostgreSQL by default and initialize timeout only when empty.

- [x] **Step 1: Ensure PostgreSQL default**

Both scripts must contain:

```bat
if "%PHONE_WATCH_DB_BACKEND%"=="" set PHONE_WATCH_DB_BACKEND=postgres
```

- [x] **Step 2: Fix timeout initialization**

Both scripts must contain:

```bat
if "%PHONE_WATCH_PG_CONNECT_TIMEOUT%"=="" set PHONE_WATCH_PG_CONNECT_TIMEOUT=10
```

and must not contain:

```bat
if "%PHONE_WATCH_PG_CONNECT_TIMEOUT%"==replace_with_local_password set PHONE_WATCH_PG_CONNECT_TIMEOUT=10
```

- [ ] **Step 3: Run focused tests**

Run:

```powershell
py -m unittest tests.test_news_static_export_and_scripts -v
```

Expected: all tests in the file pass.

### Task 3: Verification And Documentation

**Files:**
- Create or update: `D:\Yuewei\资料\爬虫\实施\2026-07-09-Web启动PGSQL默认与timeout修复沉淀.md`

**Interfaces:**
- Consumes: Completed script changes and test results.
- Produces: Maintenance note covering changed files, code logic, verification, and future guidance.

- [ ] **Step 1: Run compile verification**

Run:

```powershell
py -m compileall tests\test_news_static_export_and_scripts.py
```

Expected: command exits with code 0.

- [ ] **Step 2: Write sediment document**

Document:
- Root cause: remote PostgreSQL connection timeout is a real PGSQL connectivity/configuration issue.
- Changed files: `scripts/start_web.bat`, `scripts/start_web_background.bat`, `tests/test_news_static_export_and_scripts.py`.
- Logic: startup defaults to PostgreSQL; timeout guard corrected; no SQLite fallback.
- Maintenance: deployment must ensure PGSQL host, port, password, firewall/security group, and PostgreSQL listener are reachable.

- [ ] **Step 3: Final check**

Run:

```powershell
py -m unittest tests.test_news_static_export_and_scripts -v
py -m compileall tests\test_news_static_export_and_scripts.py
```

Expected: tests pass and compile exits with code 0.
