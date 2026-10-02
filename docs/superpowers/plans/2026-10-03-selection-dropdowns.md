# 全站选择框单击展开 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** 所有原生可编辑候选选择框有值时也能单击浏览，不清空、不改值、不改变权限和依赖过滤，并上线验收。

**Architecture:** 在已有 `app_include_js` 上注册一个独立共享 bundle，沿 Link、Autocomplete 两个继承根扩展。复用原生查询、Awesomplete 渲染、选择与验证；使用每次请求的受保护控件视图隔离过期回调，不复制搜索接口或全局拦截 `frappe.call`。Dynamic Link、MultiSelect 通过继承覆盖；Select、MultiSelectList 保持原生。

**Tech Stack:** Frappe Desk JavaScript、jQuery、Awesomplete，pytest 驱动 Node 行为测试，已有 GitHub Actions 和 Docker/bench 发布路径。

---

## 基线和复用边界

- 起点 `3abff657fff74bd79c550d6936073740594f5356`，隔离分支 `codex/selection-dropdowns`。
- 现有库存 bundle 和页面必须保留。已有 `test_category_shared_runtime_is_bundled_before_thin_pages_execute` 修改为资源成员判断，不再硬编码单脚本赋值。
- 线上 Link 的 `get_search_args` 包含原生权限、公司、仓库叶节点、物料、自定义 query、页长；必须复用，不自行构造无过滤的查询。
- 原生 Link 的 `on_input`、Autocomplete 的 `execute_query_if_exists` 可以以请求视图为接收者执行，让 `$input.is(':focus')` 和 `awesomplete.list` 更新受当前请求、真实输入、依赖上下文和关闭状态约束。
- 原生选择回调、blur 校验、键盘和多选 replace 继续在真实控件上工作。不能临时清空真实输入再恢复。
- 原生控件仍有独立用途，无被替代的旧接口、数据库迁移或删除目标；兼容退出不适用。

## Task 1: 共享控件扩展与行为测试

**Files:**
- Create: `overseas_costing/public/js/selection_dropdown.bundle.js`
- Create: `overseas_costing/tests/test_selection_dropdown_frontend.py`
- Create: `overseas_costing/tests/frontend/selection_dropdown_harness.js`（仅作为本测试的 DOM/控件边界，原生契约来自已核查线上源码）

- [x] 写测试，首个断言验证有值 Link 的 click 查询空文本而不触发变更，读取真实 bundle；源文件不存在时先按空实现加载，以行为断言失败而不是模块错误。

```javascript
const field = makeControl("Link", {value: "YUEWEI MX", options: "Company"});
field.$input.trigger("click");
assert.equal(requests.at(-1).args.txt, "");
assert.equal(field.$input.val(), "YUEWEI MX");
assert.equal(field.changed, 0);
```

- [x] 运行 `python3 -m pytest -q overseas_costing/tests/test_selection_dropdown_frontend.py`，确认缺少点击浏览行为导致失败。
- [x] 沿 `make_input` 装饰一次并绑定命名空间事件；每个输入有独立状态。点击浏览只用原生空查询，输入恢复原生搜索，readonly/disabled 不查询。安装在 Desk 控件类存在后执行，重复加载和重建不重复绑定。

```javascript
const original = Control.prototype.make_input;
Control.prototype.make_input = function (...args) {
    const result = original.apply(this, args);
    bindSelectionInput(this);
    return result;
};
```

- [x] 请求状态包含 epoch、输入对象、当前显示值和原查询上下文。为原生请求方法构造局部接收者，不改全局网络函数，不复制 native 请求参数处理；在所有展示写入点再次检查有效性，包括原生描述异步 await 之后。空浏览不能展示其他公司缓存。

```javascript
const current = () => input === control.$input && epoch === state.epoch &&
    input.is(":focus") && input.val() === value && contextKey() === context;
```

- [x] Autocomplete 浏览模式只改变候选过滤文本，不改变真实输入和多选 replace。Link 的键盘匹配扩展仅对有效浏览状态和明确候选选择生效；输入后恢复原约束，Tab 不意外覆盖当前值。
- [x] 参数化 Link/Dynamic Link、Autocomplete/MultiSelect，覆盖独立风险：查询和页长保留、依赖改变、输入/关闭/重建后的慢响应、同控件反复点击、聚焦空值、网络失败、只读禁用、普通搜索/选择、异步描述、普通原生下拉不被修改。
- [x] 运行同一测试至全部通过，`node --check overseas_costing/public/js/selection_dropdown.bundle.js` 通过；自查不用真实输入清空技巧，也不改业务字段。

## Task 2: 全站加载与打包兼容

**Files:**
- Modify: `overseas_costing/hooks.py`
- Modify: `overseas_costing/tests/test_inventory_location_page.py`
- Modify only if the effective production package requires it: existing generic release asset verification (not inventory-only business rendering).

- [x] 增加一个 hooks 契约测试，要求两项 bundle 都存在；先运行确认缺少全站资源失败。
- [x] 加载入口改为列表，保留现有资源：

```python
app_include_js = [
    "categorized_inventory_detail.bundle.js",
    "selection_dropdown.bundle.js",
]
```

- [x] 现有库存资源测试解析赋值并验证成员，不复制另一个库存测试：

```python
import ast
tree = ast.parse(hooks)
assignment = next(n for n in tree.body if isinstance(n, ast.Assign)
                  and any(isinstance(t, ast.Name) and t.id == "app_include_js" for t in n.targets))
assets = ast.literal_eval(assignment.value)
assert "categorized_inventory_detail.bundle.js" in ([assets] if isinstance(assets, str) else assets)
```

- [x] 运行 `python3 -m pytest -q overseas_costing/tests/test_selection_dropdown_frontend.py overseas_costing/tests/test_inventory_location_page.py`，以及现有全部测试 `python3 -m pytest -q overseas_costing/tests`。基线为 4754 passed、13 skipped（现有跳过），LibreSSL 警告与本变更无关。
- [x] 提交实现。独立规格审查通过后，独立代码审查；重要问题修复并复审，不把 mock 测试通过冒充真实浏览器验收。

## Task 3: 发布与线上验收

**Files:**
- Create: `docs/superpowers/plans/2026-10-03-selection-dropdowns-acceptance.md`（最终实际证据与差异统计）

- [x] 检查发布分支和生产运行 SHA，生产 host tracked diff 为零；保留所有 untracked 配置/备份。核查 `.github/workflows/deploy-overseas-costing.yml` 与已有升级/资源同步脚本，确认不覆盖其他应用或业务记录。
- [x] 用户已授权实现上线；将经过审查的提交以 fast-forward 推至 `origin/overseas_costing`。如果远端并发移动，先比对再整合，不 force push。
- [x] 用 `gh run list/view` 确认准确提交的 CI 和部署结果；检查容器健康、页面响应、运行提交证明、hooks 中资源以及 assets.json 的哈希路径，验证前端实际文件与本次代码一致。后续另一条发布干扰及未完成复验见验收文档。
- [ ] 在已登录浏览器逐类检查有值公司弹窗、单据表头、明细物料/仓库、报表筛选、自动补全/多选、原生普通下拉。不保存或提交测试单据；弹窗取消保留当前公司。输入搜索、关闭重开和重复点击也要验收。
- [x] 记录真实完成与无法复現的覆盖边界；交付列明新增、修改、删除、重复逻辑、手写业务代码/测试/文档行数净变化、独立场景与参数化用例、未处理技术债。不把 CI、HTTP 200 或脚本模拟当作线上交互通过。
