# 服务目录说明

适用目录：`overseas_costing/services`

目录下共 80 余个模块。本文件是**索引**，分两段：早期核心链路（下表）与 ERP 同步链路（下一节）。
其余模块（AI 填充、装箱与拼柜、物流结算、对账等）尚未逐一登记用途——
新增模块时请顺手补一行，不要凭印象概括自己没读过的代码。

## 核心链路（早期骨架）

| 文件 | 中文名 | 用途 |
| --- | --- | --- |
| `batch_service.py` | 批次服务 | 查批次、查明细、检查回写状态 |
| `category_service.py` | 商品品类归类服务 | 规则优先生成归类建议，预留 AI 分类接入点 |
| `import_service.py` | 导入服务 | 导入 Excel / OA 主表、登记附件 |
| `calculate_service.py` | 重算服务 | 编辑字段、批量更新、重算、切换版本 |
| `allocation_service.py` | 分摊服务 | 货值/重量/体积分摊规则占位 |
| `version_service.py` | 版本服务 | 版本摘要、版本复制辅助逻辑 |
| `audit_service.py` | 审计服务 | 写修改日志、重算日志、版本日志 |
| `attachment_parse_service.py` | 附件解析服务 | 装箱单解析任务、完税凭证 PDF 预览解析、解析快照保存、后续 OCR/AI 解析入口 |
| `packing_sheet_cache_service.py` | 装箱 Sheet 缓存服务 | 远程目录增量同步、本地物化预览、单 Sheet 手动刷新和过期状态 |
| `source_priority_service.py` | 来源字段优先级 | 支付申请、国际物流、商品采购逐字段默认值排序，保留低优先级合法候选和人工改选 |

## ERP 同步链路（多站点）

设计见 [`docs/superpowers/specs/2026-09-07-materials-fees-erp-design.md`](../../docs/superpowers/specs/2026-09-07-materials-fees-erp-design.md)，
任务分解见 [`docs/superpowers/plans/2026-09-07-multi-site-erp-sync.md`](../../docs/superpowers/plans/2026-09-07-multi-site-erp-sync.md)。

| 文件 | 中文名 | 用途 |
| --- | --- | --- |
| `erp_client.py` | ERP 客户端 | 站点化 HTTP 客户端：推送采购单、回读远端单据状态与行键映射，**不做隐式物料主数据更新** |
| `erp_routing_service.py` | 项目路由服务 | `project_collection → 公司 + 站点 + 仓库` 的行级解析；匹配走 `project_route_identity()`（NFKD 去音 + 只留字母数字 + 小写 + LEGACY） |
| `erp_site_service.py` | 站点服务 | 站点配置读取、远端元数据能力校验（失败关闭） |
| `erp_capability_service.py` | 能力校验服务 | 按远端 DocType 元数据判断字段合同是否齐备，产出 `capability_status` / `cost_update_mode` 投影 |
| `erp_sync_service.py` | 同步纯逻辑 | 稳定业务键 `purchase_business_key`、`payload_hash`、组单计划、状态机 `ALLOWED_TRANSITIONS`（**无 IO**） |
| `erp_sync_ledger_service.py` | 同步账本服务 | 账本落库与执行：行锁认领、部分成功、成功落 `Overseas Cost ERP Document Link` 行级关联、`UNCERTAIN`/`FAILED` 的核对（`reconcile_sync_request`）与重试（`retry_sync_request`） |
| `erp_sync_plan_service.py` | 站点计划服务 | 站点计划预览/保存/执行、站点请求查询、项目路由候选项 |

> 三个对外的旧入口（`batch_service.preview_erp_payload` / `writeback_to_erp` / `check_writeback_ready`）
> 是**兼容委托**，真源在 `erp_sync_plan_service`；界面目前只调旧入口，站点级界面尚未实现
> （见 [`docs/handover-gaps.md`](../../docs/handover-gaps.md)）。

## 当前约定

1. 真正的业务逻辑放服务层
2. API 层尽量不要直接算业务
3. 后续数据库读写优先从这里集中收口
4. 来源目录和后续核对遵循[字段优先级规则](../../docs/source-field-priority.md)，不因支付资料已关联而隐藏其他合法来源。
5. 前端只读服务端给出的标记与标签（`workflow_stage` / `workflow_label` / `is_voucher_name` / `attachment_category*`），
   不要自己匹配关键词或私造流程真相；服务端是判定的唯一真源。
