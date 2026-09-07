# Packing Source and Freight Comparison Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让用户在“资料与费用 → 装箱单”中从本地文件、钉钉审批附件/评论或钉钉知识库年度表选择装箱资料，确认共享包装组和整票毛重/体积后，独立比较按重量与按体积报价的整票总运费，并保存可追溯的试算历史。

**Architecture:** 阿里云 `dingtalk-oa` 使用应用身份读取白名单工作簿，把 Sheet 原始值、显示值和公式保存为不可变 MinIO 快照，并用 PostgreSQL 暴露只读索引。Vultr 上的 Frappe 使用现有 WireGuard、专用只读 PostgreSQL/MinIO 凭据读取快照；刷新通过权限仅限两个 `SECURITY DEFINER` 函数的独立提交账号进入任务队列，`costing_reader` 仍保持纯只读。四类来源最终进入同一个装箱解析/确认模型；运费比较只引用已确认快照，绝不修改费用池、SKU 分摊、批次核算状态或 ERP 回写数据。

**Tech Stack:** Frappe/Python/MariaDB、openpyxl、psycopg 3、MinIO SDK、原生 JavaScript/CSS、Node.js/TypeScript/Fastify/PostgreSQL/MinIO、Vitest、pytest。

---

## 工作目录与边界

- 综合成本仓库：`/Users/smk/Documents/ChatGPT/综合成本计算系统`
- 钉钉同步仓库本地工作目录：`/Users/smk/Documents/ChatGPT/dingtalk-oa`
- 钉钉同步生产目录：`/www/wwwroot/dingtalk-oa`，只用于部署和运行验证，不直接作为开发工作树。
- 综合成本生产站点：`deeplinkerp.com`。
- 2026 年工作簿白名单：`KGZLxjv9VG341rm7txY5p9amV6EDybno`。
- 已验证样本 Sheet：`st-d624e02f-88561`（油漆）和 `st-762f7f76-4525`（8.15 日货柜）。
- 不提交 `.env`、站点配置、SSH 私钥或 MinIO/PostgreSQL/钉钉密钥；服务器上现存的两个 `.env` 备份及 `authorized_keys` 保持不动。
- 每个任务完成后只提交该任务相关文件；两个仓库分别提交，不能把跨仓库改动混在一个 commit 中。

## 目标文件结构

### `dingtalk-oa`

- `migrations/20260907000000_create_packing_sheet_cache.cjs`：白名单、Sheet 索引、刷新队列、快照元数据、受限提交函数和只读视图。
- `src/dingtalk/document-client.ts`、`src/dingtalk/document-client.test.ts`：三个只读表格 API。
- `src/db/queries/packing-workbook.ts`、`src/db/queries/packing-workbook.test.ts`：白名单、索引、队列和快照查询。
- `src/packing/snapshot-store.ts`、`src/packing/snapshot-store.test.ts`：不可变 JSON 快照和 MinIO 完整性。
- `src/packing/refresh-worker.ts`、`src/packing/refresh-worker.test.ts`：工作簿索引及 Sheet 分块刷新任务。
- `src/cli/sync-packing-workbooks.ts`：把受控环境配置同步为数据库白名单。
- 修改 `src/config/schema.ts`、`src/index.ts`、`package.json`。

### `overseas_costing`

- `overseas_costing/services/packing_grid.py`：统一网格、表头、数值、合并范围与分组模型。
- `overseas_costing/services/packing_parse_service.py`：四类来源的统一解析与校验。
- `overseas_costing/integrations/dingtalk_packing_source.py`：只读索引、受限刷新提交、快照下载。
- `overseas_costing/services/packing_snapshot_service.py`：预览版本令牌、确认、当前快照和历史。
- `overseas_costing/services/freight_comparison_service.py`：纯 Decimal 计算和试算保存。
- `overseas_costing/api/packing_api.py`：来源、刷新、预览、确认、计算和历史白名单接口。
- `overseas_costing/doctype/overseas_packing_snapshot/*`：确认装箱快照。
- `overseas_costing/doctype/overseas_freight_comparison/*`：独立运费试算。
- `overseas_costing/page/overseas_cost_workbench/parts/86-packing-flow.js`：三步弹窗交互。
- `overseas_costing/page/overseas_cost_workbench/parts/47-packing-flow.css`：三步弹窗布局和响应式样式。
- `overseas_costing/scripts/build_workbench_assets.py`：按 parts 顺序生成并同步两份页面资源。
- 新增 `test_packing_grid.py`、`test_dingtalk_packing_source.py`、`test_packing_snapshot_service.py`、`test_freight_comparison_service.py`、`test_packing_api.py`，扩展 `test_workbench_frontend_state.py`。

## Task 1: 准备两套隔离工作树和基线

**Files:**

- Verify: `/Users/smk/Documents/ChatGPT/综合成本计算系统`
- Create if absent: `/Users/smk/Documents/ChatGPT/dingtalk-oa`

- [ ] **Step 1: 验证综合成本工作树只含已知非代码文件**

Run:

```bash
cd '/Users/smk/Documents/ChatGPT/综合成本计算系统'
git status --short
git log -1 --oneline
```

Expected: HEAD 包含 `498f43c55a docs: design packing import and freight comparison`；仅 `.superpowers/` 可保持未跟踪，不纳入任何提交。

- [ ] **Step 2: 建立钉钉仓库本地工作树**

Run only when the directory does not exist:

```bash
git clone --branch codex/dingtalk-archive \
  https://github.com/yueweiit/dingtalk-oa.git \
  '/Users/smk/Documents/ChatGPT/dingtalk-oa'
```

If it exists, run:

```bash
cd '/Users/smk/Documents/ChatGPT/dingtalk-oa'
git fetch origin
git status --short
git branch --show-current
```

Expected: branch is `codex/dingtalk-archive`; no production `.env` files are copied into this checkout.

- [ ] **Step 3: 运行两套基线测试**

```bash
cd '/Users/smk/Documents/ChatGPT/综合成本计算系统'
python -m pytest -q overseas_costing/tests

cd '/Users/smk/Documents/ChatGPT/dingtalk-oa'
npm ci
npm run test:run
npm run lint
```

Expected: all existing tests pass before feature edits.

## Task 2: 为钉钉年度表建立数据库白名单、刷新队列和只读视图

