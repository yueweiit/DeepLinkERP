-- Independent registry only: product records and their historical codes are never rewritten.
create unique index if not exists uk_plm_phone_model_normalized_name
    on plm_code_item (lower(btrim(code_name)))
    where code_type = 'phone_model' and deleted_flag = 0;

do $$
begin
    if not exists (select 1 from pg_constraint where conname = 'ck_plm_phone_model_four_digits'
                   and conrelid = 'plm_code_item'::regclass) then
        alter table plm_code_item add constraint ck_plm_phone_model_four_digits
            check (code_type <> 'phone_model' or code_value ~ '^[0-9]{4}$');
    end if;
end $$;

with pairs as (
    select btrim(phone_model_code) as code_value, lower(btrim(model)) as normalized_name,
           min(btrim(model)) as model_name
      from plm_product where deleted_flag = 0
       and nullif(btrim(phone_model_code), '') is not null and nullif(btrim(model), '') is not null
     group by btrim(phone_model_code), lower(btrim(model))
), code_counts as (
    select code_value, count(*) as name_count from pairs group by code_value
), name_counts as (
    select normalized_name, count(*) as code_count from pairs group by normalized_name
)
insert into plm_code_item (code_type, code_value, code_name, status, sort_order,
                          created_at, created_by, updated_at, updated_by, deleted_flag)
select 'phone_model', p.code_value, p.model_name, 'enabled', 0,
       current_timestamp, 'phone-model-migration', current_timestamp, 'phone-model-migration', 0
  from pairs p join code_counts c using (code_value) join name_counts n using (normalized_name)
 where c.name_count = 1 and n.code_count = 1 and p.code_value ~ '^[0-9]{4}$'
   and length(p.model_name) <= 128
   and not exists (select 1 from plm_code_item existing where existing.deleted_flag = 0
       and existing.code_type = 'phone_model'
       and (existing.code_value = p.code_value or lower(btrim(existing.code_name)) = p.normalized_name))
order by p.code_value
on conflict do nothing;
