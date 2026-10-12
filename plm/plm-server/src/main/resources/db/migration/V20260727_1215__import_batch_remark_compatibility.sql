alter table if exists plm_import_batch
    add column if not exists remark text;
