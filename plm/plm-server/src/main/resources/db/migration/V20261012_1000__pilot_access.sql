-- Opt-in pilot accounts only. Existing users and historical grants are untouched.
create table if not exists plm_pilot_account (
 user_id bigint primary key references sys_user(user_id),
 role_code varchar(24) not null check(role_code in ('administrator','domestic','finance','supplier','mexico')),
 permissions jsonb not null default '[]'::jsonb,
 all_objects boolean not null default false,
 dingtalk_user_id varchar(128),
 version_no bigint not null default 1,
 created_at timestamptz not null default now(), created_by varchar(128) not null,
 updated_at timestamptz not null default now(), updated_by varchar(128) not null,
 check(role_code not in ('supplier','mexico') or all_objects=false)
);
create unique index if not exists uk_pilot_dingtalk_user on plm_pilot_account(dingtalk_user_id) where dingtalk_user_id is not null;
create table if not exists plm_pilot_scope (
 user_id bigint not null references plm_pilot_account(user_id),
 entity_type varchar(16) not null check(entity_type in ('item','mold','product','file')),
 entity_id bigint not null check(entity_id>0),
 primary key(user_id,entity_type,entity_id)
);
create index if not exists ix_pilot_scope_object on plm_pilot_scope(entity_type,entity_id,user_id);
