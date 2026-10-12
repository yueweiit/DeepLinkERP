-- Move the previously seeded existing product lines into the archived product list.
-- Scope: Product roots only. Process routes, BOMs, SKUs, and model/color variants remain out of scope.

with seed(product_code, product_name, series_name, product_specific_code, mold_code_prefix, display_order) as (
    values
        ('NLT4030', U&'\6E05\6C34\5957TPU Liso', U&'\6E05\6C34\5957', 'LT', 'MLT', 10),
        ('NRU4030', U&'\4E09\5408\4E00UsoRudo', U&'\4E09\5408\4E00', 'RU', 'MRU', 20),
        ('NDN4030', U&'Alterna\5E7B\7532', U&'Alterna\5E7B\7532', 'DN', 'MDN', 30),
        ('NFA4020', U&'\5E7B\5F71Fantas\00EDa Case', U&'\5E7B\5F71', 'FA', 'MFA', 40),
        ('NHA4030', U&'\8D85\961FS\00FAper Capit\00E1n', U&'\8D85\7EA7\961F\957F', 'HA', 'MHA', 50),
        ('NBD4030', U&'\5723\6BBFCase Blindaje', U&'\5723\6BBF', 'BD', 'MBD', 60),
        ('NBA4030', U&'\4EAE\7532Rainbow 2.0', U&'\4EAE\75322.0', 'BA', 'MBA', 70),
        ('NFB4020', U&'titanio \9A91\58EB2.0', U&'\9A91\58EB2\4EE3', 'FB', 'MFB', 80),
        ('NIM4030', U&'IML\81EA\7814', U&'IML', 'IM', 'MIM', 90),
        ('NHB4030', U&'SUPER APITAN 2 GEN \8D85\961F2.0', U&'\8D85\7EA7\961F\957F2.0', 'HB', 'MHB', 100),
        ('NWV4030', U&'waves\8587\6B66\58EB', U&'\8587\6B66\58EBwaves', 'WV', 'MWV', 110)
)
update plm_product target
set product_name = seed.product_name,
    series_name = seed.series_name,
    product_type = 'product_line',
    parent_product_id = null,
    model = '--',
    color = '--',
    product_code_prefix = seed.product_specific_code,
    mold_code_prefix = seed.mold_code_prefix,
    product_specific_code = seed.product_specific_code,
    version_no = coalesce(nullif(target.version_no, ''), 'V1'),
    status = 'archived',
    current_step_no = 22,
    released_at = coalesce(target.released_at, target.updated_at, target.created_at, now()),
    released_by = coalesce(target.released_by, target.updated_by, target.created_by, 'system'),
    archived_at = coalesce(target.archived_at, target.released_at, target.updated_at, target.created_at, now()),
    archived_by = coalesce(target.archived_by, target.released_by, target.updated_by, target.created_by, 'system'),
    archive_reason = coalesce(nullif(target.archive_reason, ''), U&'\5386\53F2\5DF2\6709\4EA7\54C1\7EBF\8865\5F55'),
    lock_status = coalesce(nullif(target.lock_status, ''), 'unlocked'),
    remark = case
        when coalesce(target.remark, '') like '%seed_existing_product_line_20260729%' then target.remark
        when coalesce(target.remark, '') = '' then 'seed_existing_product_line_20260729; display_order=' || seed.display_order
        else target.remark || '; seed_existing_product_line_20260729; display_order=' || seed.display_order
    end,
    deleted_flag = 0,
    updated_at = now(),
    updated_by = 'system'
from seed
where target.product_code = seed.product_code
   or (
       target.product_type = 'product_line'
       and target.product_specific_code = seed.product_specific_code
   )
   or (
       target.product_type = 'product_line'
       and target.remark like '%seed_existing_product_line_20260729%'
       and target.product_code = seed.product_code
   );

with seed(product_code, product_name, series_name, product_specific_code, mold_code_prefix, display_order) as (
    values
        ('NLT4030', U&'\6E05\6C34\5957TPU Liso', U&'\6E05\6C34\5957', 'LT', 'MLT', 10),
        ('NRU4030', U&'\4E09\5408\4E00UsoRudo', U&'\4E09\5408\4E00', 'RU', 'MRU', 20),
        ('NDN4030', U&'Alterna\5E7B\7532', U&'Alterna\5E7B\7532', 'DN', 'MDN', 30),
        ('NFA4020', U&'\5E7B\5F71Fantas\00EDa Case', U&'\5E7B\5F71', 'FA', 'MFA', 40),
        ('NHA4030', U&'\8D85\961FS\00FAper Capit\00E1n', U&'\8D85\7EA7\961F\957F', 'HA', 'MHA', 50),
        ('NBD4030', U&'\5723\6BBFCase Blindaje', U&'\5723\6BBF', 'BD', 'MBD', 60),
        ('NBA4030', U&'\4EAE\7532Rainbow 2.0', U&'\4EAE\75322.0', 'BA', 'MBA', 70),
        ('NFB4020', U&'titanio \9A91\58EB2.0', U&'\9A91\58EB2\4EE3', 'FB', 'MFB', 80),
        ('NIM4030', U&'IML\81EA\7814', U&'IML', 'IM', 'MIM', 90),
        ('NHB4030', U&'SUPER APITAN 2 GEN \8D85\961F2.0', U&'\8D85\7EA7\961F\957F2.0', 'HB', 'MHB', 100),
        ('NWV4030', U&'waves\8587\6B66\58EB', U&'\8587\6B66\58EBwaves', 'WV', 'MWV', 110)
)
insert into plm_product (
    parent_product_id,
    product_code,
    product_name,
    product_type,
    series_name,
    model,
    color,
    product_code_prefix,
    mold_code_prefix,
    product_specific_code,
    version_no,
    status,
    current_step_no,
    released_at,
    released_by,
    archived_at,
    archived_by,
    archive_reason,
    lock_status,
    remark,
    created_at,
    created_by,
    updated_at,
    updated_by,
    deleted_flag
)
select
    null,
    seed.product_code,
    seed.product_name,
    'product_line',
    seed.series_name,
    '--',
    '--',
    seed.product_specific_code,
    seed.mold_code_prefix,
    seed.product_specific_code,
    'V1',
    'archived',
    22,
    now(),
    'system',
    now(),
    'system',
    U&'\5386\53F2\5DF2\6709\4EA7\54C1\7EBF\8865\5F55',
    'unlocked',
    'seed_existing_product_line_20260729; display_order=' || seed.display_order,
    now(),
    'system',
    now(),
    'system',
    0
from seed
where not exists (
    select 1
    from plm_product existing
    where existing.product_code = seed.product_code
       or (
           existing.product_type = 'product_line'
           and existing.product_specific_code = seed.product_specific_code
       )
);
