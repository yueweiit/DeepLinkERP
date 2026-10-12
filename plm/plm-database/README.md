# PLM 数据库搭建包

本目录用于沉淀手机壳制造业 PLM 系统的 PostgreSQL 数据库设计与基础搭建脚本。

## 文件说明

- `docs/数据库设计与搭建实施方案.md`：数据库设计、实施步骤、风险和验收建议。
- `postgres/V1.0__init_schema.sql`：建表、主外键、索引、约束、表注释。
- `postgres/V1.1__init_seed_data.sql`：字典、角色、权限、编码规则、基础审批定义。
- `postgres/V1.2__erp_item_bom_alignment.sql`：对照 ERPNext Item/BOM 补充后续映射友好的预留字段。
- `postgres/V1.3__workflow_locking_alignment.sql`：补齐审批、冻结、版本追溯、模具机台关系、导入/集成状态机等增量结构。
- `postgres/V1.3__workflow_locking_seed_data.sql`：补齐 V1.3 对应的字典、权限、系统配置种子数据。
- `postgres/docker-compose.database.yml`：仅启动 PostgreSQL 的数据库验证 compose。

## 快速启动

```bash
cd postgres
docker compose --env-file .env.database -f docker-compose.database.yml up -d
```

说明：

- 当前默认通过 Docker Desktop 运行。
- 本地默认映射端口为 `5433`，避免与宿主机已有 PostgreSQL `5432` 冲突。
- 启动后可直接在 Docker Desktop 中看到 `plm-postgres` 容器。

首次启动时，PostgreSQL 会自动执行：

```text
V1.0__init_schema.sql
V1.1__init_seed_data.sql
V1.2__erp_item_bom_alignment.sql
V1.3__workflow_locking_alignment.sql
V1.3__workflow_locking_seed_data.sql
```

连接参数：

```text
host: localhost
port: 5433
database: plm
username: plm
password: plm123
```

## 验证 SQL

```bash
docker exec -it plm-postgres psql -U plm -d plm -c "select count(*) from information_schema.tables where table_schema='plm';"
docker exec -it plm-postgres psql -U plm -d plm -c "select count(*) from plm.sys_dict_item;"
docker exec -it plm-postgres psql -U plm -d plm -c "select status from plm.plm_approval_instance group by status;"
```

## 设计边界

- 当前只建设 PLM 数据库。
- 不实现 ERP/MES/WMS/CRM 正式业务闭环。
- 全系统只保留 7 个核心对象作为一级业务对象。
- BOM、样品、报价、变更、文件、质量资料均作为扩展表或附件记录承载。
- ERPNext Item/BOM 参考字段只作为映射预留，不代表本期实现 ERP 库存、采购、税务或财务流程。
