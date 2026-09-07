# 物料资料、数量口径与表格导入 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在没有装箱计划时也能用 OA 和人工资料核算，并提供可追溯的发货数量默认值、字段级 Excel 导入预览和按当前核算条件标红的物料表格。

**Architecture:** 用一个纯规则模块统一解析有效发货数量、计价单位和字段缺项；现有导入服务负责可信来源，新增预览令牌和字段级采用服务，所有写入继续经过编辑租约、版本校验和审计。前端只渲染服务端返回的字段状态，不自行发明阻断规则。

**Tech Stack:** Python 3、Frappe DocType/API、openpyxl、pytest、原生 JavaScript/CSS、现有工作台 UMD 状态工具。

---

## 范围与依赖

本计划交付正式物料区、有效数量及本地 Excel 补充。OA 正文/附件沿用现有 `import_service.py` 和 `packing_source_service.py`。知识库 Sheet、共享包装快照和独立整票运费比较继续由 `2026-09-07-packing-source-and-freight-comparison.md` 交付；在执行本计划前端 Task 7 前，应先合入该计划中的统一装箱模型、API 和工作台资源生成器。

本计划不实现费用适用范围、费用最终完成确认或多站点写入；它为后两份计划提供稳定物料行、数量和结构化缺项。

## 目标文件结构

- `overseas_costing/services/material_input_service.py`：有效数量、单位关系、缺项和字段采用的纯规则及事务入口。
- `overseas_costing/services/material_import_service.py`：把现有 Excel/装箱解析输出标准化为字段级差异预览，签发并验证一次性预览修订。
- `overseas_costing/api/materials.py`：物料表格查询、预览和采用的薄权限层。
- `overseas_costing/page/overseas_cost_workbench/parts/77-material-grid.js`：表格状态、编辑、粘贴、导入预览和缺项定位。
- `overseas_costing/page/overseas_cost_workbench/parts/48-material-grid.css`：表格、缺项、来源标签和响应式样式。
- 两份 `overseas_cost_item.json`：核心数量/单位/来源字段保持镜像一致。
- `overseas_costing/tests/test_material_input_service.py`、`test_material_import_service.py`、`test_materials_api.py`：纯规则、事务和权限测试。

## Task 1: 建立有效发货数量和单位模型

**Files:**

- Modify: `overseas_costing/doctype/overseas_cost_item/overseas_cost_item.json`
- Modify: `overseas_costing/overseas_costing/doctype/overseas_cost_item/overseas_cost_item.json`
- Create: `overseas_costing/services/material_input_service.py`
- Create: `overseas_costing/tests/test_material_input_service.py`

- [x] **Step 1: 写失败测试，锁定默认值和历史值语义**

```python
from overseas_costing.services.material_input_service import resolve_effective_quantity


def test_default_quantity_follows_purchase_source() -> None:
    result = resolve_effective_quantity({
        "quantity": "34",
        "actual_shipped_qty": "",
        "actual_shipped_qty_mode": "DEFAULT_PURCHASE",
        "purchase_uom": "桶",
        "shipped_uom": "桶",
    })
    assert result == {
        "quantity": "34",
        "uom": "桶",
        "mode": "DEFAULT_PURCHASE",
        "is_default": True,
        "blocking": [],
    }


def test_explicit_quantity_does_not_follow_purchase_update() -> None:
    result = resolve_effective_quantity({
        "quantity": "34",
        "actual_shipped_qty": "32",
        "actual_shipped_qty_mode": "MANUAL_CONFIRMED",
        "purchase_uom": "桶",
        "shipped_uom": "桶",
    })
    assert result["quantity"] == "32"
    assert result["is_default"] is False


def test_legacy_equal_values_are_not_reclassified_as_default() -> None:
    result = resolve_effective_quantity({
        "quantity": "34",
        "actual_shipped_qty": "34",
        "actual_shipped_qty_mode": "LEGACY_UNVERIFIED",
        "unit": "桶",
    })
    assert result["mode"] == "LEGACY_UNVERIFIED"
    assert result["is_default"] is False
```

- [x] **Step 2: 运行并确认失败**

Run: `python -m pytest -q overseas_costing/tests/test_material_input_service.py`

Expected: FAIL because `material_input_service` does not exist.

