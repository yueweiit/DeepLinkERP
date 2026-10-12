create table if not exists plm_product_mold_code (
    product_mold_code_id bigserial primary key,
    product_id bigint not null references plm_product(product_id),
    mold_code varchar(64) not null,
    mold_prefix varchar(16),
    product_code_prefix varchar(16),
    product_specific_code varchar(16),
    mold_name varchar(255),
    key_code varchar(255),
    inventory_id bigint references plm_inventory(inventory_id),
    source_file varchar(255),
    source_row_no integer,
    status varchar(32) not null default 'active',
    created_at timestamp not null default now(),
    created_by varchar(64),
    updated_at timestamp not null default now(),
    updated_by varchar(64),
    deleted_flag integer not null default 0
);

create unique index if not exists ux_plm_product_mold_code_value
    on plm_product_mold_code (mold_code);

create index if not exists idx_plm_product_mold_code_product
    on plm_product_mold_code(product_id)
    where deleted_flag = 0;

create index if not exists idx_plm_product_mold_code_prefix
    on plm_product_mold_code(mold_prefix)
    where deleted_flag = 0;
