# 费用分摊、凭证关联与持续提醒 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把费用金额、适用范围、分摊、凭证和最终确认分开管理，让暂估已推送后仍能持续看见未完成费用，并在数据变化时准确重开待办。

**Architecture:** 扩展现有分摊规则为有稳定逻辑身份和金额状态的费用记录；用独立纯规则模块计算费用范围、分摊及待办，用凭证关联和费用完成记录保存证据及历史。前后端消费同一结构化状态，ERP 状态不负责关闭费用待办。

**Tech Stack:** Python 3、Decimal、Frappe DocType/API、pytest、原生 JavaScript/CSS、现有附件/审计/版本服务。

---

## 范围与依赖

执行本计划前完成 `2026-09-07-material-input-grid.md`，以使用稳定物料行、有效发货数量和字段缺项。多站点 ERP 状态在第三份计划实现；本阶段只输出 `cost_result_hash`、暂估/实际性质和费用待办，供后续同步消费。

本计划不自动发现从未提供的任意费用，不把上传文件直接当费用，也不联动 ERP 领用或领用后调账。

## 目标文件结构

- `overseas_costing/services/fee_allocation_service.py`：逐费用适用范围、Decimal 分摊和金额守恒。
- `overseas_costing/services/fee_status_service.py`：金额/分摊/暂估/凭证/重算待办及完成哈希。
- `overseas_costing/services/fee_service.py`：费用修改、证据关联、确认费用已齐和失效事务。
- `overseas_costing/api/fees.py`：列表、修改、关联凭证、确认和待办 API。
- `overseas_costing/doctype/overseas_cost_fee_evidence/*`：费用与附件的多对多证据关联。
- `overseas_costing/doctype/overseas_cost_fee_completion/*`：最终费用确认及失效历史。
- `overseas_costing/page/overseas_cost_workbench/parts/78-fee-worklist.js`：费用首区、待办与定位。
- `overseas_costing/page/overseas_cost_workbench/parts/49-fee-worklist.css`：费用状态、范围和提醒样式。

## Task 1: 扩展逻辑费用和历史记录模型

**Files:**

- Modify: `overseas_costing/doctype/overseas_cost_allocation_rule/overseas_cost_allocation_rule.json`
- Modify: `overseas_costing/overseas_costing/doctype/overseas_cost_allocation_rule/overseas_cost_allocation_rule.json`
- Modify: `overseas_costing/doctype/overseas_cost_version/overseas_cost_version.json`
- Modify: `overseas_costing/overseas_costing/doctype/overseas_cost_version/overseas_cost_version.json`
- Create: `overseas_costing/doctype/overseas_cost_fee_evidence/__init__.py`
- Create: `overseas_costing/doctype/overseas_cost_fee_evidence/overseas_cost_fee_evidence.py`
- Create: `overseas_costing/doctype/overseas_cost_fee_evidence/overseas_cost_fee_evidence.json`
- Create: `overseas_costing/overseas_costing/doctype/overseas_cost_fee_evidence/__init__.py`
- Create: `overseas_costing/overseas_costing/doctype/overseas_cost_fee_evidence/overseas_cost_fee_evidence.py`
- Create: `overseas_costing/overseas_costing/doctype/overseas_cost_fee_evidence/overseas_cost_fee_evidence.json`
- Create: `overseas_costing/doctype/overseas_cost_fee_completion/__init__.py`
- Create: `overseas_costing/doctype/overseas_cost_fee_completion/overseas_cost_fee_completion.py`
- Create: `overseas_costing/doctype/overseas_cost_fee_completion/overseas_cost_fee_completion.json`
- Create: `overseas_costing/overseas_costing/doctype/overseas_cost_fee_completion/__init__.py`
- Create: `overseas_costing/overseas_costing/doctype/overseas_cost_fee_completion/overseas_cost_fee_completion.py`
- Create: `overseas_costing/overseas_costing/doctype/overseas_cost_fee_completion/overseas_cost_fee_completion.json`
- Create: `overseas_costing/tests/test_fee_doctypes.py`