- [x] **Step 3: 增加显式字段，保持历史数据不猜测**

在两份镜像 JSON 的 `field_order` 和 `fields` 中加入相同定义：

```json
{
  "fieldname": "stable_line_key",
  "fieldtype": "Data",
  "label": "稳定物料行标识",
  "read_only": 1,
  "unique": 0
},
{
  "fieldname": "purchase_uom",
  "fieldtype": "Data",
  "label": "采购单位"
},
{
  "fieldname": "unit_price_uom",
  "fieldtype": "Data",
  "label": "采购单价计价单位"
},
{
  "fieldname": "shipped_uom",
  "fieldtype": "Data",
  "label": "发货单位"
},
{
  "fieldname": "cost_output_uom",
  "fieldtype": "Data",
  "label": "综合成本输出单位",
  "read_only": 1
},
{
  "fieldname": "actual_shipped_qty_mode",
  "fieldtype": "Select",
  "label": "发货数量来源状态",
  "options": "DEFAULT_PURCHASE\nEXPLICIT_SOURCE\nMANUAL_CONFIRMED\nLEGACY_UNVERIFIED"
},
{
  "fieldname": "actual_shipped_qty_source_revision",
  "fieldtype": "Data",
  "label": "发货数量来源修订"
},
{
  "fieldname": "erp_stock_uom",
  "fieldtype": "Data",
  "label": "ERP库存单位"
},
{
  "fieldname": "shipped_to_erp_factor",
  "fieldtype": "Float",
  "label": "发货单位到ERP库存单位换算"
}
```

新建业务行生成不可变 `stable_line_key`；同一业务行克隆到新成本版本时保留该键，新增的同 SKU 独立行必须生成新键。已有行首次迁移只补稳定键；`actual_shipped_qty` 有值的行标记 `LEGACY_UNVERIFIED`，没有值的行标记 `DEFAULT_PURCHASE`，不得因数值恰好相等推断为默认。`cost_output_uom` 由有效发货单位解析结果回填，只读展示并随单位修订重算。

- [x] **Step 4: 实现纯解析器**

```python
from decimal import Decimal, InvalidOperation

VALID_QTY_MODES = {
    "DEFAULT_PURCHASE", "EXPLICIT_SOURCE", "MANUAL_CONFIRMED", "LEGACY_UNVERIFIED"
}


def _positive_decimal(value) -> Decimal | None:
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return number if number > 0 else None


def resolve_effective_quantity(item: dict) -> dict:
    mode = str(item.get("actual_shipped_qty_mode") or "LEGACY_UNVERIFIED")
    if mode not in VALID_QTY_MODES:
        mode = "LEGACY_UNVERIFIED"
    raw = item.get("quantity") if mode == "DEFAULT_PURCHASE" else item.get("actual_shipped_qty")
    quantity = _positive_decimal(raw)
    uom = str(item.get("shipped_uom") or item.get("purchase_uom") or item.get("unit") or "").strip()
    blocking = []
    if quantity is None:
        blocking.append({"code": "SHIPPED_QTY_REQUIRED", "field": "actual_shipped_qty"})
    if not uom:
        blocking.append({"code": "SHIPPED_UOM_REQUIRED", "field": "shipped_uom"})
    return {
        "quantity": format(quantity, "f") if quantity is not None else "",
        "uom": uom,
        "mode": mode,
        "is_default": mode == "DEFAULT_PURCHASE",
        "blocking": blocking,
    }
```

- [x] **Step 5: 运行测试并提交**

Run: `python -m pytest -q overseas_costing/tests/test_material_input_service.py`

Expected: PASS.

```bash
git add overseas_costing/doctype/overseas_cost_item/overseas_cost_item.json overseas_costing/overseas_costing/doctype/overseas_cost_item/overseas_cost_item.json overseas_costing/services/material_input_service.py overseas_costing/tests/test_material_input_service.py
git commit -m 'feat: model effective shipped quantities'
```

## Task 2: 让成本计算使用同一数量和计价口径

**Files:**

- Modify: `overseas_costing/services/material_input_service.py`
- Modify: `overseas_costing/services/calculate_service.py`
- Modify: `overseas_costing/tests/test_calculate_service.py`
- Modify: `overseas_costing/tests/test_material_input_service.py`

