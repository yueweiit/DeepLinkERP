# 快递费用默认值与墨西哥补录 Implementation Plan

> **For agentic workers:** Use executing-plans to implement the approved scope task-by-task. Steps use checkbox syntax for tracking.

**Goal:** 快递批次的附加费默认暂估 0 RMB，当地快递费默认暂估 0 MXN，清关费与进口税费金额待补、默认 MXN；已保存数据不覆盖。

**Architecture:** 在现有只读模板和费用清单组合层提供 EXPRESS 专用默认值及补录提示，不新增数据库字段或表。前端用服务端派生标记区分默认零与已确认实际零；既有保存、权限、汇率、分摊机制不变。海运与空运保持现状。

**Tech Stack:** Frappe/Python, JavaScript/jQuery, pytest + Node harness, GitHub Actions.

## 用户已确认的设计

- international_express_fee：保留钉钉金额、币种和金额性质。
- express_surcharge：amount="0", amount_status="ESTIMATED", currency="RMB"。
- customs_clearance_fee / import_tax：amount="", amount_status="MISSING", currency="MXN"。
- destination_delivery：显示“当地快递费”，默认 amount="0", amount_status="ESTIMATED", currency="MXN"。
- 后四项提供“由墨西哥同事补充”提示；默认零另提示“默认暂估 0，待墨西哥确认”，不认定为实际或未发生。
- 缺省项仅只读投影。已有记录的金额、币种、状态、备注保留，默认零标记不能泄漏到已保存行。
- 历史“目的地配送费”别名继续匹配同一逻辑项，不产生重复行。清关、税费保持真正待补，不伪造零值。
- 未改动空金额失焦不报错、不写入；主动清空已有金额仍须拦截。零比索不要求汇率，正金额仍要求汇率。

## Task 1: Tests and default projection

**Files:** `overseas_costing/tests/test_fee_service.py`, `overseas_costing/tests/test_cost_preview_service.py`, `overseas_costing/services/fee_service.py`.

- [ ] 添加 EXPRESS 默认值、旧配送别名、已保存覆盖保护、海运空运不变测试；关键断言为 `rows['destination_delivery']['currency'] == 'MXN'`、`rows['express_surcharge']['amount_status'] == 'ESTIMATED'`。
- [ ] 运行 `python3 -m pytest -q overseas_costing/tests/test_fee_service.py overseas_costing/tests/test_cost_preview_service.py`，确认新增断言失败。
- [ ] 模板构造后仅在 mode == EXPRESS 时修改对应字段，增加 `is_default_zero` 和 `entry_responsibility` 只读元数据；已保存行清除默认零标记；配送标签只在读投影统一，保留原始数据。
- [ ] 增加默认零参与试算且不要求比索汇率、未知费用仍排除、正比索缺汇率仍阻断测试；重跑至通过。

## Task 2: UI and unchanged input

**Files:** `overseas_costing/page/overseas_cost_workbench/parts/78-material-fee-workspace.js`, `overseas_costing/tests/test_workbench_frontend_state.py`.

- [ ] 用真实 renderMaterialFeeRow 验证零金额、选中 MXN、暂估与墨西哥提示；用现有输入 fixture 验证原样失焦不产生错误/草稿/写入，清空已保存金额仍报错。
- [ ] 运行 `python3 -m pytest -q overseas_costing/tests/test_workbench_frontend_state.py` 确认新行为先失败。
- [ ] 根据模板只读元数据渲染补录说明；将无变化判断置于空值校验前，仅在金额与币种均未变且不需确认实际时短路。
- [ ] 重跑前端测试，确保已修改输入照常保存 ACTUAL，未改动默认零保留 ESTIMATED。

## Task 3: Verify and release

- [ ] `python3 overseas_costing/scripts/build_workbench_assets.py` 重建生成资源；不手工编辑聚合文件。
- [ ] `python3 -m pytest -q overseas_costing/tests`、`python3 -m compileall -q overseas_costing`、`node --check overseas_costing/page/overseas_cost_workbench/overseas_cost_workbench.js`、`git diff --check` 全部通过。
- [ ] 审查与 production 最新提交的差异，只发布本次规则与测试；使用 production 仓库 GitHub Actions，镜像仓库仅 CI，防止双重部署。
- [ ] 线上只读检查批次 202608281156000332487：国际快递费 2502.920858 保留，附加费 0 RMB、当地快递 0 MXN、清关/税费空 MXN，均有对应性质；验证已保存费用与 20 条物料未改变。
- [ ] 真实浏览器检查费用行与提示，既有数据不进行确认或试算写入。

## Baseline

- Based on production commit `6d51491e31` (includes concurrent fee, packing and linked-approval fixes).
- Clean baseline: 855 tests passed.

## Implementation and pre-release verification

- Tasks 1 and 2 completed with red-green tests: the initial new behavior produced 9 expected failures, then passed after implementation.
- Independent review found and verified two additional legacy edge cases. Four failing regressions were added, then fixed: saved blank/None currency retains the pre-existing RMB interpretation; the new local-delivery alias is restricted to EXPRESS to avoid merging SEA/AIR historical fees.
- Full suite: 873 passed. Reviewer independently ran 137 related tests successfully. Python compile, generated JavaScript syntax, and `git diff --check` passed.
- Frontend aggregate copies rebuilt using the existing script. No database schema or permission changes; no batch data migration.
- Live pre-deploy example now contains three saved fees: international express 2502.920858 RMB estimated, customs 10000 MXN actual, import tax 20000 MXN actual. These saved amounts supersede empty defaults and must be preserved.
- Live pre-deploy digests: 20 item rows `61e344cfc4b8cbf6d39898ac6b82add43cabe313699fcd7708fbccf187534d89`; 3 allocation rules `4f57cb85d68d6ac3fc7dcf83099259a2c662b6ee29cf974113652ab7224d0fc7`.