- [x] **Step 1: 写失败测试，锁定字段和镜像一致性**

```python
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _doctype(relative: str) -> dict:
    return json.loads((ROOT / relative).read_text(encoding="utf-8"))


def test_allocation_rule_has_explicit_fee_state_fields() -> None:
    doc = _doctype("doctype/overseas_cost_allocation_rule/overseas_cost_allocation_rule.json")
    fields = {row["fieldname"] for row in doc["fields"]}
    assert {
        "logical_fee_key", "amount_status", "scope_type", "scope_value_json",
        "scope_revision", "amount_revision", "required_evidence_role", "included_in_fee_key",
    } <= fields


def test_fee_doctype_mirrors_are_identical() -> None:
    for name in ("overseas_cost_fee_evidence", "overseas_cost_fee_completion"):
        assert _doctype(f"doctype/{name}/{name}.json") == _doctype(
            f"overseas_costing/doctype/{name}/{name}.json"
        )


def test_cost_version_persists_immutable_result_hash() -> None:
    doc = _doctype("doctype/overseas_cost_version/overseas_cost_version.json")
    fields = {row["fieldname"] for row in doc["fields"]}
    assert "cost_result_hash" in fields
```

- [x] **Step 2: 运行并确认失败**

Run: `python -m pytest -q overseas_costing/tests/test_fee_doctypes.py`

Expected: FAIL because the fields and DocTypes are absent.

- [x] **Step 3: 扩展分摊规则字段**

两份规则 JSON 增加：

```json
{
  "fieldname": "logical_fee_key",
  "fieldtype": "Data",
  "label": "逻辑费用标识",
  "reqd": 1
},
{
  "fieldname": "amount_status",
  "fieldtype": "Select",
  "label": "金额状态",
  "options": "MISSING\nESTIMATED\nACTUAL\nNOT_INCURRED\nINCLUDED",
  "default": "MISSING"
},
{
  "fieldname": "scope_type",
  "fieldtype": "Select",
  "label": "费用适用范围",
  "options": "ALL_ITEMS\nITEMS\nDIRECT_ITEM",
  "default": "ALL_ITEMS"
},
{
  "fieldname": "scope_value_json",
  "fieldtype": "Long Text",
  "label": "费用范围JSON"
},
{
  "fieldname": "scope_revision",
  "fieldtype": "Data",
  "label": "费用范围修订"
},
{
  "fieldname": "amount_revision",
  "fieldtype": "Data",
  "label": "金额修订"
},
{
  "fieldname": "required_evidence_role",
  "fieldtype": "Data",
  "label": "必需最终凭证角色"
},
{
  "fieldname": "included_in_fee_key",
  "fieldtype": "Data",
  "label": "已包含于费用"
}
```

两份成本版本 JSON 同步增加只读 Data 字段 `cost_result_hash`。

`logical_fee_key` 在同一批次业务中稳定，暂估转实际更新同一费用而非新增叠加。历史规则的金额为空时迁移为 `MISSING`；金额存在但没有可验证的最终凭证或费用完成记录时迁移为 `ESTIMATED`；只有有效最终凭证或完成记录能够证明时才标 `ACTUAL`，不得靠金额大小或旧状态名称猜测。

- [x] **Step 4: 创建证据和完成记录**

`Overseas Cost Fee Evidence` 至少包含 `batch`、`version`、`fee_rule`、`attachment`、`evidence_role`、`validation_status`（PENDING/VALID/INVALID/UNLINKED）、`source_revision`、`validated_by/at`、`remark`。

`Overseas Cost Fee Completion` 至少包含 `batch`、`version`、`input_hash`、`status`（CONFIRMED/INVALIDATED）、`confirmed_by/at`、`invalidated_by/at`、`invalidation_reason`。禁止覆盖原确认行。

- [x] **Step 5: 运行并提交**

Run: `python -m pytest -q overseas_costing/tests/test_fee_doctypes.py`

Expected: PASS.

