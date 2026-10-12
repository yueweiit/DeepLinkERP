-- Source code catalog only. A code is not a physical set, a receipt or inventory quantity.
create table if not exists plm_mold_code_source (
    source_code_id bigserial primary key,
    source_system varchar(32) not null check (source_system in ('erp', 'dingtalk')),
    mold_code varchar(64) not null,
    mold_name varchar(512) not null,
    item_group varchar(255),
    specifications varchar(4000),
    original_alias varchar(512),
    source_disabled boolean not null default false,
    source_modified_at varchar(64),
    product_specific_code varchar(2),
    phone_model_code varchar(4),
    part_type varchar(3) check (part_type in ('PC', 'TPU')),
    approval_instance_id varchar(128),
    approval_status varchar(32),
    payload_fingerprint varchar(64) not null,
    source_event_id varchar(128) not null,
    created_at timestamp not null default current_timestamp,
    created_by varchar(64) not null,
    unique (source_system, mold_code)
);
create index if not exists idx_mold_code_source_identity
    on plm_mold_code_source(source_system, product_specific_code, phone_model_code, part_type);
comment on table plm_mold_code_source is 'ERP/钉钉原编码待核对资料；不生成实物模具、套次、库存或交付状态';
