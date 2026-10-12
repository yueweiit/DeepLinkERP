drop index if exists uk_plm_process_business_operation_code_active;

create unique index if not exists uk_plm_process_route_business_operation_code_active
    on plm_process (parent_process_id, business_operation_code)
    where parent_process_id is not null
      and business_operation_code is not null
      and process_type = 'operation'
      and deleted_flag = 0;
