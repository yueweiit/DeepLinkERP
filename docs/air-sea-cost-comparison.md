# 空运海运成本对比

入口为海外成本核算侧栏第二项，路由 `/desk/air-sea-cost-comparison`。页面源码位于 `overseas_costing/page/air_sea_cost_comparison/parts`；运行 `python3 overseas_costing/scripts/build_air_sea_assets.py` 生成页面并同步 Frappe 模块部署副本。

## 计算与来源

公式版本 `air-sea-html-1` 保留原 HTML 参数、毛重计空运、体积汇总及 DTA = CIF × 0.0008。合计是运输及进口费用，不含采购成本。样例海运 71504.68287568 CNY，空运 92973.8233928448 CNY。前端显示金额两位、平均六位，服务端用 Decimal 重新计算并保存完整输入及结果。数据不全或有效汇率缺失时存为草稿；不同数量单位不计算平均费用。

批次带入读取当前成本版本和当前有效物流数据，采购审批号优先取 source_doc_no；保留实际发货数量及单位，仅使用明确申报字段，不以采购价格代替申报价格。已确认装箱快照的总毛重/体积作为单独可编辑整票汇总，避免共箱累加。来源包含批次、版本、快照、带入时间及带签名的版本摘要。源数据变化只提示，测算不会回写原批次。被测算引用的批次不能直接删除，以免独立快照失去来源访问权限；删除提示要求先处理引用记录。

## 系统记录

`Overseas Air Sea Comparison` 允许 System Manager 与海外成本核算用户共同 CRUD，来源批次权限同时适用于 RPC、列表和普通 Frappe REST。未授权用户无访问权限。

接口命名空间为 `overseas_costing.api.air_sea_comparison`：`search_batches`、`preview_batch`、`list_records`、`get_record`、`save_record`、`delete_record`。写接口仅 POST。名称支持搜索和分页。保存需要 UUID request_id，更新和删除需要 modified 版本。服务端使用当前行锁读取进行版本核对；新建的确定性记录名由数据库唯一键防止重复请求生成重复记录。前端保留失败或冲突时的输入，校验保存响应后才接受新版本。普通 REST 写入也重新计算并保护已有来源权限。

## 验证

- `python3 -m pytest -q overseas_costing/tests`：现有及新增单测。
- `python3 overseas_costing/scripts/build_air_sea_assets.py`：重复构建应 changed 为空；检查源码与部署副本。
- `node --check overseas_costing/page/air_sea_cost_comparison/air_sea_cost_comparison.js`：页面语法。
- 在隔离 Frappe v16 环境运行 `overseas_costing/tests/integration/run_air_sea_frappe_integration.py`：两账号共享 CRUD、205 行批次带入、来源权限及变化、普通 REST 防绕过、搜索分页和草稿。
- 同环境运行 `run_air_sea_concurrency.py`：独立进程/数据库连接验证过期删除、重复创建、同时保存。测试显式使用经典 REPEATABLE READ 行为；不修改全局数据库设置。
- 同环境运行 `air_sea_source_lifecycle_checks.py`：引用阻止批次删除，先删除测算后可删除来源。

三个集成脚本均强制仅连接 settlement-test.local / oc-settlement-test-db，使用临时合成记录并清理，不应在生产运行。

## 发布

从执行时最新 `overseas_costing` 发布分支创建隔离开发分支。推送已验证版本至 origin 与 production 的同名发布分支，沿用 DeepLinkERP CI/CD 执行备份、构建、迁移、资源同步及缓存清理。新增流水线检查校验生成资源、DocType、Page 和侧栏前两项顺序；重复迁移重建固定菜单项，不追加重复入口。

上线后验证菜单位置、原工作台与测算页切换、样例金额、保存/重新读取及未授权访问。此次不迁移原 HTML localStorage 记录。此版本只有新增数据结构，失败回退采用代码回退并保留现有数据库，详见发布回退说明。