```bash
git add overseas_costing/doctype/overseas_cost_allocation_rule overseas_costing/overseas_costing/doctype/overseas_cost_allocation_rule overseas_costing/doctype/overseas_cost_version overseas_costing/overseas_costing/doctype/overseas_cost_version overseas_costing/doctype/overseas_cost_fee_evidence overseas_costing/overseas_costing/doctype/overseas_cost_fee_evidence overseas_costing/doctype/overseas_cost_fee_completion overseas_costing/overseas_costing/doctype/overseas_cost_fee_completion overseas_costing/tests/test_fee_doctypes.py
git commit -m 'feat: model fee lifecycle and evidence'
```

## Task 2: 实现逐费用适用范围和金额守恒分摊

**Files:**

- Create: `overseas_costing/services/fee_allocation_service.py`
- Modify: `overseas_costing/services/calculate_service.py`
- Create: `overseas_costing/tests/test_fee_allocation_service.py`
- Modify: `overseas_costing/tests/test_calculate_service.py`

- [x] **Step 1: 写失败测试**

```python
def test_item_scoped_fee_excludes_unrelated_items() -> None:
    result = allocate_fee(
        fee={
            "logical_fee_key": "PRODUCTION-EXTRA",
            "amount": "90", "currency": "CNY", "amount_status": "ACTUAL",
            "scope_type": "ITEMS", "scope_item_keys": ["P1", "P2"],
            "allocation_basis": "goods_value",
        },
        items=[
            {"stable_line_key": "P1", "goods_value": "100"},
            {"stable_line_key": "P2", "goods_value": "200"},
            {"stable_line_key": "E1", "goods_value": "300"},
        ],
    )
    assert result["allocations"] == {"P1": "30.00", "P2": "60.00", "E1": "0.00"}
    assert result["allocated_total"] == "90.00"


def test_missing_basis_on_one_eligible_item_blocks_entire_fee() -> None:
    result = allocate_fee(
        fee={"amount": "100", "amount_status": "ACTUAL", "scope_type": "ITEMS",
             "scope_item_keys": ["P1", "P2"], "allocation_basis": "gross_weight"},
        items=[{"stable_line_key": "P1", "gross_weight_kg": 10},
               {"stable_line_key": "P2", "gross_weight_kg": ""}],
    )
    assert result["status"] == "BLOCKED"
    assert result["allocations"] == {}
```

- [x] **Step 2: 运行并确认失败**

Run: `python -m pytest -q overseas_costing/tests/test_fee_allocation_service.py overseas_costing/tests/test_calculate_service.py`

Expected: FAIL because current calculation builds one full-batch denominator for every rule.

- [x] **Step 3: 实现 Decimal 分摊器**

核心接口：

```python
import json
from decimal import Decimal, ROUND_DOWN


def _decimal(value) -> Decimal | None:
    if value in (None, ""):
        return None
    return Decimal(str(value))


def resolve_eligible_items(fee: dict, items: list[dict]) -> list[dict]:
    scope_type = fee.get("scope_type") or "ALL_ITEMS"
    keys = set(fee.get("scope_item_keys") or json.loads(fee.get("scope_value_json") or "[]"))
    if scope_type == "ALL_ITEMS":
        return list(items)
    if scope_type in {"ITEMS", "DIRECT_ITEM"}:
        return [row for row in items if row.get("stable_line_key") in keys]
    return []


def basis_decimal(item: dict, basis: str) -> Decimal | None:
    field = {
        "goods_value": "goods_value",
        "gross_weight": "gross_weight_kg",
        "volume": "volume_m3",
        "chargeable_weight": "chargeable_weight_kg",
    }[basis]
    return _decimal(item.get(field))


def _blocked(code: str) -> dict:
    return {"status": "BLOCKED", "code": code, "allocations": {}}


def allocate_with_stable_remainder(amount: Decimal, values: list[tuple[str, Decimal]], precision: int) -> dict:
    quantum = Decimal(1).scaleb(-precision)
    denominator = sum(value for _key, value in values)
    rows = []
    distributed = Decimal("0")
    for key, value in sorted(values):
        rounded = (amount * value / denominator).quantize(quantum, rounding=ROUND_DOWN)
        rows.append([key, rounded])
        distributed += rounded
    remainder_units = int((amount.quantize(quantum) - distributed) / quantum)
    for index in range(remainder_units):
        rows[index % len(rows)][1] += quantum
    allocations = {key: format(value, f".{precision}f") for key, value in rows}
    return {
        "status": "ALLOCATED",
        "allocations": allocations,
        "allocated_total": format(sum(value for _key, value in rows), f".{precision}f"),
    }


def allocate_fee(fee: dict, items: list[dict], *, currency_precision: int = 2) -> dict:
    eligible = resolve_eligible_items(fee, items)
    if not eligible:
        return _blocked("FEE_SCOPE_EMPTY")
    values = [(row["stable_line_key"], basis_decimal(row, fee["allocation_basis"])) for row in eligible]
    if any(value is None or value < 0 for _key, value in values):
        return _blocked("ALLOCATION_BASIS_INCOMPLETE")
    denominator = sum(value for _key, value in values)
    if denominator <= 0:
        return _blocked("ALLOCATION_DENOMINATOR_ZERO")
    return allocate_with_stable_remainder(
        Decimal(str(fee["amount"])), values, precision=currency_precision
    )
```

