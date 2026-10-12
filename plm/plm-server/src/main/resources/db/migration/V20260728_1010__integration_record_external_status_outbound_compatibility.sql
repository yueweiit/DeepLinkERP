update plm_integration_record
set external_status = processing_status
where external_status is null;

alter table if exists plm_integration_record
    alter column external_status drop not null;
