-- Repair historical seed product import data that was imported with wrong product_type / parent_product_id / step number.
-- Scope: only rows whose remark starts with the seed import markers from the documented seed workbook.

update plm_product
set product_type = 'product_line',
    parent_product_id = null,
    current_step_no = case
        when status in ('released', 'archived') then 22
        else coalesce(current_step_no, 1)
    end,
    updated_at = now(),
    updated_by = 'system'
where deleted_flag = 0
  and remark like 'seed基础产品%'
  and color is null
  and product_type <> 'product_line';

update plm_product child
set parent_product_id = parent.product_id,
    current_step_no = case
        when child.status in ('released', 'archived') then 18
        else coalesce(child.current_step_no, 1)
    end,
    updated_at = now(),
    updated_by = 'system'
from plm_product parent
where child.deleted_flag = 0
  and parent.deleted_flag = 0
  and child.remark like 'seed%'
  and child.remark like '%base_product=%'
  and parent.product_code = substring(child.remark from 'base_product=([A-Z0-9]+)')
  and child.parent_product_id is distinct from parent.product_id;

update plm_product
set current_step_no = case
        when status in ('released', 'archived') and product_type = 'product_line' then 22
        when status in ('released', 'archived') and product_type in ('model_variant', 'sku') then 18
        else coalesce(current_step_no, 1)
    end,
    updated_at = now(),
    updated_by = 'system'
where deleted_flag = 0
  and remark like 'seed%'
  and (
    current_step_no is null
    or current_step_no < 1
    or current_step_no = 1
  );