尾差按最小货币单位和 `stable_line_key` 稳定顺序分配。`MISSING/NOT_INCURRED/INCLUDED` 不进入费用池；`ESTIMATED/ACTUAL` 有效金额才计算。直接费用只允许一个物料行。

- [x] **Step 4: 替换 `calculate_item_rows()` 的全批规则循环**

先为每笔规则得到逐行分摊，再汇总到物料；`derived_json.allocated_rules` 保存 `logical_fee_key`、范围哈希、金额修订、分母和舍入结果。任何适用物料缺依据时整笔费用保持待分摊，不把金额只摊给数据齐的物料。

- [x] **Step 5: 运行并提交**

Run: `python -m pytest -q overseas_costing/tests/test_fee_allocation_service.py overseas_costing/tests/test_calculate_service.py`

Expected: PASS.

```bash
git add overseas_costing/services/fee_allocation_service.py overseas_costing/services/calculate_service.py overseas_costing/tests/test_fee_allocation_service.py overseas_costing/tests/test_calculate_service.py
git commit -m 'feat: allocate fees within explicit item scopes'
```

## Task 3: 建立独立费用待办状态机

**Files:**

- Create: `overseas_costing/services/fee_status_service.py`
- Modify: `overseas_costing/services/calculate_service.py`
- Create: `overseas_costing/tests/test_fee_status_service.py`
- Modify: `overseas_costing/tests/test_calculate_service.py`

- [x] **Step 1: 写失败测试，锁定并存待办和关闭条件**

```python
def test_estimated_allocated_fee_keeps_actual_and_evidence_todos() -> None:
    result = build_fee_status(
        fee={"logical_fee_key": "TAX", "amount": "1000", "currency": "MXN",
             "amount_status": "ESTIMATED", "required_evidence_role": "tax_certificate"},
        allocation={"status": "ALLOCATED", "amount": "1000", "allocated_total": "1000"},
        evidence=[],
        calculation={"input_hash": "H1", "fee_input_hash": "H1"},
    )
    assert {row["code"] for row in result["todos"]} == {
        "ACTUAL_AMOUNT_REQUIRED", "EVIDENCE_REQUIRED"
    }


def test_missing_amount_is_not_counted_as_zero_unallocated_money() -> None:
    result = summarize_fee_statuses([
        {
            "fee_key": "F1", "amount_state": "MISSING", "currency": "CNY", "amount": "",
            "todos": [{"code": "AMOUNT_REQUIRED"}],
        },
        {
            "fee_key": "F2", "amount_state": "ACTUAL", "currency": "CNY", "amount": "80",
            "todos": [{"code": "ALLOCATION_REQUIRED"}],
        },
    ])
    assert result["missing_amount_fee_count"] == 1
    assert result["unallocated_by_currency"] == {"CNY": "80"}
    assert result["affected_fee_count"] == 2


def test_invalidated_final_evidence_reopens_completion_without_forcing_recalc() -> None:
    result = build_fee_status(
        fee={
            "logical_fee_key": "TAX", "amount": "1000", "currency": "MXN",
            "amount_status": "ACTUAL", "required_evidence_role": "tax_certificate",
        },
        allocation={"status": "ALLOCATED", "amount": "1000", "allocated_total": "1000"},
        evidence=[{"evidence_role": "tax_certificate", "validation_status": "INVALID"}],
        calculation={"input_hash": "H1", "fee_input_hash": "H1"},
    )
    assert {t["code"] for t in result["todos"]} == {"EVIDENCE_REQUIRED", "ACTUAL_CONFIRMATION_INVALID"}
    assert "RECALCULATE_REQUIRED" not in {t["code"] for t in result["todos"]}
```

