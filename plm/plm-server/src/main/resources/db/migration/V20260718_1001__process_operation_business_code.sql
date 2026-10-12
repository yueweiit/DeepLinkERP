alter table if exists plm_process
    add column if not exists operation_craft_code varchar(20),
    add column if not exists material_status_code varchar(20),
    add column if not exists finished_product_flag boolean not null default false,
    add column if not exists business_operation_code varchar(80),
    add column if not exists business_operation_code_manual_flag boolean not null default false;

update plm_process
set
    operation_craft_code = coalesce(operation_craft_code, process_param_json ->> 'operationCraftCode'),
    material_status_code = coalesce(material_status_code, process_param_json ->> 'materialStatusCode'),
    finished_product_flag = coalesce(finished_product_flag, (process_param_json ->> 'finishedProductFlag')::boolean, false),
    business_operation_code = coalesce(business_operation_code, upper(process_param_json ->> 'businessOperationCode')),
    business_operation_code_manual_flag = coalesce(
        business_operation_code_manual_flag,
        (process_param_json ->> 'businessOperationCodeManualFlag')::boolean,
        false
    )
where process_type in ('operation', 'route_template_operation')
  and process_param_json is not null;

create index if not exists idx_plm_process_business_operation_code
    on plm_process (product_id, business_operation_code)
    where business_operation_code is not null and deleted_flag = 0;