**Files:**

- Create: `/Users/smk/Documents/ChatGPT/dingtalk-oa/migrations/20260907000000_create_packing_sheet_cache.cjs`

- [ ] **Step 1: 先写迁移契约检查**

Create a small Vitest source check in `src/db/queries/packing-workbook.test.ts` that reads the migration and asserts these security markers exist:

```ts
expect(sql).toContain('costing_read.allowed_packing_workbook');
expect(sql).toContain('costing_read.packing_sheet_snapshot');
expect(sql).toContain('costing_read.packing_refresh_request');
expect(sql).toContain('SECURITY DEFINER');
expect(sql).toContain('REVOKE ALL ON FUNCTION');
expect(sql).toContain('packing_sheet_snapshots_v1');
```

- [ ] **Step 2: 运行测试并确认失败**

```bash
cd '/Users/smk/Documents/ChatGPT/dingtalk-oa'
npm run test:run -- src/db/queries/packing-workbook.test.ts
```

Expected: FAIL because the migration does not exist.

- [ ] **Step 3: 实现数据库结构**

Migration must create:

```sql
costing_read.allowed_packing_workbook(
  corp_id, workbook_id, year, label, enabled, created_at, updated_at,
  PRIMARY KEY (corp_id, workbook_id)
)

costing_read.packing_sheet_index(
  corp_id, workbook_id, sheet_id, sheet_name, visibility,
  source_updated_at, indexed_at, deleted_at,
  PRIMARY KEY (corp_id, workbook_id, sheet_id)
)

costing_read.packing_sheet_snapshot(
  id bigserial PRIMARY KEY,
  corp_id, workbook_id, sheet_id, sheet_name, range_address,
  capture_started_at, capture_finished_at, content_sha256 char(64),
  bucket, object_key, actual_size, row_count, column_count,
  source_last_non_empty_row, source_last_non_empty_column,
  capture_consistency, status, error_code, error_message, created_at,
  UNIQUE (corp_id, workbook_id, sheet_id, content_sha256),
  UNIQUE (bucket, object_key)
)

costing_read.packing_refresh_request(
  id bigserial PRIMARY KEY,
  request_key varchar(64) UNIQUE,
  request_kind varchar(32) CHECK (request_kind IN ('workbook_index','sheet_snapshot')),
  corp_id, workbook_id, sheet_id, requested_by,
  status CHECK (status IN ('pending','running','success','failed')),
  attempts, claimed_at, completed_at, error_code, error_message,
  snapshot_id, requested_at, updated_at
)
```

Create four public read surfaces and no base-table grants:

```sql
costing_read.packing_workbooks_v1
costing_read.packing_sheet_index_v1
costing_read.packing_sheet_snapshots_v1
costing_read.packing_refresh_status_v1
```

Create two functions with fixed `search_path`, whitelist checks, a 64-hex request key check, and idempotent `ON CONFLICT (request_key) DO NOTHING` behavior:

```sql
costing_read.request_packing_workbook_index_refresh(
  p_workbook_id text, p_request_key text, p_requested_by text
) RETURNS bigint

costing_read.request_packing_sheet_refresh(
  p_workbook_id text, p_sheet_id text, p_request_key text, p_requested_by text
) RETURNS bigint
```

Both functions derive `corp_id` from the enabled whitelist. The Sheet function must also require a live row in `packing_sheet_index`. Revoke `PUBLIC`; conditionally grant only view SELECT to `costing_reader` and only function EXECUTE to `costing_job_submitter`.

- [ ] **Step 4: 运行迁移契约测试**

```bash
npm run test:run -- src/db/queries/packing-workbook.test.ts
```

Expected: PASS.

- [ ] **Step 5: 提交迁移**

```bash
git add migrations/20260907000000_create_packing_sheet_cache.cjs src/db/queries/packing-workbook.test.ts
git commit -m 'feat: add packing workbook cache schema'
```

## Task 3: 实现钉钉表格只读 API 客户端

**Files:**

- Create: `/Users/smk/Documents/ChatGPT/dingtalk-oa/src/dingtalk/document-client.ts`
- Create: `/Users/smk/Documents/ChatGPT/dingtalk-oa/src/dingtalk/document-client.test.ts`

- [ ] **Step 1: 写 URL、查询参数、计数和错误分类测试**

Test these public functions:

```ts
listWorkbookSheets(workbookId, operatorUnionId)
getWorksheet(workbookId, sheetId, operatorUnionId)
getWorksheetRange(workbookId, sheetId, rangeAddress, operatorUnionId)
```

Assert exact read-only requests:

```text
GET /v1.0/doc/workbooks/{workbookId}/sheets?operatorId={unionId}
GET /v1.0/doc/workbooks/{workbookId}/sheets/{sheetId}?operatorId={unionId}
GET /v1.0/doc/workbooks/{workbookId}/sheets/{sheetId}/ranges/{A1}?operatorId={unionId}&select=values,displayValues,formulas
```

Also assert:

- every call records `recordApiUsage` exactly once;
- HTTP 401/403 and DingTalk business permission errors are non-retryable;
- 429 and 5xx retry at most the configured count;
- returned values are shape-checked before use.

- [ ] **Step 2: 运行测试并确认失败**

```bash
npm run test:run -- src/dingtalk/document-client.test.ts
```

Expected: FAIL because the client is absent.

- [ ] **Step 3: 实现最小只读客户端**

Use `tokenManager.getToken()`, the existing API usage table, and the existing rate limiter semantics. Define explicit types:

```ts
export interface WorksheetInfo {
  id: string;
  name: string;
  visibility?: string;
  lastNonEmptyRow?: number;
  lastNonEmptyColumn?: number;
}

export interface WorksheetRange {
  values: unknown[][];
  displayValues: string[][];
  formulas: string[][];
}
```

Never add any write endpoint. Encode every path segment and query value. Preserve raw numeric `values`; do not replace them with `displayValues`.

- [ ] **Step 4: 运行聚焦测试和类型检查**

```bash
npm run test:run -- src/dingtalk/document-client.test.ts src/dingtalk/api-client-usage.test.ts
npm run lint
```

Expected: PASS.

- [ ] **Step 5: 提交客户端**

