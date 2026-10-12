alter table if exists plm_project_requirement_form
    add column if not exists product_specific_code varchar(64),
    add column if not exists phone_model_code varchar(64),
    add column if not exists material_codes text,
    add column if not exists mold_codes text,
    add column if not exists mold_match_status varchar(32),
    add column if not exists mold_match_json text;

create index if not exists idx_plm_requirement_form_mold_match_status
    on plm_project_requirement_form(mold_match_status)
    where deleted_flag = 0;
