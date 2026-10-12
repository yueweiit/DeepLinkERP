alter table if exists plm_process
    add column if not exists operation_master_process_id bigint;

alter table if exists plm_process
    drop constraint if exists ck_plm_process_type;

alter table if exists plm_process
    add constraint ck_plm_process_type
    check (process_type in (
        'routing',
        'operation',
        'change',
        'quality_gate',
        'sample_process',
        'operation_master',
        'route_template',
        'route_template_operation'
    ));

create index if not exists idx_plm_process_operation_master
    on plm_process (operation_master_process_id)
    where operation_master_process_id is not null;

create index if not exists idx_plm_process_type_code
    on plm_process (process_type, process_code, deleted_flag);

insert into plm_process (
    product_id, process_code, process_name, process_type, version_no,
    process_param_json, standard_time_mins, quality_requirement, status,
    remark, created_at, created_by, updated_at, updated_by, deleted_flag
)
select
    seed.product_id,
    seed.process_code,
    seed.process_name,
    seed.process_type,
    seed.version_no,
    seed.process_param_json::jsonb,
    seed.standard_time_mins,
    seed.quality_requirement,
    seed.status,
    seed.remark,
    now(),
    'system',
    now(),
    'system',
    0
from (
    values
        (null::bigint, 'PROC_INJECTION', '注塑成型', 'operation_master', 'V1', '{"processCategory":"成型","operationType":"加工","needWorkstation":true,"workstationType":"注塑机","defaultProcessParamJson":{"temperature":"按材料工艺卡","pressure":"按模具工艺卡"}}', 12.00::numeric, '外观无缩水、无明显披锋，尺寸符合图纸要求', 'confirmed', '基础工序库初始化'),
        (null::bigint, 'PROC_TPU_FORMING', 'TPU 成型', 'operation_master', 'V1', '{"processCategory":"成型","operationType":"加工","needWorkstation":true,"workstationType":"成型设备","defaultProcessParamJson":{"material":"TPU","temperature":"按材料工艺卡"}}', 10.00::numeric, '成型完整，无缺胶、变形和明显色差', 'confirmed', '基础工序库初始化'),
        (null::bigint, 'PROC_BASE_FORMING', '基材成型', 'operation_master', 'V1', '{"processCategory":"成型","operationType":"加工","needWorkstation":true,"workstationType":"成型设备","defaultProcessParamJson":{}}', 8.00::numeric, '基材平整，尺寸和孔位符合要求', 'confirmed', '基础工序库初始化'),
        (null::bigint, 'PROC_TRIMMING', '修边去披锋', 'operation_master', 'V1', '{"processCategory":"后处理","operationType":"加工","needWorkstation":false,"workstationType":"人工工位","defaultProcessParamJson":{}}', 4.00::numeric, '边缘平顺，无明显毛刺和刮手风险', 'confirmed', '基础工序库初始化'),
        (null::bigint, 'PROC_PUNCHING', '打孔', 'operation_master', 'V1', '{"processCategory":"后处理","operationType":"加工","needWorkstation":true,"workstationType":"冲孔设备","defaultProcessParamJson":{}}', 5.00::numeric, '孔位准确，无裂纹和毛边', 'confirmed', '基础工序库初始化'),
        (null::bigint, 'PROC_SURFACE_CLEAN', '表面清洁', 'operation_master', 'V1', '{"processCategory":"表面处理","operationType":"加工","needWorkstation":false,"workstationType":"清洁工位","defaultProcessParamJson":{}}', 3.00::numeric, '表面无油污、无明显灰尘和异物', 'confirmed', '基础工序库初始化'),
        (null::bigint, 'PROC_COATING', '喷涂', 'operation_master', 'V1', '{"processCategory":"表面处理","operationType":"加工","needWorkstation":true,"workstationType":"喷涂线","defaultProcessParamJson":{"coating":"按颜色工艺卡"}}', 9.00::numeric, '涂层均匀，无流挂、露底和明显色差', 'confirmed', '基础工序库初始化'),
        (null::bigint, 'PROC_ASSEMBLY', '组装', 'operation_master', 'V1', '{"processCategory":"组装","operationType":"加工","needWorkstation":false,"workstationType":"组装工位","defaultProcessParamJson":{}}', 6.00::numeric, '磁片、支架、饰件装配牢固，位置符合样件要求', 'confirmed', '基础工序库初始化'),
        (null::bigint, 'PROC_PACKING', '包装', 'operation_master', 'V1', '{"processCategory":"包装","operationType":"包装","needWorkstation":false,"workstationType":"包装工位","defaultProcessParamJson":{}}', 4.00::numeric, '包装资料齐套，标签与产品一致', 'confirmed', '基础工序库初始化'),
        (null::bigint, 'PROC_FINAL_INSPECTION', '成品检验', 'operation_master', 'V1', '{"processCategory":"质检","operationType":"检验","needWorkstation":false,"workstationType":"质检工位","defaultProcessParamJson":{}}', 5.00::numeric, '外观、尺寸、装配和包装抽检合格', 'confirmed', '基础工序库初始化')
) as seed(product_id, process_code, process_name, process_type, version_no, process_param_json, standard_time_mins, quality_requirement, status, remark)
where not exists (
    select 1 from plm_process existing
    where existing.process_code = seed.process_code and existing.deleted_flag = 0
);

