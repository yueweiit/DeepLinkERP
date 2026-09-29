# Inventory On Hand 最小实施计划

## 复用与边界

- 复用 ERPNext `Bin`、`Item`、`Warehouse` 和现有 Stock 工作区。
- 原始库位字段、原始标识字段和工作区链接直接在 ERP 配置，不写安装器。
- 377 条 Bin 原始库位因浏览器账号无保存权限，使用受限的一次性入口安全回填；成功复核后删除该入口及其测试，最终代码不保留迁移 API。
- 只新增最小 Script Report，解决标准报表无法按每行库存单位动态显示 0/2 位小数的问题。
- 保留标准 `Stock Projected Qty`，不改 ERPNext 核心实现。

## 实施步骤

1. 在生产 ERP 创建：
   - `Bin.custom_original_location`（原始库位，Data，只读）；
   - `Item.custom_original_identifier_alias`（原始标识/别名，Small Text）。
2. 新增 `Inventory On Hand` Script Report：
   - 只查询非零 `Bin.actual_qty`；
   - 固定返回 10 个业务字段；
   - 支持公司、仓库、原始库位、物料、物料组筛选；
   - 计数单位整数走 `Int` 格式，连续单位走 2 位 `Float` 格式。
3. 在 ERP 中预检查 377 个目标 Bin、375 个 Item 均存在且追溯字段为空；任何已有不同非空值停止处理并列出冲突。Item 别名直接配置，Bin 原始库位由临时受限入口回填并在复核后删除入口。
4. 直接把 Stock 工作区“可用数量”链接改为 `Inventory On Hand`。
5. 验证 377 行、92 个库位、数量合计 `746,610.49`、库存价值 0，且没有新增 Stock Ledger Entry 或 Stock Reconciliation。
6. 删除临时回填 API、服务和专项迁移测试；重新运行报表专项、全量测试及生产验收，确认报表不依赖迁移入口。

## 测试与验收

- 专项测试覆盖精确列顺序、实际库存查询口径、绑定筛选、停用物料不漏报、计数/连续单位格式和计数单位异常。
- 运行全量 Python 3.12 测试与 compileall。
- 生产验证两个色母粒、至少一个整数单位、一个 kg 单位、工作区入口和标准报表兼容性。
- 最终报告列出新增、修改、删除、测试、代码行数、重复逻辑和未处理技术债。
