-- Inventory supply-side supplier profile extension.
-- Supplier remains supply-side data under Inventory; this does not create a Supplier root object.

alter table if exists plm_inventory_supplier_item
  add column if not exists supplier_name varchar(255),
  add column if not exists supplier_short_name varchar(128),
  add column if not exists supplier_contact_person varchar(128),
  add column if not exists supplier_contact_phone varchar(64),
  add column if not exists supplier_contact_email varchar(128),
  add column if not exists supplier_region varchar(128),
  add column if not exists supply_categories text,
  add column if not exists payment_term varchar(128),
  add column if not exists cooperation_level varchar(128),
  add column if not exists delivery_risk varchar(32);

do $$
begin
  if exists (
    select 1
      from information_schema.columns
     where table_name = 'plm_inventory_supplier_item'
       and column_name = 'supplier_name'
  ) then
    comment on column plm_inventory_supplier_item.supplier_name is 'Inventory supply-side supplier name snapshot.';
    comment on column plm_inventory_supplier_item.supplier_contact_person is 'Inventory supply-side supplier contact person.';
    comment on column plm_inventory_supplier_item.supply_categories is 'Comma-separated supply categories shown by the supplier center.';
  end if;
end $$;