```bash
git add src/dingtalk/document-client.ts src/dingtalk/document-client.test.ts
git commit -m 'feat: add read-only DingTalk workbook client'
```

## Task 4: 实现白名单同步、不可变快照和刷新 Worker

**Files:**

- Create: `/Users/smk/Documents/ChatGPT/dingtalk-oa/src/db/queries/packing-workbook.ts`
- Create: `/Users/smk/Documents/ChatGPT/dingtalk-oa/src/packing/snapshot-store.ts`
- Create: `/Users/smk/Documents/ChatGPT/dingtalk-oa/src/packing/snapshot-store.test.ts`
- Create: `/Users/smk/Documents/ChatGPT/dingtalk-oa/src/packing/refresh-worker.ts`
- Create: `/Users/smk/Documents/ChatGPT/dingtalk-oa/src/packing/refresh-worker.test.ts`
- Create: `/Users/smk/Documents/ChatGPT/dingtalk-oa/src/cli/sync-packing-workbooks.ts`
- Modify: `/Users/smk/Documents/ChatGPT/dingtalk-oa/src/config/schema.ts`
- Modify: `/Users/smk/Documents/ChatGPT/dingtalk-oa/src/index.ts`
- Modify: `/Users/smk/Documents/ChatGPT/dingtalk-oa/package.json`

- [ ] **Step 1: 写失败测试**

Cover:

```ts
it('converts zero-based lastNonEmpty indexes to an inclusive A1 range')
it('marks an empty sheet without requesting a range')
it('chunks a wide sheet without exceeding the configured cell limit')
it('hashes canonical raw values, display values and formulas')
it('does not call DingTalk when the immutable object already exists')
it('claims pending refresh jobs with SKIP LOCKED')
it('does not retry a permission failure forever')
it('captures start/end time because multi-range reads are not atomic')
```

The oil sample test must retain raw `4197.4` and `8.7403305` even when display values are `¥4197.40` and `¥8.74`.

- [ ] **Step 2: 确认测试失败**

```bash
npm run test:run -- src/packing/snapshot-store.test.ts src/packing/refresh-worker.test.ts
```

Expected: FAIL because query/store/worker modules are absent.

- [ ] **Step 3: 增加受控配置**

Add schema fields:

```ts
DINGTALK_PACKING_READER_USER_ID: z.string().trim().min(1).optional(),
DINGTALK_PACKING_WORKBOOKS_JSON: z.string().default('[]'),
PACKING_SNAPSHOT_MINIO_BUCKET: z.string().default('dingtalk-packing-snapshots'),
PACKING_REFRESH_POLL_MS: z.coerce.number().int().min(1000).max(60000).default(5000),
PACKING_RANGE_MAX_CELLS: z.coerce.number().int().min(100).max(20000).default(5000),
PACKING_SHEET_MAX_ROWS: z.coerce.number().int().min(1).max(10000).default(5000),
PACKING_SHEET_MAX_COLUMNS: z.coerce.number().int().min(1).max(200).default(100),
```

Parse the whitelist with Zod into `{year, workbookId, label}` and reject duplicate years/IDs. Production value for the first entry is:

```json
[{"year":2026,"workbookId":"KGZLxjv9VG341rm7txY5p9amV6EDybno","label":"2026海运待出货装箱计划"}]
```

- [ ] **Step 4: 实现数据库查询层和白名单 CLI**

The CLI upserts the configured entries for `DINGTALK_CORP_ID`, disables removed entries instead of deleting history, and then queues a workbook-index refresh. Add:

```json
"packing:sync-workbooks": "tsx src/cli/sync-packing-workbooks.ts"
```

- [ ] **Step 5: 实现快照对象格式和 MinIO 幂等**

Store this canonical JSON shape:

```json
{
  "schemaVersion": 1,
  "workbookId": "...",
  "sheetId": "...",
  "sheetName": "...",
  "rangeAddress": "A1:BE11",
  "captureStartedAt": "...",
  "captureFinishedAt": "...",
  "mergeRangesAvailable": false,
  "chunks": [
    {"rangeAddress":"A1:BE11","values":[],"displayValues":[],"formulas":[]}
  ]
}
```

Canonicalize keys and array positions before SHA-256. Use immutable key:

```text
{corp_id}/{workbook_id}/{sheet_id}/{sha256}.json
```

Run MinIO `HEAD` first; upload only when absent; verify stored size and persist the same SHA-256 in PostgreSQL. Never label the JSON object as an `.xlsx` original.

- [ ] **Step 6: 实现队列 Worker**

`workbook_index` lists Sheets and soft-deletes disappeared IDs. `sheet_snapshot` revalidates whitelist + live Sheet ID, fetches metadata, derives the exact used range, chunks it, stores immutable JSON, and marks the request success with `snapshot_id`. Use bounded retries; 401/403 becomes failed immediately with an exact error code.

Start a 5-second polling worker from `src/index.ts`, stop it in graceful shutdown, and keep the existing cron jobs unchanged.

- [ ] **Step 7: 运行测试**

```bash
npm run test:run -- src/db/queries/packing-workbook.test.ts src/packing/snapshot-store.test.ts src/packing/refresh-worker.test.ts
npm run lint
npm run build
```

Expected: PASS.

- [ ] **Step 8: 提交服务端快照功能**

```bash
git add src/db/queries/packing-workbook.ts src/packing src/cli/sync-packing-workbooks.ts src/config/schema.ts src/index.ts package.json
git commit -m 'feat: cache whitelisted packing sheets'
```

## Task 5: 建立统一装箱网格和合并单元格解析器

**Files:**

- Create: `overseas_costing/services/packing_grid.py`
- Create: `overseas_costing/services/packing_parse_service.py`
- Create: `overseas_costing/tests/test_packing_grid.py`
- Modify: `overseas_costing/utils/excel_workbook.py`
- Modify: `overseas_costing/tests/test_excel_workbook.py`

- [ ] **Step 1: 写统一模型的失败测试**

Use `openpyxl` in `tmp_path` to build a 9-material workbook with merged package fields for rows `4:5`, `7:8`, and `9:10`. Assert:

```python
assert preview["material_row_count"] == 9
assert preview["package_count"] == 6
assert preview["totals"]["gross_weight_kg"]["value"] == "4197.4"
assert preview["totals"]["volume_m3"]["value"] == "8.7403305"
assert preview["totals"]["net_weight_kg"]["kind"] == "calculated_detail_sum"
assert preview["totals"]["net_weight_kg"]["value"] == "3492"
assert preview["groups"][2]["row_numbers"] == [4, 5]
assert preview["groups"][2]["gross_weight_kg"]["count_once"] is True
```

Add cases for:

- exact Sheet selection and an unknown Sheet raising `PackingSheetNotFound` instead of silently falling back;
- raw `8.7403305` winning over currency-formatted `¥8.74`;
- a date serial staying separate from the Sheet-name date;
- nonstandard/numeric-only material codes remaining unmatched candidates;
- columns after a second label header (for example AZ onward) not becoming duplicate materials;
- a genuine unmerged blank remaining missing;
- conflicting merge ranges across gross weight and volume requiring confirmation;
- formulas with no cached value reported as unresolved rather than evaluated.

- [ ] **Step 2: 运行测试并确认失败**

```bash
python -m pytest -q overseas_costing/tests/test_packing_grid.py overseas_costing/tests/test_excel_workbook.py
```

Expected: FAIL on missing model, merge preservation and strict Sheet selection.

- [ ] **Step 3: 实现来源无关的网格结构**

Use immutable dictionaries/dataclasses representing:

```python
Cell(raw_value, display_value, formula, row, column)
MergeRange(start_row, end_row, start_column, end_column, evidence_kind)
MaterialLine(source_row, material_code, quantity, unit, raw_fields)
PackageGroup(group_id, row_numbers, dimensions, net_weight, gross_weight, volume, package_count, evidence, needs_confirmation)
PackingTotals(value, unit, kind, source_range, precision)
```

Use `Decimal(str(value))`; preserve `None` separately from `Decimal('0')`.

- [ ] **Step 4: 让上传文件返回实际 merge ranges**

Add a strict reader to `excel_workbook.py`:

```python
def read_packing_grid(file_path: str, *, sheet_name: str | None, require_exact_sheet: bool) -> dict:
    ...
```

Collect `worksheet.merged_cells.ranges` from the original workbook. Keep `parse_yuewei_excel_workbook` behavior for legacy callers, but the new flow always passes `require_exact_sheet=True` after the user chooses a Sheet.

- [ ] **Step 5: 实现包装组证据规则**

- For XLSX, only explicit merge ranges in package-level columns can create confirmed shared values.
- Description/name merges never prove co-packing.
- Different physical fields with incompatible merge spans produce candidate groups with `needs_confirmation=True`.
- For DingTalk grid snapshots, `mergeRangesAvailable=false` means blanks may generate suggestions but never confirmed merges. Store suggestion reasons and require explicit link/split resolutions.
- Count shared gross weight/volume/net weight once per confirmed group and never divide them among material rows.
- Prefer an identified source total row; never use the last numeric row after the table.

- [ ] **Step 6: 运行测试**

```bash
python -m pytest -q overseas_costing/tests/test_packing_grid.py overseas_costing/tests/test_excel_workbook.py overseas_costing/tests/test_import_service.py overseas_costing/tests/test_packing_source_service.py
```

Expected: PASS, including all legacy attachment/comment behavior.

- [ ] **Step 7: 提交统一解析器**

```bash
git add overseas_costing/services/packing_grid.py overseas_costing/services/packing_parse_service.py overseas_costing/utils/excel_workbook.py overseas_costing/tests/test_packing_grid.py overseas_costing/tests/test_excel_workbook.py
git commit -m 'feat: parse grouped packing data without double counting'
```

## Task 6: 新增装箱快照和运费试算 DocType

**Files:**

- Create: `overseas_costing/doctype/overseas_packing_snapshot/__init__.py`
- Create: `overseas_costing/doctype/overseas_packing_snapshot/overseas_packing_snapshot.py`
- Create: `overseas_costing/doctype/overseas_packing_snapshot/overseas_packing_snapshot.json`
- Create: `overseas_costing/doctype/overseas_freight_comparison/__init__.py`
- Create: `overseas_costing/doctype/overseas_freight_comparison/overseas_freight_comparison.py`
- Create: `overseas_costing/doctype/overseas_freight_comparison/overseas_freight_comparison.json`
- Modify: `overseas_costing/doctype/overseas_cost_audit_log/overseas_cost_audit_log.json`
- Create: `overseas_costing/tests/test_packing_doctypes.py`

- [ ] **Step 1: 写 DocType 元数据失败测试**

Assert exact required fields and permissions. Snapshot fields:

```text
batch, version, idempotency_key(unique), source_kind, source_id,
source_revision, source_label, source_locator_json, source_read_at,
source_updated_at, source_hash, status, is_current,
material_row_count, package_count, total_net_weight_kg,
net_total_kind, total_gross_weight_kg, total_volume_m3,
material_rows_json, package_groups_json, totals_json,
validation_json, resolutions_json, confirmed_by, confirmed_at
```

Comparison fields:

```text
batch, packing_snapshot, request_id(unique), snapshot_revision,
currency, scope_confirmed, gross_weight_kg, volume_m3,
weight_unit_price, weight_min_quantity, weight_rounding_increment,
weight_min_base_freight, weight_surcharge, weight_total,
volume_unit_price, volume_min_quantity, volume_rounding_increment,
volume_min_base_freight, volume_surcharge, volume_total,
recommended_basis, difference_amount, savings_percent,
input_json, calculation_json, quote_remark
```

Cost users can create/read snapshots and comparisons but cannot delete or amend a confirmed record. Add audit action options `PACKING_CONFIRM` and `FREIGHT_COMPARE`.

- [ ] **Step 2: 运行并确认失败**

```bash
python -m pytest -q overseas_costing/tests/test_packing_doctypes.py
```

- [ ] **Step 3: 创建 DocTypes and validation hooks**

Use `autoname: hash`, `track_changes: 1`; mark JSON/source fields `permlevel: 1` and read-only where appropriate. `validate()` must reject mutation of a confirmed snapshot/comparison except the snapshot service's controlled supersede operation.

- [ ] **Step 4: 运行测试并提交**

