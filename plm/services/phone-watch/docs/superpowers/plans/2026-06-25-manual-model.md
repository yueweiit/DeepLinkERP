# Manual Model Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete and verify the existing manual phone model entry feature, then write the requested implementation sediment document.

**Architecture:** Keep the lightweight existing design: the UI opens a modal form, posts JSON to `POST /api/manual-model`, the handler validates input, normalizes the model with `normalize_model`, and writes through existing `db.upsert_phone` or `db.upsert_candidate`. No new database tables or crawler/cleaning flow changes are required.

**Tech Stack:** Python 3.11, standard-library `http.server`, SQLite/PostgreSQL abstraction in `phone_watch/db.py`, vanilla HTML/CSS/JavaScript in `phone_watch/ui.py`, `unittest`.

## Global Constraints

- Default communication and documentation for the user should be Chinese.
- Read `D:\Yuewei\资料\爬虫\docs\开发提示词.md` before implementation.
- Follow `D:\Yuewei\资料\爬虫\docs\手动添加手机型号功能沉淀.md`.
- Do not create a `manual_models` table.
- Do not bypass `normalize_model`.
- Do not write direct SQL for the feature when `db.upsert_phone`, `db.upsert_candidate`, and `db.set_display_labels` are available.
- Do not modify `.env` or `.env.baota` secrets.
- Write the final sediment document to `D:\Yuewei\资料\爬虫\实施\手动添加手机型号功能实施沉淀.md`.

---

## File Structure

- Modify: `tests/test_manual_model.py`
  - Owns regression coverage for manual candidate and manual phone insertion, deduplication, validation, and rendered UI elements.
- Modify only if a test exposes a gap: `phone_watch/webapp.py`
  - Owns `POST /api/manual-model` validation and database writes.
- Modify only if a rendered UI gap is found: `phone_watch/ui.py`
  - Owns the “手动添加型号” button, modal form, and submit/refresh behavior.
- Create or overwrite: `D:\Yuewei\资料\爬虫\实施\手动添加手机型号功能实施沉淀.md`
  - Records changed files, core code, logic, verification results, and maintenance advice.

### Task 1: Add Missing Manual Model Tests

**Files:**
- Modify: `tests/test_manual_model.py`
- Test: `tests/test_manual_model.py`

**Interfaces:**
- Consumes: `POST /api/manual-model`, `db.list_candidates`, `db.list_phones`
- Produces: regression tests proving candidate and phone manual upsert behavior

- [ ] **Step 1: Add a phone upsert regression test**

Append this test method to `ManualModelTests`:

```python
    def test_post_manual_phone_upserts_and_sets_labels(self) -> None:
        payload = {
            "type": "phones",
            "brand": "SAMSUNG",
            "model": "Galaxy S26 Manual Test",
            "source_country": "MX",
            "source_url": "https://example.com/manual-phone",
            "source_name": "Manual",
            "badge": "新品",
            "sale_status": "已售",
            "sampling_status": "未开模",
        }

        first_status, first_body = self.post_json("/api/manual-model", payload)
        second_status, second_body = self.post_json("/api/manual-model", payload)

        self.assertEqual(first_status, 200)
        self.assertEqual(second_status, 200)
        self.assertTrue(first_body["ok"])
        self.assertEqual(first_body["type"], "phones")
        self.assertEqual(first_body["normalized_model"], "galaxys26manualtest")
        self.assertEqual(second_body["normalized_model"], "galaxys26manualtest")
        with db.connect(self.db_path) as conn:
            rows = db.list_phones(conn, brand="SAMSUNG", country="MX")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["model"], "Galaxy S26 Manual Test")
        self.assertEqual(rows[0]["source_name"], "Manual")
        self.assertEqual(rows[0]["badge_override"], "新品")
        self.assertEqual(rows[0]["sale_status_override"], "已售")
        self.assertEqual(rows[0]["clean_stage"], "manual")
```

- [ ] **Step 2: Add enum validation regression tests**

Append these test methods to `ManualModelTests`:

```python
    def test_post_manual_model_rejects_invalid_type(self) -> None:
        status, body = self.post_json(
            "/api/manual-model",
            {
                "type": "manual",
                "brand": "MOTOROLA",
                "model": "moto g power 5G 2026",
                "source_url": "https://example.com/manual-source",
            },
        )

        self.assertEqual(status, 400)
        self.assertIn("入库类型只能是 phones 或 candidates", body["error"])

    def test_post_manual_model_rejects_invalid_status(self) -> None:
        status, body = self.post_json(
            "/api/manual-model",
            {
                "type": "candidates",
                "brand": "MOTOROLA",
                "model": "moto g power 5G 2026",
                "source_url": "https://example.com/manual-source",
                "sampling_status": "处理中",
            },
        )

        self.assertEqual(status, 400)
        self.assertIn("开模状态不合法", body["error"])
```

- [ ] **Step 3: Run the focused tests**

Run:

```powershell
python -m unittest tests.test_manual_model -v
```