- [x] **Step 2: 运行并确认失败**

Run: `python -m pytest -q overseas_costing/tests/test_fee_status_service.py`

Expected: FAIL because `fee_status_service` is absent.

- [x] **Step 3: 实现状态输出和输入哈希**

每笔费用输出固定结构：

```python
{
  "fee_key": "TAX",
  "amount_state": "ESTIMATED",
  "allocation_state": "ALLOCATED",
  "evidence_state": "MISSING",
  "todos": [
    {"code": "ACTUAL_AMOUNT_REQUIRED", "severity": "warning", "action": "enter_actual"},
    {"code": "EVIDENCE_REQUIRED", "severity": "warning", "action": "link_evidence"},
  ],
  "input_hash": "sha256-normalized-fee-scope-basis-amount-revisions",
}
```

`input_hash` 使用排序后的稳定物料键、费用修订、范围、依据、采用汇率及有效数量修订。凭证状态哈希单独保存：凭证失效使最终确认失效；只有数值/范围/依据等变化才产生 `RECALCULATE_REQUIRED`。

计算完成时再对规范化物料成本行、采用费用状态、汇率修订和数量修订生成 `cost_result_hash`，保存到当前 `Overseas Cost Version`。同一输入必须得到同一哈希；任一采用金额、范围、依据、汇率、有效数量或行成本变化必须得到新哈希。后续 ERP 创建与更新只引用这个持久化结果哈希，不接受客户端自报哈希。

- [x] **Step 4: 运行并提交**

Run: `python -m pytest -q overseas_costing/tests/test_fee_status_service.py overseas_costing/tests/test_calculate_service.py`

Expected: PASS.

```bash
git add overseas_costing/services/fee_status_service.py overseas_costing/services/calculate_service.py overseas_costing/tests/test_fee_status_service.py overseas_costing/tests/test_calculate_service.py
git commit -m 'feat: compute persistent fee work states'
```

## Task 4: 实现费用修改、凭证关联和最终确认事务

**Files:**

- Create: `overseas_costing/services/fee_service.py`
- Modify: `overseas_costing/services/calculate_service.py`
- Modify: `overseas_costing/services/import_service.py`
- Create: `overseas_costing/tests/test_fee_service.py`

- [x] **Step 1: 写失败测试**

覆盖：同一 `logical_fee_key` 暂估转实际只更新一笔；OA/账单/付款凭证候选不自动重复新增；费用金额/范围/依据变化使批次 Dirty 并使旧完成记录 INVALIDATED；只补普通附件不使计算失效；必需最终凭证删除/解除/无效会使最终确认失效并重开待办；无有效金额、存在待分摊或待重算时拒绝“确认费用已齐”。

```python
def test_confirm_complete_rejects_estimated_fee() -> None:
    result = validate_fee_completion([estimated_fee_status()])
    assert result["ok"] is False
    assert result["blocking"][0]["code"] == "ACTUAL_AMOUNT_REQUIRED"
```

- [x] **Step 2: 运行并确认失败**

