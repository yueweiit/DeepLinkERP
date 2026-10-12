import type { ProductSummary } from '@/types/product'
import request, { unwrapPage, unwrapResponse } from '../request'

type ProductType = 'product_line' | 'model_variant' | 'sku'
type TimelineStatus = 'completed' | 'current' | 'pending' | 'rejected'

interface BackendProjectSummary {
  projectId: number
  productId: number
  parentProductId?: number | null
  productCode: string
  productSpecificCode?: string | null
  phoneModelCode?: string | null
  colorCode?: string | null
  finishedProductCode?: string | null
  importShortCode?: string | null
  productName: string
  productType: ProductType
  productTypeName?: string
  model?: string | null
  moldCodes?: string | null
  color?: string | null
  versionNo: string
  status: ProductSummary['status']
  statusName?: string
  lockStatus?: string | null
  abandonedAt?: string | null
  abandonedBy?: string | null
  abandonReason?: string | null
  ownerUserId?: number | null
  ownerUserName?: string | null
  currentStepNo: number
  currentNodeName?: string | null
  moldTransferAt?: string | null
  expectedArrivalAt?: string | null
  actualArrivalAt?: string | null
  documentCount?: number | null
  totalCost?: number | null
  currencyCode?: string | null
  createdAt?: string | null
  updatedAt?: string | null
}

interface BackendProjectDetail extends BackendProjectSummary {
  parentProductId?: number | null
  customerId?: number | null
  seriesName?: string | null
  material?: string | null
  packageType?: string | null
  surfaceProcess?: string | null
  coreProcess?: string | null
  composition?: string | null
  colorSummary?: {
    skuColorCount?: number | null
    productionColorCount?: number | null
    skuColors?: BackendProjectColorUsage[] | null
    productionColors?: BackendProjectColorUsage[] | null
    skuOnlyColors?: BackendProjectColorUsage[] | null
    productionOnlyColors?: BackendProjectColorUsage[] | null
  } | null
  timeline?: BackendTimelineDetail | null
  remark?: string | null
}

interface BackendProjectColorUsage {
  colorCode?: string | null
  colorName?: string | null
  skuCount?: number | null
  decisionCount?: number | null
}

interface BackendTimelineNode {
  stepNo: number
  nodeCode: string
  nodeName: string
  stageCode?: string | null
  stageName?: string | null
  phaseName?: string | null
  requiredFileCategory?: string | null
  requiredAttachment?: boolean | null
  uploadPrompt?: string | null
  confirmPrompt?: string | null
  emptyFileMessage?: string | null
  gateFlag?: boolean | null
  enabledFlag?: boolean | null
  nodeStatus: TimelineStatus
  documentCount?: number | null
  confirmed?: boolean | null
}

interface BackendTimelineDetail {
  projectId: number
  productId: number
  productType: ProductType
  started?: boolean | null
  startBlockReason?: string | null
  timelineCompleted?: boolean | null
  currentStepNo: number
  currentStageCode?: string | null
  currentStageName?: string | null
  currentPhaseName?: string | null
  currentStepCode?: string | null
  currentStepName?: string | null
  currentConfirmed?: boolean | null
  confirmedNodeKey?: string | null
  lastAction?: string | null
  lastReason?: string | null
  lastOperatedAt?: string | null
  lastOperatorUserId?: number | null
  lastOperatorUserName?: string | null
  moldTransferExpress?: MoldTransferExpressVO | null
  nodes: BackendTimelineNode[]
}

export type ProjectSummaryVO = ProductSummary

export interface ProjectDetailVO extends ProjectSummaryVO {
  projectId: number
  productId: number
  parentProductId?: number | null
  material: string
  packageType: string
  surfaceProcess: string
  coreProcess: string
  composition: string
  summary: string
  timeline?: TimelineDetailVO
}