```bash
python -m pytest -q overseas_costing/tests/test_packing_doctypes.py
git add overseas_costing/doctype/overseas_packing_snapshot overseas_costing/doctype/overseas_freight_comparison overseas_costing/doctype/overseas_cost_audit_log/overseas_cost_audit_log.json overseas_costing/tests/test_packing_doctypes.py
git commit -m 'feat: persist packing snapshots and freight comparisons'
```

## Task 7: 接入 PostgreSQL 列表、受限刷新提交和 MinIO 快照读取

**Files:**

- Create: `overseas_costing/integrations/dingtalk_packing_source.py`
- Create: `overseas_costing/tests/test_dingtalk_packing_source.py`
- Modify: `overseas_costing/integrations/dingtalk_approval_source.py`

- [ ] **Step 1: 写失败测试**

Cover:

```python
def test_reader_lists_only_enabled_workbooks_and_live_sheets(): ...
def test_refresh_submitter_uses_a_separate_connection_without_read_grants(): ...
def test_refresh_request_key_is_sha256_and_idempotent(): ...
def test_snapshot_download_verifies_size_and_sha256(): ...
def test_snapshot_status_must_be_ready(): ...
def test_browser_cannot_supply_an_arbitrary_workbook_url(): ...
```

Assert the read connection retains `default_transaction_read_only=on`; the submit connection calls only the named function and cannot issue arbitrary SQL through public methods.

- [ ] **Step 2: 运行并确认失败**

```bash
python -m pytest -q overseas_costing/tests/test_dingtalk_packing_source.py
```

- [ ] **Step 3: 实现两个最小客户端**

`PackingSheetCatalog` reuses `ApprovalSourceConfig` and queries only the four packing views. `PackingRefreshSubmitter` exposes only:

```python
request_workbook_index_refresh(workbook_id, request_key, requested_by)
request_sheet_refresh(workbook_id, sheet_id, request_key, requested_by)
```

No generic `execute()` method is public. `PackingSnapshotArchive.download()` reuses MinIO integrity logic but uses the configured `dingtalk-packing-snapshots` bucket and parses only schema version 1 JSON.

- [ ] **Step 4: 加入运行配置读取**

Use existing OA host/port/database values for both PostgreSQL clients. Add server-only site config keys:

```text
overseas_costing_packing_refresh_db_user
overseas_costing_packing_refresh_db_password
overseas_costing_packing_snapshot_bucket
```

The reader continues using `costing_reader`; the submitter uses `costing_job_submitter`. Never return either credential to API responses.

- [ ] **Step 5: 运行并提交**

```bash
python -m pytest -q overseas_costing/tests/test_dingtalk_packing_source.py overseas_costing/tests/test_dingtalk_postgres_source.py
git add overseas_costing/integrations/dingtalk_packing_source.py overseas_costing/integrations/dingtalk_approval_source.py overseas_costing/tests/test_dingtalk_packing_source.py
git commit -m 'feat: read and refresh cached DingTalk packing sheets'
```

## Task 8: 实现四来源预览、版本确认和当前快照

**Files:**

- Create: `overseas_costing/services/packing_snapshot_service.py`
- Create: `overseas_costing/tests/test_packing_snapshot_service.py`
- Modify: `overseas_costing/services/packing_source_service.py`
- Modify: `overseas_costing/tests/test_packing_source_service.py`

- [ ] **Step 1: 写失败测试**

Cover source aliases and trust boundaries:

```text
manual_attachment      -> stored Frappe File, exact selected Sheet
approval_attachment    -> existing archived attachment, no direct DingTalk fallback
approval_comment       -> re-read trusted server comment and verify its hash
wiki_sheet             -> whitelist view + verified MinIO snapshot
```

Add tests that:

- rejected/revoked/terminated approval sources remain excluded;
- changing the source hash makes the preview revision stale;
- browser-supplied comment text, workbook URL, totals or group metrics are ignored;
- unconfirmed grouping blocks confirmation;
- confirmation uses a batch row lock, supersedes the old current snapshot, and is idempotent for the same `(batch, source_revision)`;
- confirming a snapshot does not modify `Overseas Cost Item`, the expense pool, `Overseas Cost Version`, batch calculation status or ERP state.

- [ ] **Step 2: 运行并确认失败**

```bash
python -m pytest -q overseas_costing/tests/test_packing_snapshot_service.py overseas_costing/tests/test_packing_source_service.py
```

- [ ] **Step 3: 扩展来源解析而不破坏兼容入口**

Keep the existing signed revision mechanism and legacy `preview_packing_source`/`apply_packing_source`. Add normalized source aliases and a new preview result:

```python
{
  "ok": True,
  "source_kind": "wiki_sheet",
  "source_revision": "signed-token",
  "source": {...},
  "material_rows": [...],
  "package_groups": [...],
  "totals": {...},
  "validation": {
    "blocking": [...], "warnings": [...], "needs_group_confirmation": True
  }
}
```

For the knowledge-base source, merge suggestions are unresolved until `resolutions_json` explicitly links/splits rows. For uploaded XLSX, actual merge evidence may auto-confirm nonconflicting groups.

- [ ] **Step 4: 实现确认事务**

`confirm_packing_snapshot(batch_name, source_revision, resolutions_json)` must:

1. check batch read/write permission;
2. lock the batch row;
3. re-resolve the trusted source and recompute its hash;
4. apply only validated group/total resolutions;
5. reject missing gross weight or volume for freight comparison;
6. insert one immutable snapshot or return the existing idempotent record;
7. set prior current snapshot `Superseded`/`is_current=0`;
8. write a `PACKING_CONFIRM` audit row;
9. commit without calling any recalculate/writeback method.

- [ ] **Step 5: 运行回归并提交**

```bash
python -m pytest -q overseas_costing/tests/test_packing_snapshot_service.py overseas_costing/tests/test_packing_source_service.py overseas_costing/tests/test_import_service.py overseas_costing/tests/test_dingtalk_approval_service.py
git add overseas_costing/services/packing_snapshot_service.py overseas_costing/services/packing_source_service.py overseas_costing/tests/test_packing_snapshot_service.py overseas_costing/tests/test_packing_source_service.py
git commit -m 'feat: confirm immutable packing source snapshots'
```

## Task 9: 实现独立整票运费比较计算与历史

**Files:**

- Create: `overseas_costing/services/freight_comparison_service.py`
- Create: `overseas_costing/tests/test_freight_comparison_service.py`

