-- Fallback cleanup for inventory rows imported with sequence-only ECOUNT codes.
-- Earlier cleanup relied on localized remark text; this version uses the ECOUNT material group link as the boundary.


with candidates as (
    select i.inventory_id
    from plm_inventory i
    join plm_material_group g
      on g.material_group_id = i.material_group_id
     and g.deleted_flag = 0
     and g.source_system = 'ECOUNT'
    where i.deleted_flag = 0
      and i.inventory_code ~ '^[0-9]{3,}$'
)
update plm_inventory inventory
set deleted_flag = 1,
    remark = case
        when coalesce(inventory.remark, '') like '%cleanup_numeric_inventory_import_codes_fallback_20260730%' then inventory.remark
        when coalesce(inventory.remark, '') = '' then 'cleanup_numeric_inventory_import_codes_fallback_20260730'
        else inventory.remark || '; cleanup_numeric_inventory_import_codes_fallback_20260730'
    end,
    updated_at = now(),
    updated_by = 'system'
from candidates
where inventory.inventory_id = candidates.inventory_id;
