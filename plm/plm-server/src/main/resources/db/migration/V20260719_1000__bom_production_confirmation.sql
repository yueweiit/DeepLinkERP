create table if not exists plm_process_production_operation_selection (
    process_production_operation_selection_id bigserial primary key,
    product_id bigint not null,
    product_bom_route_id bigint not null,
    process_id bigint not null,
    operation_process_id bigint not null,
    route_version_no varchar(32),
    selection_batch_no varchar(64) not null,
    status varchar(24) not null default 'confirmed',
    confirmed_at timestamp not null,
    confirmed_by varchar(64) not null,
    created_at timestamp not null default current_timestamp,
    created_by varchar(64) not null default 'system',
    updated_at timestamp not null default current_timestamp,
    updated_by varchar(64) not null default 'system',
    deleted_flag integer not null default 0
);

create unique index if not exists uk_process_production_operation_active
    on plm_process_production_operation_selection(product_id, product_bom_route_id, operation_process_id)
    where deleted_flag = 0 and status = 'confirmed';

create table if not exists plm_product_production_color_decision (
    product_production_color_decision_id bigserial primary key,
    product_id bigint not null,
    color_name varchar(64) not null,
    product_bom_id bigint not null,
    product_bom_route_id bigint not null,
    decision_batch_no varchar(64) not null,
    selected_flag integer not null default 1,
    status varchar(24) not null default 'confirmed',
    created_sku_product_id bigint,
    confirmed_at timestamp not null,
    confirmed_by varchar(64) not null,
    created_at timestamp not null default current_timestamp,
    created_by varchar(64) not null default 'system',
    updated_at timestamp not null default current_timestamp,
    updated_by varchar(64) not null default 'system',
    deleted_flag integer not null default 0
);

create unique index if not exists uk_product_production_color_active
    on plm_product_production_color_decision(product_id, color_name)
    where deleted_flag = 0 and status = 'confirmed';