- [ ] **Step 1: 写失败测试，覆盖按 kg 计价、按桶发货及部分发货**

```python
def test_explicit_goods_value_can_produce_per_shipped_uom_cost() -> None:
    rows, _summary = calculate_item_rows([{
        "quantity": 612,
        "purchase_uom": "kg",
        "unit_price": 25,
        "unit_price_uom": "kg",
        "goods_value": 15300,
        "actual_shipped_qty": 34,
        "actual_shipped_qty_mode": "EXPLICIT_SOURCE",
        "shipped_uom": "桶",
    }], [])
    assert rows[0]["goods_value"] == 15300
    assert rows[0]["total_unit_rmb"] == 450
    assert rows[0]["cost_output_uom"] == "桶"


def test_incompatible_units_do_not_multiply_price_by_shipping_quantity() -> None:
    rows, summary = calculate_item_rows([{
        "quantity": 34,
        "purchase_uom": "桶",
        "unit_price": 25,
        "unit_price_uom": "kg",
        "goods_value": "",
        "actual_shipped_qty_mode": "DEFAULT_PURCHASE",
    }], [])
    assert rows[0]["goods_value"] == 0
    assert summary["blocking"][0]["code"] == "GOODS_VALUE_OR_UOM_CONVERSION_REQUIRED"
```

- [ ] **Step 2: 运行并确认失败**

Run: `python -m pytest -q overseas_costing/tests/test_calculate_service.py overseas_costing/tests/test_material_input_service.py`

Expected: FAIL because calculation currently uses `quantity` for both goods amount and unit denominator.

- [ ] **Step 3: 实现明确的采购金额与输出分母解析**

在 `material_input_service.py` 增加：

```python
def resolve_goods_value(item: dict) -> dict:
    explicit = _positive_decimal(item.get("goods_value"))
    if explicit is not None:
        return {"amount": explicit, "source": "EXPLICIT_AMOUNT", "blocking": []}
    price = _positive_decimal(item.get("unit_price"))
    purchase_qty = _positive_decimal(item.get("quantity"))
    price_uom = str(item.get("unit_price_uom") or "").strip()
    purchase_uom = str(item.get("purchase_uom") or item.get("unit") or "").strip()
    if price is not None and purchase_qty is not None and price_uom and price_uom == purchase_uom:
        return {"amount": price * purchase_qty, "source": "PRICE_X_PURCHASE_QTY", "blocking": []}
    return {"amount": Decimal("0"), "source": "UNRESOLVED", "blocking": [
        {"code": "GOODS_VALUE_OR_UOM_CONVERSION_REQUIRED", "field": "goods_value"}
    ]}
```

`calculate_item_rows()` 对每行调用 `resolve_goods_value()` 和 `resolve_effective_quantity()`；行成本为本批采购金额加该行直接及分摊费用，`total_unit_rmb` 只除以该行有效发货数量。把结构化阻断原因放进汇总和行 `derived_json`，不得将缺失解析为零后宣称有效。

- [ ] **Step 4: 更新旧测试的输入语义并运行**

为依赖旧 `quantity` 语义的测试显式增加同单位或 `goods_value`。不要仅修改断言来保留错误行为。

Run: `python -m pytest -q overseas_costing/tests/test_calculate_service.py overseas_costing/tests/test_batch_service.py`

Expected: PASS.

- [ ] **Step 5: 提交**

```bash
git add overseas_costing/services/material_input_service.py overseas_costing/services/calculate_service.py overseas_costing/tests/test_material_input_service.py overseas_costing/tests/test_calculate_service.py overseas_costing/tests/test_batch_service.py
git commit -m 'fix: calculate costs from effective shipped quantities'
```

## Task 3: 生成随当前分摊规则变化的字段缺项

**Files:**

- Modify: `overseas_costing/services/material_input_service.py`
- Modify: `overseas_costing/services/workbench_service.py`
- Modify: `overseas_costing/tests/test_material_input_service.py`
- Modify: `overseas_costing/tests/test_workbench_service.py`

- [ ] **Step 1: 写失败测试**

