create table if not exists plm_import_batch (
    import_batch_id bigserial primary key,
    object_type varchar(64) not null,
    file_name varchar(255) not null,
    total_count integer not null default 0,
    success_count integer not null default 0,
    fail_count integer not null default 0,
    status varchar(32) not null default 'draft',
    remark text,
    created_at timestamp not null default now(),
    created_by varchar(64) not null default 'system',
    updated_at timestamp not null default now(),
    updated_by varchar(64) not null default 'system',
    deleted_flag integer not null default 0
);

create index if not exists idx_plm_import_batch_object_status
    on plm_import_batch (object_type, status, created_at desc);

create table if not exists plm_import_detail (
    import_detail_id bigserial primary key,
    import_batch_id bigint not null references plm_import_batch(import_batch_id),
    row_no integer not null,
    business_key varchar(255),
    status varchar(32) not null,
    error_message text,
    raw_payload jsonb,
    created_at timestamp not null default now(),
    created_by varchar(64) not null default 'system',
    updated_at timestamp not null default now(),
    updated_by varchar(64) not null default 'system',
    deleted_flag integer not null default 0
);

create index if not exists idx_plm_import_detail_batch_status
    on plm_import_detail (import_batch_id, status, row_no);

alter table if exists plm_product
    drop constraint if exists ck_plm_product_type;

alter table if exists plm_product
    add constraint ck_plm_product_type check (product_type in ('product_line', 'model_variant', 'sku'));

alter table if exists plm_product
    drop constraint if exists ck_plm_product_variant_parent;

alter table if exists plm_product
    add constraint ck_plm_product_variant_parent check (
        product_type not in ('model_variant', 'sku') or parent_product_id is not null
    );