export interface TimelineNodeVO {
  nodeKey: string
  nodeName: string
  stageCode?: string | null
  stageName?: string | null
  phaseName: string
  requiredFileCategory?: string | null
  requiredAttachment?: boolean | null
  uploadPrompt?: string | null
  confirmPrompt?: string | null
  emptyFileMessage?: string | null
  gateFlag?: boolean | null
  enabledFlag?: boolean | null
  stepNo: number
  status: TimelineStatus
  nodeStatus: TimelineStatus
  summary: string
  experienceSummary?: string
  ownerRole: string
  receiverRole?: string
  receiverUserName?: string
  receivedAt?: string
  promoterRole?: string
  promoterUserName?: string
  promotedAt?: string
  nextAction?: string
  riskNote?: string
  gateLabel?: string
  detailLines?: string[]
  documentCount: number
  confirmed?: boolean
}

export interface TimelineDetailVO {
  projectId: number
  productId?: number
  productType?: ProductType
  started: boolean
  startBlockReason?: string | null
  timelineCompleted?: boolean | null
  currentNode: string
  currentStepNo: number
  currentStageCode?: string | null
  currentStageName?: string | null
  currentPhaseName?: string | null
  currentStepCode?: string | null
  currentStepName?: string | null
  currentConfirmed?: boolean | null
  confirmedNodeKey?: string | null
  lastAction?: string | null
  lastReason?: string | null
  lastOperatedAt?: string | null
  lastOperatorUserId?: number | null
  lastOperatorUserName?: string | null
  moldTransferExpress?: MoldTransferExpressVO | null
  nodes: TimelineNodeVO[]
}

export interface MoldTransferExpressVO {
  moldTransferExpressId?: number | null
  projectId: number
  timelineNodeKey: string
  trackingNo?: string | null
  shippedAt?: string | null
  status?: string | null
}

export interface MoldTransferExpressSavePayload {
  trackingNo: string
  shippedAt?: string
}

export interface TimelineActionResultVO {
  projectId: number
  productId: number
  action: 'confirm' | 'advance' | 'return'
  nodeKey: string
  beforeStepNo: number
  currentStepNo: number
  currentNodeKey: string
  currentNodeName: string
  currentConfirmed: boolean
  productStatus: string
  logId: number
  warnings?: string[]
}

export interface TimelineActionPayload {
  remark?: string
  reason?: string
  returnToPrevious?: boolean
}

export interface ProductReleaseGateMissingItemVO {
  code: string
  message: string
  severity?: 'blocker' | 'warning'
}

export interface ProductReleaseGateCheckVO {
  projectId: number
  productId: number
  passed: boolean
  blocking?: boolean
  confirmRequired?: boolean
  currentStatus: string
  currentNodeKey?: string | null
  currentNodeConfirmed?: boolean | null
  frozenBomCount: number
  lockedProcessRouteCount: number
  drawingFileCount: number
  sopFileCount: number
  sipFileCount: number
  testingFileCount: number
  missingItems: ProductReleaseGateMissingItemVO[]
}

export interface ProductLifecycleActionPayload {
  reason?: string
  riskConfirmed?: boolean
}

export interface ProductLifecycleResultVO {
  productId: number
  productCode: string
  productName: string
  status: ProductSummary['status']
  lockStatus?: string | null
  releasedAt?: string | null
  releasedBy?: string | null
  archivedAt?: string | null
  archivedBy?: string | null
  abandonedAt?: string | null
  abandonedBy?: string | null
}

interface ProjectQueryParams {
  page?: number
  size?: number
  keyword?: string
  status?: string
  productType?: string
  ownerUserId?: number
}

function normalizeProductType(value?: string | null): ProductType {
  return value === 'model_variant' || value === 'sku' ? value : 'product_line'
}

function getSeriesName(item: Pick<BackendProjectSummary, 'productName'> & { seriesName?: string | null }) {
  return item.seriesName || item.productName.split(/\s+/)[0] || item.productName
}

