alter table plm_product
    add column if not exists archived_at timestamp,
    add column if not exists archived_by varchar(64),
    add column if not exists archive_reason text,
    add column if not exists abandoned_at timestamp,
    add column if not exists abandoned_by varchar(64),
    add column if not exists abandon_reason text;

create index if not exists idx_plm_product_status_lock
    on plm_product (status, lock_status)
    where deleted_flag = 0;
