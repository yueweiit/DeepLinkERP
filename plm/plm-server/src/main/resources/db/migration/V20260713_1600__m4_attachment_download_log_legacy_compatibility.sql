do $$
begin
    if exists (
        select 1
        from information_schema.columns
        where table_schema = current_schema()
          and table_name = 'plm_attachment_download_log'
          and column_name = 'attachment_download_log_id'
    ) and not exists (
        select 1
        from information_schema.columns
        where table_schema = current_schema()
          and table_name = 'plm_attachment_download_log'
          and column_name = 'download_log_id'
    ) then
        alter table plm_attachment_download_log
            rename column attachment_download_log_id to download_log_id;
    end if;

    if exists (
        select 1
        from information_schema.columns
        where table_schema = current_schema()
          and table_name = 'plm_attachment_download_log'
          and column_name = 'download_user_id'
    ) and not exists (
        select 1
        from information_schema.columns
        where table_schema = current_schema()
          and table_name = 'plm_attachment_download_log'
          and column_name = 'operator_user_id'
    ) then
        alter table plm_attachment_download_log
            rename column download_user_id to operator_user_id;
    end if;

    if exists (
        select 1
        from information_schema.columns
        where table_schema = current_schema()
          and table_name = 'plm_attachment_download_log'
          and column_name = 'download_user_name'
    ) and not exists (
        select 1
        from information_schema.columns
        where table_schema = current_schema()
          and table_name = 'plm_attachment_download_log'
          and column_name = 'operator_user_name'
    ) then
        alter table plm_attachment_download_log
            rename column download_user_name to operator_user_name;
    end if;

    if exists (
        select 1
        from information_schema.columns
        where table_schema = current_schema()
          and table_name = 'plm_attachment_download_log'
          and column_name = 'download_ip'
    ) and not exists (
        select 1
        from information_schema.columns
        where table_schema = current_schema()
          and table_name = 'plm_attachment_download_log'
          and column_name = 'client_ip'
    ) then
        alter table plm_attachment_download_log
            rename column download_ip to client_ip;
    end if;
end
$$;

alter table if exists plm_attachment_download_log
    add column if not exists request_id varchar(64),
    add column if not exists user_agent varchar(512),
    add column if not exists created_by varchar(64) not null default 'system',
    add column if not exists updated_at timestamp not null default now(),
    add column if not exists updated_by varchar(64) not null default 'system',
    add column if not exists deleted_flag integer not null default 0;
