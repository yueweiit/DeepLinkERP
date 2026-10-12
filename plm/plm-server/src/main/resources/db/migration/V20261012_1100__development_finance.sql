-- Colour-neutral development finance. Budgets, approval amounts and ERP postings are separate facts.
create table if not exists plm_development_budget (
  budget_id bigserial primary key,
  budget_kind varchar(16) not null check (budget_kind in ('platform','mold')),
  budget_name varchar(255) not null,
  product_line_id bigint references plm_product(product_id),
  item_id bigint references plm_collaboration_item(item_id),
  mold_set_id bigint references plm_collaboration_mold_set(mold_set_id),
  parent_budget_id bigint references plm_development_budget(budget_id),
  currency_code varchar(8) not null default 'CNY',
  calculation_mode varchar(16) not null default 'manual' check(calculation_mode in ('manual','mold_formula')),
  budget_amount numeric(18,2), mold_cost numeric(18,2), mold_weight numeric(18,3),
  transport_rate numeric(18,4), fuel_rate numeric(18,4), customs_cost numeric(18,2),
  sale_price numeric(18,4), unit_production_cost numeric(18,4), notes text,
  version_no integer not null default 1,
  created_at timestamptz not null default now(), created_by varchar(128) not null,
  updated_at timestamptz not null default now(), updated_by varchar(128) not null,
  deleted_flag integer not null default 0,
  check ((budget_kind='platform' and product_line_id is not null and item_id is null and mold_set_id is null and parent_budget_id is null)
      or (budget_kind='mold' and item_id is not null)),
  check (budget_amount is null or budget_amount>=0), check (mold_cost is null or mold_cost>=0),
  check (mold_weight is null or mold_weight>=0), check (transport_rate is null or transport_rate>=0),
  check (fuel_rate is null or fuel_rate>=0), check (customs_cost is null or customs_cost>=0),
  check (sale_price is null or sale_price>=0), check (unit_production_cost is null or unit_production_cost>=0)
);
create unique index if not exists uk_development_platform_budget on plm_development_budget(product_line_id,currency_code)
  where deleted_flag=0 and budget_kind='platform';
create unique index if not exists uk_development_mold_budget on plm_development_budget(item_id,coalesce(mold_set_id,0),currency_code)
  where deleted_flag=0 and budget_kind='mold';
create index if not exists ix_development_budget_updated on plm_development_budget(updated_at desc,budget_id desc);
-- Upgrade the existing expense ledger/state machine, retaining IDs and legacy routes.
-- Existing colour-project costs are not guessed into shared budgets or silently deduplicated.
alter table plm_project_cost_item alter column product_id drop not null;
alter table plm_project_cost_item alter column amount drop not null;
alter table plm_project_cost_item alter column amount drop default;
alter table plm_project_cost_item add column if not exists product_line_id bigint references plm_product(product_id),
  add column if not exists item_id bigint references plm_collaboration_item(item_id),
  add column if not exists mold_set_id bigint references plm_collaboration_mold_set(mold_set_id),
  add column if not exists budget_id bigint references plm_development_budget(budget_id),
  add column if not exists requested_amount numeric(18,2), add column if not exists approved_amount numeric(18,2),
  add column if not exists approval_instance_id varchar(128), add column if not exists approval_status varchar(16) not null default 'unknown',
  add column if not exists source_system varchar(16) not null default 'manual',
  add column if not exists erp_voucher_id varchar(128), add column if not exists erp_line_id varchar(128),
  add column if not exists erp_posted_amount numeric(18,2), add column if not exists erp_posted_at varchar(64),
  add column if not exists erp_reversal_of varchar(255), add column if not exists erp_fingerprint varchar(64);
alter table plm_project_cost_item add constraint ck_development_source check(source_system in ('manual','erp')),
  add constraint ck_development_posting check(source_system<>'erp' or (erp_voucher_id is not null and erp_line_id is not null and erp_posted_amount is not null)),
  add constraint ck_development_requested check(requested_amount is null or requested_amount>=0),
  add constraint ck_development_approved check(approved_amount is null or approved_amount>=0);
create unique index if not exists uk_development_erp_posting on plm_project_cost_item(source_system,erp_voucher_id,erp_line_id)
  where source_system='erp';
create index if not exists ix_development_expense_scope on plm_project_cost_item(item_id,budget_id,updated_at desc);
create table if not exists plm_development_finance_history (
  history_id bigserial primary key, entity_type varchar(16) not null check(entity_type in ('budget','expense')),
  entity_id bigint not null, version_no integer, field_name varchar(64) not null,
  before_value jsonb, after_value jsonb, reason text,
  actor_id bigint not null, actor_name varchar(128) not null, changed_at timestamptz not null default now()
);
create index if not exists ix_development_finance_history on plm_development_finance_history(entity_type,entity_id,history_id desc);
create table if not exists plm_development_finance_import (
  import_id bigserial primary key, file_hash varchar(64) not null, import_kind varchar(32) not null,
  source_sheet varchar(128) not null, source_row integer not null, entity_id bigint not null,
  created_at timestamptz not null default now(), created_by varchar(128) not null,
  unique(file_hash,import_kind,source_sheet,source_row)
);
comment on table plm_development_budget is '开模专项投资预算；同颜色项目共享档案，不与BOM单位成本或父子预算叠加';
comment on column plm_project_cost_item.erp_posted_amount is 'ERP已过账原币净额；稳定单据/明细ID含负数冲销，不替代审批/手工申报金额';