Run: `python -m pytest -q overseas_costing/tests/test_fee_service.py`

Expected: FAIL because lifecycle transaction methods are absent.

- [x] **Step 3: 实现写事务**

公开 service 方法：

```python
save_fee(batch_name, version_name, fee_payload, edit_token, expected_modified)
link_fee_evidence(batch_name, fee_rule, attachment, evidence_role, edit_token, expected_modified)
set_fee_evidence_status(batch_name, evidence_name, status, remark, edit_token, expected_modified)
confirm_all_fees_complete(batch_name, version_name, expected_input_hash, edit_token, expected_modified)
```

所有方法锁定批次、复核审批有效性、权限、版本和编辑租约。`save_fee` 更新金额时生成新 `amount_revision`；实际值替换同逻辑费用的暂估采用值而不是叠加。`NOT_INCURRED/INCLUDED` 必须有原因，`INCLUDED` 必须引用另一费用键或本批采购金额。

- [x] **Step 4: 统一附件删除/撤销通知**

现有附件删除和税费核对状态变更调用 `invalidate_fee_completion_for_evidence()`。它不删历史完成记录；插入失效时间、原因和操作者。只有采用金额发生变化才标记 Dirty，单纯证据失效只重开凭证/最终确认状态。

- [x] **Step 5: 运行并提交**

Run: `python -m pytest -q overseas_costing/tests/test_fee_service.py overseas_costing/tests/test_import_service.py overseas_costing/tests/test_calculate_service.py`

Expected: PASS.

```bash
git add overseas_costing/services/fee_service.py overseas_costing/services/calculate_service.py overseas_costing/services/import_service.py overseas_costing/tests/test_fee_service.py overseas_costing/tests/test_import_service.py overseas_costing/tests/test_calculate_service.py
git commit -m 'feat: manage fee evidence and final confirmation'
```

## Task 5: 把费用待办加入批次列表和详情查询

**Files:**

- Modify: `overseas_costing/services/workbench_service.py`
- Modify: `overseas_costing/services/batch_service.py`
- Modify: `overseas_costing/tests/test_workbench_service.py`
- Modify: `overseas_costing/tests/test_batch_service.py`

- [x] **Step 1: 写失败测试**

```python
def test_pushed_batch_remains_pending_when_fee_is_estimated() -> None:
    row = classify_batch(
        {"writeback_status": "Success", "status": "Calculated"},
        {"item_count": 2, "fee_status": {"temporary_fee_count": 1, "affected_fee_count": 1}},
    )
    assert "fees_incomplete" in row["issue_codes"]


def test_workbench_summary_does_not_sum_fee_todo_labels_as_fee_count() -> None:
    summary = summarize_batches([{
        "name": "B1",
        "fee_work": {
            "affected_fee_count": 1,
            "todo_count": 3,
            "items": [{
                "fee_key": "TAX",
                "todos": [
                    {"code": "ACTUAL_AMOUNT_REQUIRED"},
                    {"code": "EVIDENCE_REQUIRED"},
                    {"code": "RECALCULATE_REQUIRED"},
                ],
            }],
        },
    }])
    assert summary["fees_incomplete"] == 1
    assert summary["fee_todos"] == 3
```

- [x] **Step 2: 运行并确认失败**

Run: `python -m pytest -q overseas_costing/tests/test_workbench_service.py overseas_costing/tests/test_batch_service.py`

Expected: FAIL because workbench classification currently only knows purchase/logistics/calculation/ERP failure.

- [x] **Step 3: 加入结构化摘要**

批次列表每行返回：

```python
"fee_work": {
  "affected_fee_count": 2,
  "missing_amount_fee_count": 1,
  "unallocated_by_currency": {"CNY": "80.00"},
  "estimated_fee_count": 1,
  "evidence_todo_count": 1,
  "recalculate_fee_count": 0,
  "completion_status": "INCOMPLETE"
}
```

`filter_batches_for_task()` 增加 `fees` 筛选，但保留 `pending/cost/erp` 兼容。详情同时返回逐费用待办和可定位稳定键；不同币种不直接相加。

