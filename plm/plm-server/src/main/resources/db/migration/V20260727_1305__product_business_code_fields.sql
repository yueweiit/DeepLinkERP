alter table if exists plm_product
    add column if not exists product_specific_code varchar(20),
    add column if not exists phone_model_code varchar(20),
    add column if not exists color_code varchar(20),
    add column if not exists finished_product_code varchar(80),
    add column if not exists import_short_code varchar(20);

update plm_product
set product_specific_code = upper(product_code_prefix)
where product_specific_code is null
  and product_code_prefix is not null;

create unique index if not exists uk_plm_product_specific_code_active
    on plm_product (product_specific_code)
    where product_specific_code is not null
      and product_type = 'product_line'
      and deleted_flag = 0;

create unique index if not exists uk_plm_product_finished_product_code_active
    on plm_product (finished_product_code)
    where finished_product_code is not null
      and deleted_flag = 0;

create unique index if not exists uk_plm_product_variant_color_code_active
    on plm_product (parent_product_id, phone_model_code, color_code)
    where parent_product_id is not null
      and phone_model_code is not null
      and color_code is not null
      and product_type in ('model_variant', 'sku')
      and deleted_flag = 0;

create index if not exists idx_plm_product_business_code_search
    on plm_product (product_specific_code, phone_model_code, color_code, finished_product_code, import_short_code)
    where deleted_flag = 0;
