create table if not exists plm_code_item (
    code_item_id bigserial primary key,
    code_type varchar(32) not null,
    code_value varchar(64) not null,
    code_name varchar(128) not null,
    status varchar(16) not null default 'enabled',
    sort_order integer not null default 0,
    created_at timestamp not null default current_timestamp,
    created_by varchar(64) not null default 'system',
    updated_at timestamp not null default current_timestamp,
    updated_by varchar(64) not null default 'system',
    deleted_flag integer not null default 0
);

create unique index if not exists uk_plm_code_item_type_value_active
    on plm_code_item(code_type, code_value)
    where deleted_flag = 0;

create index if not exists idx_plm_code_item_query
    on plm_code_item(code_type, status, sort_order, code_value)
    where deleted_flag = 0;

alter table if exists plm_product_bom_route_color
    add column if not exists code_item_id bigint,
    add column if not exists color_code varchar(64);

alter table if exists plm_product_production_color_decision
    add column if not exists code_item_id bigint,
    add column if not exists color_code varchar(64);

create index if not exists idx_plm_product_bom_route_color_code_item
    on plm_product_bom_route_color(code_item_id)
    where deleted_flag = 0;

create index if not exists idx_plm_product_production_color_code_item
    on plm_product_production_color_decision(code_item_id)
    where deleted_flag = 0;
