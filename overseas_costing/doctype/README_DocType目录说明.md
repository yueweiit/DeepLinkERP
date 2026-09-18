# DocType 目录说明

适用目录：`overseas_costing/doctype`

## 当前核心 DocType

| 目录 | 中文名 | 用途 |
| --- | --- | --- |
| `overseas_cost_batch` | 海外成本批次主单 | 表示一票海运/空运/快递批次主单 |
| `overseas_cost_version` | 海外成本版本单 | 表示暂估版/实际版/调整版 |
| `overseas_cost_item` | 海外成本明细行 | 表示单行 SKU / 物料成本明细 |
| `overseas_cost_allocation_rule` | 海外成本分摊规则 | 表示每个费用池的分摊规则 |
| `overseas_cost_attachment` | 海外成本附件单 | 表示附件、凭证、解析任务登记 |
| `overseas_cost_audit_log` | 海外成本审计日志 | 表示编辑、重算、版本切换日志 |
| `overseas_cost_erp_site` | ERP站点配置 | 表示目标 ERP 站点、凭据和能力核验状态，仅管理员维护 |
| `overseas_cost_project_route` | 项目ERP路由 | 表示项目归属到业务主体及 ERP 站点的生效映射 |
| `overseas_cost_erp_document_link` | ERP单据关联 | 表示本地稳定物料行与远端单据行的关联 |
| `overseas_cost_erp_sync_request` | ERP同步请求 | 表示不可变同步请求、回执和重试状态 |

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

当前 ERP 对接先完成“成本确认后按项目归属分站点生成同步草稿”的本地链路：

1. 未配置或冲突的项目路由会阻断整批草稿生成。
2. 草稿保存到 `overseas_cost_erp_sync_request`，用于幂等、审计和后续重试。
3. 站点能力核验只读取目标 ERP 元数据，站点凭据不返回普通业务页面。
4. 启用费用仍为 `MISSING` 或 `ESTIMATED` 时，可继续在海外成本系统暂估核算，但不能生成 ERP 推送草稿或真实推送；`ACTUAL`、`NOT_INCURRED`、`INCLUDED` 才可进入推送门禁。
5. 当前尚未执行真实 ERP 写入，也未定义“暂估转实际”应修改的远端库存成本单据。
