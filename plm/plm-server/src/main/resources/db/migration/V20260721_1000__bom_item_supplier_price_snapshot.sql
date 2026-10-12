alter table if exists plm_product_bom_item
    add column if not exists supplier_code_snapshot varchar(64),
    add column if not exists supplier_name_snapshot varchar(255),
    add column if not exists line_cost_snapshot numeric(18,6),
    add column if not exists material_source varchar(16) not null default 'inventory',
    add column if not exists unmatched_flag integer not null default 0;

create index if not exists idx_plm_product_bom_item_material_source
    on plm_product_bom_item (product_bom_id, material_source, unmatched_flag)
    where deleted_flag = 0;
