import type { CommonStatus } from './common'

export type ProcessCenterViewMode = 'route' | 'operation' | 'change'
export type ProcessTemplateSource = 'standard' | 'inherited' | 'manual'
export type ProcessRouteType = 'new_product_line' | 'new_model_variant'
export type ProcessRiskLevel = 'high' | 'medium' | 'low'
export type ProcessAttachmentStatus = 'complete' | 'partial' | 'missing'
export type ProcessConfirmationState = 'approved' | 'pending' | 'blocked'

export interface ProcessMetricCard {
  label: string
  value: string | number
  hint: string
}

export interface ProcessTemplateOption {
  templateKey: string
  templateName: string
  category: string
  operationCount: number
  summary: string
  highlightedSteps: string[]
}

export interface ProcessRouteListItem {
  routeId: number
  processId?: number
  routeCode: string
  routeName: string
  productId: number
  productCode: string
  productName: string
  model?: string | null
  versionNo: string
  routeType: ProcessRouteType
  status: CommonStatus
  templateSource: ProcessTemplateSource
  owner: string
  operationCount: number
  colorCount?: number
  colors?: ProcessRouteColor[]
  skuCount?: number
  totalCost: number
  currentGate: string
  riskLevel: ProcessRiskLevel
  hasExternalOperation: boolean
  hasDifferenceOperation: boolean
  updatedAt?: string
  targetPath: string
}

export interface ProcessOperationRecord {
  operationId: number
  operationCode?: string
  sequenceNo: number
  operationName: string
  operationType: string
  workstationName: string
  supplierName: string | null
  parameterSummary: string
  qualityRequirement: string
  unitCost: number
  leadDays: number
  attachmentStatus: ProcessAttachmentStatus
  isKeyProcess: boolean
  isExternalOperation: boolean
  isDifferenceOperation: boolean
  changedInCurrentVersion: boolean
  confirmerName?: string
  confirmerRole?: string
}

export interface ProcessConfirmationRecord {
  roleName: string
  ownerName: string
  status: ProcessConfirmationState
  note: string
  confirmedAt: string | null
}

export interface ProcessGateCheck {
  gateName: string
  passed: boolean
  note: string
}

export interface ProcessAttachmentSummary {
  operationId?: number
  operationName: string
  sopCount: number
  sipCount: number
  parameterSheetCount: number
  qualitySpecCount: number
  status: ProcessAttachmentStatus
  updatedAt: string
  previewPath?: string
  canAdd?: boolean
}

export interface ProcessChangeRecord {
  versionNo: string
  changeType: string
  changeReason: string
  affectedOperations: string[]
  costDelta: number
  leadDayDelta: number
  ownerName: string
  changedAt: string
  canFinalize?: boolean
  canApplyChange?: boolean
}

export interface ProcessImpactLink {
  label: string
  summary: string
  targetPath: string
}

export interface ProcessRouteDetail {
  routeId: number
  routeCode: string
  routeName: string
  productId: number
  productCode: string
  productName: string
  versionNo: string
  routeType: ProcessRouteType
  status: CommonStatus
  templateSource: ProcessTemplateSource
  owner: string
  currentGate: string
  totalCost: number
  passedGate: boolean
  isLocked: boolean
  differenceOperationCount: number
  inheritedFrom: string | null
  overviewNote: string
  canFinalize?: boolean
  canApplyChange?: boolean
  operations: ProcessOperationRecord[]
  confirmations: ProcessConfirmationRecord[]
  gateChecks: ProcessGateCheck[]
  attachments: ProcessAttachmentSummary[]
  changes: ProcessChangeRecord[]
  impacts: ProcessImpactLink[]
}

export interface ProcessCenterSnapshot {
  metrics: ProcessMetricCard[]
  routes: ProcessRouteListItem[]
  routeDetails: Record<number, ProcessRouteDetail>
  templates: ProcessTemplateOption[]
}

export interface ProcessRouteColor {
  codeItemId?: number | null
  colorCode?: string | null
  colorName: string
}

export interface ProcessRouteSku {
  productId: number
  skuCode: string
  productName: string
  phoneModel?: string | null
  phoneModelCode?: string | null
  color?: string | null
  colorCode?: string | null
  finishedProductCode?: string | null
  status: CommonStatus
  productBomRouteId?: number | null
  routeCode?: string | null
  routeName?: string | null
}

export interface LinkedBomRoute {
  productBomRouteId: number
  productBomId: number
  routeCode: string
  routeName: string
  status: string
}

export interface ProcessRouteRelation {
  processId: number
  processCode: string
  processName: string
  productId: number
  productCode: string
  productName: string
  versionNo: string
  status: CommonStatus
  colors: ProcessRouteColor[]
  skus: ProcessRouteSku[]
  operations: Array<{
    processId: number
    parentProcessId: number
    processCode?: string | null
    operationCode?: string | null
    operationCraftCode?: string | null
    sequenceNo: number
    processName: string
    qualityRequirement?: string | null
    status: string
  }>
  linkedBomRoutes?: LinkedBomRoute[]
}