Expected: If the existing implementation is complete, all tests pass. If any test fails, use the failure to make the minimal implementation fix in Task 2.

### Task 2: Patch Only Confirmed Implementation Gaps

**Files:**
- Modify if needed: `phone_watch/webapp.py`
- Modify if needed: `phone_watch/ui.py`
- Test: `tests/test_manual_model.py`

**Interfaces:**
- Consumes: failing assertions from Task 1
- Produces: `POST /api/manual-model` and rendered UI behavior matching the sediment document

- [ ] **Step 1: If phone insertion fails, ensure `phones` rows use `country` and `clean_stage`**

Expected code shape in `phone_watch/webapp.py`:

```python
                    if table == "phones":
                        country = str(payload.get("country") or payload.get("source_country") or "MX").strip().upper()
                        db.upsert_phone(conn, {
                            "brand": brand,
                            "country": country,
                            "model": model,
                            "normalized_model": normalized_model,
                            "image_url": payload.get("image_url") or None,
                            "price": payload.get("price") or None,
                            "release_date": payload.get("release_date") or None,
                            "launch_date": payload.get("launch_date") or None,
                            "source_url": source_url,
                            "source_name": payload.get("source_name") or "Manual",
                            "badge": badge or None,
                            "first_seen_at": now,
                            "last_seen_at": now,
                            "sampling_status": sampling_status,
                            "clean_stage": "manual",
                        })
```

- [ ] **Step 2: If candidate insertion fails, ensure `missing_country`, `reason`, and normalization are set**

Expected code shape in `phone_watch/webapp.py`:

```python
                    else:
                        source_country = str(payload.get("source_country") or "CN").strip().upper()
                        missing_country = str(payload.get("missing_country") or "MX").strip().upper()
                        db.upsert_candidate(conn, {
                            "brand": brand,
                            "source_country": source_country,
                            "missing_country": missing_country,
                            "model": model,
                            "normalized_model": normalized_model,
                            "image_url": payload.get("image_url") or None,
                            "price": payload.get("price") or None,
                            "release_date": payload.get("release_date") or None,
                            "launch_date": payload.get("launch_date") or None,
                            "source_url": source_url,
                            "source_name": payload.get("source_name") or "Manual",
                            "reason": payload.get("reason") or "人工添加",
                            "first_seen_at": now,
                            "last_seen_at": now,
                            "sampling_status": sampling_status,
                        })
```

- [ ] **Step 3: If UI rendering fails, ensure these elements exist in `phone_watch/ui.py`**

Required rendered snippets:

```html
<button id="open-manual-model" class="secondary" type="button">手动添加型号</button>
<div id="manual-model-modal" class="modal-backdrop hidden">
<form id="manual-model-form" class="manual-modal">
```

Required JavaScript functions:

```javascript
function openManualModel() {
function saveManualModel(event) {
```

- [ ] **Step 4: Re-run focused tests**

Run:

```powershell
python -m unittest tests.test_manual_model -v
```

Expected: all tests pass.

### Task 3: Run Broader Verification

**Files:**
- Read-only: `config/sources.json`, `docker-compose.yml`
- Test: project commands

**Interfaces:**
- Consumes: completed Task 1 and Task 2
- Produces: verification evidence for the final sediment document

- [ ] **Step 1: Validate JSON config**

Run:

```powershell
python -m json.tool config/sources.json
```

Expected: prints formatted JSON and exits with code 0.

- [ ] **Step 2: Run manual model and cleaning unit tests**

Run:

```powershell
python -m unittest tests.test_manual_model tests.test_cleaning -v
```

Expected: all tests pass.

- [ ] **Step 3: Run database connection check**

Run:

```powershell
python -m phone_watch check-db
```

Expected: command exits with code 0 and reports an ok database connection.

- [ ] **Step 4: Validate Docker Compose config if Docker is available**

Run:

```powershell
docker compose config
```

Expected: command exits with code 0. If Docker is unavailable, record the exact error as an unverified item.

### Task 4: Write Implementation Sediment Document

**Files:**
- Create or overwrite: `D:\Yuewei\资料\爬虫\实施\手动添加手机型号功能实施沉淀.md`

**Interfaces:**
- Consumes: final implementation and verification outputs
- Produces: a Chinese maintenance document for future work

- [ ] **Step 1: Write the document with these sections**

Use this structure:

```markdown
# 手动添加手机型号功能实施沉淀

## 1. 本次目标

## 2. 改动文件

## 3. 核心代码与逻辑

## 4. 数据写入逻辑

## 5. 前端交互逻辑

## 6. 验证结果

## 7. 后期维护建议

## 8. 风险与边界
```

- [ ] **Step 2: Include exact changed files**

Mention:

```text
phone_watch/webapp.py
phone_watch/ui.py
tests/test_manual_model.py
D:\Yuewei\资料\爬虫\实施\手动添加手机型号功能实施沉淀.md
```

- [ ] **Step 3: Include verification command results**

Record every command from Task 3 with pass/fail status and any unavailable environment notes.

