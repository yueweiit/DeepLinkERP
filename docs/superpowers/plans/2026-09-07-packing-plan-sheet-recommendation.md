# Packing Plan Sheet Recommendation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 默认展示“装箱计划表”，按最近到最远排列 Sheet，并基于当前批次、主国际物流审批、关联采购审批及已有快照给出可解释的 Sheet 推荐，同时让预览按钮在长列表中始终可见。

**Architecture:** 新增一个纯 Python 推荐模块，负责日期解析、候选评分、置信度和稳定排序；装箱来源服务一次取得批次物料及现有批量审批详情，并从 PostgreSQL 一次读取每个工作簿的最新快照清单，只解析已经缓存于 MinIO 的内容，不触发钉钉刷新。前端仅消费白名单推荐摘要，默认选中可靠推荐并通过粘性操作栏进入预览，绝不直接确认或写入。

**Tech Stack:** Python/Frappe、psycopg 3、MinIO SDK、现有装箱网格解析器、原生 JavaScript/CSS、pytest、Node.js 静态前端契约测试。

---

## 文件结构

- Create: `overseas_costing/services/packing_sheet_recommendation.py`：纯日期解析、快照摘要、评分、置信度和排序。
- Create: `overseas_costing/tests/test_packing_sheet_recommendation.py`：纯推荐逻辑测试。
- Modify: `overseas_costing/integrations/dingtalk_packing_source.py`：一次查询工作簿全部最新快照元数据。
- Modify: `overseas_costing/tests/test_dingtalk_packing_source.py`：验证批量快照查询及参数化 SQL。
- Modify: `overseas_costing/services/packing_snapshot_service.py`：收集批次/审批上下文、解析已有快照并装饰来源响应。
- Modify: `overseas_costing/tests/test_packing_snapshot_service.py`：验证批次来源推荐集成、故障隔离和无自动刷新。
- Modify: `overseas_costing/page/overseas_cost_workbench/parts/86-packing-flow.js`：默认 Tab、可见文案、推荐卡片、自动选中和明确预览按钮。
- Modify: `overseas_costing/page/overseas_cost_workbench/parts/47-packing-flow.css`：推荐提示及粘性底部操作栏。
- Modify: `overseas_costing/tests/test_workbench_frontend_state.py`：前端静态契约。
- Regenerate: `overseas_costing/page/overseas_cost_workbench/overseas_cost_workbench.js`、`overseas_costing/page/overseas_cost_workbench/overseas_cost_workbench.css` 及镜像页面资源，由现有构建脚本生成。

### Task 1: 实现纯 Sheet 日期解析、摘要和推荐评分

**Files:**

- Create: `overseas_costing/services/packing_sheet_recommendation.py`
- Create: `overseas_costing/tests/test_packing_sheet_recommendation.py`

- [ ] **Step 1: 写日期排序失败测试**

测试 `parse_sheet_business_date()` 支持 `2026.9.05`、`2026-08-28`、`8.15`、`5月9日`，无年份时使用工作簿年份，无法识别返回 `None`；测试 `sort_packing_sheets()` 把推荐项置顶，其余按日期降序，未知日期最后并以名称/ID 稳定排序。

- [ ] **Step 2: 运行测试并确认 RED**

Run:

```bash
python3 -m pytest -q overseas_costing/tests/test_packing_sheet_recommendation.py
```

Expected: FAIL because `packing_sheet_recommendation` does not exist.

- [ ] **Step 3: 实现最小日期解析和稳定排序**

公开接口固定为：

```python
def parse_sheet_business_date(sheet_name: str, workbook_year: int | str | None) -> date | None: ...

def sort_packing_sheets(sheets: list[dict[str, Any]]) -> list[dict[str, Any]]: ...
```

输出为复制后的字典，并增加 ISO `business_date`；不能修改调用方原列表。

- [ ] **Step 4: 运行聚焦测试并确认 GREEN**

Run the Task 1 command. Expected: PASS.

- [ ] **Step 5: 写快照摘要和评分失败测试**

测试 `summarize_packing_preview()` 从标准预览中提取去重后的物料编码；测试 `recommend_packing_sheets()`：

```python
batch = {
    "item_codes": ["FL000427", "FL000428", "FL000429", "FL000430", "FL003377"],
    "references": ["202609032107000062462"],
    "keywords": ["指环扣"],
}
summary = {
    "item_codes": ["FL000427", "FL000428", "FL000429", "FL000430", "FL003377", "CW000224"],
    "references": [],
}
```

要求 `指环扣-packing list2026.9.05` 为 `is_recommended=True`、`recommendation_confidence="high"`，理由包含“匹配当前批次 5/5 个 SKU”和“含 1 个批次外物料”；仅日期接近的候选只能为低置信，完全无正向证据不得推荐。

- [ ] **Step 6: 运行测试并确认评分逻辑缺失导致 RED**

Run the Task 1 command. Expected: FAIL on the new scoring assertions.

- [ ] **Step 7: 实现纯摘要和评分**

公开接口固定为：

