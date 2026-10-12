create table if not exists sys_user (
    user_id bigserial primary key,
    username varchar(64) not null unique,
    password_hash varchar(128) not null,
    display_name varchar(64) not null,
    department_name varchar(64) not null,
    formal_flag integer not null default 1,
    all_permissions boolean not null default false,
    status varchar(32) not null default 'active',
    created_at timestamp not null default now(),
    created_by varchar(64),
    updated_at timestamp not null default now(),
    updated_by varchar(64),
    deleted_flag integer not null default 0
);

alter table if exists sys_user add column if not exists password_hash varchar(128);
alter table if exists sys_user add column if not exists user_code varchar(64);
alter table if exists sys_user add column if not exists username varchar(64);
alter table if exists sys_user add column if not exists login_name varchar(128);
alter table if exists sys_user add column if not exists user_name varchar(128);
alter table if exists sys_user add column if not exists display_name varchar(64);
alter table if exists sys_user add column if not exists department_name varchar(64);
alter table if exists sys_user add column if not exists formal_flag integer not null default 1;
alter table if exists sys_user add column if not exists all_permissions boolean not null default false;
alter table if exists sys_user add column if not exists status varchar(32) not null default 'active';
alter table if exists sys_user add column if not exists created_at timestamp not null default now();
alter table if exists sys_user add column if not exists created_by varchar(64);
alter table if exists sys_user add column if not exists updated_at timestamp not null default now();
alter table if exists sys_user add column if not exists updated_by varchar(64);
alter table if exists sys_user add column if not exists deleted_flag integer not null default 0;

update sys_user
set username = coalesce(username, login_name),
    login_name = coalesce(login_name, username),
    user_name = coalesce(user_name, display_name),
    display_name = coalesce(display_name, user_name),
    user_code = coalesce(user_code, username)
where username is null
   or login_name is null
   or user_name is null
   or display_name is null
   or user_code is null;

create unique index if not exists uk_sys_user_code_m1 on sys_user(user_code) where user_code is not null;
create unique index if not exists uk_sys_user_username on sys_user(username) where username is not null;
create index if not exists idx_sys_user_username on sys_user(username);
create index if not exists idx_sys_user_status on sys_user(status);

create table if not exists plm_operation_log (
    log_id bigserial primary key,
    request_id varchar(64) not null,
    operator_user_id bigint,
    operator_user_name varchar(64),
    action varchar(64) not null,
    business_type varchar(64) not null,
    business_id varchar(64),
    business_code varchar(128),
    business_name varchar(256),
    result varchar(32) not null default 'success',
    request_method varchar(16),
    request_uri varchar(512),
    client_ip varchar(64),
    user_agent varchar(512),
    detail_json text,
    created_at timestamp not null default now(),
    created_by varchar(64),
    updated_at timestamp,
    updated_by varchar(64),
    deleted_flag integer not null default 0
);

alter table if exists plm_operation_log add column if not exists log_id bigserial;
alter table if exists plm_operation_log add column if not exists business_type varchar(64);
alter table if exists plm_operation_log add column if not exists business_id varchar(64);
alter table if exists plm_operation_log add column if not exists business_code varchar(128);
alter table if exists plm_operation_log add column if not exists business_name varchar(256);
alter table if exists plm_operation_log add column if not exists action varchar(64);
alter table if exists plm_operation_log add column if not exists result varchar(32) not null default 'success';
alter table if exists plm_operation_log add column if not exists request_method varchar(16);
alter table if exists plm_operation_log add column if not exists request_uri varchar(512);
alter table if exists plm_operation_log add column if not exists client_ip varchar(64);
alter table if exists plm_operation_log add column if not exists user_agent varchar(512);
alter table if exists plm_operation_log add column if not exists detail_json text;
alter table if exists plm_operation_log add column if not exists created_by varchar(64);
alter table if exists plm_operation_log add column if not exists updated_at timestamp;
alter table if exists plm_operation_log add column if not exists updated_by varchar(64);
alter table if exists plm_operation_log add column if not exists deleted_flag integer not null default 0;
alter table if exists plm_operation_log alter column object_type set default 'System';
alter table if exists plm_operation_log alter column object_id set default 0;
alter table if exists plm_operation_log alter column action_type set default 'create';
alter table if exists plm_operation_log alter column action_result set default 'success';

create index if not exists idx_operation_log_request_id on plm_operation_log(request_id);
create index if not exists idx_operation_log_operator on plm_operation_log(operator_user_id);
create index if not exists idx_operation_log_action on plm_operation_log(action);
create index if not exists idx_operation_log_business on plm_operation_log(business_type, business_id);
create index if not exists idx_operation_log_created_at on plm_operation_log(created_at desc);

insert into sys_user (
    user_code,
    username,
    login_name,
    user_name,
    password_hash,
    display_name,
    department_name,
    formal_flag,
    all_permissions,
    status,
    created_by,
    updated_by
) values
('ENG001', 'engineer01', 'engineer01', '工程部用户一', '$2a$10$Cl10evRTNecje9kt72atyuF2vYp47ebcMJQCjuXt4/GgbSCpG8RqK', '工程部用户一', '工程部', 1, true, 'active', 'seed', 'seed'),
('ENG002', 'engineer02', 'engineer02', '工程部用户二', '$2a$10$Cl10evRTNecje9kt72atyuF2vYp47ebcMJQCjuXt4/GgbSCpG8RqK', '工程部用户二', '工程部', 1, true, 'active', 'seed', 'seed')
on conflict (user_code) do update set
    username = excluded.username,
    login_name = excluded.login_name,
    user_name = excluded.user_name,
    password_hash = excluded.password_hash,
    display_name = excluded.display_name,
    department_name = excluded.department_name,
    formal_flag = excluded.formal_flag,
    all_permissions = excluded.all_permissions,
    status = excluded.status,
    updated_by = excluded.updated_by,
    updated_at = now();
