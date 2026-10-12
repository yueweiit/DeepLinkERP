# ECOUNT Inventory Import Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Inventory import accept the ECOUNT material master workbook directly, including multi-row headers, ECOUNT material groups, unit normalization, default supplier/status/currency, and implementation documentation.

**Architecture:** Keep the feature inside the existing `MasterDataImportExportServiceImpl` import pipeline. Do not add new root objects or formal ERP integration tables; preserve ECOUNT source metadata in row values and append it to `remark` for the current schema.

**Tech Stack:** Java 17, Spring Boot, Apache POI, Vue 3 TypeScript, Markdown docs.

---

### Task 1: Regression Tests For ECOUNT Inventory Import

**Files:**
- Modify: `plm-server/src/test/java/com/yuewei/plm/module/importexport/service/impl/MasterDataImportExportServiceImplTest.java`

- [ ] **Step 1: Add failing tests**

Add tests that build an in-memory ECOUNT workbook with sheet `物料编码表`, row 2/3 composite headers, row 4 auxiliary status, and data from row 5. Assert that preview maps `新物料编码` to `inventory_code`, normalizes `个 PIEZA` to `个`, derives `YL 原料` to `material`, defaults status/currency/supplier, and appends ECOUNT metadata to remark. Add a second test for duplicate ECOUNT material codes.

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
plm-server\.codex_tmp\apache-maven-3.9.9\bin\mvn.cmd -f plm-server\pom.xml -Dtest=MasterDataImportExportServiceImplTest test
```

Expected locally if Java is available: the new tests fail before implementation. Current known environment may fail earlier with `JAVA_HOME environment variable is not defined correctly`.

### Task 2: Implement ECOUNT Workbook And CSV Parsing

**Files:**
- Modify: `plm-server/src/main/java/com/yuewei/plm/module/importexport/service/impl/MasterDataImportExportServiceImpl.java`

- [ ] **Step 1: Select source reader**

Dispatch `readRows` by file extension: `.csv` uses a CSV reader, all other files continue through Apache POI `.xlsx`.

- [ ] **Step 2: Detect ECOUNT headers**

For Excel, select sheet `物料编码表` when present; otherwise use the first sheet. Scan the first five rows for ECOUNT header tokens including `新物料编码` and `物料名称`. For ECOUNT headers, combine parent/child headers into keys such as `一级.大类编码` and `二级.名称`.

- [ ] **Step 3: Normalize inventory row values**

After row extraction, apply inventory-specific defaults and derivations: unit normalization, type derivation from ECOUNT major group, default `available`, default `CNY`, default supplier `默认供应商`, empty barcode normalization, and ECOUNT metadata remark append.

### Task 3: Frontend Type Compatibility

**Files:**
- Modify: `plm-web/src/api/modules/importExport.ts`

- [ ] **Step 1: Keep API backward-compatible**

Allow preview row status to include a future `warning` value without changing current UI behavior. Existing `ready` and `error` behavior remains.

### Task 4: Implementation Documentation

**Files:**
- Create: `docs/文件沉淀/2026-07-27-PLM-ECOUNT新物料编码总表导入规则代码实现沉淀.md`

- [ ] **Step 1: Document changed files**

List every modified file and why it changed.

- [ ] **Step 2: Document code and logic**

Explain multi-row header detection, field mapping, unit normalization, material group derivation, default values, and duplicate handling.

- [ ] **Step 3: Document benefits and maintenance**

Explain operational benefits and future maintenance suggestions, especially when Inventory fields are expanded later.

### Task 5: Verification

**Files:**
- Verify all changed files.

- [ ] **Step 1: Run focused backend tests**

Run the Maven test command from Task 1 and report the exact result.

- [ ] **Step 2: Run whitespace checks**

Run:

```powershell
git diff --check -- plm-server/src/main/java/com/yuewei/plm/module/importexport/service/impl/MasterDataImportExportServiceImpl.java plm-web/src/api/modules/importExport.ts
git diff --no-index --check -- NUL plm-server/src/test/java/com/yuewei/plm/module/importexport/service/impl/MasterDataImportExportServiceImplTest.java
```

- [ ] **Step 3: Summarize remaining risks**

Call out environment blockers, especially local `JAVA_HOME` if tests cannot execute.