```python
def test_required_cells_follow_active_fee_basis() -> None:
    result = build_material_requirements(
        [{"name": "I1", "goods_value": 100, "gross_weight_kg": "", "volume_m3": ""}],
        [{"name": "F1", "allocation_basis": "gross_weight", "scope_item_names": ["I1"]}],
    )
    assert result["by_item"]["I1"]["gross_weight_kg"]["severity"] == "blocking"
    assert result["by_item"]["I1"]["volume_m3"]["severity"] == "optional"


def test_missing_project_warns_for_push_but_not_cost_preview() -> None:
    result = build_material_requirements([{"name": "I1", "project_collection": ""}], [])
    assert result["by_item"]["I1"]["project_collection"]["gate"] == "erp_push"
```

- [ ] **Step 2: 运行并确认失败**

Run: `python -m pytest -q overseas_costing/tests/test_material_input_service.py overseas_costing/tests/test_workbench_service.py`

Expected: FAIL with missing `build_material_requirements`.

- [ ] **Step 3: 实现单一缺项输出**

返回契约固定为：

```python
{
    "summary": {"blocking_for_calculation": 1, "blocking_for_erp": 1, "warnings": 0},
    "by_item": {
        "I1": {
            "gross_weight_kg": {
                "severity": "blocking",
                "gate": "calculation",
                "code": "GROSS_WEIGHT_REQUIRED_BY_F1",
                "message": "费用 F1 按毛重分摊，请补毛重",
            }
        }
    },
}
```

只要求适用费用所需字段；专属范围在第二阶段接入前可读取 `scope_item_names` 预览字段，但本阶段不持久化费用范围。项目/站点使用 `erp_push` gate；发货数量和采购金额使用 `calculation` gate。

- [ ] **Step 4: 在物料查询中附加缺项并运行**

`get_batch_items_page()` 一次读取当前版本规则，把 `cell_requirements` 附加到每行，并返回汇总；不要让浏览器重复推导。

Run: `python -m pytest -q overseas_costing/tests/test_material_input_service.py overseas_costing/tests/test_workbench_service.py`

Expected: PASS.

- [ ] **Step 5: 提交**

```bash
git add overseas_costing/services/material_input_service.py overseas_costing/services/workbench_service.py overseas_costing/tests/test_material_input_service.py overseas_costing/tests/test_workbench_service.py
git commit -m 'feat: expose contextual material requirements'
```

## Task 4: 建立字段级 Excel 预览和安全采用

**Files:**

- Create: `overseas_costing/services/material_import_service.py`
- Modify: `overseas_costing/services/import_service.py`
- Modify: `overseas_costing/services/packing_source_service.py`
- Create: `overseas_costing/tests/test_material_import_service.py`
- Modify: `overseas_costing/tests/test_import_service.py`

- [ ] **Step 1: 写失败测试，禁止只按 SKU 猜测及空值覆盖**

```python
def test_preview_keeps_duplicate_sku_rows_and_requires_line_choice() -> None:
    result = build_material_import_preview(
        existing=[
            {"name": "I1", "stable_line_key": "L1", "material_code": "FL000103", "source_doc_no": "PO1"},
            {"name": "I2", "stable_line_key": "L2", "material_code": "FL000103", "source_doc_no": "PO2"},
        ],
        incoming=[{"source_row": 9, "material_code": "FL000103", "actual_shipped_qty": 15}],
        source={"kind": "manual_xlsx", "revision": "R1"},
    )
    assert result["rows"][0]["match_status"] == "choice_required"
    assert {c["stable_line_key"] for c in result["rows"][0]["candidates"]} == {"L1", "L2"}


def test_blank_excel_shipping_quantity_never_clears_current_value() -> None:
    changes = build_field_changes(
        existing={"actual_shipped_qty": 17, "actual_shipped_qty_mode": "MANUAL_CONFIRMED"},
        incoming={"actual_shipped_qty": ""},
    )
    assert changes == []
```

- [ ] **Step 2: 运行并确认失败**

Run: `python -m pytest -q overseas_costing/tests/test_material_import_service.py overseas_costing/tests/test_import_service.py`

Expected: FAIL because the new preview service is absent and current supplement matching rejects duplicate SKU without a reviewable choice.

- [ ] **Step 3: 定义预览令牌和字段差异契约**

`preview_material_import(batch_name, source_kind, source_id, sheet_name)` 复用可信解析器并返回：

