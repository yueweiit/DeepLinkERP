# AI 填充确认与 SKU 查询修复实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan.

**Goal:** 恢复可确认的 AI 物料填充，并消除 SKU 明细中虚拟装箱字段引起的 MySQL 查询错误。

**Architecture:** AI 预览先生成实际字段变更，再把未校验合并金额组限定到本次采用的货值来源。SKU 查询将持久化列和虚拟展示列分离，查询后再由现有元数据投影补全虚拟字段。

**Tech Stack:** Python, Frappe, MySQL/MariaDB, pytest.

---

### Task 1: 固化 AI 阻塞范围回归测试

**Files:**
- Modify: `overseas_costing/tests/test_ai_selection_service.py`

1. 将现有合并金额阻塞测试改为明确采用货值且来源/物料/工作表匹配。
2. 新增无关历史工作表不阻塞物理字段填充的测试。
3. 新增同物料但来源或工作表不同时不阻塞的测试。
4. 运行单文件，确认新测试在实现前失败。

### Task 2: 收窄合并金额阻塞逻辑

**Files:**
- Modify: `overseas_costing/services/material_ai_selection_service.py`

1. 增加纯函数，从投影变更中筛选所选货值变更，再与金额组的物料与来源定位信息求交。
2. `merged_amount_blocking` 仅反映相关未校验组，同时保留全部组作审计。
3. 运行 AI 选择服务测试并确认转绿。

### Task 3: 固化 SKU 虚拟字段查询回归测试

**Files:**
- Modify: `overseas_costing/tests/test_workbench_service.py`

1. 请求 `total`/`all` 列组，捕获传给 `frappe.get_all` 的字段。
2. 断言 SQL 查询不包含 `package_count` 和 `packaging_type`，但包含 `extra_json`。
3. 提供带 `ai_row_packing_values` 的元数据，断言响应仍显示箱数和包装类型。
4. 运行单测试，确认实现前失败。

### Task 4: 分离 SKU 持久化列与展示列

**Files:**
- Modify: `overseas_costing/services/workbench_service.py`

1. 声明 SKU 虚拟展示字段集合。
2. 查询字段排除虚拟字段并保证 `extra_json` 存在。
3. 继续用 `project_batch_items` 投影有效箱数和包装类型。
4. 运行工作台服务测试并确认转绿。

### Task 5: 受影响验证与部署

**Files:**
- Test: material AI selection, row review, valuation, workbench, batch/item query suites.

1. 运行与变更相关的 pytest 集合和影响选择器。
2. 运行 Python 编译检查与 `git diff --check`。
3. 复查差异，提交并推送功能分支和部署分支。
4. 等待生产部署工作流成功。
5. 线上只读验收 AI 预览和 SKU 明细，不执行数据确认。
