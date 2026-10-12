-- Frontend test data for DingTalk mold-code intake and model-variant requirement form.
-- Run after the PLM schema and Flyway migrations are applied.
--
-- Scenario:
--   Product line: FA / 幻影 Fantasia Case / released
--   Phone model: Xiaomi Redmi A7 Pro / phone model code 1291
--   Colors: 01 黑色, 02 透明色
--   Existing mold: MFA101291
--   Missing mold: MFA201291, expected to be auto-created as plm_inventory.tooling/draft by the API.

begin;

update plm_code_item target
set code_name = seed.code_name,
    status = 'enabled',
    sort_order = seed.sort_order,
    updated_at = current_timestamp,
    updated_by = 'frontend-test'
from (
    values
        ('01', '黑色', 10),
        ('02', '透明色', 20)
) as seed(code_value, code_name, sort_order)
where target.code_type = 'color'
  and target.code_value = seed.code_value
  and target.deleted_flag = 0;

insert into plm_code_item (
    code_type, code_value, code_name, status, sort_order,
    created_by, updated_by, deleted_flag
)
select 'color', seed.code_value, seed.code_name, 'enabled', seed.sort_order,
       'frontend-test', 'frontend-test', 0
from (
    values
        ('01', '黑色', 10),
        ('02', '透明色', 20)
) as seed(code_value, code_name, sort_order)
where not exists (
    select 1
    from plm_code_item existing
    where existing.code_type = 'color'
      and existing.code_value = seed.code_value
      and existing.deleted_flag = 0
);

insert into plm_product (
    product_code, product_name, product_type, series_name, model,
    version_no, status, current_step_no, timeline_current_confirmed,
    released_at, released_by, lock_status, remark,
    created_by, updated_by, deleted_flag
)
values (
    'FA', '幻影 Fantasia Case', 'product_line', '幻影', 'Fantasía Case',
    'A', 'released', 6, true,
    current_timestamp, 'frontend-test', 'unlocked',
    '编码规则前端联调用父产品线；产品特定编码=FA',
    'frontend-test', 'frontend-test', 0
)
on conflict (product_code) do update
set product_name = excluded.product_name,
    product_type = 'product_line',
    series_name = excluded.series_name,
    model = excluded.model,
    version_no = excluded.version_no,
    status = 'released',
    current_step_no = 6,
    timeline_current_confirmed = true,
    released_at = coalesce(plm_product.released_at, current_timestamp),
    released_by = coalesce(plm_product.released_by, 'frontend-test'),
    lock_status = 'unlocked',
    remark = excluded.remark,
    updated_at = current_timestamp,
    updated_by = 'frontend-test',
    deleted_flag = 0;

with parent_product as (
    select product_id
    from plm_product
    where product_code = 'FA'
      and deleted_flag = 0
)
insert into plm_process (
    product_id, process_code, process_name, process_type,
    version_no, sequence_no, status,
    material_status_code, finished_product_flag, business_operation_code,
    remark, created_by, updated_by, deleted_flag
)
select parent_product.product_id,
       'FA-OP-4030',
       '组装完成',
       'operation',
       'A',
       4030,
       'confirmed',
       '4030',
       true,
       '4030',
       '编码规则前端联调用最终工序；4030 表示组装完成/成品状态',
       'frontend-test',
       'frontend-test',
       0
from parent_product
where not exists (
    select 1
    from plm_process existing
    where existing.process_code = 'FA-OP-4030'
      and existing.deleted_flag = 0
);

update plm_process
set product_id = parent_product.product_id,
    process_name = '组装完成',
    process_type = 'operation',
    version_no = 'A',
    sequence_no = 4030,
    status = 'confirmed',
    material_status_code = '4030',
    finished_product_flag = true,
    business_operation_code = '4030',
    updated_at = current_timestamp,
    updated_by = 'frontend-test',
    deleted_flag = 0
from (
    select product_id
    from plm_product
    where product_code = 'FA'
      and deleted_flag = 0
) parent_product
where plm_process.process_code = 'FA-OP-4030';

with parent_product as (
    select product_id
    from plm_product
    where product_code = 'FA'
      and deleted_flag = 0
)
insert into plm_product_bom (
    product_id, bom_code, bom_name, bom_type, version_no, status,
    bom_scope, source_type, currency_code,
    confirmed_at, confirmed_by, released_at, released_by,
    remark, created_by, updated_by, deleted_flag
)
select parent_product.product_id,
       'BOM-FA-MBOM-A',
       '幻影 Fantasia Case 正式 MBOM',
       'mbom',
       'A',
       'released',
       'formal',
       'manual',
       'CNY',
       current_timestamp,
       'frontend-test',
       current_timestamp,
       'frontend-test',
       '编码规则前端联调用最小正式 BOM',
       'frontend-test',
       'frontend-test',
       0
