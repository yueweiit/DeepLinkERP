-- YUEWEI PLM seed data
SET search_path TO plm;

INSERT INTO sys_dict_type (dict_type_code, dict_type_name, status, created_by, updated_by)
VALUES
('core_object_type', '核心对象类型', 'active', 'system', 'system'),
('customer_status', '客户状态', 'active', 'system', 'system'),
('product_status', '产品状态', 'active', 'system', 'system'),
('order_status', '订单状态', 'active', 'system', 'system'),
('production_order_status', '生产单状态', 'active', 'system', 'system'),
('process_status', '工艺状态', 'active', 'system', 'system'),
('inventory_status', '库存对象状态', 'active', 'system', 'system'),
('workstation_status', '工作站状态', 'active', 'system', 'system'),
('product_type', '产品类型', 'active', 'system', 'system'),
('order_type', '订单类型', 'active', 'system', 'system'),
('order_source_type', '订单来源类型', 'active', 'system', 'system'),
('production_order_type', '生产单类型', 'active', 'system', 'system'),
('process_type', '工艺类型', 'active', 'system', 'system'),
('inventory_type', '库存对象类型', 'active', 'system', 'system'),
('workstation_type', '工作站类型', 'active', 'system', 'system'),
('bom_type', 'BOM 类型', 'active', 'system', 'system'),
('attachment_status', '附件状态', 'active', 'system', 'system'),
('file_category', '文件分类', 'active', 'system', 'system'),
('quality_type', '质量资料类型', 'active', 'system', 'system'),
('approval_status', '审批状态', 'active', 'system', 'system'),
('operation_action_type', '操作动作类型', 'active', 'system', 'system'),
('currency_code', '币种', 'active', 'system', 'system'),
('target_system_code', '后续目标系统', 'active', 'system', 'system'),
('erp_reference_object', 'ERP 参考对象', 'active', 'system', 'system'),
('material_cost_mode', 'BOM 原材料取价方式', 'active', 'system', 'system'),
('valuation_method', '估值方式', 'active', 'system', 'system'),
('tax_category', '物料税分类预留', 'active', 'system', 'system')
ON CONFLICT (dict_type_code) DO NOTHING;

INSERT INTO sys_dict_item (dict_type_code, item_code, item_name, sort_no, status, created_by, updated_by)
VALUES
('core_object_type', 'Customer', '客户', 10, 'active', 'system', 'system'),
('core_object_type', 'Product', '产品', 20, 'active', 'system', 'system'),
('core_object_type', 'Order', '订单/需求', 30, 'active', 'system', 'system'),
('core_object_type', 'ProductionOrder', '生产单', 40, 'active', 'system', 'system'),
('core_object_type', 'Process', '工艺过程', 50, 'active', 'system', 'system'),
('core_object_type', 'Inventory', '库存对象', 60, 'active', 'system', 'system'),
('core_object_type', 'Workstation', '工作站', 70, 'active', 'system', 'system'),

('customer_status', 'draft', '草稿', 10, 'active', 'system', 'system'),
('customer_status', 'active', '启用', 20, 'active', 'system', 'system'),
('customer_status', 'inactive', '停用', 30, 'active', 'system', 'system'),

('product_status', 'draft', '草稿', 10, 'active', 'system', 'system'),
('product_status', 'developing', '开发中', 20, 'active', 'system', 'system'),
('product_status', 'released', '已发布', 40, 'active', 'system', 'system'),
('product_status', 'archived', '已归档', 50, 'active', 'system', 'system'),

('order_status', 'draft', '草稿', 10, 'active', 'system', 'system'),
('order_status', 'confirmed', '已确认', 20, 'active', 'system', 'system'),
('order_status', 'in_production', '执行中', 30, 'active', 'system', 'system'),
('order_status', 'completed', '已完成', 40, 'active', 'system', 'system'),
('order_status', 'closed', '已关闭', 50, 'active', 'system', 'system'),

('production_order_status', 'draft', '草稿', 10, 'active', 'system', 'system'),
('production_order_status', 'scheduled', '已排期', 20, 'active', 'system', 'system'),
('production_order_status', 'in_progress', '执行中', 30, 'active', 'system', 'system'),
('production_order_status', 'completed', '已完成', 40, 'active', 'system', 'system'),
('production_order_status', 'closed', '已关闭', 50, 'active', 'system', 'system'),

