-- Incremental capabilities only: use existing attachment, BOM, collaboration and cost identities.
alter table plm_product_bom drop constraint if exists ck_plm_product_bom_status;
alter table plm_product_bom add constraint ck_plm_product_bom_status check(status in ('draft','reviewing','frozen','released','archived'));
alter table plm_attachment add column if not exists family_id bigint references plm_attachment(attachment_id);
alter table plm_attachment add column if not exists change_reason text;
alter table plm_attachment add column if not exists released_at timestamptz;
alter table plm_attachment add column if not exists released_by bigint references sys_user(user_id);
alter table plm_attachment add column if not exists collaboration_item_id bigint references plm_collaboration_item(item_id);
alter table plm_attachment add column if not exists mold_set_id bigint references plm_collaboration_mold_set(mold_set_id);
alter table plm_attachment add column if not exists derived_pdf_attachment_id bigint references plm_attachment(attachment_id);
create unique index if not exists uq_attachment_family_version on plm_attachment(family_id,version_no) where family_id is not null and deleted_flag=0;
create index if not exists ix_attachment_family on plm_attachment(family_id,attachment_id);
create table if not exists plm_pilot_bom_release (
  bom_id bigint not null references plm_product_bom(product_bom_id), version_no varchar(64) not null,
  event_id varchar(128) not null unique, snapshot jsonb not null, fingerprint varchar(64) not null,
  actor_id bigint not null references sys_user(user_id), released_at timestamptz not null default now(),
  primary key(bom_id,version_no)
);
create table if not exists plm_pilot_delivery_task (
  task_id bigserial primary key, kind varchar(32) not null, event_id varchar(128) not null unique,
  payload jsonb not null, status varchar(32) not null default 'pending', attempts integer not null default 0,
  available_at timestamptz not null default now(), lease_until timestamptz,
  last_error varchar(255), receipt jsonb, actor_id bigint references sys_user(user_id),
  created_at timestamptz not null default now(), updated_at timestamptz not null default now()
);
create index if not exists ix_pilot_delivery_pending on plm_pilot_delivery_task(status,available_at);
alter table plm_mold_schedule_reminder add column if not exists delivery_event_id varchar(128);
create index if not exists ix_schedule_reminder_delivery on plm_mold_schedule_reminder(delivery_event_id);
create table if not exists plm_pilot_trial (
  trial_id bigserial primary key, name varchar(255) not null, platform_ids jsonb not null,
  new_platform_id bigint references plm_product(product_id), project_ids jsonb not null default '[]',
  status varchar(16) not null default 'preparing', preparation_at timestamptz not null default now(),
  started_on date, review_on date, extension_reason text,
  baseline jsonb not null default '{}', revision integer not null default 1,
  created_by bigint not null references sys_user(user_id), updated_by bigint not null references sys_user(user_id),
  updated_at timestamptz not null default now()
);
create table if not exists plm_pilot_trial_history (
  history_id bigserial primary key, trial_id bigint not null references plm_pilot_trial(trial_id),
  before_value jsonb, after_value jsonb not null, reason text, actor_id bigint not null references sys_user(user_id),
  changed_at timestamptz not null default now()
);
