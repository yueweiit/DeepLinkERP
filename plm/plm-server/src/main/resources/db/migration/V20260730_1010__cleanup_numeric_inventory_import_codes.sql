-- Soft-delete inventory rows imported with sequence-only ECOUNT codes, such as 000001/000008.
-- The corrected importer rebuilds full codes from material group prefixes, for example GL + 000008 -> GL000008.

with candidates as (
    select i.inventory_id
    from plm_inventory i
    join plm_material_group g
      on g.material_group_id = i.material_group_id
     and g.deleted_flag = 0
     and g.source_system = 'ECOUNT'
    where i.deleted_flag = 0
      and i.inventory_code ~ '^[0-9]{3,}$'
      and (
          coalesce(i.remark, '') like '%ECOUNT导入%'
          or coalesce(i.remark, '') like '%历史存档导入%'
      )
)
update plm_inventory inventory
set deleted_flag = 1,
    remark = case
        when coalesce(inventory.remark, '') like '%cleanup_numeric_inventory_import_codes_20260730%' then inventory.remark
        when coalesce(inventory.remark, '') = '' then 'cleanup_numeric_inventory_import_codes_20260730'
        else inventory.remark || '; cleanup_numeric_inventory_import_codes_20260730'
    end,
    updated_at = now(),
    updated_by = 'system'
from candidates
where inventory.inventory_id = candidates.inventory_id;
