-- Repair historical seed product data imported from product_import.xlsx.
-- Base products are product_line roots; color variants are model_variant children.

update plm_product
set product_type = 'product_line',
    current_step_no = 22,
    archived_at = coalesce(archived_at, updated_at, created_at, now()),
    archived_by = coalesce(archived_by, updated_by, created_by, 'system'),
    archive_reason = coalesce(archive_reason, U&'\5386\53F2\7A2E\5B50\5BFC\5165\810F\6570\636E\56DE\586B')
where deleted_flag = 0
  and status = 'archived'
  and product_type = 'model_variant'
  and remark like U&'%seed\57FA\7840\4EA7\54C1%'
  and coalesce(model, '') = ''
  and coalesce(color, '') = '';

with variant_parent_map as (
    select
        child.product_id as child_product_id,
        substring(child.remark from 'base_product=([^;]+)') as parent_product_code
    from plm_product child
    where child.deleted_flag = 0
      and child.status = 'archived'
      and child.product_type = 'model_variant'
      and child.remark like U&'%seed BOM\7236\9879%'
)
update plm_product child
set parent_product_id = parent.product_id,
    current_step_no = 18,
    archived_at = coalesce(child.archived_at, child.updated_at, child.created_at, now()),
    archived_by = coalesce(child.archived_by, child.updated_by, child.created_by, 'system'),
    archive_reason = coalesce(child.archive_reason, U&'\5386\53F2\7A2E\5B50\5BFC\5165\810F\6570\636E\56DE\586B')
from variant_parent_map m
join plm_product parent
  on parent.product_code = m.parent_product_code
 and parent.deleted_flag = 0
where child.product_id = m.child_product_id;