- [ ] **Step 1: 写公式和“不改正式成本”的失败测试**

Use concrete cases:

```python
result = compare_freight(
    gross_weight_kg="4197.4",
    volume_m3="8.7403305",
    currency="USD",
    scope_confirmed=True,
    weight={"unit_price":"1.2", "min_quantity":"4200", "rounding_increment":"10", "min_base_freight":"5000", "surcharge":"100"},
    volume={"unit_price":"560", "min_quantity":"0", "rounding_increment":"0.1", "min_base_freight":"0", "surcharge":"80"},
)
```

Assert ceiling increments, minimum base freight before surcharge, exact decimal process values, display rounding, cheaper/equal outcomes, difference and `difference / higher_total * 100` savings. Also test:

- absent vs explicit zero;
- negative/NaN/infinite values rejected;
- same common currency required;
- `scope_confirmed=False` returns both totals but no recommendation;
- retrying the same `request_id` returns the same saved row;
- saving leaves expense, item, version, batch status and writeback records byte-for-byte unchanged;
- an old comparison remains readable and is marked `based_on_superseded_snapshot` when a newer snapshot becomes current.

- [ ] **Step 2: 运行并确认失败**

```bash
python -m pytest -q overseas_costing/tests/test_freight_comparison_service.py
```

- [ ] **Step 3: 实现纯 Decimal 计算**

Core helper:

```python
def ceil_to_increment(quantity: Decimal, increment: Decimal | None) -> Decimal:
    if increment in (None, Decimal("0")):
        return quantity
    return (quantity / increment).to_integral_value(rounding=ROUND_CEILING) * increment
```

For each basis:

```text
chargeable = ceil_to_increment(max(actual, minimum_quantity), increment)
base = max(chargeable * unit_price, minimum_base_freight)
total = base + surcharge
```

Keep unrounded decimal strings in `calculation_json`; only format amounts by currency precision for presentation. Do not introduce a kg/m³ conversion factor.

- [ ] **Step 4: 实现保存和审计**

Require an already confirmed snapshot and its exact revision. Create a unique `request_id` record under a transaction and audit as `FREIGHT_COMPARE`. Do not call `calculate_service`, `allocation_service`, `import_service._mark_batch_dirty`, ERP preview, or ERP writeback.

- [ ] **Step 5: 运行并提交**

```bash
python -m pytest -q overseas_costing/tests/test_freight_comparison_service.py
git add overseas_costing/services/freight_comparison_service.py overseas_costing/tests/test_freight_comparison_service.py
git commit -m 'feat: compare shipment freight by weight and volume'
```

## Task 10: 暴露最小权限 Frappe API

**Files:**

- Create: `overseas_costing/api/packing_api.py`
- Create: `overseas_costing/tests/test_packing_api.py`
- Modify: `overseas_costing/services/access_control.py`

- [ ] **Step 1: 写 API 权限和响应白名单失败测试**

Endpoints:

```python
list_packing_sources(batch_name)
request_packing_workbook_refresh(batch_name, workbook_id, request_id)
request_packing_sheet_refresh(batch_name, workbook_id, sheet_id, request_id)
get_packing_refresh_status(batch_name, request_id)
preview_packing_source_v2(batch_name, source_kind, source_id, sheet_name=None)
confirm_packing_snapshot(batch_name, source_revision, resolutions_json)
get_current_packing_snapshot(batch_name)
preview_freight_comparison(batch_name, snapshot_revision, quote_json)
save_freight_comparison(batch_name, snapshot_revision, request_id, quote_json)
list_freight_comparisons(batch_name)
```

Test batch-level permission for every endpoint, role-based write permission for refresh/confirm/save, input length limits, valid 64-hex request IDs, JSON size caps, and output field allowlists. A user with no batch read permission receives no source existence clues.

- [ ] **Step 2: 运行并确认失败**

```bash
python -m pytest -q overseas_costing/tests/test_packing_api.py overseas_costing/tests/test_access_control.py
```

- [ ] **Step 3: 实现薄 API 层**

API functions validate/authorize and delegate; they do not parse spreadsheets or calculate themselves. `list_packing_sources` returns three source groups and marks unavailable reasons, never credentials, object presigned URLs, raw approval payloads, or arbitrary workbook URLs.

- [ ] **Step 4: 运行并提交**

```bash
python -m pytest -q overseas_costing/tests/test_packing_api.py overseas_costing/tests/test_access_control.py
git add overseas_costing/api/packing_api.py overseas_costing/services/access_control.py overseas_costing/tests/test_packing_api.py overseas_costing/tests/test_access_control.py
git commit -m 'feat: expose secure packing and freight APIs'
```

## Task 11: 添加可重复的工作台资源生成器

**Files:**

- Create: `overseas_costing/scripts/build_workbench_assets.py`
- Create: `overseas_costing/tests/test_workbench_asset_builder.py`

- [ ] **Step 1: 写失败测试**

Assert the builder:

- concatenates JS parts in lexical order;
- concatenates CSS parts in lexical order;
- writes both source and deployed package copies;
- produces identical output on a second run;
- never includes `.superpowers` or temporary files.

- [ ] **Step 2: 运行并确认失败**

```bash
python -m pytest -q overseas_costing/tests/test_workbench_asset_builder.py
```

- [ ] **Step 3: 实现生成器并重建无变化基线**

Inputs:

```text
overseas_costing/page/overseas_cost_workbench/parts/*.js
overseas_costing/page/overseas_cost_workbench/parts/*.css
```

Outputs:

```text
overseas_costing/page/overseas_cost_workbench/overseas_cost_workbench.{js,css}
overseas_costing/overseas_costing/page/overseas_cost_workbench/overseas_cost_workbench.{js,css}
```

Use normalized UTF-8 and one newline between parts. Run:

```bash
python overseas_costing/scripts/build_workbench_assets.py
git diff --exit-code -- overseas_costing/page/overseas_cost_workbench/overseas_cost_workbench.js overseas_costing/page/overseas_cost_workbench/overseas_cost_workbench.css overseas_costing/overseas_costing/page/overseas_cost_workbench/overseas_cost_workbench.js overseas_costing/overseas_costing/page/overseas_cost_workbench/overseas_cost_workbench.css
```

