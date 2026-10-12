create table if not exists plm_workflow_template (
    workflow_template_id bigserial primary key,
    flow_type varchar(32) not null,
    template_name varchar(128) not null,
    version_no varchar(32) not null,
    status varchar(32) not null default 'draft',
    active_flag integer not null default 0,
    description varchar(1000),
    created_at timestamp not null default now(),
    created_by varchar(64),
    updated_at timestamp not null default now(),
    updated_by varchar(64),
    deleted_flag integer not null default 0
);

comment on table plm_workflow_template is '审批中心流程模板配置';
comment on column plm_workflow_template.flow_type is '流程线：product_line/model_variant';
comment on column plm_workflow_template.active_flag is '是否当前生效模板：1是，0否';

create table if not exists plm_workflow_template_node (
    workflow_node_id bigserial primary key,
    workflow_template_id bigint not null,
    step_no integer not null,
    node_code varchar(128) not null,
    node_name varchar(128) not null,
    stage_code varchar(128),
    stage_name varchar(128),
    phase_name varchar(128),
    required_attachment integer not null default 0,
    required_file_category varchar(64),
    upload_prompt varchar(500),
    confirm_prompt varchar(500),
    empty_file_message varchar(500),
    gate_flag integer not null default 0,
    enabled_flag integer not null default 1,
    remark varchar(1000),
    created_at timestamp not null default now(),
    created_by varchar(64),
    updated_at timestamp not null default now(),
    updated_by varchar(64),
    deleted_flag integer not null default 0
);

comment on table plm_workflow_template_node is '审批中心流程模板节点配置';
comment on column plm_workflow_template_node.required_attachment is '是否必传资料';
comment on column plm_workflow_template_node.upload_prompt is '节点上传资料提示';
comment on column plm_workflow_template_node.confirm_prompt is '节点确认操作提示';
comment on column plm_workflow_template_node.empty_file_message is '缺少必传资料时提示';

alter table if exists plm_product
    add column if not exists workflow_template_id bigint,
    add column if not exists workflow_template_version_no varchar(32);

create unique index if not exists uk_plm_workflow_template_active
    on plm_workflow_template(flow_type)
    where deleted_flag = 0 and active_flag = 1;

create unique index if not exists uk_plm_workflow_template_version
    on plm_workflow_template(flow_type, version_no)
    where deleted_flag = 0;

create index if not exists idx_plm_workflow_template_flow_status
    on plm_workflow_template(flow_type, status)
    where deleted_flag = 0;

create unique index if not exists uk_plm_workflow_template_node_step
    on plm_workflow_template_node(workflow_template_id, step_no)
    where deleted_flag = 0;

create unique index if not exists uk_plm_workflow_template_node_code
    on plm_workflow_template_node(workflow_template_id, node_code)
    where deleted_flag = 0;

insert into plm_workflow_template (
    flow_type, template_name, version_no, status, active_flag, description, created_by, updated_by, deleted_flag
)
select 'product_line', '新产品线标准流程', 'V1', 'active', 1, '审批中心初始化的新产品线流程模板', 'system', 'system', 0
where not exists (
    select 1 from plm_workflow_template where flow_type = 'product_line' and version_no = 'V1' and deleted_flag = 0
);

insert into plm_workflow_template (
    flow_type, template_name, version_no, status, active_flag, description, created_by, updated_by, deleted_flag
)
select 'model_variant', '新型号线标准流程', 'V1', 'active', 1, '审批中心初始化的新型号线流程模板，默认与新产品线节点一致', 'system', 'system', 0
where not exists (
    select 1 from plm_workflow_template where flow_type = 'model_variant' and version_no = 'V1' and deleted_flag = 0
);

