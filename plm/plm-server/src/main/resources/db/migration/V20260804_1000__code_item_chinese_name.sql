alter table if exists plm_code_item
    add column if not exists code_name_zh varchar(128);

update plm_code_item
set code_name_zh = code_name
where code_type = 'color'
  and code_name_zh is null;
