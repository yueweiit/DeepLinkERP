alter table if exists plm_product_bom
    add column if not exists bom_scope varchar(16) not null default 'formal',
    add column if not exists source_type varchar(16) not null default 'manual',
    add column if not exists source_product_id bigint,
    add column if not exists source_product_bom_id bigint,
    add column if not exists test_total_cost numeric(18,6),
    add column if not exists currency_code varchar(8) not null default 'CNY',
    add column if not exists calculated_at timestamp,
    add column if not exists confirmed_at timestamp,
    add column if not exists confirmed_by varchar(64),
    add column if not exists frozen_flag integer not null default 0,
    add column if not exists released_at timestamp,
    add column if not exists released_by varchar(64);

alter table if exists plm_product_bom_item
    add column if not exists product_bom_route_id bigint,
    add column if not exists unit_cost_snapshot numeric(18,6),
    add column if not exists currency_code varchar(8) not null default 'CNY';

create table if not exists plm_product_bom_route (
    product_bom_route_id bigserial primary key,
    product_bom_id bigint not null,
    product_id bigint not null,
    process_id bigint not null,
    route_code varchar(64) not null,
    route_name varchar(255) not null,
    status varchar(16) not null default 'active',
    source_product_bom_route_id bigint,
    created_at timestamp not null default now(),
    created_by varchar(64) not null default 'system',
    updated_at timestamp not null default now(),
    updated_by varchar(64) not null default 'system',
    deleted_flag integer not null default 0
);

create unique index if not exists uk_plm_product_bom_route_process
    on plm_product_bom_route (product_bom_id, process_id)
    where status = 'active' and deleted_flag = 0;

create index if not exists idx_plm_product_bom_route_product
    on plm_product_bom_route (product_id, product_bom_id, status, deleted_flag);

create table if not exists plm_product_bom_route_color (
    product_bom_route_color_id bigserial primary key,
    product_bom_id bigint not null,
    product_bom_route_id bigint not null,
    color_name varchar(64) not null,
    status varchar(16) not null default 'active',
    created_at timestamp not null default now(),
    created_by varchar(64) not null default 'system',
    updated_at timestamp not null default now(),
    updated_by varchar(64) not null default 'system',
    deleted_flag integer not null default 0
);

create unique index if not exists uk_plm_product_bom_route_color_active
    on plm_product_bom_route_color (product_bom_id, color_name)
    where status = 'active' and deleted_flag = 0;

create index if not exists idx_plm_product_bom_route_color_route
    on plm_product_bom_route_color (product_bom_route_id, status, deleted_flag);

create table if not exists plm_product_bom_cost_snapshot (
    product_bom_cost_snapshot_id bigserial primary key,
    product_bom_id bigint not null,
    product_bom_route_id bigint not null,
    product_id bigint not null,
    version_no varchar(32) not null,
    material_cost numeric(18,6) not null default 0,
    loss_cost numeric(18,6) not null default 0,
    process_cost numeric(18,6) not null default 0,
    package_cost numeric(18,6) not null default 0,
    labor_cost numeric(18,6) not null default 0,
    tooling_cost numeric(18,6) not null default 0,
    other_cost numeric(18,6) not null default 0,
    total_cost numeric(18,6) not null default 0,
    currency_code varchar(8) not null default 'CNY',
    source_snapshot_json jsonb not null default '{}'::jsonb,
    calculated_at timestamp not null,
    status varchar(16) not null default 'current',
    created_at timestamp not null default now(),
    created_by varchar(64) not null default 'system',
    updated_at timestamp not null default now(),
    updated_by varchar(64) not null default 'system',
    deleted_flag integer not null default 0
);

create unique index if not exists uk_plm_product_bom_cost_current
    on plm_product_bom_cost_snapshot (product_bom_id, product_bom_route_id)
    where status = 'current' and deleted_flag = 0;

create table if not exists plm_product_bom_import_batch (
    product_bom_import_batch_id bigserial primary key,
    product_id bigint not null,
    product_bom_id bigint,
    import_token varchar(64) not null,
    bom_scope varchar(16) not null,
    file_name varchar(255) not null,
    status varchar(16) not null default 'previewed',
    total_rows integer not null default 0,
    valid_rows integer not null default 0,
    error_rows integer not null default 0,
    preview_json jsonb not null default '[]'::jsonb,
    error_json jsonb not null default '[]'::jsonb,
    expires_at timestamp not null,
    committed_at timestamp,
    committed_by varchar(64),
    created_at timestamp not null default now(),
    created_by varchar(64) not null default 'system',
    updated_at timestamp not null default now(),
    updated_by varchar(64) not null default 'system',
    deleted_flag integer not null default 0
);

create unique index if not exists uk_plm_product_bom_import_token
    on plm_product_bom_import_batch (import_token);

create index if not exists idx_plm_product_bom_import_product
    on plm_product_bom_import_batch (product_id, status, created_at desc);
