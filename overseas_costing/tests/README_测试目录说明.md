# 测试目录说明

适用目录：`overseas_costing/tests`

## 怎么跑

```bash
# 本机（需要 node 在 PATH 里：前端测试会把 parts 源码塞进 Node 跑）
export PATH="/c/Users/lin/.workbuddy/binaries/node/versions/22.22.2-3:$PATH"
cd DeepLinkERP
PYTHONUTF8=1 PYTHONIOENCODING=utf-8 python -m pytest overseas_costing/tests/<file>.py -q -p no:cacheprovider --basetemp=.pytest_tmp

# 只跑"这次改动会波及到的"测试（CI 用的就是这个选择器）
python overseas_costing/scripts/run_affected_tests.py            # 另见 test_affected_tests.py
```

**本机全量基线是红的**（62 failed / 4438 passed / 1 skipped），红全在经理域的 AI 相关文件里，
而 CI 同批是绿的（本机缺 `frappe` / `psycopg` / `minio`）。判断回归的正确方法是：
看失败清单里有没有**自己改过的文件**，而不是看总数。详见 `docs/handover-gaps.md` 2.6。

## 约定

1. 服务端测试直接 import `overseas_costing.services.*`，用 `monkeypatch` 打桩 Frappe 依赖，
   不连真库；需要 DB 的走 `frappe` 可用性判断后跳过。
2. 前端测试不启浏览器：把 `page/overseas_cost_workbench/parts/*.js` 的源码读出来，
   用 `Function('return class {…}')()` 拼成一个类在 Node 里跑（见
   `test_workbench_frontend_state.py` 的 `_fee_workspace_result`），或做源码级断言。
   **夹具只加载部分 parts 时，跨部件调用必须写成可选链**，否则 `TypeError`。
3. 测试数量变化要在提交信息里说明原因；不要为了让测试变绿放宽断言。

## 按域划分（172 个文件）

| 域 | 代表文件 |
| --- | --- |
| 批次 / 工作台 | `test_batch_service` `test_workbench_service` `test_workbench_query_scope` `test_workbench_review_readiness` `test_version_lifecycle` `test_access_control` |
| 费用与凭证 | `test_fee_service` `test_fee_allocation_service` `test_fee_status_service` `test_fee_evidence_review_service` `test_fee_doctypes` `test_supplier_resolution_service` |
| 物料与 AI 填充 | `test_material_input_service` `test_material_import_service` `test_material_ai_*`（10 个） `test_material_grid_reviews` `test_material_bulk_edit_service` `test_material_scope_reset` `test_materials_api` |
| 计算 / 试算 | `test_calculate_service` `test_calculate_preview_api` `test_cost_preview_service` `test_cost_trial_ai_service` `test_saved_comprehensive_cost` `test_saved_trial_regressions` |
| ERP 同步（多站点） | `test_erp_client` `test_erp_routing_service` `test_erp_sync_service` `test_erp_sync_ledger_service` `test_erp_sync_plan_service` `test_erp_capability_service` `test_erp_site_service` `test_erp_work_state` `test_erp_sync_doctypes` |
| 装箱 / 物流 / 月结 | `test_packing_*`（11 个） `test_logistics_*`（8 个） `test_settlement_*`（17 个） `test_freight_*` `test_payment_*` |
| 空海运对比 / 利润 | `test_air_sea_*`（7 个） `test_profit_service` `test_shipment_*` |
| 数据源与导入 | `test_dingtalk*`（7 个） `test_import_service` `test_transport_import_service` `test_unified_*` `test_source_*` `test_field_mapper` `test_excel_*` |
| 前端界面 | `test_*_ui`（14 个）+ `test_*_frontend`（5 个）+ `test_workbench_asset_builder`（产物构建校验） |
| 发布 / 部署 / 仓库外基础设施 | `test_deploy_workflow` `test_additive_release_rollback` `test_host_infra_archive` `test_workbench_release` `test_affected_tests` |
