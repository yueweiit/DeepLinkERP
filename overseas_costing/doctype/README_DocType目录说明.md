# DocType 目录说明

适用目录：`overseas_costing/doctype`

## 当前核心 DocType

共 21 个（`overseas_cost_erp_settings` 是单例，其余都是独立单表，没有子表 DocType）。

| 目录 | 中文名 | 用途 |
| --- | --- | --- |
| `overseas_cost_batch` | 海外成本批次主单 | 表示一票海运/空运/快递批次主单 |
| `overseas_cost_version` | 海外成本版本单 | 表示暂估版/实际版/调整版 |
| `overseas_cost_item` | 海外成本明细行 | 表示单行 SKU / 物料成本明细 |
| `overseas_cost_allocation_rule` | 海外成本分摊规则 | 表示每个费用池的分摊规则 |
| `overseas_cost_attachment` | 海外成本附件单 | 表示附件、凭证、解析任务登记 |
| `overseas_cost_audit_log` | 海外成本审计日志 | 表示编辑、重算、版本切换日志 |
| `overseas_cost_fee_evidence` | 费用凭证证据 | 表示费用的最终凭证与校验状态 |
| `overseas_cost_fee_evidence_ai_run` | 凭证 AI 校验运行 | 表示凭证 AI 复核的每次运行与结论 |
| `overseas_cost_fee_sku_component` | 费用 SKU 分摊明细 | 表示一笔费用分到各 SKU 的分量 |
| `overseas_cost_erp_settings` | ERP 连接设置（**单例**） | 默认站点 `DEEPLINKERP` 的连接、凭据与报文映射；必须 `frappe.get_single` |
| `overseas_cost_erp_site` | ERP 站点配置 | 非默认站点的连接、凭据与能力核验状态，仅管理员维护 |
| `overseas_cost_project_route` | 项目 ERP 路由 | 项目归属 → 业务主体 / ERP 站点 / 收货仓库的生效映射（真键是 `project_collection`） |
| `overseas_cost_erp_document_link` | ERP 单据关联 | 本地稳定物料行与远端单据行的关联（按 `(business_key, stable_line_key)` 原地更新） |
| `overseas_cost_erp_sync_request` | ERP 同步请求账本 | 不可变同步请求、回执与重试状态；站点级待办的唯一事实来源 |
| `overseas_cost_review_round` | 成本复核轮次 | 表示一次复核整改的轮次 |
| `overseas_cost_review_issue` | 成本复核问题 | 表示轮次下的具体整改问题 |
| `overseas_cost_trial_ai_run` | 成本试算 AI 运行 | 表示成本试算 AI 的每次运行与预览 |
| `overseas_cost_usage_log` | 使用记录 | 工作台动作留痕 |
| `overseas_air_sea_comparison` | 空海运成本对比 | 独立于批次的空/海运测算记录 |
| `overseas_freight_comparison` | 运费对比 | 装箱来源的独立运费试算 |
| `overseas_packing_snapshot` | 装箱单快照 | 装箱来源的不可变快照 |

## 每个 DocType 目录内文件用途

| 文件 | 中文名 | 用途 |
| --- | --- | --- |
| `*.json` | DocType 元数据定义 | 定义字段、权限、列表展示、排序等 |
| `*.py` | DocType 控制器 | 放校验逻辑和后续单据行为 |
| `__init__.py` | 包入口文件 | 让 Frappe / Python 识别目录 |

## 当前阶段说明

这一版 JSON 先放“第一版最小字段骨架”，
后续会继续根据：

1. Excel A~BE 字段
2. OA 国际物流单映射
3. 版本、留痕、回写需求

继续补全字段。

## 分站点同步边界

当前 ERP 对接完成“成本确认后按项目归属分站点生成同步草稿”的本地链路：

1. 未配置或冲突的项目路由会阻断整批草稿生成。
2. 草稿保存到 `overseas_cost_erp_sync_request`，用于幂等、审计和后续重试。
3. 站点能力核验只读取目标 ERP 元数据，站点凭据不返回普通业务页面。
4. 推送门槛看**费用性质**是否允许：`ACTUAL`、`NOT_INCURRED`、`INCLUDED` 才可进入推送门禁。
5. **站点级待办**由 `services/fee_status_service.build_erp_work_state()` 从账本派生
   （`SYNCED` / `UPDATE_REQUIRED` / `IN_PROGRESS` / `ATTENTION_REQUIRED` / `NOT_PUSHED`），
   批次级 `writeback_status` 只是它的历史投影，页面不再自行推导。
6. “暂估转实际”应修改的远端单据**仍未定义**：`cost_update_mode` 只存在于
   `overseas_cost_erp_site`，而默认站点走单例 `overseas_cost_erp_settings`（没有该字段），
   所以线上没有启用路径。详见 `docs/handover-gaps.md` 1.2。