function getCompletionRate(currentStepNo?: number | null, productType?: ProductType) {
  const maxStep = productType === 'product_line' ? 22 : 18
  const step = Math.max(1, Math.min(Number(currentStepNo || 1), maxStep))
  return Number((step / maxStep).toFixed(2))
}

function mapProjectSummary(item: BackendProjectSummary | BackendProjectDetail): ProductSummary {
  const productType = normalizeProductType(item.productType)
  const currentStepNo = Number(item.currentStepNo || 1)
  return {
    productId: Number(item.productId || item.projectId),
    parentProductId: item.parentProductId || null,
    productCode: item.productCode,
    productSpecificCode: item.productSpecificCode || null,
    phoneModelCode: item.phoneModelCode || null,
    colorCode: item.colorCode || null,
    finishedProductCode: item.finishedProductCode || null,
    importShortCode: item.importShortCode || null,
    productName: item.productName,
    productType,
    seriesName: getSeriesName(item),
    model: item.model || '--',
    moldCodes: item.moldCodes || null,
    color: item.color || '--',
    material: 'material' in item ? item.material || '' : '',
    moldTransferAt: item.moldTransferAt || null,
    expectedArrivalAt: item.expectedArrivalAt || null,
    actualArrivalAt: item.actualArrivalAt || null,
    ownerUserName: item.ownerUserName || '--',
    versionNo: item.versionNo || 'A',
    status: item.status,
    lockStatus: item.lockStatus || null,
    abandonedAt: item.abandonedAt || null,
    abandonedBy: item.abandonedBy || null,
    abandonReason: item.abandonReason || null,
    currentStage: item.currentNodeName || '待推进',
    currentStepNo,
    customerName: '',
    frozenFlag: false,
    releasedAt: ['released', 'archived'].includes(item.status) ? item.updatedAt || null : null,
    completionRate: getCompletionRate(currentStepNo, productType),
    estimatedCost: 0,
    estimatedCostCurrency: 'CNY',
    actualCost: null,
    rdCost: null,
    productCost: null,
    totalCost: item.totalCost ?? null,
    testItemCount: 0,
    activeBomVersion: '',
    productFlowMode: productType === 'product_line' ? 'new_product_line' : 'new_model_variant',
    lifecycle: 'initiation',
    moldAction: productType === 'product_line' ? null : 'modify',
    nextAction: item.currentNodeName ? `继续处理：${item.currentNodeName}` : '继续推进当前节点',
    gateSummary: '来自后端 M2 项目时间轴'
  }
}

function mapTimelineNode(node: BackendTimelineNode): TimelineNodeVO {
  const status = node.nodeStatus
  return {
    nodeKey: node.nodeCode,
    nodeName: node.nodeName,
    stageCode: node.stageCode || null,
    stageName: node.stageName || null,
    phaseName: node.phaseName || `第 ${node.stepNo} 节点`,
    requiredFileCategory: node.requiredFileCategory || null,
    requiredAttachment: Boolean(node.requiredAttachment),
    uploadPrompt: node.uploadPrompt || null,
    confirmPrompt: node.confirmPrompt || null,
    emptyFileMessage: node.emptyFileMessage || null,
    gateFlag: Boolean(node.gateFlag),
    enabledFlag: node.enabledFlag !== false,
    stepNo: node.stepNo,
    status,
    nodeStatus: status,
    summary: status === 'completed' ? '已完成' : node.confirmed ? '当前节点已确认' : '等待节点处理',
    experienceSummary: status === 'completed' ? '节点已完成。' : node.confirmed ? '节点确认记录已写入后端。' : '节点状态来自后端 M2 时间轴。',
    ownerRole: '工程',
    receiverRole: '工程',
    nextAction: status === 'current' ? '处理当前节点' : undefined,
    documentCount: Number(node.documentCount || 0),
    confirmed: Boolean(node.confirmed)
  }
}

