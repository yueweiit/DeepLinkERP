create table if not exists plm_product_bom_route_formal_selection (
    product_bom_route_formal_selection_id bigserial primary key,
    product_id bigint not null,
    product_bom_id bigint not null,
    product_bom_route_id bigint not null,
    process_id bigint not null,
    bom_version_no varchar(32),
    selection_batch_no varchar(64) not null,
    status varchar(24) not null default 'active',
    confirmed_at timestamp not null,
    confirmed_by varchar(64) not null,
    invalidated_at timestamp,
    invalidated_reason text,
    remark text,
    created_at timestamp not null default current_timestamp,
    created_by varchar(64) not null default 'system',
    updated_at timestamp not null default current_timestamp,
    updated_by varchar(64) not null default 'system',
    deleted_flag integer not null default 0
);

create unique index if not exists uk_product_bom_route_formal_active
    on plm_product_bom_route_formal_selection(product_id, process_id)
    where status = 'active' and deleted_flag = 0;

create index if not exists idx_product_bom_route_formal_bom
    on plm_product_bom_route_formal_selection(product_bom_id, product_bom_route_id, status, deleted_flag);

create index if not exists idx_product_bom_route_formal_project
    on plm_product_bom_route_formal_selection(product_id, status, confirmed_at desc)
    where deleted_flag = 0;