('process_status', 'draft', '草稿', 10, 'active', 'system', 'system'),
('process_status', 'confirmed', '已确认', 20, 'active', 'system', 'system'),
('process_status', 'locked', '已锁定', 30, 'active', 'system', 'system'),
('process_status', 'changed', '已变更', 40, 'active', 'system', 'system'),
('process_status', 'archived', '已归档', 50, 'active', 'system', 'system'),

('inventory_status', 'draft', '草稿', 10, 'active', 'system', 'system'),
('inventory_status', 'available', '可用', 20, 'active', 'system', 'system'),
('inventory_status', 'reserved', '已占用', 30, 'active', 'system', 'system'),
('inventory_status', 'consumed', '已消耗', 40, 'active', 'system', 'system'),
('inventory_status', 'closed', '已关闭', 50, 'active', 'system', 'system'),

('workstation_status', 'draft', '草稿', 10, 'active', 'system', 'system'),
('workstation_status', 'available', '可用', 20, 'active', 'system', 'system'),
('workstation_status', 'in_use', '使用中', 30, 'active', 'system', 'system'),
('workstation_status', 'maintenance', '维护中', 40, 'active', 'system', 'system'),
('workstation_status', 'inactive', '停用', 50, 'active', 'system', 'system'),

('product_type', 'product_line', '产品线', 10, 'active', 'system', 'system'),
('product_type', 'model_variant', '型号/颜色版本', 20, 'active', 'system', 'system'),

('order_type', 'market_requirement', '市场需求', 10, 'active', 'system', 'system'),
('order_type', 'customer_requirement', '客户需求', 20, 'active', 'system', 'system'),
('order_type', 'sample', '样品需求', 30, 'active', 'system', 'system'),
('order_type', 'quote', '报价需求', 40, 'active', 'system', 'system'),
('order_type', 'internal', '内部立项', 50, 'active', 'system', 'system'),

('order_source_type', 'customer', '客户', 10, 'active', 'system', 'system'),
('order_source_type', 'market', '市场', 20, 'active', 'system', 'system'),
('order_source_type', 'internal_plan', '内部规划', 30, 'active', 'system', 'system'),
('order_source_type', 'sales_opportunity', '销售机会', 40, 'active', 'system', 'system'),
('order_source_type', 'management_decision', '管理决策', 50, 'active', 'system', 'system'),

('production_order_type', 'sample', '打样', 10, 'active', 'system', 'system'),
('production_order_type', 'trial', '试产', 20, 'active', 'system', 'system'),
('production_order_type', 'mass_prep', '量产准备', 30, 'active', 'system', 'system'),
('production_order_type', 'rework', '返工试制', 40, 'active', 'system', 'system'),
('production_order_type', 'tooling_trial', '试模', 50, 'active', 'system', 'system'),

('process_type', 'routing', '工艺路线', 10, 'active', 'system', 'system'),
('process_type', 'operation', '工序', 20, 'active', 'system', 'system'),
('process_type', 'change', '工程变更', 30, 'active', 'system', 'system'),
('process_type', 'quality_gate', '质量门', 40, 'active', 'system', 'system'),
('process_type', 'sample_process', '样品工艺', 50, 'active', 'system', 'system'),

('inventory_type', 'material', '物料', 10, 'active', 'system', 'system'),
('inventory_type', 'semi_finished', '半成品', 20, 'active', 'system', 'system'),
('inventory_type', 'finished', '成品', 30, 'active', 'system', 'system'),
('inventory_type', 'packaging', '包材', 40, 'active', 'system', 'system'),
('inventory_type', 'tooling', '模具', 50, 'active', 'system', 'system'),
('inventory_type', 'fixture', '治具', 60, 'active', 'system', 'system'),

('workstation_type', 'machine', '机台', 10, 'active', 'system', 'system'),
('workstation_type', 'station', '工位', 20, 'active', 'system', 'system'),
('workstation_type', 'line', '产线', 30, 'active', 'system', 'system'),
('workstation_type', 'work_center', '工作中心', 40, 'active', 'system', 'system'),

('bom_type', 'ebom', '研发 BOM', 10, 'active', 'system', 'system'),
('bom_type', 'mbom', '制造 BOM', 20, 'active', 'system', 'system'),
('bom_type', 'packaging_bom', '包装 BOM', 30, 'active', 'system', 'system'),

('attachment_status', 'draft', '草稿', 10, 'active', 'system', 'system'),
('attachment_status', 'reviewing', '评审中', 20, 'active', 'system', 'system'),
('attachment_status', 'released', '已发布', 30, 'active', 'system', 'system'),
('attachment_status', 'archived', '已归档', 40, 'active', 'system', 'system'),

