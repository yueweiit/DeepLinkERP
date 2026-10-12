-- Align legacy import metadata tables with the runtime import/export service.
-- Older initialized databases created these tables in V1.0 with title-case object types,
-- workflow-oriented detail statuses, and a raw_data column. The current import service
-- writes lower-case object types, success/fail detail statuses, and raw_payload.

alter table if exists plm_import_batch
    drop constraint if exists ck_plm_import_batch_object_type;

alter table if exists plm_import_batch
    add constraint ck_plm_import_batch_object_type check (
        object_type in (
            'Customer', 'Product', 'Order', 'ProductionOrder', 'Process', 'Inventory', 'Workstation', 'Attachment',
            'product', 'inventory', 'process', 'attachment'
        )
    );

alter table if exists plm_import_detail
    add column if not exists raw_payload jsonb;

do $$
begin
    if to_regclass('plm_import_detail') is not null
       and exists (
           select 1
           from information_schema.columns
           where table_schema = current_schema()
             and table_name = 'plm_import_detail'
             and column_name = 'raw_data'
       ) then
        execute 'update plm_import_detail set raw_payload = raw_data where raw_payload is null and raw_data is not null';
    end if;
end $$;

alter table if exists plm_import_detail
    add column if not exists created_by varchar(64) not null default 'system';

alter table if exists plm_import_detail
    add column if not exists updated_at timestamp not null default now();

alter table if exists plm_import_detail
    add column if not exists updated_by varchar(64) not null default 'system';

alter table if exists plm_import_detail
    add column if not exists deleted_flag smallint not null default 0;

alter table if exists plm_import_detail
    alter column business_key type varchar(255);

alter table if exists plm_import_detail
    drop constraint if exists ck_plm_import_detail_status;

alter table if exists plm_import_detail
    add constraint ck_plm_import_detail_status check (
        status in ('draft', 'in_progress', 'completed', 'failed', 'skipped', 'success', 'fail')
    );
