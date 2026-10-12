alter table if exists plm_product_bom_route
    add column if not exists shared_bom_group_code varchar(64),
    add column if not exists route_variant_no varchar(32),
    add column if not exists variant_name varchar(128),
    add column if not exists variant_source_type varchar(24) not null default 'manual';

update plm_product_bom_route
set shared_bom_group_code = coalesce(shared_bom_group_code, 'BOM-' || product_bom_id),
    route_variant_no = coalesce(route_variant_no, 'BASE'),
    variant_name = coalesce(variant_name, '基础用料')
where shared_bom_group_code is null or route_variant_no is null or variant_name is null;

alter table if exists plm_product_bom_route
    alter column shared_bom_group_code set not null,
    alter column route_variant_no set not null;

alter table if exists plm_product_bom_item
    add column if not exists shared_bom_group_code varchar(64);

update plm_product_bom_item item
set shared_bom_group_code = route.shared_bom_group_code
from plm_product_bom_route route
where item.product_bom_route_id = route.product_bom_route_id
  and item.shared_bom_group_code is null;

drop index if exists uk_plm_product_bom_route_process;
create unique index if not exists uk_plm_product_bom_route_process_variant
    on plm_product_bom_route (product_bom_id, process_id, route_variant_no)
    where status = 'active' and deleted_flag = 0;

drop index if exists uk_plm_product_bom_item_line;
create unique index if not exists uk_plm_product_bom_item_route_line
    on plm_product_bom_item (product_bom_id, product_bom_route_id, line_no)
    where deleted_flag = 0;

create index if not exists idx_plm_product_bom_route_group
    on plm_product_bom_route (product_bom_id, shared_bom_group_code, status, deleted_flag);