from parent_product
where not exists (
    select 1
    from plm_product_bom existing
    where existing.product_id = parent_product.product_id
      and existing.bom_type = 'mbom'
      and existing.version_no = 'A'
      and existing.deleted_flag = 0
);

update plm_product_bom
set status = 'released',
    bom_scope = 'formal',
    source_type = 'manual',
    currency_code = coalesce(currency_code, 'CNY'),
    confirmed_at = coalesce(confirmed_at, current_timestamp),
    confirmed_by = coalesce(confirmed_by, 'frontend-test'),
    released_at = coalesce(released_at, current_timestamp),
    released_by = coalesce(released_by, 'frontend-test'),
    updated_at = current_timestamp,
    updated_by = 'frontend-test',
    deleted_flag = 0
where product_id = (select product_id from plm_product where product_code = 'FA' and deleted_flag = 0)
  and bom_type = 'mbom'
  and version_no = 'A';

with parent_product as (
    select product_id
    from plm_product
    where product_code = 'FA'
      and deleted_flag = 0
),
formal_bom as (
    select product_bom_id, product_id
    from plm_product_bom
    where product_id = (select product_id from parent_product)
      and bom_type = 'mbom'
      and version_no = 'A'
      and deleted_flag = 0
    order by product_bom_id
    limit 1
),
final_process as (
    select process_id
    from plm_process
    where process_code = 'FA-OP-4030'
      and deleted_flag = 0
)
insert into plm_product_bom_route (
    product_bom_id, product_id, process_id, route_code, route_name, status,
    created_by, updated_by, deleted_flag
)
select formal_bom.product_bom_id,
       parent_product.product_id,
       final_process.process_id,
       'ROUTE-FA-4030-A',
       '幻影 Fantasia Case 4030 组装完成路线',
       'active',
       'frontend-test',
       'frontend-test',
       0
from parent_product
cross join formal_bom
cross join final_process
where not exists (
    select 1
    from plm_product_bom_route existing
    where existing.product_bom_id = formal_bom.product_bom_id
      and existing.process_id = final_process.process_id
      and existing.deleted_flag = 0
);

update plm_product_bom_route route
set route_code = 'ROUTE-FA-4030-A',
    route_name = '幻影 Fantasia Case 4030 组装完成路线',
    status = 'active',
    updated_at = current_timestamp,
    updated_by = 'frontend-test',
    deleted_flag = 0
from plm_product_bom bom
join plm_process process on process.process_code = 'FA-OP-4030' and process.deleted_flag = 0
where route.product_bom_id = bom.product_bom_id
  and route.process_id = process.process_id
  and bom.product_id = (select product_id from plm_product where product_code = 'FA' and deleted_flag = 0)
  and bom.bom_type = 'mbom'
  and bom.version_no = 'A';

with route_context as (
    select bom.product_bom_id, route.product_bom_route_id
    from plm_product_bom bom
    join plm_product_bom_route route on route.product_bom_id = bom.product_bom_id
    join plm_process process on process.process_id = route.process_id
    where bom.product_id = (select product_id from plm_product where product_code = 'FA' and deleted_flag = 0)
      and bom.bom_type = 'mbom'
      and bom.version_no = 'A'
      and process.process_code = 'FA-OP-4030'
      and bom.deleted_flag = 0
      and route.deleted_flag = 0
    order by route.product_bom_route_id
    limit 1
),
colors as (
    select code_item_id, code_value as color_code, code_name as color_name
    from plm_code_item
    where code_type = 'color'
      and code_value in ('01', '02')
      and deleted_flag = 0
)
insert into plm_product_bom_route_color (
    product_bom_id, product_bom_route_id, code_item_id, color_code, color_name,
    status, created_by, updated_by, deleted_flag
)
select route_context.product_bom_id,
       route_context.product_bom_route_id,
       colors.code_item_id,
       colors.color_code,
       colors.color_name,
       'active',
       'frontend-test',
       'frontend-test',
       0
from route_context
cross join colors
where not exists (
    select 1
    from plm_product_bom_route_color existing
    where existing.product_bom_id = route_context.product_bom_id
      and existing.color_name = colors.color_name
      and existing.deleted_flag = 0
);

with route_context as (
    select bom.product_bom_id, route.product_bom_route_id
    from plm_product_bom bom
    join plm_product_bom_route route on route.product_bom_id = bom.product_bom_id
    join plm_process process on process.process_id = route.process_id
    where bom.product_id = (select product_id from plm_product where product_code = 'FA' and deleted_flag = 0)
      and bom.bom_type = 'mbom'
      and bom.version_no = 'A'
      and process.process_code = 'FA-OP-4030'
      and bom.deleted_flag = 0
      and route.deleted_flag = 0
    order by route.product_bom_route_id
    limit 1
),
colors as (
    select code_item_id, code_value as color_code, code_name as color_name
    from plm_code_item
    where code_type = 'color'
      and code_value in ('01', '02')
      and deleted_flag = 0
)
insert into plm_product_production_color_decision (
    product_id, color_name, product_bom_id, product_bom_route_id,
    code_item_id, color_code, decision_batch_no,
    selected_flag, status, confirmed_at, confirmed_by,
    created_by, updated_by, deleted_flag
)
select (select product_id from plm_product where product_code = 'FA' and deleted_flag = 0),
       colors.color_name,
       route_context.product_bom_id,
       route_context.product_bom_route_id,
       colors.code_item_id,
       colors.color_code,
       'TEST-FA-1291-20260723',
       1,
       'confirmed',
       current_timestamp,
       'frontend-test',
       'frontend-test',
       'frontend-test',
       0
