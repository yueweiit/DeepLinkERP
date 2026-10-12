alter table if exists plm_attachment
    add column if not exists preview_type varchar(32),
    add column if not exists preview_status varchar(32) not null default 'none',
    add column if not exists preview_storage_key varchar(512),
    add column if not exists preview_error_message varchar(1000);

create index if not exists idx_plm_attachment_preview_status
    on plm_attachment(preview_status, created_at desc)
    where deleted_flag = 0;

create table if not exists plm_project_mold_transfer_express (
    mold_transfer_express_id bigserial primary key,
    project_id bigint not null,
    timeline_node_key varchar(128) not null,
    carrier_code varchar(64),
    carrier_name varchar(128),
    tracking_no varchar(128) not null,
    sender_name varchar(128),
    sender_phone varchar(64),
    receiver_name varchar(128),
    receiver_phone varchar(64),
    ship_from varchar(255),
    ship_to varchar(255),
    shipped_at timestamp,
    latest_status varchar(64) not null default 'pending',
    latest_status_text varchar(500),
    latest_checkpoint_at timestamp,
    last_query_at timestamp,
    query_status varchar(32) not null default 'not_queried',
    query_error_message varchar(1000),
    raw_trace_json text,
    status varchar(32) not null default 'active',
    remark text,
    created_at timestamp not null default current_timestamp,
    created_by varchar(64) not null default 'system',
    updated_at timestamp not null default current_timestamp,
    updated_by varchar(64) not null default 'system',
    deleted_flag integer not null default 0
);

create unique index if not exists uk_plm_mold_transfer_express_project_node
    on plm_project_mold_transfer_express(project_id, timeline_node_key)
    where deleted_flag = 0;

create index if not exists idx_plm_mold_transfer_express_tracking
    on plm_project_mold_transfer_express(carrier_code, tracking_no)
    where deleted_flag = 0;