```python
{
  "preview_revision": "signed-token-bound-to-batch-version-source-hash",
  "sheet": {"selected": "油漆", "available": ["油漆", "五金"]},
  "mapping": [{"source": "总个数", "target": "actual_shipped_qty", "confidence": "header"}],
  "rows": [{
    "source_row": 9,
    "match_status": "choice_required",
    "candidates": [{"stable_line_key": "L1"}, {"stable_line_key": "L2"}],
    "changes": [{"field": "actual_shipped_qty", "old": 17, "new": 15, "conflict": True}],
  }],
  "source_totals": {"gross_weight_kg": "4197.4", "volume_m3": "8.7403305"},
}
```

令牌绑定批次、版本、来源哈希、选择的 Sheet 和预览结果哈希；服务端采用时重新解析可信来源。工作簿必须显式选 Sheet；评论等非工作簿来源不要求 Sheet。

- [ ] **Step 4: 实现原子采用**

`apply_material_import(batch_name, preview_revision, choices_json, edit_token, expected_modified)` 必须：校验权限/租约/版本；重新核对来源哈希；要求每个歧义行有明确稳定行选择；忽略来源空值；明确发货数量将模式写为 `EXPLICIT_SOURCE`；不清空费用、凭证或 OA 关联；统一审计后将批次标记 Dirty。共享包装值只通过已确认的包装组归属进入物料，不按重复行复制。

- [ ] **Step 5: 运行回归并提交**

Run: `python -m pytest -q overseas_costing/tests/test_material_import_service.py overseas_costing/tests/test_import_service.py overseas_costing/tests/test_packing_source_service.py`

Expected: PASS.

```bash
git add overseas_costing/services/material_import_service.py overseas_costing/services/import_service.py overseas_costing/services/packing_source_service.py overseas_costing/tests/test_material_import_service.py overseas_costing/tests/test_import_service.py overseas_costing/tests/test_packing_source_service.py
git commit -m 'feat: preview and apply material field imports'
```

## Task 5: 暴露带权限和编辑租约的物料 API

**Files:**

- Create: `overseas_costing/api/materials.py`
- Create: `overseas_costing/tests/test_materials_api.py`
- Modify: `overseas_costing/services/access_control.py`

- [ ] **Step 1: 写 API 权限失败测试**

锁定接口：

```python
get_material_grid(batch_name, version_name=None, page=1, page_length=100)
preview_material_import(batch_name, source_kind, source_id, sheet_name=None)
apply_material_import(batch_name, preview_revision, choices_json, edit_token, expected_modified)
set_shipping_quantity(batch_name, item_name, mode, value, uom, edit_token, expected_modified)
```

测试无批次读取权限不返回来源存在性；写接口要求物料/批次权限、有效编辑租约、请求体大小限制及匹配批次的签名预览。

- [ ] **Step 2: 运行并确认失败**

Run: `python -m pytest -q overseas_costing/tests/test_materials_api.py overseas_costing/tests/test_access_control.py`

Expected: FAIL because `api.materials` is absent.

- [ ] **Step 3: 实现薄 API 层**

API 只做输入归一化、权限校验和调用 service；不在 API 里解析 Excel 或计算红格。`choices_json` 限制条数和字节数，`source_id` 不接受任意服务器路径或 URL。

- [ ] **Step 4: 运行并提交**

Run: `python -m pytest -q overseas_costing/tests/test_materials_api.py overseas_costing/tests/test_access_control.py`

Expected: PASS.

```bash
git add overseas_costing/api/materials.py overseas_costing/services/access_control.py overseas_costing/tests/test_materials_api.py overseas_costing/tests/test_access_control.py
git commit -m 'feat: expose secure material grid APIs'
```

## Task 6: 把计算确认与 ERP 门槛分开

**Files:**

- Modify: `overseas_costing/services/batch_service.py`
- Modify: `overseas_costing/tests/test_batch_service.py`

- [ ] **Step 1: 写失败测试**

