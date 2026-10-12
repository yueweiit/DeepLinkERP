create table if not exists plm_market_watch_link (
  source_kind varchar(16) not null check (source_kind in ('phone','candidate')),
  source_id bigint not null,
  collaboration_item_id bigint not null references plm_collaboration_item(item_id),
  source_snapshot jsonb not null,
  promoted_by_id bigint not null references sys_user(user_id),
  promoted_by_name varchar(128) not null,
  promoted_at timestamptz not null default now(),
  primary key(source_kind, source_id)
);

create index if not exists ix_market_watch_link_item
  on plm_market_watch_link(collaboration_item_id, promoted_at desc);
