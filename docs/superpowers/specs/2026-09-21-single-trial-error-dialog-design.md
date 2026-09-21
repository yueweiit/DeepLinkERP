# 试算错误单弹窗设计

## 目标

同一次开始或重新试算失败时，只显示工作台的「操作失败」业务弹窗，不再同时显示 Frappe 原始的「服务器错误」弹窗。

## 根因

工作台试算通过 `frappe.call` 发起请求。服务器返回业务拒绝时，Frappe 的全局 500 处理先弹出「服务器错误」，随后工作台 `recalculate()` 的 `catch` 再调用 `showError()` 弹出「操作失败」，因此同一错误被展示两次。

## 方案

- 复用现有 AI 请求的「由页面自行展示错误」传输模式，将 `recalculate_batch` 加入显式允许列表。
- `recalculate()` 调用试算接口时传入 `inlineErrors: true`，使用本地 `$.ajax` 而不是会自动弹窗的 `frappe.call`。
- 异常继续原样抛回，仍由 `recalculate()` 现有 `catch` 记录失败并调用 `showError()`，业务文案和审计逻辑不变。
- 其他接口仍默认使用 `frappe.call`，避免全局吞掉未处理的服务器错误。

## 验证

- 传输层测试验证 `recalculate_batch + inlineErrors` 只走 `$.ajax`，并保留原异常对象。
- 试算流程测试验证请求显式开启 `inlineErrors`，失败后仍只调用一次 `showError()`。
- 重建两套工作台资源，要求第二次构建返回 `changed: []`，再运行 JS 语法、受影响测试、全量测试和线上弹窗验收。