```python
def test_cost_preview_does_not_require_project_or_subsidiary() -> None:
    result = _build_calculation_confirmation_readiness(
        batch={"status": "Calculated", "current_version": "V1", "subsidiary_code": ""},
        items=[{
            "name": "I1", "stable_line_key": "L1", "material_code": "M1",
            "product_name": "原料", "quantity": 2, "actual_shipped_qty": 2,
            "actual_shipped_qty_mode": "MANUAL_CONFIRMED", "purchase_uom": "件",
            "shipped_uom": "件", "unit_price": 8, "unit_price_uom": "件",
            "purchase_currency": "CNY", "goods_value": 16,
            "freight_alloc_rmb": 6, "mexico_customs_mxn": 10,
            "import_tax_total": 4, "total_unit_rmb": 18, "project_collection": "",
        }],
        rules=[
            {"expense_category": "国际运费", "amount": 6},
            {"expense_category": "清关费", "amount": 10},
            {"expense_category": "关税", "amount": 4},
        ],
        resolved_version_name="V1",
    )
    assert "当前批次缺少归属业务主体。" not in result["blocking_reasons"]


def test_erp_readiness_still_requires_route_fields() -> None:
    result = _build_writeback_readiness(
        batch={
            "status": "Calculated", "confirm_status": "Confirmed", "current_version": "V1",
            "subsidiary_code": "", "item_count": 1, "actual_total_cost_rmb": 36,
        },
        items=[{
            "name": "I1", "stable_line_key": "L1", "material_code": "M1",
            "product_name": "原料", "quantity": 2, "actual_shipped_qty": 2,
            "actual_shipped_qty_mode": "MANUAL_CONFIRMED", "purchase_uom": "件",
            "shipped_uom": "件", "unit_price": 8, "unit_price_uom": "件",
            "purchase_currency": "CNY", "goods_value": 16, "total_unit_rmb": 18,
            "project_collection": "",
        }],
        resolved_version_name="V1",
    )
    assert result["ready"] is False
```

- [ ] **Step 2: 运行并确认失败**

Run: `python -m pytest -q overseas_costing/tests/test_batch_service.py`

Expected: FAIL because calculation confirmation currently reuses ERP-oriented item checks.

- [ ] **Step 3: 拆分门槛实现**

将规则拆为 `build_cost_preview_state`、`build_calculation_confirmation_state` 和 `build_erp_push_state`。前两者消费 `material_input_service` 的 calculation gate；ERP 状态额外消费 route gate。继续阻断被拒绝/撤销/终止审批，不能通过拆分删除业务有效性校验。

- [ ] **Step 4: 运行并提交**

Run: `python -m pytest -q overseas_costing/tests/test_batch_service.py overseas_costing/tests/test_calculate_service.py`

Expected: PASS.

```bash
git add overseas_costing/services/batch_service.py overseas_costing/tests/test_batch_service.py overseas_costing/tests/test_calculate_service.py
git commit -m 'refactor: separate costing and ERP readiness gates'
```

## Task 7: 实现费用在前、物料表格在后的正式页面

**Files:**

- Create: `overseas_costing/page/overseas_cost_workbench/parts/77-material-grid.js`
- Create: `overseas_costing/page/overseas_cost_workbench/parts/48-material-grid.css`
- Modify: `overseas_costing/page/overseas_cost_workbench/parts/05-workbench-state.js`
- Modify: `overseas_costing/page/overseas_cost_workbench/parts/82-detail-page.js`
- Modify: `overseas_costing/page/overseas_cost_workbench/parts/65-manual-documents.js`
- Modify: `overseas_costing/tests/test_workbench_frontend_state.py`
- Modify generated files via: `overseas_costing/scripts/build_workbench_assets.py`

- [ ] **Step 1: 写前端状态失败测试**

用 Node 执行 UMD helper，验证：默认数量显示“采购数量默认”；红格数量随 server requirements 更新；Tab 移到下一可编辑格；多格粘贴不会修改稳定行 ID；Excel 预览必须确认 Sheet/映射/冲突后才能采用；没有装箱来源时仍显示 OA/人工补充入口。

- [ ] **Step 2: 运行并确认失败**

Run: `python -m pytest -q overseas_costing/tests/test_workbench_frontend_state.py`

Expected: FAIL because the new grid state and markup markers are absent.

- [ ] **Step 3: 实现表格和导入预览**

