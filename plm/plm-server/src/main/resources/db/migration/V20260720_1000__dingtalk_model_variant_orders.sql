alter table if exists plm_order add column if not exists project_id bigint;
alter table if exists plm_order add column if not exists ding_talk_approval_no varchar(128);
alter table if exists plm_order add column if not exists project_type varchar(32);
alter table if exists plm_order add column if not exists phone_model varchar(128);
alter table if exists plm_order add column if not exists product_name varchar(255);
alter table if exists plm_order add column if not exists previous_status varchar(32);
alter table if exists plm_order add column if not exists close_reason varchar(500);
alter table if exists plm_order add column if not exists closed_at timestamp;
alter table if exists plm_order add column if not exists closed_by varchar(64);
alter table if exists plm_order add column if not exists source_action varchar(64);
alter table if exists plm_order add column if not exists customer_requirement text;
alter table if exists plm_order add column if not exists source_payload_json text;

create unique index if not exists uk_plm_order_ding_talk_approval_no
    on plm_order(ding_talk_approval_no)
    where ding_talk_approval_no is not null and deleted_flag = 0;

create unique index if not exists uk_plm_order_project
    on plm_order(project_id)
    where project_id is not null and deleted_flag = 0;

create index if not exists idx_plm_order_status_created_at
    on plm_order(status, created_at desc);

create table if not exists plm_integration_record (
    integration_record_id bigserial primary key,
    source_system varchar(32) not null,
    integration_type varchar(64) not null,
    external_instance_id varchar(128) not null,
    external_status varchar(32) not null,
    source_payload_json text,
    processing_status varchar(32) not null,
    order_id bigint,
    project_id bigint,
    error_code varchar(64),
    error_message varchar(1000),
    created_at timestamp not null default current_timestamp,
    created_by varchar(64) not null,
    updated_at timestamp not null default current_timestamp,
    updated_by varchar(64) not null,
    deleted_flag integer not null default 0
);

create unique index if not exists uk_plm_integration_external_instance
    on plm_integration_record(source_system, integration_type, external_instance_id)
    where deleted_flag = 0;

create table if not exists plm_product_variant_color (
    variant_color_id bigserial primary key,
    project_product_id bigint not null,
    source_product_id bigint not null,
    source_decision_id bigint not null,
    code_item_id bigint,
    color_code varchar(64),
    color_name varchar(128) not null,
    source_decision_batch_no varchar(128),
    source_confirmed_at timestamp,
    default_selected_flag integer not null default 1,
    selected_flag integer not null default 1,
    deselected_at timestamp,
    deselected_by varchar(64),
    snapshot_status varchar(32) not null default 'active',
    created_at timestamp not null default current_timestamp,
    created_by varchar(64) not null,
    updated_at timestamp not null default current_timestamp,
    updated_by varchar(64) not null,
    deleted_flag integer not null default 0
);

create unique index if not exists uk_plm_variant_color_project_code
    on plm_product_variant_color(project_product_id, code_item_id)
    where deleted_flag = 0;

create table if not exists plm_project_requirement_form (
    requirement_form_id bigserial primary key,
    project_id bigint not null,
    ding_talk_approval_no varchar(128) not null,
    network_type varchar(32),
    hole_type varchar(64),
    mobile_function text,
    tipo varchar(128),
    priority varchar(32),
    manufacturing_location varchar(128),
    mold_marking varchar(128),
    reference_url varchar(1000),
    remark text,
    expected_delivery_date date,
    requirement_type varchar(32),
    customer_requirement text,
    status varchar(32) not null default 'draft',
    confirmed_at timestamp,
    confirmed_by varchar(64),
    created_at timestamp not null default current_timestamp,
    created_by varchar(64) not null,
    updated_at timestamp not null default current_timestamp,
    updated_by varchar(64) not null,
    deleted_flag integer not null default 0
);

create unique index if not exists uk_plm_requirement_form_project
    on plm_project_requirement_form(project_id)
    where deleted_flag = 0;
