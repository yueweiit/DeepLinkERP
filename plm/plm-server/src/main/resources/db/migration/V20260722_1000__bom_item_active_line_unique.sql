alter table if exists plm_product_bom_item
    drop constraint if exists uk_plm_product_bom_item_line;

drop index if exists uk_plm_product_bom_item_line;

create unique index uk_plm_product_bom_item_line
    on plm_product_bom_item (product_bom_id, line_no)
    where deleted_flag = 0;
