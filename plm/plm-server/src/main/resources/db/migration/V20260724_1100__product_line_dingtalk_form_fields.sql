alter table if exists plm_product
    add column if not exists product_code_prefix varchar(64),
    add column if not exists mold_code_prefix varchar(64);
