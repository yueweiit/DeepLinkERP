alter table if exists plm_product
    add column if not exists expected_delivery_date date,
    add column if not exists source_system varchar(32),
    add column if not exists source_instance_id varchar(128),
    add column if not exists source_form_url varchar(1000),
    add column if not exists source_approved_at timestamp;

create index if not exists idx_plm_product_source_instance
    on plm_product(source_system, source_instance_id)
    where source_system is not null and source_instance_id is not null and deleted_flag = 0;

alter table if exists plm_attachment
    add column if not exists source_system varchar(32),
    add column if not exists source_file_id varchar(256),
    add column if not exists source_url varchar(1000);

create index if not exists idx_plm_attachment_source_file
    on plm_attachment(source_system, source_file_id)
    where source_system is not null and source_file_id is not null and deleted_flag = 0;

alter table if exists plm_integration_record
    add column if not exists process_code varchar(128),
    add column if not exists direction varchar(16),
    add column if not exists node_key varchar(128),
    add column if not exists external_url varchar(1000),
    add column if not exists retry_count integer not null default 0,
    add column if not exists last_triggered_at timestamp;

update plm_integration_record
set direction = 'inbound'
where direction is null
  and deleted_flag = 0;

create unique index if not exists uk_plm_integration_dingtalk_outbound_node
    on plm_integration_record(source_system, integration_type, project_id, node_key, direction)
    where deleted_flag = 0 and direction = 'outbound';