('file_category', 'drawing', '图纸', 10, 'active', 'system', 'system'),
('file_category', 'package_artwork', '包装稿', 20, 'active', 'system', 'system'),
('file_category', 'customer_confirmation', '客户确认资料', 30, 'active', 'system', 'system'),
('file_category', 'test_report', '测试报告', 40, 'active', 'system', 'system'),
('file_category', 'quality', '质量合规资料', 50, 'active', 'system', 'system'),
('file_category', 'sop', 'SOP', 60, 'active', 'system', 'system'),
('file_category', 'sip', 'SIP', 70, 'active', 'system', 'system'),
('file_category', 'sample_photo', '样品照片', 80, 'active', 'system', 'system'),

('quality_type', 'test', '测试', 10, 'active', 'system', 'system'),
('quality_type', 'inspection', '检验', 20, 'active', 'system', 'system'),
('quality_type', 'compliance', '合规', 30, 'active', 'system', 'system'),
('quality_type', 'customer_feedback', '客户反馈', 40, 'active', 'system', 'system'),

('approval_status', 'draft', '草稿', 10, 'active', 'system', 'system'),
('approval_status', 'in_progress', '审批中', 20, 'active', 'system', 'system'),
('approval_status', 'approved', '已通过', 30, 'active', 'system', 'system'),
('approval_status', 'rejected', '已拒绝', 40, 'active', 'system', 'system'),
('approval_status', 'cancelled', '已取消', 50, 'active', 'system', 'system'),
('approval_status', 'closed', '已关闭', 60, 'active', 'system', 'system'),

('operation_action_type', 'create', '新增', 10, 'active', 'system', 'system'),
('operation_action_type', 'update', '编辑', 20, 'active', 'system', 'system'),
('operation_action_type', 'delete', '删除', 30, 'active', 'system', 'system'),
('operation_action_type', 'submit', '提交', 40, 'active', 'system', 'system'),
('operation_action_type', 'approve', '审批通过', 50, 'active', 'system', 'system'),
('operation_action_type', 'reject', '审批拒绝', 60, 'active', 'system', 'system'),
('operation_action_type', 'freeze', '冻结', 70, 'active', 'system', 'system'),
('operation_action_type', 'publish', '发布', 80, 'active', 'system', 'system'),
('operation_action_type', 'void', '作废', 90, 'active', 'system', 'system'),
('operation_action_type', 'download', '下载', 100, 'active', 'system', 'system'),
('operation_action_type', 'import', '导入', 110, 'active', 'system', 'system'),
('operation_action_type', 'retry', '重试', 120, 'active', 'system', 'system'),
('operation_action_type', 'compensate', '人工补偿', 130, 'active', 'system', 'system'),

('currency_code', 'CNY', '人民币', 10, 'active', 'system', 'system'),
('currency_code', 'USD', '美元', 20, 'active', 'system', 'system'),
('currency_code', 'MXN', '墨西哥比索', 30, 'active', 'system', 'system'),

('target_system_code', 'ERP', '后续 ERP', 10, 'active', 'system', 'system'),
('target_system_code', 'MES', '后续 MES', 20, 'active', 'system', 'system'),
('target_system_code', 'WMS', '后续 WMS', 30, 'active', 'system', 'system'),

('erp_reference_object', 'tabItem', 'ERPNext Item 主表', 10, 'active', 'system', 'system'),
('erp_reference_object', 'tabItem Barcode', 'ERPNext Item Barcode 子表', 20, 'active', 'system', 'system'),
('erp_reference_object', 'tabItem Reorder', 'ERPNext Item Reorder 子表', 30, 'active', 'system', 'system'),
('erp_reference_object', 'tabUOM Conversion Detail', 'ERPNext UOM Conversion 子表', 40, 'active', 'system', 'system'),
('erp_reference_object', 'tabItem Default', 'ERPNext Item Default 子表', 50, 'active', 'system', 'system'),
('erp_reference_object', 'tabItem Supplier', 'ERPNext Item Supplier 子表', 60, 'active', 'system', 'system'),
('erp_reference_object', 'tabItem Tax', 'ERPNext Item Tax 子表', 70, 'active', 'system', 'system'),
('erp_reference_object', 'tabBOM', 'ERPNext BOM 主表', 80, 'active', 'system', 'system'),
('erp_reference_object', 'tabBOM Item', 'ERPNext BOM Item 子表', 90, 'active', 'system', 'system'),
('erp_reference_object', 'tabBOM Operation', 'ERPNext BOM Operation 子表', 100, 'active', 'system', 'system'),
('erp_reference_object', 'tabBOM Explosion Item', 'ERPNext BOM Explosion Item 子表', 110, 'active', 'system', 'system'),

