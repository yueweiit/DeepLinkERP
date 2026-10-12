update plm_product
set status = 'released',
    released_at = coalesce(released_at, current_timestamp),
    released_by = coalesce(released_by, updated_by, 'system'),
    updated_at = current_timestamp,
    updated_by = coalesce(updated_by, 'system')
where status = 'reviewing'
  and (
    coalesce(timeline_current_confirmed, false) = true
    or (product_type = 'product_line' and coalesce(current_step_no, 0) >= 22)
    or (product_type = 'model_variant' and coalesce(current_step_no, 0) >= 18)
  );

update plm_product
set status = 'developing',
    updated_at = current_timestamp,
    updated_by = coalesce(updated_by, 'system')
where status = 'reviewing';

alter table if exists plm_product
    drop constraint if exists ck_plm_product_status;

alter table if exists plm_product
    add constraint ck_plm_product_status
    check (status in ('draft', 'developing', 'released', 'archived'));

update plm_product_bom
set status = 'released',
    released_at = coalesce(released_at, current_timestamp),
    released_by = coalesce(released_by, updated_by, 'system'),
    updated_at = current_timestamp,
    updated_by = coalesce(updated_by, 'system')
where status = 'reviewing';

alter table if exists plm_product_bom
    drop constraint if exists ck_plm_product_bom_status;

alter table if exists plm_product_bom
    add constraint ck_plm_product_bom_status
    check (status in ('draft', 'frozen', 'released', 'archived'));

update sys_dict_item
set status = 'inactive',
    updated_at = current_timestamp,
    updated_by = 'system'
where dict_type_code = 'product_status'
  and item_code = 'reviewing';