详情页默认业务顺序为：费用与凭证、物料与装箱数据、核算结果。保留顶层来源/凭证/审计入口，但不再用九张同级文件卡表达完成度。表格从 API 的 `cell_requirements` 渲染：`blocking` 红色、`erp_push` 红色并写“推送前补”、`optional` 中性；每格提供文字或 `aria-label` 原因。

导入采用三步状态：选择来源及 Sheet、确认字段映射和匹配、确认字段差异。浏览器不解析后直接写数据库；文件先注册为私有 File，再由服务端预览。

- [ ] **Step 4: 生成两份页面资源并运行测试**

```bash
python overseas_costing/scripts/build_workbench_assets.py
python -m pytest -q overseas_costing/tests/test_workbench_frontend_state.py overseas_costing/tests/test_workbench_asset_builder.py
```

Expected: PASS and the two generated JS copies plus two CSS copies are byte-identical.

- [ ] **Step 5: 本地浏览器验收**

在 `development.localhost` 只使用本地样本验证：仅 OA 无装箱单、默认数量、手工数量冲突、Excel 两个 Sheet、重复 SKU、共享箱候选、按货值/毛重切换、红格定位、键盘与粘贴。确认未调用真实 ERP。

- [ ] **Step 6: 提交**

```bash
git add overseas_costing/page/overseas_cost_workbench/parts/77-material-grid.js overseas_costing/page/overseas_cost_workbench/parts/48-material-grid.css overseas_costing/page/overseas_cost_workbench/parts/05-workbench-state.js overseas_costing/page/overseas_cost_workbench/parts/82-detail-page.js overseas_costing/page/overseas_cost_workbench/parts/65-manual-documents.js overseas_costing/page/overseas_cost_workbench/overseas_cost_workbench.js overseas_costing/page/overseas_cost_workbench/overseas_cost_workbench.css overseas_costing/overseas_costing/page/overseas_cost_workbench/overseas_cost_workbench.js overseas_costing/overseas_costing/page/overseas_cost_workbench/overseas_cost_workbench.css overseas_costing/tests/test_workbench_frontend_state.py
git commit -m 'feat: add spreadsheet material input workflow'
```

## Task 8: 阶段回归和迁移验收

**Files:**

- Modify: `overseas_costing/scripts/seed_workbench_sample.py`
- Create: `overseas_costing/tests/test_material_grid_acceptance.py`

- [ ] **Step 1: 增加不含真实业务数据的验收样本**

样本覆盖：只有 OA、采购默认发货、明确不同发货量、按 kg 计价按桶出货、重复 SKU、共享箱、缺毛重但按货值可算、缺项目可预览。

- [ ] **Step 2: 运行完整相关测试**

```bash
python -m pytest -q \
  overseas_costing/tests/test_material_input_service.py \
  overseas_costing/tests/test_material_import_service.py \
  overseas_costing/tests/test_materials_api.py \
  overseas_costing/tests/test_calculate_service.py \
  overseas_costing/tests/test_import_service.py \
  overseas_costing/tests/test_packing_source_service.py \
  overseas_costing/tests/test_batch_service.py \
  overseas_costing/tests/test_workbench_service.py \
  overseas_costing/tests/test_workbench_frontend_state.py \
  overseas_costing/tests/test_material_grid_acceptance.py
```

Expected: PASS with no test accessing a real DingTalk or ERP endpoint.

- [ ] **Step 3: 验证 DocType 镜像和资源镜像**

```bash
cmp overseas_costing/doctype/overseas_cost_item/overseas_cost_item.json overseas_costing/overseas_costing/doctype/overseas_cost_item/overseas_cost_item.json
python overseas_costing/scripts/build_workbench_assets.py
git diff --exit-code -- overseas_costing/page/overseas_cost_workbench/overseas_cost_workbench.js overseas_costing/page/overseas_cost_workbench/overseas_cost_workbench.css overseas_costing/overseas_costing/page/overseas_cost_workbench/overseas_cost_workbench.js overseas_costing/overseas_costing/page/overseas_cost_workbench/overseas_cost_workbench.css
git diff --check
```

Expected: all commands exit 0.

- [ ] **Step 4: 提交验收样本**

```bash
git add overseas_costing/scripts/seed_workbench_sample.py overseas_costing/tests/test_material_grid_acceptance.py
git commit -m 'test: cover material input workflow acceptance'
```
