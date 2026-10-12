-- Seed existing product-line master data from the confirmed mould/product option list.
-- Scope: Product roots only. Process routes, BOMs, SKUs, and color/model variants are imported separately.

with seed(product_code, product_name, series_name, product_specific_code, mold_code_prefix, display_order) as (
    values
        ('NLT4030', '清水套TPU Liso', '清水套', 'LT', 'MLT', 10),
        ('NRU4030', '三合一UsoRudo', '三合一', 'RU', 'MRU', 20),
        ('NDN4030', 'Alterna幻甲', 'Alterna幻甲', 'DN', 'MDN', 30),
        ('NFA4020', '幻影Fantasía Case', '骑士', 'FA', 'MFA', 40),
        ('NHA4030', '超队Súper Capitán', '超级队长', 'HA', 'MHA', 50),
        ('NBD4030', '圣殿Case Blindaje', '圣殿', 'BD', 'MBD', 60),
        ('NBA4030', '亮甲Rainbow 2.0', '亮甲2.0', 'BA', 'MBA', 70),
        ('NFB4020', 'titanio 骑士2.0', '骑士2代', 'FB', 'MFB', 80),
        ('NIM4030', 'IML自研', 'IML', 'IM', 'MIM', 90),
        ('NHB4030', 'SUPER APITAN 2 GEN 超队2.0', '超级队长2.0', 'HB', 'MHB', 100),
        ('NWV4030', 'waves薇武士', '薇武士waves', 'WV', 'MWV', 110)
),
updated as (
    update plm_product target
    set parent_product_id = null,
        product_code = case
            when target.product_code = seed.product_code then target.product_code
            when not exists (
                select 1
                from plm_product conflict_product
                where conflict_product.product_code = seed.product_code
                  and conflict_product.product_id <> target.product_id
            ) then seed.product_code
            else target.product_code
        end,
        product_name = seed.product_name,
        product_type = 'product_line',
        series_name = seed.series_name,
        model = '--',
        color = '--',
        product_code_prefix = seed.product_specific_code,
        mold_code_prefix = seed.mold_code_prefix,
        product_specific_code = seed.product_specific_code,
        version_no = coalesce(nullif(target.version_no, ''), 'V1'),
        status = 'released',
        current_step_no = 22,
        released_at = coalesce(target.released_at, now()),
        released_by = coalesce(target.released_by, 'system'),
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
    returning seed.product_code
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
    'released',
    22,
    now(),
    'system',
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
    from updated
    where updated.product_code = seed.product_code
)
and not exists (
    select 1
    from plm_product existing
    where existing.product_code = seed.product_code
       or (
           existing.product_type = 'product_line'
           and existing.product_specific_code = seed.product_specific_code
       )
);