from route_context
cross join colors
where not exists (
    select 1
    from plm_product_production_color_decision existing
    where existing.product_id = (select product_id from plm_product where product_code = 'FA' and deleted_flag = 0)
      and existing.color_name = colors.color_name
      and existing.status = 'confirmed'
      and existing.deleted_flag = 0
);

update plm_product_production_color_decision decision
set selected_flag = 1,
    status = 'confirmed',
    code_item_id = colors.code_item_id,
    color_code = colors.color_code,
    product_bom_id = route_context.product_bom_id,
    product_bom_route_id = route_context.product_bom_route_id,
    confirmed_at = coalesce(decision.confirmed_at, current_timestamp),
    confirmed_by = coalesce(decision.confirmed_by, 'frontend-test'),
    updated_at = current_timestamp,
    updated_by = 'frontend-test',
    deleted_flag = 0
from (
    select bom.product_bom_id, route.product_bom_route_id
    from plm_product_bom bom
    join plm_product_bom_route route on route.product_bom_id = bom.product_bom_id
    join plm_process process on process.process_id = route.process_id
    where bom.product_id = (select product_id from plm_product where product_code = 'FA' and deleted_flag = 0)
      and bom.bom_type = 'mbom'
      and bom.version_no = 'A'
      and process.process_code = 'FA-OP-4030'
      and bom.deleted_flag = 0
      and route.deleted_flag = 0
    order by route.product_bom_route_id
    limit 1
) route_context
join (
    select code_item_id, code_value as color_code, code_name as color_name
    from plm_code_item
    where code_type = 'color'
      and code_value in ('01', '02')
      and deleted_flag = 0
) colors on colors.color_name = decision.color_name
where decision.product_id = (select product_id from plm_product where product_code = 'FA' and deleted_flag = 0)
  and decision.color_name = colors.color_name;

with parent_product as (
    select product_id
    from plm_product
    where product_code = 'FA'
      and deleted_flag = 0
)
insert into plm_inventory (
    inventory_code, inventory_name, inventory_type, product_id,
    specification, description, stock_uom, quantity,
    status, remark, created_by, updated_by, deleted_flag
)
select 'MFA101291',
       '幻影 Fantasia Case Xiaomi Redmi A7 Pro TPU 模具',
       'tooling',
       parent_product.product_id,
       '10/1291',
       '前端联调预置已存在模具；产品特定编码=FA；材质编码=10；手机型号编码=1291',
       'set',
       0,
       'available',
       '用于验证钉钉模具编码 MFA101291 匹配已有 Inventory/tooling',
       'frontend-test',
       'frontend-test',
       0
from parent_product
where not exists (
    select 1
    from plm_inventory existing
    where existing.inventory_code = 'MFA101291'
      and existing.deleted_flag = 0
);

update plm_inventory
set inventory_name = '幻影 Fantasia Case Xiaomi Redmi A7 Pro TPU 模具',
    inventory_type = 'tooling',
    product_id = (select product_id from plm_product where product_code = 'FA' and deleted_flag = 0),
    specification = '10/1291',
    description = '前端联调预置已存在模具；产品特定编码=FA；材质编码=10；手机型号编码=1291',
    stock_uom = 'set',
    quantity = coalesce(quantity, 0),
    status = 'available',
    remark = '用于验证钉钉模具编码 MFA101291 匹配已有 Inventory/tooling',
    updated_at = current_timestamp,
    updated_by = 'frontend-test',
    deleted_flag = 0
where inventory_code = 'MFA101291';

commit;

select
    product_id as parent_product_id,
    product_code,
    product_name,
    status
from plm_product
where product_code = 'FA'
  and deleted_flag = 0;

select
    decision.color_code,
    decision.color_name,
    decision.selected_flag,
    decision.status
from plm_product_production_color_decision decision
join plm_product product on product.product_id = decision.product_id
where product.product_code = 'FA'
  and decision.deleted_flag = 0
order by decision.color_code;

select
    inventory_id,
    inventory_code,
    inventory_type,
    status
from plm_inventory
where inventory_code in ('MFA101291', 'MFA201291')
  and deleted_flag = 0
order by inventory_code;
