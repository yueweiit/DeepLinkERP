-- An independent, colour-neutral ledger. No historical Product/BOM/code is rewritten.
create table if not exists plm_collaboration_item (
  item_id bigserial primary key,
  product_line_id bigint references plm_product(product_id),
  style_name varchar(255) not null,
  brand varchar(128), compatible_models varchar(512) not null,
  phone_model_code varchar(20), phone_price numeric(16,2), price_currency varchar(12),
  sales_platform varchar(512), reference_url text, notes text,
  pc_total bigint check (pc_total >= 0), tpu_total bigint check (tpu_total >= 0),
  finished_total bigint check (finished_total >= 0), production_notes text,
  created_at timestamptz not null default now(), created_by varchar(128) not null,
  updated_at timestamptz not null default now(), updated_by varchar(128) not null,
  deleted_flag integer not null default 0
);
create index if not exists ix_collaboration_item_line on plm_collaboration_item(product_line_id, item_id);
create table if not exists plm_collaboration_item_project (
  item_id bigint not null references plm_collaboration_item(item_id),
  project_id bigint primary key references plm_product(product_id),
  linked_at timestamptz not null default now(), linked_by varchar(128) not null
);
create index if not exists ix_collaboration_project_item on plm_collaboration_item_project(item_id);
create table if not exists plm_collaboration_mold_set (
  mold_set_id bigserial primary key, item_id bigint not null references plm_collaboration_item(item_id),
  set_no integer not null check (set_no > 0), set_name varchar(255) not null,
  opened_date date, planned_mold_delivery_date date, actual_ship_date date,
  planned_factory_arrival_date date, actual_mexico_arrival_date date,
  arrival_confirmed_basis_date date, notes text,
  created_at timestamptz not null default now(), created_by varchar(128) not null,
  updated_at timestamptz not null default now(), updated_by varchar(128) not null,
  deleted_flag integer not null default 0, unique(item_id, set_no)
);
create index if not exists ix_collaboration_mold_item on plm_collaboration_mold_set(item_id);
create table if not exists plm_collaboration_mold_part (
  mold_set_id bigint not null references plm_collaboration_mold_set(mold_set_id),
  part_type varchar(8) not null check (part_type in ('PC','TPU')),
  product_mold_code_id bigint references plm_product_mold_code(product_mold_code_id),
  status varchar(16) not null default 'pending' check (status in ('pending','making','ready')),
  primary key(mold_set_id, part_type)
);
create table if not exists plm_collaboration_assignment (
  field_group varchar(32) not null check (field_group in ('market','engineering','logistics','mexico','production')),
  user_id bigint not null references sys_user(user_id), primary key(field_group, user_id)
);
create table if not exists plm_collaboration_history (
  history_id bigserial primary key, item_id bigint not null references plm_collaboration_item(item_id),
  entity_type varchar(16) not null, entity_id bigint not null, field_name varchar(64) not null,
  before_value jsonb, after_value jsonb, reason text,
  actor_id bigint not null, actor_name varchar(128) not null,
  changed_at timestamptz not null default now()
);
create index if not exists ix_collaboration_history_item on plm_collaboration_history(item_id, history_id desc);
create table if not exists plm_collaboration_import_batch (
  batch_id bigserial primary key, file_hash varchar(64) not null, import_kind varchar(16) not null,
  file_name varchar(512) not null, imported_at timestamptz not null default now(), imported_by varchar(128) not null,
  unique(file_hash, import_kind)
);
create table if not exists plm_collaboration_import_row (
  batch_id bigint not null references plm_collaboration_import_batch(batch_id),
  sheet_name varchar(128) not null, row_no integer not null,
  item_id bigint not null references plm_collaboration_item(item_id),
  mold_set_id bigint references plm_collaboration_mold_set(mold_set_id),
  primary key(batch_id, sheet_name, row_no)
);

-- Only initialise exact, confirmed one-to-one codes, grouped across historical colours.
with eligible as (
  select p.parent_product_id, btrim(p.phone_model_code) as phone_code,
         lower(btrim(p.model)) as model_key, min(btrim(p.model)) as model_name
  from plm_product p join plm_product parent on parent.product_id=p.parent_product_id
  join plm_code_item c on c.code_type='phone_model' and c.deleted_flag=0
    and c.code_value=btrim(p.phone_model_code) and lower(btrim(c.code_name))=lower(btrim(p.model))
  where p.deleted_flag=0 and p.product_type='model_variant'
    and parent.deleted_flag=0 and parent.product_type='product_line'
    and not exists (select 1 from plm_product other where other.deleted_flag=0
      and btrim(other.phone_model_code)=btrim(p.phone_model_code)
      and nullif(btrim(other.model),'') is not null and lower(btrim(other.model))<>lower(btrim(p.model)))
  group by p.parent_product_id,btrim(p.phone_model_code),lower(btrim(p.model))
)
insert into plm_collaboration_item(product_line_id,style_name,compatible_models,phone_model_code,created_by,updated_by)
select e.parent_product_id,parent.product_name,e.model_name,e.phone_code,'collaboration-migration','collaboration-migration'
from eligible e join plm_product parent on parent.product_id=e.parent_product_id
where not exists (select 1 from plm_collaboration_item i where i.deleted_flag=0
  and i.product_line_id=e.parent_product_id and i.phone_model_code=e.phone_code
  and lower(btrim(i.compatible_models))=e.model_key);

insert into plm_collaboration_item_project(item_id,project_id,linked_by)
select i.item_id,p.product_id,'collaboration-migration'
from plm_collaboration_item i join plm_product p on p.parent_product_id=i.product_line_id
  and btrim(p.phone_model_code)=i.phone_model_code and lower(btrim(p.model))=lower(btrim(i.compatible_models))
where i.created_by='collaboration-migration' and p.deleted_flag=0 and p.product_type='model_variant'
on conflict(project_id) do nothing;
