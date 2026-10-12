-- Extend the existing colour-neutral sets. Do not infer physical assets from inventory.
alter table plm_collaboration_mold_set
  add column if not exists source_mold_set_id bigint references plm_collaboration_mold_set(mold_set_id),
  add column if not exists manufacturer_name varchar(255),
  add column if not exists owner_user_id bigint references sys_user(user_id);
alter table plm_collaboration_mold_part
  add column if not exists original_mold_code varchar(64),
  add column if not exists inventory_id bigint references plm_inventory(inventory_id),
  add column if not exists current_location varchar(32),
  add column if not exists location_detail varchar(255),
  add column if not exists factory_arrival_date date,
  add column if not exists acceptance_status varchar(16) not null default 'pending',
  add column if not exists acceptance_date date,
  add column if not exists acceptance_issues text;
alter table plm_collaboration_mold_part
  add constraint ck_mold_location check (current_location is null or current_location in ('china_maker','china_dispatch','in_transit','mexico_transit','mexico_factory','other')),
  add constraint ck_mold_acceptance check (acceptance_status in ('pending','passed','failed')),
  add constraint ck_mold_acceptance_passed check (acceptance_status <> 'passed' or (factory_arrival_date is not null and acceptance_date is not null and acceptance_date >= factory_arrival_date)),
  add constraint ck_mold_acceptance_failed check (acceptance_status <> 'failed' or nullif(btrim(acceptance_issues),'') is not null);
create index if not exists ix_mold_part_location on plm_collaboration_mold_part(current_location,mold_set_id);
create index if not exists ix_mold_copy_source on plm_collaboration_mold_set(source_mold_set_id);
