create table if not exists plm_product_bom (
    product_bom_id bigserial primary key,
    product_id bigint not null,
    bom_code varchar(64) not null,
    bom_name varchar(255) not null,
    bom_type varchar(64) not null,
    version_no varchar(32) not null,
    status varchar(32) not null default 'draft',
    frozen_at timestamp,
    frozen_by varchar(64),
    remark text,
    created_at timestamp not null default now(),
    created_by varchar(64) not null default 'system',
    updated_at timestamp not null default now(),
    updated_by varchar(64) not null default 'system',
    deleted_flag integer not null default 0
);

create unique index if not exists uk_plm_product_bom_code
    on plm_product_bom (bom_code);

create index if not exists idx_plm_product_bom_product
    on plm_product_bom (product_id, version_no, status);

create table if not exists plm_product_bom_item (
    product_bom_item_id bigserial primary key,
    product_bom_id bigint not null,
    inventory_id bigint,
    item_code varchar(64),
    item_name varchar(255) not null,
    specification varchar(255),
    line_no integer not null,
    quantity numeric(18,6) not null,
    unit varchar(32) not null,
    loss_rate numeric(10,4) not null default 0,
    substitute_flag integer not null default 0,
    remark text,
    status varchar(32) not null default 'draft',
    created_at timestamp not null default now(),
    created_by varchar(64) not null default 'system',
    updated_at timestamp not null default now(),
    updated_by varchar(64) not null default 'system',
    deleted_flag integer not null default 0
);

create unique index if not exists uk_plm_product_bom_item_line
    on plm_product_bom_item (product_bom_id, line_no)
    where deleted_flag = 0;

create index if not exists idx_plm_product_bom_item_bom
    on plm_product_bom_item (product_bom_id, deleted_flag);

create table if not exists plm_process (
    process_id bigserial primary key,
    parent_process_id bigint,
    product_id bigint not null,
    process_code varchar(64) not null,
    process_name varchar(255) not null,
    process_type varchar(32) not null,
    version_no varchar(32) not null default 'A',
    sequence_no integer,
    process_param_json text,
    standard_time_mins numeric(10,2),
    quality_requirement text,
    status varchar(32) not null default 'draft',
    frozen_at timestamp,
    frozen_by varchar(64),
    remark text,
    created_at timestamp not null default now(),
    created_by varchar(64) not null default 'system',
    updated_at timestamp not null default now(),
    updated_by varchar(64) not null default 'system',
    deleted_flag integer not null default 0
);

alter table if exists plm_process
    add column if not exists parent_process_id bigint,
    add column if not exists product_id bigint,
    add column if not exists process_code varchar(64),
    add column if not exists process_name varchar(255),
    add column if not exists process_type varchar(32),
    add column if not exists version_no varchar(32) not null default 'A',
    add column if not exists sequence_no integer,
    add column if not exists process_param_json text,
    add column if not exists standard_time_mins numeric(10,2),
    add column if not exists quality_requirement text,
    add column if not exists status varchar(32) not null default 'draft',
    add column if not exists frozen_at timestamp,
    add column if not exists frozen_by varchar(64),
    add column if not exists remark text,
    add column if not exists created_at timestamp not null default now(),
    add column if not exists created_by varchar(64) not null default 'system',
    add column if not exists updated_at timestamp not null default now(),
    add column if not exists updated_by varchar(64) not null default 'system',
    add column if not exists deleted_flag integer not null default 0;

create unique index if not exists uk_plm_process_code
    on plm_process (process_code)
    where process_code is not null;

create index if not exists idx_plm_process_product_type
    on plm_process (product_id, process_type, status);

create index if not exists idx_plm_process_parent
    on plm_process (parent_process_id, sequence_no);

create table if not exists plm_attachment (
    attachment_id bigserial primary key,
    owner_object_type varchar(64) not null,
    owner_object_id bigint not null,
    timeline_node_key varchar(128),
    file_category varchar(64) not null,
    file_name varchar(255) not null,
    original_file_name varchar(255) not null,
    file_ext varchar(32),
    content_type varchar(128),
    file_size bigint not null,
    checksum varchar(128),
    storage_type varchar(32) not null default 'local',
    storage_key varchar(512) not null,
    version_no varchar(32) not null default 'V1',
    status varchar(32) not null default 'draft',
    remark text,
    created_at timestamp not null default now(),
    created_by varchar(64) not null default 'system',
    updated_at timestamp not null default now(),
    updated_by varchar(64) not null default 'system',
    deleted_flag integer not null default 0
);

alter table if exists plm_attachment
    add column if not exists attachment_id bigserial,
    add column if not exists owner_object_type varchar(64),
    add column if not exists owner_object_id bigint,
    add column if not exists timeline_node_key varchar(128),
    add column if not exists file_category varchar(64),
    add column if not exists file_name varchar(255),
    add column if not exists original_file_name varchar(255),
    add column if not exists file_ext varchar(32),
    add column if not exists content_type varchar(128),
    add column if not exists file_size bigint,
    add column if not exists checksum varchar(128),
    add column if not exists storage_type varchar(32) default 'local',
    add column if not exists storage_key varchar(512),
    add column if not exists version_no varchar(32) default 'V1',
    add column if not exists status varchar(32) default 'draft',
    add column if not exists remark text,
    add column if not exists created_at timestamp default now(),
    add column if not exists created_by varchar(64) default 'system',
    add column if not exists updated_at timestamp default now(),
    add column if not exists updated_by varchar(64) default 'system',
    add column if not exists deleted_flag integer not null default 0;

create index if not exists idx_plm_attachment_owner_node
    on plm_attachment (owner_object_type, owner_object_id, timeline_node_key, deleted_flag);

create index if not exists idx_plm_attachment_file_center
    on plm_attachment (owner_object_id, timeline_node_key, file_category, created_at desc);

create table if not exists plm_attachment_download_log (
    download_log_id bigserial primary key,
    attachment_id bigint not null,
    operator_user_id bigint,
    operator_user_name varchar(64),
    request_id varchar(64),
    client_ip varchar(64),
    user_agent varchar(512),
    created_at timestamp not null default now(),
    created_by varchar(64) not null default 'system',
    updated_at timestamp not null default now(),
    updated_by varchar(64) not null default 'system',
    deleted_flag integer not null default 0
);

create index if not exists idx_plm_attachment_download_attachment
    on plm_attachment_download_log (attachment_id, created_at desc);
