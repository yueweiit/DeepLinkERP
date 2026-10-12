-- Imported BOMs and process routes are authoritative formal versions.

update plm_product_bom bom
set bom_scope = 'formal',
    source_type = case
        when bom.source_type = 'seed_reference' then 'import'
        when coalesce(nullif(bom.source_type, ''), '') = '' then 'import'
        else bom.source_type
    end,
    status = 'released',
    frozen_flag = 1,
    confirmed_at = coalesce(bom.confirmed_at, bom.released_at, bom.frozen_at, bom.updated_at, bom.created_at, now()),
    confirmed_by = coalesce(nullif(bom.confirmed_by, ''), 'import'),
    frozen_at = coalesce(bom.frozen_at, bom.released_at, bom.updated_at, bom.created_at, now()),
    frozen_by = coalesce(nullif(bom.frozen_by, ''), 'import'),
    released_at = coalesce(bom.released_at, bom.frozen_at, bom.updated_at, bom.created_at, now()),
    released_by = coalesce(nullif(bom.released_by, ''), 'import'),
    updated_at = now(),
    updated_by = 'system'
where bom.deleted_flag = 0
  and (
      bom.source_type in ('import', 'seed_reference')
      or bom.released_by = 'history-import'
      or exists (
          select 1
          from plm_product_bom_import_batch batch
          where batch.product_bom_id = bom.product_bom_id
            and batch.status = 'committed'
            and batch.deleted_flag = 0
      )
  );

update plm_process process
set status = 'confirmed',
    updated_at = now(),
    updated_by = 'system'
where process.deleted_flag = 0
  and process.process_type in ('routing', 'operation')
  and (
      process.process_code like 'ROUTE-%-IMPORT-%'
      or process.remark like U&'%\5386\53F2\5B58\6863\5BFC\5165%'
      or exists (
          select 1
          from plm_process route
          where route.process_id = process.parent_process_id
            and route.deleted_flag = 0
            and route.process_code like 'ROUTE-%-IMPORT-%'
      )
  );
