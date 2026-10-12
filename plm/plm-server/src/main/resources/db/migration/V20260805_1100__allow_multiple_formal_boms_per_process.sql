drop index if exists uk_product_bom_route_formal_active;

create unique index if not exists uk_product_bom_route_formal_active
    on plm_product_bom_route_formal_selection(product_id, process_id, product_bom_route_id)
    where status = 'active' and deleted_flag = 0;