function mapTimeline(detail: BackendTimelineDetail): TimelineDetailVO {
  const nodes = (detail.nodes || []).map(mapTimelineNode)
  const current = nodes.find((node) => node.status === 'current')
  const timelineCompleted = Boolean(detail.timelineCompleted)
    || (nodes.length > 0 && !current && nodes.every((node) => node.status === 'completed'))
  const displayNode = current || (timelineCompleted ? nodes[nodes.length - 1] : nodes[0])
  return {
    projectId: Number(detail.projectId),
    productId: Number(detail.productId),
    productType: normalizeProductType(detail.productType),
    started: detail.started !== false,
    startBlockReason: detail.startBlockReason || null,
    timelineCompleted,
    currentNode: displayNode?.nodeName || '待推进',
    currentStepNo: Number(detail.currentStepNo || displayNode?.stepNo || 1),
    currentStageCode: detail.currentStageCode || displayNode?.stageCode || null,
    currentStageName: detail.currentStageName || displayNode?.stageName || null,
    currentPhaseName: detail.currentPhaseName || displayNode?.phaseName || null,
    currentStepCode: detail.currentStepCode || displayNode?.nodeKey || null,
    currentStepName: detail.currentStepName || displayNode?.nodeName || null,
    currentConfirmed: detail.currentConfirmed,
    confirmedNodeKey: detail.confirmedNodeKey,
    lastAction: detail.lastAction,
    lastReason: detail.lastReason,
    lastOperatedAt: detail.lastOperatedAt,
    lastOperatorUserId: detail.lastOperatorUserId,
    lastOperatorUserName: detail.lastOperatorUserName,
    moldTransferExpress: detail.moldTransferExpress || null,
    nodes
  }
}

function mapProjectDetail(item: BackendProjectDetail): ProjectDetailVO {
  const summary = mapProjectSummary(item)
  return {
    ...summary,
    projectId: Number(item.projectId || item.productId),
    productId: Number(item.productId || item.projectId),
    parentProductId: item.parentProductId || null,
    material: item.material || '',
    packageType: item.packageType || '',
    surfaceProcess: item.surfaceProcess || '',
    coreProcess: item.coreProcess || '',
    composition: item.composition || '',
    colorSummary: item.colorSummary ? {
      skuColorCount: Number(item.colorSummary.skuColorCount || 0),
      productionColorCount: Number(item.colorSummary.productionColorCount || 0),
      skuColors: mapProjectColorUsages(item.colorSummary.skuColors),
      productionColors: mapProjectColorUsages(item.colorSummary.productionColors),
      skuOnlyColors: mapProjectColorUsages(item.colorSummary.skuOnlyColors),
      productionOnlyColors: mapProjectColorUsages(item.colorSummary.productionOnlyColors)
    } : null,
    summary: item.remark || item.currentNodeName || '',
    timeline: item.timeline ? mapTimeline(item.timeline) : undefined
  }
}

function mapProjectColorUsages(items?: BackendProjectColorUsage[] | null) {
  return (items || []).map((item) => ({
    colorCode: item.colorCode || null,
    colorName: item.colorName || item.colorCode || '--',
    skuCount: Number(item.skuCount || 0),
    decisionCount: Number(item.decisionCount || 0)
  }))
}

export async function getWorkbenchInProgressProjects(params?: ProjectQueryParams): Promise<ProjectSummaryVO[]> {
  const response = await request.get('/workbench/projects/in-progress', { params })
  return unwrapPage<BackendProjectSummary>(response).content.map(mapProjectSummary)
}

export async function getProjects(params?: ProjectQueryParams): Promise<ProjectSummaryVO[]> {
  const response = await request.get('/projects', { params })
  return unwrapPage<BackendProjectSummary>(response).content.map(mapProjectSummary)
}

export async function getProjectDetail(projectId: number): Promise<ProjectDetailVO> {
  const response = await request.get(`/projects/${projectId}`)
  return mapProjectDetail(unwrapResponse<BackendProjectDetail>(response))
}

