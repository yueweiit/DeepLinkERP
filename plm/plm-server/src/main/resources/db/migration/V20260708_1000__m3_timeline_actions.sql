alter table plm_product
    add column if not exists timeline_current_confirmed boolean not null default false,
    add column if not exists timeline_confirmed_node_key varchar(128),
    add column if not exists timeline_last_action varchar(64),
    add column if not exists timeline_last_reason text,
    add column if not exists timeline_last_operated_at timestamp,
    add column if not exists timeline_last_operator_user_id bigint,
    add column if not exists timeline_last_operator_user_name varchar(64);

comment on column plm_product.timeline_current_confirmed is '当前时间轴节点是否已确认';
comment on column plm_product.timeline_confirmed_node_key is '最近一次确认的节点key';
comment on column plm_product.timeline_last_action is '最近一次时间轴动作: confirm/advance/return';
comment on column plm_product.timeline_last_reason is '最近一次时间轴动作原因或备注';
comment on column plm_product.timeline_last_operated_at is '最近一次时间轴动作时间';
comment on column plm_product.timeline_last_operator_user_id is '最近一次时间轴操作人ID';
comment on column plm_product.timeline_last_operator_user_name is '最近一次时间轴操作人姓名';
