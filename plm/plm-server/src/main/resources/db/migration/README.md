# Flyway Migration Placeholder

当前数据库初始化脚本位于 `plm-database/postgres/`。

后续接入 Flyway 时，建议按以下顺序迁移：

- `V1.0__init_schema.sql`
- `V1.1__init_seed_data.sql`
- `V1.2__erp_item_bom_alignment.sql`
- `V1.3__workflow_locking_alignment.sql`
- `V1.3__workflow_locking_seed_data.sql`