with target as (
    select workflow_template_id
    from plm_workflow_template
    where flow_type = 'product_line' and version_no = 'V1' and deleted_flag = 0
    order by workflow_template_id
    limit 1
)
insert into plm_workflow_template_node (
    workflow_template_id, step_no, node_code, node_name, stage_code, stage_name, phase_name,
    required_attachment, required_file_category, upload_prompt, confirm_prompt, empty_file_message,
    gate_flag, enabled_flag, remark, created_by, updated_by, deleted_flag
)
select target.workflow_template_id, node.step_no, node.node_code, node.node_name, node.stage_code, node.stage_name, node.phase_name,
       node.required_attachment, node.required_file_category,
       '请按节点要求上传资料，可补充版本号和备注。',
       '确认前请检查必传资料、BOM、工艺或门禁条件是否完成。',
       '当前节点必传资料未上传：' || node.node_name,
       node.gate_flag, 1, null, 'system', 'system', 0
from target
cross join (values
    (1, 'PRODUCT_LINE_INIT_CREATE', '产品立项', 'PRODUCT_LINE_INIT_CONFIRM', '立项确认', '立项阶段', 1, 'other', 0),
    (2, 'PRODUCT_LINE_INIT_APPROVE', '确认立项', 'PRODUCT_LINE_INIT_CONFIRM', '立项确认', '立项阶段', 0, null, 0),
    (3, 'PRODUCT_LINE_DESIGN_DRAWING', '画图查看', 'PRODUCT_LINE_DESIGN_CONFIRM', '设计确认', '设计验证阶段', 1, 'drawing', 0),
    (4, 'PRODUCT_LINE_DESIGN_SUPPLIER_CONFIRM', '供应商确认外观图纸', 'PRODUCT_LINE_DESIGN_CONFIRM', '设计确认', '设计验证阶段', 1, 'drawing', 0),
    (5, 'PRODUCT_LINE_MOLD_APPLY', '申请开模', 'PRODUCT_LINE_MOLD_TRIAL', '开模试模', '开模阶段', 0, null, 0),
    (6, 'PRODUCT_LINE_MOLD_MAKE', '制作模具', 'PRODUCT_LINE_MOLD_TRIAL', '开模试模', '开模阶段', 1, 'other', 0),
    (7, 'PRODUCT_LINE_MOLD_TEST', '测试模具', 'PRODUCT_LINE_MOLD_TRIAL', '开模试模', '开模阶段', 1, 'testing', 0),
    (8, 'PRODUCT_LINE_SAMPLE_SIGN', '签样确认', 'PRODUCT_LINE_SAMPLE_PROCESS', '样品与工艺', '样品/工艺定型阶段', 1, 'customer_confirm', 0),
    (9, 'PRODUCT_LINE_PROCESS_PLAN', '加工艺', 'PRODUCT_LINE_SAMPLE_PROCESS', '样品与工艺', '样品/工艺定型阶段', 1, 'sop', 1),
    (10, 'PRODUCT_LINE_PROCESS_CONFIRM', '敲定工序', 'PRODUCT_LINE_SAMPLE_PROCESS', '样品与工艺', '样品/工艺定型阶段', 1, 'sop', 1),
    (11, 'PRODUCT_LINE_COMPONENT_CONFIRM', '确认组件', 'PRODUCT_LINE_SAMPLE_PROCESS', '样品与工艺', '样品/工艺定型阶段', 0, null, 0),
    (12, 'PRODUCT_LINE_COMPONENT_FINISH_CONFIRM', '确认组件成品', 'PRODUCT_LINE_SAMPLE_PROCESS', '样品与工艺', '样品/工艺定型阶段', 0, null, 0),
    (13, 'PRODUCT_LINE_FINAL_APPEARANCE_SAMPLE', '最终外观确认样', 'PRODUCT_LINE_SAMPLE_PROCESS', '样品与工艺', '样品/工艺定型阶段', 1, 'customer_confirm', 0),
    (14, 'PRODUCT_LINE_RED_SAMPLE_TEST', '红样测试', 'PRODUCT_LINE_SAMPLE_PROCESS', '样品与工艺', '样品/工艺定型阶段', 1, 'testing', 0),
    (15, 'PRODUCT_LINE_PRODUCTION_DOCS', '整理生产资料', 'PRODUCT_LINE_SAMPLE_PROCESS', '样品与工艺', '样品/工艺定型阶段', 1, 'sop', 0),
    (16, 'PRODUCT_LINE_YELLOW_SAMPLE', '黄样', 'PRODUCT_LINE_SAMPLE_PROCESS', '样品与工艺', '样品/工艺定型阶段', 1, 'testing', 0),
    (17, 'PRODUCT_LINE_SMALL_BATCH_TEST', '小批量测试', 'PRODUCT_LINE_SMALL_BATCH_MX', '小批与 MX 验证', '市场验证阶段', 1, 'testing', 0),
    (18, 'PRODUCT_LINE_MOLD_TRANSFER', '运模', 'PRODUCT_LINE_SMALL_BATCH_MX', '小批与 MX 验证', '市场验证阶段', 0, null, 1),
    (19, 'PRODUCT_LINE_MX_ACCEPTANCE', 'MX 验收', 'PRODUCT_LINE_SMALL_BATCH_MX', '小批与 MX 验证', '市场验证阶段', 1, 'testing', 0),
    (20, 'PRODUCT_LINE_TEST_VERIFY', '测试验证', 'PRODUCT_LINE_SMALL_BATCH_MX', '小批与 MX 验证', '市场验证阶段', 1, 'testing', 0),
    (21, 'PRODUCT_LINE_MX_MARKET_TEST', 'MX 小批量测试', 'PRODUCT_LINE_SMALL_BATCH_MX', '小批与 MX 验证', '市场验证阶段', 1, 'testing', 0),
    (22, 'PRODUCT_LINE_PRODUCTION_DECISION_STEP', '投产决策', 'PRODUCT_LINE_PRODUCTION_DECISION', '投产决策', '投产发布阶段', 0, null, 1)
) as node(step_no, node_code, node_name, stage_code, stage_name, phase_name, required_attachment, required_file_category, gate_flag)
where not exists (
    select 1 from plm_workflow_template_node
    where workflow_template_id = target.workflow_template_id and deleted_flag = 0
);