export async function getProjectSummary(projectId: number): Promise<ProjectSummaryVO> {
  const response = await request.get(`/projects/${projectId}/summary`)
  return mapProjectSummary(unwrapResponse<BackendProjectSummary>(response))
}

export async function getProjectTimeline(projectId: number): Promise<TimelineDetailVO> {
  const response = await request.get(`/projects/${projectId}/timeline`)
  return mapTimeline(unwrapResponse<BackendTimelineDetail>(response))
}

export async function getMoldTransferExpress(projectId: number, nodeKey: string): Promise<MoldTransferExpressVO | null> {
  const response = await request.get(`/projects/${projectId}/timeline/${nodeKey}/mold-transfer/express`)
  return unwrapResponse<MoldTransferExpressVO | null>(response)
}

export async function saveMoldTransferExpress(
  projectId: number,
  nodeKey: string,
  payload: MoldTransferExpressSavePayload
): Promise<MoldTransferExpressVO> {
  const response = await request.put(`/projects/${projectId}/timeline/${nodeKey}/mold-transfer/express`, payload)
  return unwrapResponse<MoldTransferExpressVO>(response)
}

export async function confirmTimelineNode(
  projectId: number,
  nodeKey: string,
  remark?: string
): Promise<TimelineActionResultVO> {
  const payload: TimelineActionPayload = remark?.trim() ? { remark: remark.trim() } : {}
  const response = await request.post(`/projects/${projectId}/timeline/${nodeKey}/confirm`, payload)
  return unwrapResponse<TimelineActionResultVO>(response)
}

export async function advanceTimelineNode(
  projectId: number,
  nodeKey: string,
  remark?: string
): Promise<TimelineActionResultVO> {
  const payload: TimelineActionPayload = remark?.trim() ? { remark: remark.trim() } : {}
  const response = await request.post(`/projects/${projectId}/timeline/${nodeKey}/advance`, payload)
  return unwrapResponse<TimelineActionResultVO>(response)
}

export async function returnTimelineNode(
  projectId: number,
  nodeKey: string,
  reason: string,
  returnToPrevious = true
): Promise<TimelineActionResultVO> {
  const cleanReason = reason.trim()
  if (!cleanReason) throw new Error('请填写退回原因')
  const response = await request.post(`/projects/${projectId}/timeline/${nodeKey}/return`, {
    reason: cleanReason,
    returnToPrevious
  })
  return unwrapResponse<TimelineActionResultVO>(response)
}

export async function checkProjectReleaseGate(projectId: number): Promise<ProductReleaseGateCheckVO> {
  const response = await request.get(`/projects/${projectId}/release-gate`)
  return unwrapResponse<ProductReleaseGateCheckVO>(response)
}

export async function freezeProject(
  projectId: number,
  payload: ProductLifecycleActionPayload = {}
): Promise<ProductLifecycleResultVO> {
  const response = await request.post(`/projects/${projectId}/freeze`, payload)
  return unwrapResponse<ProductLifecycleResultVO>(response)
}

export async function publishProject(
  projectId: number,
  payload: ProductLifecycleActionPayload = {}
): Promise<ProductLifecycleResultVO> {
  const response = await request.post(`/projects/${projectId}/publish`, payload)
  return unwrapResponse<ProductLifecycleResultVO>(response)
}

export async function archiveProject(
  projectId: number,
  payload: ProductLifecycleActionPayload = {}
): Promise<ProductLifecycleResultVO> {
  const response = await request.post(`/projects/${projectId}/archive`, payload)
  return unwrapResponse<ProductLifecycleResultVO>(response)
}

export async function abandonProject(
  projectId: number,
  payload: ProductLifecycleActionPayload
): Promise<ProductLifecycleResultVO> {
  const reason = payload.reason?.trim()
  if (!reason) throw new Error('请填写停止原因')
  const response = await request.post(`/projects/${projectId}/abandon`, { reason })
  return unwrapResponse<ProductLifecycleResultVO>(response)
}
