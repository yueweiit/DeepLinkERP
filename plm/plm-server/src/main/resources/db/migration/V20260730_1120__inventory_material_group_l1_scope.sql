-- Inventory rows must belong to real material groups, not item-like ECOUNT minor records.
-- Keep ECOUNT L2 dictionary rows for traceability, but move existing inventory links back to L1 groups.

with l2_links as (
    select i.inventory_id,
           parent.material_group_id as parent_material_group_id
      from plm_inventory i
      join plm_material_group child
        on child.material_group_id = i.material_group_id
       and child.deleted_flag = 0
       and child.source_system = 'ECOUNT'
       and child.group_level = 2
      join plm_material_group parent
        on parent.material_group_id = child.parent_material_group_id
       and parent.deleted_flag = 0
       and parent.source_system = 'ECOUNT'
       and parent.group_level = 1
     where i.deleted_flag = 0
)
update plm_inventory inventory
   set material_group_id = l2_links.parent_material_group_id,
       remark = case
           when coalesce(inventory.remark, '') like '%inventory_material_group_l1_scope_20260730%' then inventory.remark
           when coalesce(inventory.remark, '') = '' then 'inventory_material_group_l1_scope_20260730'
           else inventory.remark || '; inventory_material_group_l1_scope_20260730'
       end,
       updated_at = now(),
       updated_by = 'system'
  from l2_links
 where inventory.inventory_id = l2_links.inventory_id;