insert into plm_process (
    product_id, process_code, process_name, process_type, version_no,
    process_param_json, status, remark, created_at, created_by, updated_at, updated_by, deleted_flag
)
select
    seed.product_id,
    seed.process_code,
    seed.process_name,
    seed.process_type,
    seed.version_no,
    seed.process_param_json::jsonb,
    seed.status,
    seed.remark,
    now(),
    'system',
    now(),
    'system',
    0
from (
    values
        (null::bigint, 'ROUTE-STD-INJECTION', '标准注塑组装路线', 'route_template', 'V1', '{"productCode":"COMMON","defaultTemplate":true,"priority":100}', 'confirmed', '基础标准工艺路线初始化'),
        (null::bigint, 'ROUTE-STD-TPU-PUNCH', 'TPU 打孔组装路线', 'route_template', 'V1', '{"productCode":"COMMON","defaultTemplate":false,"priority":80}', 'confirmed', '基础标准工艺路线初始化'),
        (null::bigint, 'ROUTE-STD-COATING', '表面处理喷涂路线', 'route_template', 'V1', '{"productCode":"COMMON","defaultTemplate":false,"priority":60}', 'confirmed', '基础标准工艺路线初始化')
) as seed(product_id, process_code, process_name, process_type, version_no, process_param_json, status, remark)
where not exists (
    select 1 from plm_process existing
    where existing.process_code = seed.process_code and existing.deleted_flag = 0
);

insert into plm_process (
    parent_process_id, product_id, operation_master_process_id, process_code, process_name,
    process_type, version_no, sequence_no, process_param_json, standard_time_mins,
    quality_requirement, status, remark, created_at, created_by, updated_at, updated_by, deleted_flag
)
select
    template.process_id,
    null,
    master.process_id,
    seed.child_code,
    master.process_name,
    'route_template_operation',
    'V1',
    seed.sequence_no,
    jsonb_build_object(
        'operationCode', master.process_code,
        'operationMasterProcessId', master.process_id,
        'operationMasterCode', master.process_code,
        'operationMasterName', master.process_name,
        'defaultProcessParamJson', coalesce(master.process_param_json::jsonb -> 'defaultProcessParamJson', '{}'::jsonb)
    ),
    master.standard_time_mins,
    master.quality_requirement,
    'confirmed',
    seed.remark,
    now(),
    'system',
    now(),
    'system',
    0
from (
    values
        ('ROUTE-STD-INJECTION', 'ROUTE-STD-INJECTION-OP-010', 'PROC_INJECTION', 10, '模板工序：注塑成型'),
        ('ROUTE-STD-INJECTION', 'ROUTE-STD-INJECTION-OP-020', 'PROC_TRIMMING', 20, '模板工序：修边去披锋'),
        ('ROUTE-STD-INJECTION', 'ROUTE-STD-INJECTION-OP-030', 'PROC_ASSEMBLY', 30, '模板工序：组装'),
        ('ROUTE-STD-INJECTION', 'ROUTE-STD-INJECTION-OP-040', 'PROC_FINAL_INSPECTION', 40, '模板工序：成品检验'),
        ('ROUTE-STD-INJECTION', 'ROUTE-STD-INJECTION-OP-050', 'PROC_PACKING', 50, '模板工序：包装'),
        ('ROUTE-STD-TPU-PUNCH', 'ROUTE-STD-TPU-PUNCH-OP-010', 'PROC_TPU_FORMING', 10, '模板工序：TPU 成型'),
        ('ROUTE-STD-TPU-PUNCH', 'ROUTE-STD-TPU-PUNCH-OP-020', 'PROC_PUNCHING', 20, '模板工序：打孔'),
        ('ROUTE-STD-TPU-PUNCH', 'ROUTE-STD-TPU-PUNCH-OP-030', 'PROC_ASSEMBLY', 30, '模板工序：组装'),
        ('ROUTE-STD-TPU-PUNCH', 'ROUTE-STD-TPU-PUNCH-OP-040', 'PROC_FINAL_INSPECTION', 40, '模板工序：成品检验'),
        ('ROUTE-STD-COATING', 'ROUTE-STD-COATING-OP-010', 'PROC_BASE_FORMING', 10, '模板工序：基材成型'),
        ('ROUTE-STD-COATING', 'ROUTE-STD-COATING-OP-020', 'PROC_SURFACE_CLEAN', 20, '模板工序：表面清洁'),
        ('ROUTE-STD-COATING', 'ROUTE-STD-COATING-OP-030', 'PROC_COATING', 30, '模板工序：喷涂'),
        ('ROUTE-STD-COATING', 'ROUTE-STD-COATING-OP-040', 'PROC_FINAL_INSPECTION', 40, '模板工序：成品检验')
) as seed(template_code, child_code, master_code, sequence_no, remark)
join plm_process template on template.process_code = seed.template_code and template.deleted_flag = 0
join plm_process master on master.process_code = seed.master_code and master.deleted_flag = 0
where not exists (
    select 1 from plm_process existing
    where existing.process_code = seed.child_code and existing.deleted_flag = 0
);