('material_cost_mode', 'valuation_rate', '估值价', 10, 'active', 'system', 'system'),
('material_cost_mode', 'last_purchase_rate', '最近采购价', 20, 'active', 'system', 'system'),
('material_cost_mode', 'price_list', '价格表', 30, 'active', 'system', 'system'),

('valuation_method', 'fifo', 'FIFO', 10, 'active', 'system', 'system'),
('valuation_method', 'moving_average', 'Moving Average', 20, 'active', 'system', 'system'),
('valuation_method', 'lifo', 'LIFO', 30, 'active', 'system', 'system'),

('tax_category', 'purchase', '采购税模板预留', 10, 'active', 'system', 'system'),
('tax_category', 'sales', '销售税模板预留', 20, 'active', 'system', 'system'),
('tax_category', 'both', '采购/销售共用税模板预留', 30, 'active', 'system', 'system')
ON CONFLICT (dict_type_code, item_code) DO NOTHING;

INSERT INTO sys_role (role_code, role_name, role_type, status, created_by, updated_by)
VALUES
('sales', '销售', 'business', 'active', 'system', 'system'),
('project_manager', '项目经理', 'business', 'active', 'system', 'system'),
('engineering', '工程', 'business', 'active', 'system', 'system'),
('purchase', '采购', 'business', 'active', 'system', 'system'),
('quality', '品质', 'business', 'active', 'system', 'system'),
('production', '生产', 'business', 'active', 'system', 'system'),
('finance', '财务', 'business', 'active', 'system', 'system'),
('management', '管理层', 'business', 'active', 'system', 'system'),
('admin', '管理员', 'system', 'active', 'system', 'system')
ON CONFLICT (role_code) DO NOTHING;

INSERT INTO sys_permission (permission_code, permission_name, permission_type, resource_type, resource_path, action_code, status, created_by, updated_by)
VALUES
('customer:view', 'Customer 查看', 'api', 'Customer', '/api/v1/customers', 'view', 'active', 'system', 'system'),
('customer:create', 'Customer 新建', 'api', 'Customer', '/api/v1/customers', 'create', 'active', 'system', 'system'),
('customer:update', 'Customer 编辑', 'api', 'Customer', '/api/v1/customers', 'update', 'active', 'system', 'system'),

('product:view', 'Product 查看', 'api', 'Product', '/api/v1/products', 'view', 'active', 'system', 'system'),
('product:create', 'Product 新建', 'api', 'Product', '/api/v1/products', 'create', 'active', 'system', 'system'),
('product:update', 'Product 编辑', 'api', 'Product', '/api/v1/products', 'update', 'active', 'system', 'system'),
('product:freeze', 'Product 冻结', 'button', 'Product', '/api/v1/products/*/freeze', 'freeze', 'active', 'system', 'system'),
('product:publish', 'Product 发布', 'button', 'Product', '/api/v1/products/*/publish', 'publish', 'active', 'system', 'system'),

('order:view', 'Order 查看', 'api', 'Order', '/api/v1/orders', 'view', 'active', 'system', 'system'),
('order:create', 'Order 新建', 'api', 'Order', '/api/v1/orders', 'create', 'active', 'system', 'system'),
('order:update', 'Order 编辑', 'api', 'Order', '/api/v1/orders', 'update', 'active', 'system', 'system'),

('production_order:view', 'ProductionOrder 查看', 'api', 'ProductionOrder', '/api/v1/production-orders', 'view', 'active', 'system', 'system'),
('production_order:create', 'ProductionOrder 新建', 'api', 'ProductionOrder', '/api/v1/production-orders', 'create', 'active', 'system', 'system'),
('production_order:update', 'ProductionOrder 编辑', 'api', 'ProductionOrder', '/api/v1/production-orders', 'update', 'active', 'system', 'system'),

('process:view', 'Process 查看', 'api', 'Process', '/api/v1/processes', 'view', 'active', 'system', 'system'),
('process:create', 'Process 新建', 'api', 'Process', '/api/v1/processes', 'create', 'active', 'system', 'system'),
('process:update', 'Process 编辑', 'api', 'Process', '/api/v1/processes', 'update', 'active', 'system', 'system'),
('process:change', 'Process 变更', 'button', 'Process', '/api/v1/processes/*/change', 'change', 'active', 'system', 'system'),