Expected: no diff before new UI parts are added.

- [ ] **Step 4: 提交生成器**

```bash
git add overseas_costing/scripts/build_workbench_assets.py overseas_costing/tests/test_workbench_asset_builder.py
git commit -m 'build: generate workbench assets from ordered parts'
```

## Task 12: 实现三步弹窗前端

**Files:**

- Create: `overseas_costing/page/overseas_cost_workbench/parts/86-packing-flow.js`
- Create: `overseas_costing/page/overseas_cost_workbench/parts/47-packing-flow.css`
- Modify: `overseas_costing/page/overseas_cost_workbench/parts/65-manual-documents.js`
- Modify: `overseas_costing/page/overseas_cost_workbench/parts/84-dingtalk-approval.js`
- Modify: `overseas_costing/tests/test_workbench_frontend_state.py`
- Modify generated files via `overseas_costing/scripts/build_workbench_assets.py`

- [ ] **Step 1: 写纯状态和静态 UI 失败测试**

Extend the UMD state helper or add a UMD block in `86-packing-flow.js` so Node can test:

```js
createPackingFlowState()
selectPackingSource(state, sourceKind, sourceId)
applyPackingPreview(state, preview)
resolvePackageGroup(state, groupId, action)
buildFreightQuotePayload(state, fields)
```

Assert source switching clears unconfirmed preview, unresolved groups disable Step 3, a stale refresh replaces the preview rather than merging it, and the quote payload contains no formal cost/allocation action.

Static assertions must find these labels:

```text
本地上传
钉钉审批附件/评论
知识库年度表
刷新列表
刷新资料
共享箱级数据
保存草稿
下一步：比较运费
独立试算，不修改正式费用
保存比较结果
```

- [ ] **Step 2: 运行并确认失败**

```bash
python -m pytest -q overseas_costing/tests/test_workbench_frontend_state.py
```

- [ ] **Step 3: Step 1—来源选择**

The existing 装箱单 card gets one primary action `获取装箱单`. Open a large three-step dialog:

1. Local upload: choose file then exact Sheet when more than one exists.
2. DingTalk approval: reuse archived form attachments, comment attachments and trusted pure comments.
3. Knowledge base: year/workbook list, searchable Sheet list, source update time, cached state, `刷新列表` and `刷新资料` queue status.

The browser submits only server-issued `source_kind/source_id`; it cannot enter a URL or node ID. When refreshing, disable duplicate clicks for the same request ID and poll with bounded intervals until success/failure.

- [ ] **Step 4: Step 2—分组预览和确认**

Desktop layout:

- central grouped table with one material per row;
- package group values shown once with a visual rowspan-like block and `共享箱级数据` badge;
- right summary for material count, package count, declared/calculated totals, differences and blockers;
- unresolved candidate groups expose `关联到上一包装组`, `拆分为独立包装组`, and explicit row selection;
- the oil sample renders 9 material rows and 6 package groups;
- mobile layout uses package cards.

Allow `保存草稿`; enable `下一步：比较运费` only after all blocking grouping/total decisions are resolved and gross weight + volume are trustworthy.

- [ ] **Step 5: Step 3—报价输入和结果**

Left side:

- read-only confirmed gross weight and volume;
- required weight price, volume price and one common currency;
- separate surcharge inputs;
- collapsed advanced fields for minimum quantities, increments and minimum base freight;
- required same-scope confirmation and quote note.

Right side:

- two calculation traces;
- recommended cheaper basis only after same-scope confirmation;
- difference and savings percent;
- equal/incomplete states;
- one primary button `保存比较结果`, no `采用方案` action.

After save, update the packing card with latest comparison and a history link, while keeping the warning `独立试算，不修改正式费用`.

- [ ] **Step 6: 保留兼容入口**

Existing `从钉钉获取` and `作为装箱单使用` buttons open the new dialog with the relevant source preselected. Legacy `preview_packing_list_attachment` and `apply_packing_list_fillable_fields` remain callable; no existing approval preview/download behavior is removed.

- [ ] **Step 7: 生成、检查并测试**

```bash
python overseas_costing/scripts/build_workbench_assets.py
node --check overseas_costing/page/overseas_cost_workbench/overseas_cost_workbench.js
node --check overseas_costing/overseas_costing/page/overseas_cost_workbench/overseas_cost_workbench.js
python -m pytest -q overseas_costing/tests/test_workbench_frontend_state.py overseas_costing/tests/test_workbench_asset_builder.py
```

Expected: PASS and both generated copies are identical.

- [ ] **Step 8: 提交前端**

```bash
git add overseas_costing/page/overseas_cost_workbench/parts/86-packing-flow.js overseas_costing/page/overseas_cost_workbench/parts/47-packing-flow.css overseas_costing/page/overseas_cost_workbench/parts/65-manual-documents.js overseas_costing/page/overseas_cost_workbench/parts/84-dingtalk-approval.js overseas_costing/page/overseas_cost_workbench/overseas_cost_workbench.js overseas_costing/page/overseas_cost_workbench/overseas_cost_workbench.css overseas_costing/overseas_costing/page/overseas_cost_workbench/overseas_cost_workbench.js overseas_costing/overseas_costing/page/overseas_cost_workbench/overseas_cost_workbench.css overseas_costing/tests/test_workbench_frontend_state.py
git commit -m 'feat: add three-step packing and freight workflow'
```

## Task 13: 跨服务集成、安全和真实样本回归

**Files:**

- Create: `overseas_costing/tests/test_packing_workflow_integration.py`
- Modify: `.github/scripts/sync_and_verify_assets.sh`
- Modify in dingtalk repo: `src/packing/refresh-worker.test.ts`

- [ ] **Step 1: 写端到端契约测试**

Use fakes at the external boundaries but real service transformations. The test sequence is:

```text
whitelisted workbook -> sheet index -> queued refresh -> MinIO JSON snapshot
-> Frappe verified download -> grid parse -> user group resolutions
-> confirmed snapshot -> quote preview -> saved comparison -> history
```

Assert:

