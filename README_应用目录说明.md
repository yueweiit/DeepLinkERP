# 应用目录说明

适用目录：仓库根（app 为 `overseas_costing`，本线分支 `overseas_costing`）

这是接入 ERP 的 Frappe 自定义 app 根目录。

## 目录清单

| 路径 | 中文名 | 用途 |
| --- | --- | --- |
| `setup.py` | 安装配置文件 | 让 app 可被 Frappe/bench 识别和安装 |
| `modules.txt` | 模块声明文件 | 声明应用模块名 |
| `patches.txt` | 补丁登记文件 | 登记后续数据库补丁与数据修复补丁 |
| `requirements.txt` | 依赖文件 | 记录额外依赖 |
| `license.txt` | 许可证文件 | 当前先占位 |
| `overseas_costing/` | 应用 Python 包 | 正式后端代码主体（DocType / API / services / page / scripts / tests） |
| `docs/` | 项目文档 | 来源字段优先级、结算与发布运维说明、设计计划（`docs/superpowers/`） |
| `.github/` | 流水线 | 测试与部署工作流，以及部署脚本（`workflows/`、`scripts/`） |
| `tmp/` | 临时目录 | 本机排查用探针与临时文件，**不入库** |

## 入口索引

1. Doctype 与字段：`overseas_costing/doctype`、`overseas_costing/overseas_costing/doctype`（两份必须一致）
2. 服务层（业务逻辑真源）：`overseas_costing/services`，索引见该目录的 `README_服务目录说明.md`
3. API 层（只做参数入口与结果封装）：`overseas_costing/api`，索引见该目录的 `README_API目录说明.md`
4. 前端：`overseas_costing/page/overseas_cost_workbench/parts`（**源**），
   改完必须跑 `python overseas_costing/scripts/build_workbench_assets.py` 合成产物
5. 测试：`overseas_costing/tests`
   （本机有若干既有红，与 CI 不一致，见 `docs/handover-gaps.md` 第 2.6 节）
6. 交接缺口与运维要点：`docs/handover-gaps.md`
