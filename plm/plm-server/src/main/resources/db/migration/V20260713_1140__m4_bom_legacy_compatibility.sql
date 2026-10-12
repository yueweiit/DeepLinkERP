alter table if exists plm_product_bom
    alter column quantity set default 1;

alter table if exists plm_product_bom
    drop constraint if exists ck_plm_product_bom_status;

alter table if exists plm_product_bom
    add constraint ck_plm_product_bom_status
    check (status in ('draft', 'reviewing', 'frozen', 'released', 'archived'));

alter table if exists plm_product_bom_item
    add column if not exists product_id bigint,
    add column if not exists version_no varchar(32) default 'A',
    add column if not exists uom_code varchar(32),
    add column if not exists unit varchar(32),
    add column if not exists specification varchar(255),
    add column if not exists remark text;

update plm_product_bom_item item
set product_id = coalesce(item.product_id, bom.product_id),
    version_no = coalesce(item.version_no, bom.version_no, 'A'),
    uom_code = coalesce(item.uom_code, item.unit, 'pcs')
from plm_product_bom bom
where bom.product_bom_id = item.product_bom_id
  and (item.product_id is null or item.version_no is null or item.uom_code is null);

alter table if exists plm_product_bom_item
    alter column inventory_id drop not null,
    alter column uom_code set default 'pcs';