```python
def summarize_packing_preview(preview: dict[str, Any]) -> dict[str, Any]: ...

def recommend_packing_sheets(
    sheets: list[dict[str, Any]],
    *,
    batch_context: dict[str, Any],
    snapshot_summaries: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]: ...
```

按设计使用 SKU 60 分、审批/订单引用 25 分、关键词 10 分、日期接近 5 分、额外物料最多扣 10 分；返回分数、置信度、理由、命中/缺少/额外编码和 `is_recommended`。只有最高候选具有正向业务证据时才置顶推荐。

- [ ] **Step 8: 运行 Task 1 测试并提交**

Expected: PASS.

```bash
git add overseas_costing/services/packing_sheet_recommendation.py overseas_costing/tests/test_packing_sheet_recommendation.py
git commit -m 'feat: score packing plan sheet recommendations'
```

### Task 2: 批量读取已有快照并接入批次/审批上下文

**Files:**

- Modify: `overseas_costing/integrations/dingtalk_packing_source.py`
- Modify: `overseas_costing/tests/test_dingtalk_packing_source.py`
- Modify: `overseas_costing/services/packing_snapshot_service.py`
- Modify: `overseas_costing/tests/test_packing_snapshot_service.py`

- [ ] **Step 1: 写批量快照查询失败测试**

新增 `PackingSheetCatalog.list_latest_snapshots(workbook_id)` 测试，断言只执行一次参数化查询：

```sql
SELECT ...
  FROM costing_read.packing_sheet_snapshots_v1
 WHERE workbook_id = %s AND is_latest = TRUE
 ORDER BY created_at DESC, id DESC
```

并验证非法工作簿 ID 被 `_validate_id()` 拒绝。

- [ ] **Step 2: 运行聚焦测试并确认 RED**

```bash
python3 -m pytest -q overseas_costing/tests/test_dingtalk_packing_source.py
```

Expected: FAIL because `list_latest_snapshots` is absent.

- [ ] **Step 3: 实现批量快照查询并确认 GREEN**

方法仅访问 `costing_read.packing_sheet_snapshots_v1`；不增加基础表权限，不连接钉钉。Run the Task 2 test command. Expected: PASS.

- [ ] **Step 4: 写来源集成失败测试**

在 `test_packing_snapshot_service.py` 用假 Frappe、假审批详情、假 catalog/archive 覆盖：

- 当前批次物料仅通过一次 `Overseas Cost Item` 列表查询取得。
- 复用已经取得的 `main_approval` 与 `linked_purchase_approvals`，排除 `excluded` 审批。
- 对一个工作簿只调用一次 `list_latest_snapshots()`；只下载 `ready` 的已有 MinIO 快照，不调用 `submitter`，也不调用刷新接口。
- 某个快照损坏时仅让该 Sheet 失去内容推荐证据，不让整个来源列表失败。
- 返回的 Sheet 包含设计中的推荐字段和真实批次的 5/5 匹配理由。

- [ ] **Step 5: 运行集成测试并确认 RED**

```bash
python3 -m pytest -q overseas_costing/tests/test_packing_snapshot_service.py
```

Expected: FAIL on missing recommendation fields.

- [ ] **Step 6: 实现上下文收集和推荐装饰**

在 `packing_snapshot_service.py` 增加私有辅助函数：

```python
def _packing_batch_context(batch_name: str, detail: dict[str, Any]) -> dict[str, Any]: ...
def _packing_snapshot_summaries(clients: Any, workbook_id: str) -> dict[str, dict[str, Any]]: ...
```

批次字段读取 `batch_no`、`waybill_no`、`source_approval_no`、`source_instance_id`、`project_collection`，物料读取 `material_code`、`product_name`、`source_doc_no`。审批引用从主审批与未排除关联审批的 `business_id`、`instance_id`、`title` 和 `form_fields` 提取。快照通过现有 `build_grid_from_dingtalk_snapshot()` 与 `parse_packing_grid()` 转为摘要；逐个快照异常被隔离。

`list_packing_sources()` 必须只调用一次 `get_batch_dingtalk_approval_detail()`，把同一 `detail` 同时用于评论来源和推荐上下文；返回旧的来源字段并增加推荐字段，不返回 MinIO 路径、对象键、原始快照或审批正文。

- [ ] **Step 7: 运行 Task 2 两组测试并提交**

```bash
python3 -m pytest -q overseas_costing/tests/test_dingtalk_packing_source.py overseas_costing/tests/test_packing_snapshot_service.py
git add overseas_costing/integrations/dingtalk_packing_source.py overseas_costing/services/packing_snapshot_service.py overseas_costing/tests/test_dingtalk_packing_source.py overseas_costing/tests/test_packing_snapshot_service.py
git commit -m 'feat: recommend cached packing plan sheets'
```

Expected: all selected tests PASS.

### Task 3: 修改来源首屏、推荐卡片和粘性预览操作栏

**Files:**

- Modify: `overseas_costing/page/overseas_cost_workbench/parts/86-packing-flow.js`
- Modify: `overseas_costing/page/overseas_cost_workbench/parts/47-packing-flow.css`
- Modify: `overseas_costing/tests/test_workbench_frontend_state.py`