('inventory:view', 'Inventory 查看', 'api', 'Inventory', '/api/v1/inventories', 'view', 'active', 'system', 'system'),
('inventory:create', 'Inventory 新建', 'api', 'Inventory', '/api/v1/inventories', 'create', 'active', 'system', 'system'),
('inventory:update', 'Inventory 编辑', 'api', 'Inventory', '/api/v1/inventories', 'update', 'active', 'system', 'system'),

('workstation:view', 'Workstation 查看', 'api', 'Workstation', '/api/v1/workstations', 'view', 'active', 'system', 'system'),
('workstation:create', 'Workstation 新建', 'api', 'Workstation', '/api/v1/workstations', 'create', 'active', 'system', 'system'),
('workstation:update', 'Workstation 编辑', 'api', 'Workstation', '/api/v1/workstations', 'update', 'active', 'system', 'system'),

('attachment:view', 'Attachment 查看', 'api', 'Attachment', '/api/v1/attachments', 'view', 'active', 'system', 'system'),
('attachment:upload', 'Attachment 上传', 'api', 'Attachment', '/api/v1/attachments', 'upload', 'active', 'system', 'system'),
('attachment:download', 'Attachment 下载', 'button', 'Attachment', '/api/v1/attachments/*/download', 'download', 'active', 'system', 'system'),

('approval:view', '审批查看', 'api', 'Approval', '/api/v1/approvals', 'view', 'active', 'system', 'system'),
('approval:approve', '审批处理', 'button', 'Approval', '/api/v1/approvals/*/approve', 'approve', 'active', 'system', 'system'),

('cost:view', '成本查看', 'field', 'Product', 'product_cost', 'view', 'active', 'system', 'system'),
('quote:approve', '报价审批', 'button', 'Order', '/api/v1/orders/*/quote/approve', 'approve', 'active', 'system', 'system'),
('integration:retry', '后续集成重试预留', 'button', 'System', '/api/v1/integration-jobs/*/retry', 'retry', 'active', 'system', 'system'),
('admin:manage', '系统管理', 'menu', 'System', '/api/v1/admin', 'manage', 'active', 'system', 'system')
ON CONFLICT (permission_code) DO NOTHING;

INSERT INTO sys_role_permission (role_id, permission_id, created_by)
SELECT r.role_id, p.permission_id, 'system'
FROM sys_role r
JOIN sys_permission p ON (
  r.role_code = 'admin'
  OR (r.role_code = 'sales' AND p.permission_code IN ('customer:view', 'customer:create', 'customer:update', 'product:view', 'order:view', 'order:create', 'order:update', 'attachment:view', 'attachment:upload', 'attachment:download'))
  OR (r.role_code = 'project_manager' AND p.permission_code IN ('customer:view', 'product:view', 'product:create', 'product:update', 'product:freeze', 'order:view', 'order:create', 'order:update', 'production_order:view', 'production_order:create', 'production_order:update', 'process:view', 'inventory:view', 'workstation:view', 'attachment:view', 'attachment:upload', 'attachment:download', 'approval:view', 'approval:approve', 'cost:view'))
  OR (r.role_code = 'engineering' AND p.permission_code IN ('product:view', 'product:create', 'product:update', 'product:freeze', 'product:publish', 'order:view', 'production_order:view', 'process:view', 'process:create', 'process:update', 'process:change', 'inventory:view', 'workstation:view', 'attachment:view', 'attachment:upload', 'attachment:download', 'approval:view', 'approval:approve'))
  OR (r.role_code = 'purchase' AND p.permission_code IN ('product:view', 'order:view', 'production_order:view', 'process:view', 'inventory:view', 'inventory:create', 'inventory:update', 'attachment:view', 'attachment:upload', 'approval:view', 'approval:approve', 'cost:view'))
  OR (r.role_code = 'quality' AND p.permission_code IN ('product:view', 'order:view', 'production_order:view', 'process:view', 'inventory:view', 'workstation:view', 'attachment:view', 'attachment:upload', 'approval:view', 'approval:approve'))
  OR (r.role_code = 'production' AND p.permission_code IN ('product:view', 'production_order:view', 'production_order:update', 'process:view', 'inventory:view', 'workstation:view', 'attachment:view', 'attachment:download'))
  OR (r.role_code = 'finance' AND p.permission_code IN ('product:view', 'order:view', 'approval:view', 'approval:approve', 'cost:view', 'quote:approve'))
  OR (r.role_code = 'management' AND p.permission_code IN ('customer:view', 'product:view', 'product:publish', 'order:view', 'production_order:view', 'process:view', 'inventory:view', 'workstation:view', 'attachment:view', 'approval:view', 'approval:approve', 'cost:view', 'quote:approve', 'integration:retry'))
)
ON CONFLICT (role_id, permission_id) DO NOTHING;