with target as (
    select workflow_template_id
    from plm_workflow_template
    where flow_type = 'model_variant' and version_no = 'V1' and deleted_flag = 0
    order by workflow_template_id
    limit 1
)
insert into plm_workflow_template_node (
    workflow_template_id, step_no, node_code, node_name, stage_code, stage_name, phase_name,
    required_attachment, required_file_category, upload_prompt, confirm_prompt, empty_file_message,
    gate_flag, enabled_flag, remark, created_by, updated_by, deleted_flag
)
select target.workflow_template_id, node.step_no, node.node_code, node.node_name, node.stage_code, node.stage_name, node.phase_name,
       node.required_attachment, node.required_file_category,
       '请按节点要求上传资料，可补充版本号和备注。',
       '确认前请检查必传资料、BOM、工艺或门禁条件是否完成。',
       '当前节点必传资料未上传：' || node.node_name,
       node.gate_flag, 1, null, 'system', 'system', 0
from target
cross join (values
    (1, 'MODEL_VARIANT_INIT_CREATE', '产品立项', 'MODEL_VARIANT_INIT_CONFIRM', '立项确认', '立项阶段', 1, 'other', 0),
    (2, 'MODEL_VARIANT_INIT_APPROVE', '确认立项', 'MODEL_VARIANT_INIT_CONFIRM', '立项确认', '立项阶段', 0, null, 0),
    (3, 'MODEL_VARIANT_DESIGN_DRAWING', '画图查看', 'MODEL_VARIANT_DESIGN_CONFIRM', '设计确认', '设计验证阶段', 1, 'drawing', 0),
    (4, 'MODEL_VARIANT_DESIGN_SUPPLIER_CONFIRM', '供应商确认外观图纸', 'MODEL_VARIANT_DESIGN_CONFIRM', '设计确认', '设计验证阶段', 1, 'drawing', 0),
    (5, 'MODEL_VARIANT_MOLD_APPLY', '申请开模', 'MODEL_VARIANT_MOLD_TRIAL', '开模试模', '开模阶段', 0, null, 0),
    (6, 'MODEL_VARIANT_MOLD_MAKE', '制作模具', 'MODEL_VARIANT_MOLD_TRIAL', '开模试模', '开模阶段', 1, 'other', 0),
    (7, 'MODEL_VARIANT_MOLD_TEST', '测试模具', 'MODEL_VARIANT_MOLD_TRIAL', '开模试模', '开模阶段', 1, 'testing', 0),
    (8, 'MODEL_VARIANT_SAMPLE_SIGN', '签样确认', 'MODEL_VARIANT_SAMPLE_PROCESS', '样品与工艺', '样品/工艺定型阶段', 1, 'customer_confirm', 0),
    (9, 'MODEL_VARIANT_PROCESS_PLAN', '加工艺', 'MODEL_VARIANT_SAMPLE_PROCESS', '样品与工艺', '样品/工艺定型阶段', 1, 'sop', 1),
    (10, 'MODEL_VARIANT_PROCESS_CONFIRM', '敲定工序', 'MODEL_VARIANT_SAMPLE_PROCESS', '样品与工艺', '样品/工艺定型阶段', 1, 'sop', 1),
    (11, 'MODEL_VARIANT_COMPONENT_CONFIRM', '确认组件', 'MODEL_VARIANT_SAMPLE_PROCESS', '样品与工艺', '样品/工艺定型阶段', 0, null, 0),
    (12, 'MODEL_VARIANT_COMPONENT_FINISH_CONFIRM', '确认组件成品', 'MODEL_VARIANT_SAMPLE_PROCESS', '样品与工艺', '样品/工艺定型阶段', 0, null, 0),
    (13, 'MODEL_VARIANT_FINAL_APPEARANCE_SAMPLE', '最终外观确认样', 'MODEL_VARIANT_SAMPLE_PROCESS', '样品与工艺', '样品/工艺定型阶段', 1, 'customer_confirm', 0),
    (14, 'MODEL_VARIANT_RED_SAMPLE_TEST', '红样测试', 'MODEL_VARIANT_SAMPLE_PROCESS', '样品与工艺', '样品/工艺定型阶段', 1, 'testing', 0),
    (15, 'MODEL_VARIANT_PRODUCTION_DOCS', '整理生产资料', 'MODEL_VARIANT_SAMPLE_PROCESS', '样品与工艺', '样品/工艺定型阶段', 1, 'sop', 0),
    (16, 'MODEL_VARIANT_YELLOW_SAMPLE', '黄样', 'MODEL_VARIANT_SAMPLE_PROCESS', '样品与工艺', '样品/工艺定型阶段', 1, 'testing', 0),
    (17, 'MODEL_VARIANT_SMALL_BATCH_TEST', '小批量测试', 'MODEL_VARIANT_SMALL_BATCH_MX', '小批与 MX 验证', '市场验证阶段', 1, 'testing', 0),
    (18, 'MODEL_VARIANT_MOLD_TRANSFER', '运模', 'MODEL_VARIANT_SMALL_BATCH_MX', '小批与 MX 验证', '市场验证阶段', 0, null, 1),
    (19, 'MODEL_VARIANT_MX_ACCEPTANCE', 'MX 验收', 'MODEL_VARIANT_SMALL_BATCH_MX', '小批与 MX 验证', '市场验证阶段', 1, 'testing', 0),
    (20, 'MODEL_VARIANT_TEST_VERIFY', '测试验证', 'MODEL_VARIANT_SMALL_BATCH_MX', '小批与 MX 验证', '市场验证阶段', 1, 'testing', 0),
    (21, 'MODEL_VARIANT_MX_MARKET_TEST', 'MX 小批量测试', 'MODEL_VARIANT_SMALL_BATCH_MX', '小批与 MX 验证', '市场验证阶段', 1, 'testing', 0),
    (22, 'MODEL_VARIANT_RELEASE', '投产决策', 'MODEL_VARIANT_PRODUCTION_DECISION', '投产决策', '投产发布阶段', 0, null, 1)
) as node(step_no, node_code, node_name, stage_code, stage_name, phase_name, required_attachment, required_file_category, gate_flag)
where not exists (
    select 1 from plm_workflow_template_node
    where workflow_template_id = target.workflow_template_id and deleted_flag = 0
);
