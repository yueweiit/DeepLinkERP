create unique index if not exists uk_plm_product_sku_parent_color_active
    on plm_product(parent_product_id, lower(color))
    where product_type = 'sku' and deleted_flag = 0;
