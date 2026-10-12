alter table if exists plm_process
    add column if not exists product_specific_code varchar(20),
    add column if not exists phone_model_code varchar(20),
    add column if not exists color_code varchar(20),
    add column if not exists generated_finished_product_code varchar(80),
    add column if not exists code_generation_context varchar(30);

drop index if exists idx_plm_process_business_operation_code;

create unique index if not exists uk_plm_process_business_operation_code_active
    on plm_process (business_operation_code)
    where business_operation_code is not null
      and process_type = 'operation'
      and deleted_flag = 0;

create index if not exists idx_plm_process_code_context_search
    on plm_process (product_specific_code, phone_model_code, color_code, operation_craft_code)
    where deleted_flag = 0;