- [ ] **Step 1: 写前端契约失败测试**

更新静态契约，要求：

- `dialog.packingSourceTab = options.sourceTab || "wiki"`。
- Tab 标签和顺序为“装箱计划表、钉钉审批附件/评论、本地上传”。
- 可见代码不再包含“知识库年度表”。
- 默认无草稿/显式来源时调用推荐自动选择逻辑；草稿或从审批入口打开时继续尊重显式来源。
- 推荐卡片显示“系统推荐”、置信度和 `recommendation_reasons`。
- 主按钮文案为“预览这张装箱计划”。
- CSS 含来源步骤的 flex/grid 高度约束及 `position: sticky` 的操作栏。

- [ ] **Step 2: 运行测试并确认 RED**

```bash
python3 -m pytest -q overseas_costing/tests/test_workbench_frontend_state.py::test_packing_flow_static_ui_contract
```

Expected: FAIL because the old default, order and wording remain.

- [ ] **Step 3: 实现默认选择和推荐展示**

在 `loadPackingFlowSources()` 中按优先级处理选择：显式 `options` → 有效本地草稿 → `is_recommended` Sheet。推荐自动选择仅更新 `packingFlowState`，不调用预览或确认 API。

把 `renderPackingWikiSources()` 拆出推荐元数据渲染辅助函数，显示：

```text
系统推荐 · 高置信度
匹配当前批次 5/5 个 SKU
含 1 个批次外物料，预览时确认
```

无推荐时显示“暂无可靠推荐，请手动选择”。日期使用后端 `business_date`，刷新状态优先使用 `snapshot_updated_at`，不能再把空 `source_updated_at` 一律显示成“待刷新”。

- [ ] **Step 4: 实现粘性操作栏和响应式样式**

来源步骤采用固定可滚动列表区域，`.ocw-packing-flow-footer` 在弹窗内容底部 `position: sticky; bottom: 0; z-index`，带不透明背景和上边框。移动端仍显示当前选择和主按钮，不遮住 Sheet 的“刷新资料”操作。

- [ ] **Step 5: 运行聚焦测试并确认 GREEN**

Run the Task 3 test command. Expected: PASS.

- [ ] **Step 6: 重新生成页面资源并检查无漂移**

```bash
python3 overseas_costing/scripts/build_workbench_assets.py
python3 overseas_costing/scripts/build_workbench_assets.py --check
```

Expected: build succeeds; `--check` reports generated assets are current.

- [ ] **Step 7: 提交前端变更**

```bash
git add overseas_costing/page/overseas_cost_workbench/parts/86-packing-flow.js overseas_costing/page/overseas_cost_workbench/parts/47-packing-flow.css overseas_costing/page/overseas_cost_workbench/overseas_cost_workbench.js overseas_costing/page/overseas_cost_workbench/overseas_cost_workbench.css overseas_costing/overseas_costing/page/overseas_cost_workbench/overseas_cost_workbench.js overseas_costing/overseas_costing/page/overseas_cost_workbench/overseas_cost_workbench.css overseas_costing/tests/test_workbench_frontend_state.py
git commit -m 'feat: prioritize recommended packing plan sheets'
```

### Task 4: 完整回归和真实数据只读验收

**Files:**

- Verify all files changed by Tasks 1—3.

- [ ] **Step 1: 运行装箱相关回归**

```bash
python3 -m pytest -q overseas_costing/tests/test_packing_sheet_recommendation.py overseas_costing/tests/test_dingtalk_packing_source.py overseas_costing/tests/test_packing_snapshot_service.py overseas_costing/tests/test_packing_grid.py overseas_costing/tests/test_packing_source_service.py overseas_costing/tests/test_packing_api.py overseas_costing/tests/test_packing_workflow_integration.py overseas_costing/tests/test_workbench_frontend_state.py
```

Expected: all selected tests PASS.

- [ ] **Step 2: 运行全量测试和语法检查**

```bash
python3 -m pytest -q overseas_costing/tests
python3 -m compileall -q overseas_costing
python3 overseas_costing/scripts/build_workbench_assets.py --check
git diff --check
```

Expected: all tests pass; compile/build/diff checks exit 0.

- [ ] **Step 3: 用生产配置执行只读推荐验收**

通过现有受控部署流程在站点后端调用 `list_packing_sources(batch_name="vunn2lvq4k")`，确认：

- 不提交任何刷新任务，钉钉 API 调用计数不增加。
- `指环扣-packing list2026.9.05` 为唯一推荐项。
- 置信度为高，理由包含 5/5 SKU 命中和 `CW000224` 额外物料。
- 返回列表中其余 Sheet 按业务日期由近到远。

- [ ] **Step 4: 检查工作树与提交历史**

```bash
git status --short
git log --oneline --max-count=5
```

Expected: 工作树干净；仅包含设计和本实施计划规定的提交，不含 `.env`、SSH 私钥、服务器备份或其他密钥。
