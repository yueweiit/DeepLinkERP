alter table if exists plm_process
    drop constraint if exists uk_plm_process_code;

drop index if exists uk_plm_process_code;

create unique index if not exists uk_plm_process_code
    on plm_process (process_code)
    where process_code is not null and deleted_flag = 0;
