create table if not exists plm_project_cost_item (
    project_cost_item_id bigserial primary key,
    product_id bigint not null,
    cost_category varchar(32) not null,
    cost_name varchar(128) not null,
    amount numeric(18, 6) not null default 0,
    currency_code varchar(16) not null default 'CNY',
    supplier_name varchar(128),
    occurred_at timestamp,
    status varchar(32) not null default 'draft',
    confirmed_at timestamp,
    confirmed_by varchar(64),
    voided_at timestamp,
    voided_by varchar(64),
    remark text,
    created_at timestamp not null default current_timestamp,
    created_by varchar(64) not null default 'system',
    updated_at timestamp not null default current_timestamp,
    updated_by varchar(64) not null default 'system',
    deleted_flag integer not null default 0
);

create index if not exists idx_plm_project_cost_item_product_category_status
    on plm_project_cost_item(product_id, cost_category, status)
    where deleted_flag = 0;

create index if not exists idx_plm_project_cost_item_product_updated
    on plm_project_cost_item(product_id, updated_at desc)
    where deleted_flag = 0;
