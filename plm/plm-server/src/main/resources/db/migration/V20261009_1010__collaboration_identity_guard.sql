-- A colour-neutral model group is a single ledger, including under concurrent creation/import.
create unique index if not exists uq_collaboration_item_identity
  on plm_collaboration_item(lower(btrim(style_name)), lower(btrim(compatible_models)))
  where deleted_flag=0;
create index if not exists ix_collaboration_item_page
  on plm_collaboration_item(updated_at desc,item_id desc) where deleted_flag=0;
create index if not exists ix_collaboration_mold_page
  on plm_collaboration_mold_set(updated_at desc,mold_set_id desc) where deleted_flag=0;
