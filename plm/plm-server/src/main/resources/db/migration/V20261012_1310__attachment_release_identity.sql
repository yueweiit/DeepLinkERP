-- Keep historical release timestamps and publisher names as-is; add the stable identity separately.
alter table plm_attachment add column if not exists released_by_user_id bigint references sys_user(user_id);