- no Vultr-side test calls a DingTalk hostname;
- no rejected/revoked/terminated approval enters a source list;
- oil sample: 9 materials, 6 confirmed groups after resolution, gross `4197.4`, volume `8.7403305`, net detail sum `3492`;
- 8.15 sample: 24 rows, 368 packages, gross `25360.08`, volume `55.33429`;
- refresh changes the content hash and invalidates an unconfirmed revision;
- old confirmed snapshot and comparison remain immutable/history-readable;
- all formal batch costs and allocations are unchanged.

- [ ] **Step 2: 运行所有本地测试**

```bash
cd '/Users/smk/Documents/ChatGPT/综合成本计算系统'
python -m pytest -q overseas_costing/tests
python -m compileall -q overseas_costing
node --check overseas_costing/page/overseas_cost_workbench/overseas_cost_workbench.js
git diff --check
```

Expected: PASS.

- [ ] **Step 3: 运行所有钉钉服务测试**

```bash
cd '/Users/smk/Documents/ChatGPT/dingtalk-oa'
npm run test:run
npm run lint
npm run build
git diff --check
```

Expected: PASS.

- [ ] **Step 4: 扩展部署后 smoke check**

Update `.github/scripts/sync_and_verify_assets.sh` to verify:

- `overseas_costing.api.packing_api` imports;
- both new DocTypes exist after migrate;
- generated page contains `openPackingFlowDialog` and the independent-simulation warning;
- the PostgreSQL reader can select the four packing views;
- the submitter role can call only the two refresh functions;
- the snapshot bucket is reachable read-only.

- [ ] **Step 5: 提交集成检查**

```bash
cd '/Users/smk/Documents/ChatGPT/综合成本计算系统'
git add overseas_costing/tests/test_packing_workflow_integration.py .github/scripts/sync_and_verify_assets.sh
git commit -m 'test: cover packing workflow end to end'
```

## Task 14: 分阶段部署和人工验收

**Files:**

- Server-only: `/www/wwwroot/dingtalk-oa/.env`
- Server-only: Frappe `site_config.json`
- Server-only: PostgreSQL roles/policies and MinIO bucket policy

- [ ] **Step 1: 先备份，不触碰现有密钥文件**

Create timestamped database dumps and export MinIO policy/config. Do not remove or rotate the temporary SSH keys or existing `.env` backups per the user's explicit instruction.

- [ ] **Step 2: 创建最小权限运行身份**

Create:

- private bucket `dingtalk-packing-snapshots` with versioning enabled;
- archive service write policy limited to that bucket;
- existing Vultr MinIO reader extended with read-only access to that bucket;
- PostgreSQL login `costing_job_submitter` with no schema/table privileges and EXECUTE only on the two refresh functions.

Keep PostgreSQL 5432 and MinIO 9000 private on WireGuard; no new public port is required.

- [ ] **Step 3: 配置阿里云同步服务**

Set, without printing values to logs:

把当前服务端已经验证成功的操作身份 userId 写入 `DINGTALK_PACKING_READER_USER_ID`；该值只在服务器 `.env` 中复制，不写入计划、Git 或日志。其余非密钥配置为：

```text
DINGTALK_PACKING_WORKBOOKS_JSON=[{"year":2026,"workbookId":"KGZLxjv9VG341rm7txY5p9amV6EDybno","label":"2026海运待出货装箱计划"}]
PACKING_SNAPSHOT_MINIO_BUCKET=dingtalk-packing-snapshots
PACKING_REFRESH_POLL_MS=5000
PACKING_RANGE_MAX_CELLS=5000
PACKING_SHEET_MAX_ROWS=5000
PACKING_SHEET_MAX_COLUMNS=100
```

Run migration, whitelist sync, tests/build, then restart the service. Confirm the existing approval/archive workers remain healthy.

- [ ] **Step 4: 配置 Frappe**

Add the submitter username/password and snapshot bucket to `site_config.json`; reuse existing OA PostgreSQL host/database and MinIO endpoint/access pair. Run `bench migrate`, build assets, clear site/website cache, and restart workers/scheduler/frontend.

- [ ] **Step 5: 影子验收两个真实 Sheet**

Without saving a formal comparison, refresh and preview:

- `st-d624e02f-88561`: confirm 25-sheet catalog, 9 material rows, 6 groups after user resolution, 4197.4 kg and 8.7403305 m³.
- `st-762f7f76-4525`: confirm 24 rows, 368 packages, 25360.08 kg and 55.33429 m³.

Verify personal DingTalk is logged out in the browser; server refresh must still succeed because the app/operator identity is server-side.

- [ ] **Step 6: 真实批次完整验收**

For one authorized batch:

1. preview each available source type;
2. confirm one knowledge-base Sheet;
3. enter two same-currency shipment quotes including at least one minimum/increment rule;
4. save comparison;
5. reopen history and verify the trace;
6. compare formal expense pool, SKU allocation, batch status and ERP state before/after—they must be unchanged.

- [ ] **Step 7: 故障和权限验收**

Verify exact UI messages for permission loss, deleted Sheet, stale snapshot, MinIO hash mismatch, queue failure and PostgreSQL outage. Verify `costing_reader` cannot call refresh functions, `costing_job_submitter` cannot select base tables, and neither credential can write arbitrary PostgreSQL rows.

- [ ] **Step 8: 完成发布记录**

Record the two repository commit SHAs, migration result, two sample hashes, API call counts, MinIO object keys, Frappe release time and rollback commands. Rollback switches the UI entry off and redeploys prior commits; it does not delete snapshots, comparisons, database tables or MinIO objects.

## 完成定义

- 本地上传、审批附件、评论附件/纯评论、知识库 Sheet 都进入同一预览与确认模型。
- 上传 XLSX 使用真实 merge ranges；钉钉知识库缺少 merge ranges 时只提出候选，未经用户确认不共享、不重复计重。
- 油漆样本稳定得到 9 条物料和 6 个确认包装组；两份真实样本总数与设计基线一致。
- 用户浏览器不登录个人钉钉时，阿里云服务仍可读取已授权工作簿。
- 每次报价在弹窗填写；按毛重和体积的整票计算过程、差额和节省比例可审计。
- 所有运费比较都是独立试算，不修改正式费用、分摊、批次核算状态或 ERP 数据。
- Vultr 不保存钉钉 App 密钥、不直调钉钉；PostgreSQL/MinIO 不开放公网。
- 两套仓库全量测试、类型检查、构建、迁移及真实批次人工验收均通过。
