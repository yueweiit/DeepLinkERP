-- Seed data alignment for workflow, locking, import/integration, and super admin controls.

SET search_path TO plm;

INSERT INTO sys_dict_type (dict_type_code, dict_type_name, status, created_by, updated_by)
VALUES
('lock_status', '锁定状态', 'active', 'system', 'system'),
('quality_issue_status', '质量问题闭环状态', 'active', 'system', 'system'),
('import_status', '导入状态', 'active', 'system', 'system'),
('integration_status', '集成状态', 'active', 'system', 'system')
ON CONFLICT (dict_type_code) DO NOTHING;

INSERT INTO sys_dict_item (dict_type_code, item_code, item_name, sort_no, status, created_by, updated_by)
VALUES
('approval_status', 'completed', '已完成', 30, 'active', 'system', 'system'),
('approval_status', 'super_admin_forced', '超管强推', 70, 'active', 'system', 'system'),
('approval_status', 'super_admin_blocked', '超管锁定', 80, 'active', 'system', 'system'),

('lock_status', 'unlocked', '未锁定', 10, 'active', 'system', 'system'),
('lock_status', 'frozen', '已冻结', 20, 'active', 'system', 'system'),
('lock_status', 'super_admin_locked', '超管锁定', 30, 'active', 'system', 'system'),

('quality_issue_status', 'normal', '正常', 10, 'active', 'system', 'system'),
('quality_issue_status', 'open', '未处理', 20, 'active', 'system', 'system'),
('quality_issue_status', 'improving', '改善中', 30, 'active', 'system', 'system'),
('quality_issue_status', 'closed', '已闭环', 40, 'active', 'system', 'system'),
('quality_issue_status', 'expired', '已过期', 50, 'active', 'system', 'system'),

('import_status', 'draft', '草稿', 10, 'active', 'system', 'system'),
('import_status', 'in_progress', '导入中', 20, 'active', 'system', 'system'),
('import_status', 'completed', '已完成', 30, 'active', 'system', 'system'),
('import_status', 'partial', '部分成功', 40, 'active', 'system', 'system'),
('import_status', 'closed', '已关闭', 50, 'active', 'system', 'system'),
('import_status', 'failed', '失败', 60, 'active', 'system', 'system'),

('integration_status', 'draft', '草稿', 10, 'active', 'system', 'system'),
('integration_status', 'pending', '待处理', 20, 'active', 'system', 'system'),
('integration_status', 'in_progress', '执行中', 30, 'active', 'system', 'system'),
('integration_status', 'completed', '成功', 40, 'active', 'system', 'system'),
('integration_status', 'failed', '失败', 50, 'active', 'system', 'system'),
('integration_status', 'retrying', '重试中', 60, 'active', 'system', 'system'),
('integration_status', 'manual_review', '人工补偿', 70, 'active', 'system', 'system'),
('integration_status', 'closed', '已关闭', 80, 'active', 'system', 'system'),

('operation_action_type', 'force_advance', '强制推进', 140, 'active', 'system', 'system'),
('operation_action_type', 'force_block', '强制禁止', 150, 'active', 'system', 'system'),
('operation_action_type', 'emergency_unlock', '紧急解锁', 160, 'active', 'system', 'system'),
('operation_action_type', 'transfer', '转交', 170, 'active', 'system', 'system'),
('operation_action_type', 'comment', '评论', 180, 'active', 'system', 'system')
ON CONFLICT (dict_type_code, item_code) DO NOTHING;

UPDATE sys_dict_item
SET item_name = '已完成', sort_no = 30, updated_by = 'system'
WHERE dict_type_code = 'approval_status' AND item_code = 'approved';

INSERT INTO sys_role (role_code, role_name, role_type, status, created_by, updated_by)
VALUES
('super_admin', '超级管理员', 'system', 'active', 'system', 'system')
ON CONFLICT (role_code) DO NOTHING;

INSERT INTO sys_permission (permission_code, permission_name, permission_type, resource_type, resource_path, action_code, status, created_by, updated_by)
VALUES
('approval:force_advance', '审批强制推进', 'api', 'Approval', '/api/v1/approvals/*/force-advance', 'force_advance', 'active', 'system', 'system'),
('approval:force_block', '审批强制禁止', 'api', 'Approval', '/api/v1/approvals/*/force-block', 'force_block', 'active', 'system', 'system'),
('approval:emergency_unlock', '审批紧急解锁', 'api', 'Approval', '/api/v1/approvals/*/emergency-unlock', 'emergency_unlock', 'active', 'system', 'system'),
('attachment:download', '附件下载', 'api', 'Attachment', '/api/v1/attachments/*/download', 'download', 'active', 'system', 'system'),
('cost:field_view', '成本字段查看', 'field', 'System', '/api/v1/cost-fields', 'field_view', 'active', 'system', 'system')
ON CONFLICT (permission_code) DO NOTHING;

INSERT INTO sys_role_permission (role_id, permission_id, created_by)
SELECT r.role_id, p.permission_id, 'system'
FROM sys_role r
JOIN sys_permission p ON p.permission_code IN (
  'approval:force_advance',
  'approval:force_block',
  'approval:emergency_unlock',
  'attachment:download',
  'cost:field_view'
)
WHERE r.role_code = 'super_admin'
ON CONFLICT (role_id, permission_id) DO NOTHING;

INSERT INTO sys_system_config (config_key, config_value, config_name, config_group, remark, status, created_by, updated_by)
VALUES
('plm.workflow.super_admin_notify_management', 'true', '超级管理员操作是否通知管理层', 'workflow', '超级管理员操作后是否触发管理层通知。', 'active', 'system', 'system'),
('plm.workflow.import_partial_allowed', 'true', '导入是否允许部分成功状态', 'workflow', '用于控制导入批次是否允许进入 partial 状态。', 'active', 'system', 'system'),
('plm.workflow.integration_manual_review_retry_limit', '3', '集成进入人工补偿前最大自动重试次数', 'workflow', '超过该次数后建议转人工补偿。', 'active', 'system', 'system')
ON CONFLICT (config_key) DO NOTHING;