- [x] **Step 4: 运行并提交**

Run: `python -m pytest -q overseas_costing/tests/test_workbench_service.py overseas_costing/tests/test_batch_service.py`

Expected: PASS.

```bash
git add overseas_costing/services/workbench_service.py overseas_costing/services/batch_service.py overseas_costing/tests/test_workbench_service.py overseas_costing/tests/test_batch_service.py
git commit -m 'feat: surface fee work across batches'
```

## Task 6: 暴露费用 API 并保持权限边界

**Files:**

- Create: `overseas_costing/api/fees.py`
- Create: `overseas_costing/tests/test_fees_api.py`
- Modify: `overseas_costing/services/access_control.py`

- [x] **Step 1: 写失败测试**

锁定接口：

```python
get_fee_worklist(batch_name, version_name=None)
save_fee(batch_name, version_name, fee_json, edit_token, expected_modified)
link_fee_evidence(batch_name, fee_rule, attachment, evidence_role, edit_token, expected_modified)
set_fee_evidence_status(batch_name, evidence_name, status, remark, edit_token, expected_modified)
confirm_all_fees_complete(batch_name, version_name, expected_input_hash, edit_token, expected_modified)
```

测试批次级读写权限、附件归属本批、字段白名单、JSON 大小和枚举；不能由客户端传 `confirmed_by`、状态哈希或已分摊金额。

- [x] **Step 2: 运行并确认失败**

Run: `python -m pytest -q overseas_costing/tests/test_fees_api.py overseas_costing/tests/test_access_control.py`

Expected: FAIL because `api.fees` is absent.

- [x] **Step 3: 实现薄 API 并运行**

Run: `python -m pytest -q overseas_costing/tests/test_fees_api.py overseas_costing/tests/test_access_control.py`

Expected: PASS; API delegates all state decisions to services.

- [x] **Step 4: 提交**

```bash
git add overseas_costing/api/fees.py overseas_costing/services/access_control.py overseas_costing/tests/test_fees_api.py overseas_costing/tests/test_access_control.py
git commit -m 'feat: expose secure fee work APIs'
```

## Task 7: 实现费用首区和一目了然的持续提醒

**Files:**

- Create: `overseas_costing/page/overseas_cost_workbench/parts/78-fee-worklist.js`
- Create: `overseas_costing/page/overseas_cost_workbench/parts/49-fee-worklist.css`
- Modify: `overseas_costing/page/overseas_cost_workbench/parts/05-workbench-state.js`
- Modify: `overseas_costing/page/overseas_cost_workbench/parts/35-workbench-view.js`
- Modify: `overseas_costing/page/overseas_cost_workbench/parts/82-detail-page.js`
- Modify: `overseas_costing/page/overseas_cost_workbench/parts/40-vouchers.js`
- Modify: `overseas_costing/tests/test_workbench_frontend_state.py`
- Modify generated files via: `overseas_costing/scripts/build_workbench_assets.py`

- [x] **Step 1: 写前端失败测试**

验证批次列表显示“费用未完成”；详情头部分开显示成本处理/ERP 同步；费用区位于物料区之前；金额待补、待分摊、暂估待实际、凭证待补、待重算分别有文案和定位动作；已推送 Success 不隐藏费用待办；一笔费用三个标签仍显示“一笔费用、三项待办”。

- [x] **Step 2: 运行并确认失败**

Run: `python -m pytest -q overseas_costing/tests/test_workbench_frontend_state.py`

Expected: FAIL because fee worklist markers and state helpers are absent.

- [x] **Step 3: 实现费用列表与操作**

费用行按异常优先，支持切换全部；普通操作直接编辑金额/性质/依据，少见“费用归属”默认收起并选择相关物料。凭证入口打开已有附件选择/上传，再确认关联角色。未发生/已包含要求原因；确认费用已齐先展示仍会阻断的项目。

