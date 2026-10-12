export type ObjectType =
  | 'customer'
  | 'product'
  | 'order'
  | 'production-order'
  | 'process'
  | 'inventory'
  | 'workstation'

export type CommonStatus =
  | 'draft'
  | 'active'
  | 'inactive'
  | 'developing'
  | 'released'
  | 'archived'
  | 'confirmed'
  | 'in_production'
  | 'completed'
  | 'closed'
  | 'scheduled'
  | 'in_progress'
  | 'locked'
  | 'changed'
  | 'available'
  | 'reserved'
  | 'consumed'
  | 'in_use'
  | 'maintenance'
  | 'pending'
  | 'approved'
  | 'rejected'
  | 'blocked'
  | 'skipped'

export type ProductFlowMode = 'new_product_line' | 'new_model_variant'

export type ProductLifecycle =
  | 'initiation'
  | 'design'
  | 'tooling'
  | 'sampling'
  | 'process'
  | 'pilot'
  | 'mx'
  | 'release'

export type MoldAction = 'modify' | 'new' | 'none'

export interface UserProfile {
  userId: number
  userName: string
  roleName: string
  department: string
  roleCode?: string
}

export interface SearchFieldOption {
  label: string
  value: string | number
}

export interface SearchField {
  prop: string
  label: string
  type: 'input' | 'select' | 'date'
  placeholder?: string
  options?: SearchFieldOption[]
}

export interface TimelineItem {
  stepNo?: number
  title: string
  time: string | null
  owner?: string
  description?: string
  status?: CommonStatus
  phase?: string
  gate?: boolean
  variantTag?: 'inherited' | 'difference' | 'optional'
  lifecycle?: ProductLifecycle
  nodeType?: 'stage' | 'gate' | 'decision'
  branchLabel?: string
  branchStatus?: 'selected' | 'optional' | 'skipped'
  detailLines?: string[]
  gateLabel?: string
}

export interface ApprovalStep {
  stepName: string
  approver: string
  status: CommonStatus
  time: string | null
  comment: string
}

export interface OperateLogEntry {
  time: string
  operator: string
  action: string
  level: 'normal' | 'danger'
}

export interface MenuItem {
  path: string
  title: string
  icon: string
  permission: string
  children?: MenuItem[]
}

export interface MenuGroup {
  title: string
  items: MenuItem[]
}

export interface DashboardKpi {
  label: string
  value: number
  trend: string
  targetPath: string
}

export interface DashboardMilestone {
  stage: string
  owner: string
  dueDate: string
  status: CommonStatus
  summary: string
  targetPath: string
}

export interface DashboardRisk {
  title: string
  level: 'high' | 'medium' | 'low'
  owner: string
  action: string
  targetPath: string
}

export interface DashboardStageOverview {
  stage: string
  total: number
  delayed: number
  completionRate: number
  targetPath: string
}

export interface DashboardFocusItem {
  title: string
  owner: string
  dueDate: string
  status: CommonStatus
  summary: string
  targetPath: string
}

export interface DashboardTodoItem {
  title: string
  owner: string
  dueDate: string
  tag: string
  targetPath: string
}

export interface DashboardSnapshot {
  hero: {
    title: string
    subtitle: string
  }
  kpis: DashboardKpi[]
  milestones: DashboardMilestone[]
  risks: DashboardRisk[]
  stageOverview: DashboardStageOverview[]
  focusItems: DashboardFocusItem[]
  todoItems: DashboardTodoItem[]
}

export interface ApprovalTask {
  taskId: number
  objectType: ObjectType
  objectName: string
  nodeName: string
  initiator: string
  approver: string
  dueDate: string
  status: CommonStatus
  targetPath?: string
}

export type ApprovalTemplateStatus = 'draft' | 'active' | 'inactive'

export interface ApprovalTemplateNode {
  nodeId: number
  stepNo: number
  nodeName: string
  approverRole: string
  approverUserId?: number
  approverUserName: string
  isGate: boolean
  note: string
}

export interface ApprovalTemplate {
  templateId: number
  templateName: string
  objectType: 'product' | 'order' | 'process'
  flowType: string
  status: ApprovalTemplateStatus
  description: string
  updatedAt: string
  nodes: ApprovalTemplateNode[]
}

export interface WorkflowTemplateNode {
  workflowNodeId?: number
  workflowTemplateId?: number
  stepNo: number
  nodeCode: string
  nodeName: string
  stageCode?: string | null
  stageName?: string | null
  phaseName?: string | null
  requiredAttachment: boolean
  requiredFileCategory?: string | null
  uploadPrompt?: string | null
  confirmPrompt?: string | null
  emptyFileMessage?: string | null
  gateFlag: boolean
  enabledFlag: boolean
  remark?: string | null
}

export interface WorkflowTemplate {
  workflowTemplateId?: number
  flowType: 'product_line' | 'model_variant'
  templateName: string
  versionNo: string
  status: ApprovalTemplateStatus
  activeFlag?: boolean
  description?: string | null
  updatedAt?: string | null
  nodes: WorkflowTemplateNode[]
}

export interface UserOption {
  userId: number
  userName: string
  roleName: string
  department: string
}

export type SystemRecordStatus = 'active' | 'inactive'

/* ========== 字段管理类型 ========== */

export type SystemFieldScope =
  | 'product'
  | 'sku'
  | 'order'
  | 'project'
  | 'bom'
  | 'process'
  | 'inventory'
  | 'approval'
  | 'system'

export type SystemFieldInputType =
  | 'text'
  | 'select'
  | 'multi_select'
  | 'number'
  | 'date'
  | 'switch'
  | 'textarea'

export type SystemFieldStatus = 'active' | 'inactive'

export interface SystemFieldOption {
  optionId: number
  label: string
  value: string
  sortNo: number
  status: SystemFieldStatus
  isSystem: boolean
}

export interface SystemFieldItem {
  fieldId: number
  fieldCode: string
  fieldName: string
  scope: SystemFieldScope
  inputType: SystemFieldInputType
  status: SystemFieldStatus
  required: boolean
  visibleInList: boolean
  visibleInDetail: boolean
  visibleInFilter: boolean
  editable: boolean
  sortNo: number
  description: string
  usageScenes: string[]
  options: SystemFieldOption[]
  isSystem: boolean
  updatedAt: string
}