INSERT INTO sys_code_rule (object_type, rule_code, rule_name, prefix_pattern, date_pattern, sequence_length, status, created_by, updated_by)
VALUES
('Customer', 'customer_default', '客户编码', 'CUS-{region}-', NULL, 4, 'active', 'system', 'system'),
('Product', 'product_default', '产品编码', 'PRD-{product_short}-{model}-{color}-{version}', NULL, 4, 'active', 'system', 'system'),
('Order', 'order_default', '订单编码', 'ORD-{type}-{yyyyMMdd}-', 'yyyyMMdd', 3, 'active', 'system', 'system'),
('ProductionOrder', 'production_order_default', '生产单编码', 'PO-{type}-{yyyyMMdd}-', 'yyyyMMdd', 3, 'active', 'system', 'system'),
('Process', 'process_default', '工艺编码', 'PROC-{product_short}-{process_short}-', NULL, 3, 'active', 'system', 'system'),
('Inventory', 'inventory_default', '库存对象编码', 'INV-{type}-', NULL, 4, 'active', 'system', 'system'),
('Workstation', 'workstation_default', '工作站编码', 'WS-{type}-', NULL, 3, 'active', 'system', 'system')
ON CONFLICT (object_type, rule_code) DO NOTHING;

INSERT INTO sys_system_config (config_key, config_value, config_name, config_group, status, created_by, updated_by)
VALUES
('plm.object_types', 'Customer,Product,Order,ProductionOrder,Process,Inventory,Workstation', '核心对象白名单', 'plm', 'active', 'system', 'system'),
('plm.default_currency', 'CNY', '默认币种', 'plm', 'active', 'system', 'system'),
('plm.file.max_size_mb', '100', '文件上传最大 MB', 'attachment', 'active', 'system', 'system'),
('plm.integration.allowed_status', 'released,locked', '后续外发允许状态', 'integration', 'active', 'system', 'system'),
('plm.integration.default_retry_count', '3', '后续集成默认重试次数', 'integration', 'active', 'system', 'system')
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO plm_approval_definition (approval_code, approval_name, object_type, version_no, status, config_json, created_by, updated_by)
VALUES
('product_release', 'Product 发布审批', 'Product', 'V1', 'active',
 '{"nodes":[{"node_code":"engineering_submit","node_name":"工程提交"},{"node_code":"purchase_countersign","node_name":"采购会签"},{"node_code":"quality_countersign","node_name":"品质会签"},{"node_code":"project_confirm","node_name":"项目经理确认"},{"node_code":"management_approve","node_name":"管理层审批"}]}'::jsonb,
 'system', 'system'),
('tooling_request', '开模申请审批', 'Inventory', 'V1', 'active',
 '{"nodes":[{"node_code":"project_submit","node_name":"项目经理发起"},{"node_code":"engineering_confirm","node_name":"工程确认"},{"node_code":"purchase_confirm","node_name":"采购确认"},{"node_code":"management_approve","node_name":"管理层审批"}]}'::jsonb,
 'system', 'system'),
('quote_approval', '报价审批', 'Order', 'V1', 'active',
 '{"nodes":[{"node_code":"sales_submit","node_name":"销售/项目发起"},{"node_code":"purchase_cost_confirm","node_name":"采购成本确认"},{"node_code":"finance_review","node_name":"财务审核"},{"node_code":"management_approve","node_name":"管理层审批"}]}'::jsonb,
 'system', 'system'),
('process_change', '工程变更审批', 'Process', 'V1', 'active',
 '{"nodes":[{"node_code":"change_submit","node_name":"变更申请"},{"node_code":"impact_analysis","node_name":"影响分析"},{"node_code":"countersign","node_name":"多部门会签"},{"node_code":"approve","node_name":"批准"},{"node_code":"effective","node_name":"生效"}]}'::jsonb,
 'system', 'system')
ON CONFLICT (approval_code, version_no) DO NOTHING;
