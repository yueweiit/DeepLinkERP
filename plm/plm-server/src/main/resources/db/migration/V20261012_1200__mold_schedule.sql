-- One physical set remains the single authority for all shared delivery dates.
alter table plm_collaboration_mold_set
  add column if not exists plan_start_date date,
  add column if not exists manufacturing_days integer check (manufacturing_days between 1 and 365),
  add column if not exists holiday_days integer not null default 0 check (holiday_days between 0 and 365),
  add column if not exists extra_days integer not null default 0 check (extra_days between 0 and 365),
  add column if not exists forecast_delivery_date date,
  add column if not exists forecast_factory_date date,
  add column if not exists forecast_acceptance_date date,
  add column if not exists forecast_production_date date,
  add column if not exists planned_acceptance_date date,
  add column if not exists planned_production_date date,
  add column if not exists actual_port_arrival_date date,
  add column if not exists pc_signed_date date,
  add column if not exists tpu_signed_date date,
  add column if not exists actual_supplier_trial_date date,
  add column if not exists actual_trial_date date,
  add column if not exists actual_production_date date,
  add column if not exists market_ready_date date,
  add column if not exists logistics_owner_user_id bigint references sys_user(user_id),
  add column if not exists mexico_owner_user_id bigint references sys_user(user_id),
  add column if not exists production_owner_user_id bigint references sys_user(user_id),
  add column if not exists schedule_notes text;

create table if not exists plm_mold_schedule_plan (
  plan_id bigserial primary key,
  mold_set_id bigint not null references plm_collaboration_mold_set(mold_set_id),
  version_no integer not null check(version_no > 0),
  plan_snapshot jsonb not null,
  reason text not null,
  actor_id bigint not null references sys_user(user_id),
  actor_name varchar(128) not null,
  confirmed_at timestamptz not null default now(),
  unique(mold_set_id,version_no)
);
create table if not exists plm_mold_schedule_reminder (
  reminder_id bigserial primary key,
  mold_set_id bigint not null references plm_collaboration_mold_set(mold_set_id),
  task_key varchar(64) not null,
  due_date date not null,
  recipient_id bigint not null references sys_user(user_id),
  status varchar(16) not null default 'pending' check(status in ('pending','acknowledged')),
  payload jsonb not null,
  created_by varchar(128) not null,
  created_at timestamptz not null default now(),
  acknowledged_at timestamptz,
  unique(mold_set_id,task_key,due_date,recipient_id)
);
create index if not exists ix_mold_schedule_reminder_recipient on plm_mold_schedule_reminder(recipient_id,status,reminder_id);
create index if not exists ix_mold_schedule_delivery_due on plm_collaboration_mold_set(planned_mold_delivery_date) where deleted_flag=0;