颜色规则：缺失/无效为红，暂估为橙，已完成为中性或成功色；每个状态有文字和图标标签，不能只用颜色。顶部点击定位到费用稳定键，焦点和 URL issue 参数保持可恢复。

- [x] **Step 4: 生成资源并运行测试**

```bash
python overseas_costing/scripts/build_workbench_assets.py
python -m pytest -q overseas_costing/tests/test_workbench_frontend_state.py overseas_costing/tests/test_workbench_asset_builder.py
```

Expected: PASS and source/deployed assets match.

- [x] **Step 5: 浏览器验收并提交**

用本地样本验证：未知金额、明确未发生、暂估已分摊、实际已分摊但缺凭证、一个费用多待办、费用变化重开、最终凭证失效、ERP 显示成功但费用仍提醒。不得上传或改动真实业务文件。

```bash
git add overseas_costing/page/overseas_cost_workbench/parts/78-fee-worklist.js overseas_costing/page/overseas_cost_workbench/parts/49-fee-worklist.css overseas_costing/page/overseas_cost_workbench/parts/05-workbench-state.js overseas_costing/page/overseas_cost_workbench/parts/35-workbench-view.js overseas_costing/page/overseas_cost_workbench/parts/82-detail-page.js overseas_costing/page/overseas_cost_workbench/parts/40-vouchers.js overseas_costing/page/overseas_cost_workbench/overseas_cost_workbench.js overseas_costing/page/overseas_cost_workbench/overseas_cost_workbench.css overseas_costing/overseas_costing/page/overseas_cost_workbench/overseas_cost_workbench.js overseas_costing/overseas_costing/page/overseas_cost_workbench/overseas_cost_workbench.css overseas_costing/tests/test_workbench_frontend_state.py
git commit -m 'feat: add persistent fee worklist'
```

## Task 8: 阶段回归和完成度验收

**Files:**

- Modify: `overseas_costing/scripts/seed_workbench_sample.py`
- Create: `overseas_costing/tests/test_fee_workflow_acceptance.py`

- [ ] **Step 1: 建立脱敏样本和端到端断言**

样本覆盖全批共同费、生产物料专属费、直接费、暂估转实际、同金额性质变化、凭证失效、金额/范围变化及确认费用已齐。断言每笔分摊守恒、范围外为零、完成记录按输入哈希失效、ERP 字段不参与费用待办关闭。

- [ ] **Step 2: 运行完整相关测试**

```bash
python -m pytest -q \
  overseas_costing/tests/test_fee_doctypes.py \
  overseas_costing/tests/test_fee_allocation_service.py \
  overseas_costing/tests/test_fee_status_service.py \
  overseas_costing/tests/test_fee_service.py \
  overseas_costing/tests/test_fees_api.py \
  overseas_costing/tests/test_calculate_service.py \
  overseas_costing/tests/test_import_service.py \
  overseas_costing/tests/test_batch_service.py \
  overseas_costing/tests/test_workbench_service.py \
  overseas_costing/tests/test_workbench_frontend_state.py \
  overseas_costing/tests/test_fee_workflow_acceptance.py
```

Expected: PASS without real DingTalk/ERP calls.

- [ ] **Step 3: 验证镜像和提交**

```bash
cmp overseas_costing/doctype/overseas_cost_allocation_rule/overseas_cost_allocation_rule.json overseas_costing/overseas_costing/doctype/overseas_cost_allocation_rule/overseas_cost_allocation_rule.json
cmp overseas_costing/doctype/overseas_cost_fee_evidence/overseas_cost_fee_evidence.json overseas_costing/overseas_costing/doctype/overseas_cost_fee_evidence/overseas_cost_fee_evidence.json
cmp overseas_costing/doctype/overseas_cost_fee_completion/overseas_cost_fee_completion.json overseas_costing/overseas_costing/doctype/overseas_cost_fee_completion/overseas_cost_fee_completion.json
git diff --check
git add overseas_costing/scripts/seed_workbench_sample.py overseas_costing/tests/test_fee_workflow_acceptance.py
git commit -m 'test: cover fee workflow acceptance'
```
