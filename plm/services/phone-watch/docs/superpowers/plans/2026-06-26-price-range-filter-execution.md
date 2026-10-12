# 原始货币价格区间筛选 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为手机新品监控列表增加基于原始货币文本的价格区间筛选，并保持 API、页面、静态导出和 CSV 导出一致。

**Architecture:** 后端在 `phone_watch/db.py` 集中实现价格文本解析和内存筛选，不修改数据库结构。`phone_watch/webapp.py` 只负责解析查询参数并传递给列表函数，`phone_watch/ui.py` 增加控件和静态页面前端筛选逻辑。

**Tech Stack:** Python 3.11、SQLite/PostgreSQL 兼容查询、标准库 `http.server`、原生 HTML/CSS/JavaScript、`unittest`/`pytest`。

## Global Constraints

- 不改表结构，不新增依赖，不引入前端构建工具。
- 普通 `$` 固定按 MXN 处理；`US$`/`USD` 才按 USD 处理。
- `¥`、`￥`、`RMB`、`CNY`、`元` 按 CNY 处理；`₩`、`원`、`KRW` 按 KRW 处理。
- 价格分类 `all/priced/unpriced` 必须可区分；非法数字输入返回 400。
- 生成实施沉淀文档到 `D:\Yuewei\资料\爬虫\实施\2026-06-26-原始货币价格区间筛选实施沉淀.md`。

---

### Task 1: 后端价格解析与筛选

**Files:**
- Create: `tests/test_price_filtering.py`
- Modify: `phone_watch/db.py`

**Interfaces:**
- Produces: `parse_price_for_filter(price: Any) -> tuple[str | None, float | None]`
- Produces: `filter_rows_by_price(rows, currency=None, min_price=None, max_price=None, price_bucket=None) -> list[Any]`
- Produces: `list_phones/list_candidates/list_new_phones/list_new_candidates` 新增 `price_currency/price_min/price_max/price_bucket`

- [ ] 写价格解析、筛选和列表查询测试。
- [ ] 运行测试，确认因缺少函数或参数失败。
- [ ] 实现 `db.py` 价格解析、筛选和四个列表函数参数。
- [ ] 运行 `py -m pytest tests/test_price_filtering.py -v`。

### Task 2: API 参数接入

**Files:**
- Modify: `phone_watch/webapp.py`
- Test: `tests/test_price_filtering.py`

**Interfaces:**
- Consumes: `db.list_*` 价格筛选参数
- Produces: `parse_optional_float(value)`、`price_filter_args(query)`

- [ ] 增加 API 价格筛选测试和非法数字 400 测试。
- [ ] 运行测试，确认 API 尚未接入导致失败。
- [ ] 修改 `webapp.py` 接入所有 GET/export 端点。
- [ ] 运行价格筛选测试。

### Task 3: 前端控件与静态筛选

**Files:**
- Modify: `phone_watch/ui.py`
- Test: `tests/test_price_filtering.py`

**Interfaces:**
- Produces: HTML 控件 `#price-currency/#price-min/#price-max/#price-bucket`
- Produces: JS `parsePriceForFilter(price)`、`priceMatches(row, f)`

- [ ] 增加 HTML 渲染断言测试。
- [ ] 运行测试，确认控件尚不存在导致失败。
- [ ] 修改 `ui.py` 工具栏、filters、API 请求、静态筛选、事件监听和 reset。
- [ ] 运行价格筛选测试。

### Task 4: 验证与沉淀文档

**Files:**
- Create/Update: `D:\Yuewei\资料\爬虫\实施\2026-06-26-原始货币价格区间筛选实施沉淀.md`

- [ ] 运行 `py -m pytest tests/test_price_filtering.py -v`。
- [ ] 运行 `py -m pytest -v`。
- [ ] 运行语法/导入检查。
- [ ] 生成实施沉淀文档，包含改动文件、核心代码、逻辑、验证结果、后期维护建议。
