<script setup lang="ts">
import { ElMessage, ElMessageBox } from 'element-plus'
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useUserStore } from '@/stores/user'

import { getProductPresentation } from '@/api/modules/foundation'
import { getProductDetail as getProductBasicDetail, updateProductBasicInfo } from '@/api/modules/product'
import {
  abandonProject,
  archiveProject,
  checkProjectReleaseGate,
  confirmTimelineNode,
  freezeProject,
  getProjectDetail,
  getProjects,
  getProjectTimeline,
  publishProject,
  returnTimelineNode,
  saveMoldTransferExpress,
  type ProductReleaseGateCheckVO,
  type MoldTransferExpressVO,
  type TimelineDetailVO
} from '@/api/modules/project'
import { commitImport, previewImport, type ImportPreviewVO } from '@/api/modules/importExport'
import FilePreview from '@/components/FilePreview/index.vue'
import PageContainer from '@/components/PageContainer/index.vue'
import FixedTableViewport from '@/components/FixedTableViewport/index.vue'
import StatusTag from '@/components/StatusTag/index.vue'
import ProjectBomPanel from './components/ProjectBomPanel.vue'
import ProjectCostPanel from './components/ProjectCostPanel.vue'
import ProjectProcessRoutePanel from './components/ProjectProcessRoutePanel.vue'
import ProjectReleaseGatePanel from './components/ProjectReleaseGatePanel.vue'
import ProductionConfirmationDialog from './components/ProductionConfirmationDialog.vue'
import TimelineAttachmentPanel from './components/TimelineAttachmentPanel.vue'
import type { CommonStatus } from '@/types/common'
import type { BomCompareRow, ProductBomItemRow, ProductDetailPresentation, ProductTimelineNode, ProductionDocumentPreviewFile, SkuProcessRouteRow } from '@/types/foundation'
import type { ProductBasicInfo, ProductSummary } from '@/types/product'
import { formatAmount, formatDate } from '@/utils/format'
import { toArchivedProductRoute } from '@/utils/projectRoute'
import { findCurrentTimelineStep, mapTimelineStages, mapTimelineSteps, type TimelineStageView } from '@/utils/timelineAdapter'

type ProjectTab = 'all_projects' | 'in_progress' | 'archived' | 'abandoned'
type ProjectQuickTag = 'all_projects' | 'in_progress' | 'archived_product' | 'archived_sku' | 'abandoned'
type ProjectFlowFilter = 'all' | 'product_line' | 'model_variant'
type ArchiveView = 'overview' | 'product' | 'sku'
type DetailSectionKey =
  | 'basic'
  | 'current_node'
  | 'project_flow'
  | 'bom_manage'
  | 'process_detail'
  | 'materials'
  | 'business'
  | 'quality'
  | 'cost'
  | 'bom'
  | 'process'
  | 'production_docs'
type SkuPageStage = 'product-home' | 'sku-list'
type ProductFlowStageStatus = ProductTimelineNode['status']
type ProcessDetailFilter = 'all' | 'key' | 'changed'
type ProductProcessDetailTag = 'key' | 'changed' | 'outsourced'
type TimelinePresentationNode = ProductTimelineNode & { confirmed?: boolean }

interface ProjectTimelineNode {
  nodeKey: string
  stageCode?: string
  title: string
  phase: string
  gate?: boolean
  hint: string
  childStepNos: number[]
  childNodes: string[]
  count: number
}

type ProjectTimelineDefinition = Omit<ProjectTimelineNode, 'count'>

interface ProductFlowStageNode {
  stepNo: number
  nodeKey: string
  nodeCode?: string
  nodeName: string
  status: ProductFlowStageStatus
  actionLabel?: string
  documentCount?: number
  visualStatus?: string
  processConfirmation?: boolean
}

interface ProductFlowStage {
  stageKey: string
  stageName: string
  phaseName: string
  status: ProductFlowStageStatus
  summary: string
  receiverRole?: string
  receiverUserName?: string
  receivedAt?: string
  promoterRole?: string
  promoterUserName?: string
  promotedAt?: string
  nextAction?: string
  riskNote?: string
  childNodes: ProductFlowStageNode[]
}

interface ProductProcessDetailRow {
  sequenceNo: number
  processCode: string
  processName: string
  processType: string
  workstationName?: string | null
  supplierName?: string | null
  confirmerName?: string
  confirmerRole?: string
  processParamSummary?: string
  qualityRequirement?: string
  unitProcessCost?: number
  tags: ProductProcessDetailTag[]
}

interface SkuProjectFlowRow {
  seqNo: number
  stageKey: string
  stageName: string
  nodeKey: string
  nodeName: string
  phaseName: string
  status: ProductFlowStageStatus
  experienceSummary: string
  receiverRole?: string
  receiverUserName?: string
  receivedAt?: string
  promoterRole?: string
  promoterUserName?: string
  promotedAt?: string
  nextAction?: string
  riskNote?: string
  gateLabel?: string
  documentCount?: number
}

interface AllProjectRow {
  productId: number
  productCode: string
  productName: string
  projectType: string
  projectTag: string
  currentStage: string
  ownerUserName: string
  versionNo: string
  updatedAt: string
  sourceStatus?: CommonStatus
  abandoned?: boolean
  source?: ProductSummary
}

const router = useRouter()
const user = useUserStore()
const route = useRoute()

const loading = ref(false)
const rows = ref<ProductSummary[]>([])
const keyword = ref('')
const activeTab = ref<ProjectTab>('in_progress')
const activeFlow = ref<ProjectFlowFilter>('all')
const selectedTimelineNode = ref<ProjectTimelineNode | null>(null)

const overviewVisible = ref(false)
const overviewProject = ref<AllProjectRow | null>(null)
const importVisible = ref(false)
const importType = ref<'product' | 'sku'>('product')
const archiveImportFile = ref<File | null>(null)
const archiveImportInputKey = ref(0)
const archiveImportPreview = ref<ImportPreviewVO | null>(null)
const archiveImportLoading = ref(false)

const detailVisible = ref(false)
const productionConfirmationVisible = ref(false)
const productionConfirmationMode = ref<'operations' | 'colors'>('operations')
const productionConfirmationDefaultRouteId = ref<number | null>(null)
const routeDetailLoading = ref(false)
const processConfirmationNodeKeys = new Set([
  'PRODUCT_LINE_PROCESS_CONFIRM',
  'MODEL_VARIANT_PROCESS_CONFIRM'
])

function isProcessConfirmationNode(node: Pick<ProductFlowStageNode, 'nodeKey' | 'nodeCode' | 'nodeName'>) {
  const key = node.nodeKey || node.nodeCode || ''
  return processConfirmationNodeKeys.has(key)
    || key.endsWith('_PROCESS_CONFIRM_STEP')
    || node.nodeName.includes('敲定投产工序')
    || node.nodeName.includes('敲定工序')
}

function openProductionConfirmation(mode: 'operations' | 'colors', defaultProductBomRouteId?: number | null) {
  productionConfirmationMode.value = mode
  productionConfirmationDefaultRouteId.value = defaultProductBomRouteId || null
  productionConfirmationVisible.value = true
}
const detailTarget = ref<ProductSummary | null>(null)
const detailLoading = ref(false)
const detailPresentation = ref<ProductDetailPresentation | null>(null)
const basicInfoEditing = ref(false)
const basicInfoSaving = ref(false)
const basicInfoExtra = ref<Partial<ProductBasicInfo> | null>(null)
const basicInfoForm = reactive({
  productName: '',
  seriesName: '',
  ownerUserName: '',
  model: '',
  color: '',
  material: '',
  packageType: '',
  surfaceProcess: '',
  coreProcess: '',
  composition: '',
  expectedReleaseDate: '',
  expectedArrivalAt: '',
  actualArrivalAt: '',
  networkType: '',
  holeType: '',
  mobileFunction: '',
  tipo: '',
  priority: '',
  manufacturingLocation: '',
  moldMarking: '',
  referenceUrl: '',
  requirementType: '',
  customerRequirement: ''
})
const detailBomVersion = ref('')
const timelineActionLoading = ref<false | 'confirm' | 'advance' | 'return'>(false)
const detailLifecycleLoading = ref<false | 'freeze' | 'publish' | 'archive' | 'abandon'>(false)
const timelineCurrentConfirmed = ref<boolean | null>(null)
const timelineStarted = ref<boolean | null>(null)
const timelineStartBlockReason = ref<string | null>(null)
const timelineCompleted = ref(false)
const timelineLastAction = ref<string | null>(null)
const timelineLastReason = ref<string | null>(null)
const timelineLastOperatedAt = ref<string | null>(null)
const timelineLastOperatorUserName = ref<string | null>(null)
const timelineFlowStages = ref<ProductFlowStage[] | null>(null)
const moldTransferExpress = ref<MoldTransferExpressVO | null>(null)
const moldTransferLoading = ref(false)
const moldTransferForm = reactive({
  trackingNo: '',
  shippedAt: ''
})
const activeDetailSection = ref<DetailSectionKey>('basic')
const activeProductFlowStageKey = ref('')
const activeSkuFlowStageKey = ref('')
const processDetailFilter = ref<ProcessDetailFilter>('all')
const processDetailKeyword = ref('')
const skuFlowTableExpanded = ref<string[]>([])

/* 生产资料预览 */
const productionPreviewVisible = ref(false)
const activeProductionDoc = ref<ProductionDocumentPreviewFile | null>(null)

const skuPageStage = ref<SkuPageStage>('product-home')
const skuActiveProductId = ref<number | null>(null)
const skuKeyword = ref('')

const productDetailSections = [
  { key: 'current_node' as const, label: '当前节点' },
  { key: 'basic' as const, label: '基础信息' },
  { key: 'project_flow' as const, label: '项目流程' },
  { key: 'bom_manage' as const, label: 'BOM管理' },
  { key: 'cost' as const, label: '成本管理' },
  { key: 'process_detail' as const, label: '工序明细' },
  { key: 'materials' as const, label: '资料区' },
  { key: 'business' as const, label: '商务区' },
  { key: 'quality' as const, label: '质量区' }
]

const skuDetailSections = [
  { key: 'basic' as const, label: '基础信息' },
  { key: 'cost' as const, label: '成本' },
  { key: 'bom' as const, label: '当前版本 BOM' },
  { key: 'process' as const, label: '工艺路线' },
  { key: 'project_flow' as const, label: '项目流程' },
  { key: 'production_docs' as const, label: '生产资料' }
]

const projectQuickTags = [
  { label: '全部项目', value: 'all_projects' },
  { label: '进行中', value: 'in_progress' },
  { label: '已归档（产品）', value: 'archived_product' },
  { label: '已归档（SKU）', value: 'archived_sku' },
  { label: '已停止', value: 'abandoned' }
] as const

const flowFilters = [
  { label: '全部', value: 'all' },
  { label: '新产品线', value: 'product_line' },
  { label: '新型号线', value: 'model_variant' }
] as const

const newProductLineTimeline: ProjectTimelineDefinition[] = [
  { nodeKey: 'initiation', title: '立项确认', phase: '立项阶段', gate: true, hint: '确认需求、成本、周期和投入边界。', childStepNos: [1, 2], childNodes: ['产品立项', '确认立项'] },
  { nodeKey: 'design', title: '设计确认', phase: '设计验证阶段', hint: '收敛图纸、外观、结构和供应商可制造性。', childStepNos: [3, 4], childNodes: ['画图查看', '供应商确认外观图纸'] },
  { nodeKey: 'tooling', title: '开模试模', phase: '开模阶段', gate: true, hint: '完成开模申请、模具制作和试模验证。', childStepNos: [5, 6, 7], childNodes: ['申请开模', '制作模具', '测试模具'] },
  { nodeKey: 'sampling-process', title: '样品与工艺', phase: '样品 / 工艺定型阶段', gate: true, hint: '签样、工艺、组件、红样、黄样和生产资料整理。', childStepNos: [8, 9, 10, 11, 12, 13, 14, 15, 16], childNodes: ['签样确认', '加工艺', '敲定工序', '整理生产资料', '黄样'] },
  { nodeKey: 'pilot-mx', title: '小批与 MX 验证', phase: '市场验证阶段', gate: true, hint: '验证产线、物流、MX 端承接和小批量跑通。', childStepNos: [17, 18, 19, 20, 21], childNodes: ['小批量测试', '运模', 'MX 验收', '测试验证', 'MX 小批量测试'] },
  { nodeKey: 'launch', title: '投产决策', phase: '投产发布阶段', gate: true, hint: '根据验证结果决定投产或回退。', childStepNos: [22], childNodes: ['投产决策'] }
]

const modelVariantTimeline: ProjectTimelineDefinition[] = [
  { nodeKey: 'ext-confirm', title: '立项确认', phase: '立项阶段', gate: true, hint: '确认新型号需求来源和父产品关系。', childStepNos: [1, 2], childNodes: ['产品立项', '确认立项'] },
  { nodeKey: 'diff-design', title: '设计确认', phase: '设计验证阶段', hint: '确认图纸、外观和供应商可制造性差异。', childStepNos: [3, 4], childNodes: ['画图查看', '供应商确认外观图纸'] },
  { nodeKey: 'mold-branch', title: '开模试模', phase: '开模阶段', gate: true, hint: '完成开模申请、模具制作和试模验证。', childStepNos: [5, 6, 7], childNodes: ['申请开模', '制作模具', '测试模具'] },
  { nodeKey: 'diff-verify', title: '样品与工艺', phase: '样品 / 工艺定型阶段', gate: true, hint: '确认签样、工艺、组件、测试和生产资料。', childStepNos: [8, 9, 10, 11, 12, 13, 14, 15, 16], childNodes: ['签样确认', '加工艺', '敲定工序', '确认组件', '确认组件成品', '最终外观确认样', '红样测试', '整理生产资料', '黄样'] },
  { nodeKey: 'variant-pilot', title: '小批与 MX 验证', phase: '市场验证阶段', gate: true, hint: '完成小批量测试和运模移交，运模确认后 PLM 进入完成/归档/移交状态。', childStepNos: [17, 18], childNodes: ['小批量测试', '运模 / 移交 MX'] }
]

const timelineStageCodeByKey: Record<string, string> = {
  initiation: 'PRODUCT_LINE_INIT_CONFIRM',
  design: 'PRODUCT_LINE_DESIGN_CONFIRM',
  tooling: 'PRODUCT_LINE_MOLD_TRIAL',
  'sampling-process': 'PRODUCT_LINE_SAMPLE_PROCESS',
  'pilot-mx': 'PRODUCT_LINE_SMALL_BATCH_MX',
  launch: 'PRODUCT_LINE_PRODUCTION_DECISION',
  'ext-confirm': 'MODEL_VARIANT_INIT_CONFIRM',
  'diff-design': 'MODEL_VARIANT_DESIGN_CONFIRM',
  'mold-branch': 'MODEL_VARIANT_MOLD_TRIAL',
  'diff-verify': 'MODEL_VARIANT_SAMPLE_PROCESS',
  'variant-pilot': 'MODEL_VARIANT_SMALL_BATCH_MX'
}

const archiveView = computed<ArchiveView>(() => {
  const value = String(route.query.archiveView || 'overview')
  return ['overview', 'product', 'sku'].includes(value) ? (value as ArchiveView) : 'overview'
})

const projectQuickTag = computed<ProjectQuickTag>(() => {
  if (activeTab.value === 'all_projects') return 'all_projects'
  if (activeTab.value === 'in_progress') return 'in_progress'
  if (activeTab.value === 'abandoned') return 'abandoned'
  return archiveView.value === 'sku' ? 'archived_sku' : 'archived_product'
})

const filteredRows = computed(() => {
  const search = keyword.value.trim().toLowerCase()
  if (!search) return rows.value
  return rows.value.filter((item) =>
    [item.productCode, item.productName, item.seriesName, item.ownerUserName, item.model, item.color]
      .filter(Boolean)
      .some((value) => String(value).toLowerCase().includes(search))
  )
})

function isAbandonedProject(item: ProductSummary) {
  return item.lockStatus === 'abandoned' || Boolean(item.abandonedAt)
}

function formatScalarOrArray(value: unknown) {
  if (Array.isArray(value)) {
    const values = value.map((item) => String(item || '').trim()).filter(Boolean)
    return values.length ? values.join('、') : '--'
  }
  if (typeof value === 'string') {
    const trimmed = value.trim()
    if (!trimmed || trimmed === '--') return '--'
    if (trimmed.startsWith('[')) {
      try {
        const parsed = JSON.parse(trimmed)
        if (Array.isArray(parsed)) {
          const values = parsed.map((item) => String(item || '').trim()).filter(Boolean)
          return values.length ? values.join('、') : '--'
        }
      } catch {
        return trimmed
      }
    }
    return trimmed
  }
  return value == null ? '--' : String(value)
}

function formatOwnerName(value?: string | null) {
  const trimmed = String(value || '').trim()
  return trimmed && trimmed !== '--' ? trimmed : '待分配'
}

function normalizeProjectDetailRoute(target: ProductSummary) {
  if (!['released', 'archived'].includes(target.status) || String(route.query.tab || '') === 'archived') return
  router.push({
    path: route.path,
    query: {
      ...route.query,
      tab: 'archived',
      archiveView: target.productType === 'model_variant' ? 'sku' : 'product',
      productId: String(target.productId)
    }
  })
}

const runningProjects = computed(() =>
  filteredRows.value.filter((item) => ['draft', 'developing', 'pending'].includes(item.status))
)

const flowFilteredProjects = computed(() => {
  if (activeFlow.value === 'all') return runningProjects.value
  return runningProjects.value.filter((item) => item.productType === activeFlow.value)
})

const flowTimeline = computed<ProjectTimelineNode[]>(() => {
  const source = activeFlow.value === 'product_line' ? newProductLineTimeline : modelVariantTimeline
  return source.map((node) => ({
    ...node,
    count: flowFilteredProjects.value.filter((project) => node.childStepNos.includes(project.currentStepNo || -1)).length
  }))
})

const timelineProjects = computed(() => {
  if (activeFlow.value === 'all') return flowFilteredProjects.value
  if (!selectedTimelineNode.value) return flowFilteredProjects.value
  return flowFilteredProjects.value.filter((item) => selectedTimelineNode.value!.childStepNos.includes(item.currentStepNo || -1))
})

const archivedProjects = computed(() =>
  rows.value.filter((item) => !isAbandonedProject(item) && ['released', 'archived'].includes(item.status))
)
const archivedProductRows = computed(() => archivedProjects.value.filter((item) => item.productType === 'product_line'))
const archivedSkuRows = computed(() =>
  archivedProjects.value.filter((item) => item.productType === 'model_variant' || item.productType === 'sku' || Boolean(item.parentProductId))
)
const abandonedProjectRows = computed(() => filteredRows.value.filter(isAbandonedProject))

const archiveSummary = computed(() => ({
  total: archivedProjects.value.length,
  products: archivedProductRows.value.length,
  skus: archivedSkuRows.value.length
}))

const allProjectRows = computed<AllProjectRow[]>(() =>
  rows.value.map((item) => ({
    productId: item.productId,
    productCode: item.productCode,
    productName: item.productName,
    projectType: item.productType === 'product_line' ? '产品' : item.productType === 'model_variant' ? '新型号' : 'SKU',
    projectTag: isAbandonedProject(item)
      ? '已停止'
      : ['released', 'archived'].includes(item.status)
      ? item.productType === 'product_line'
        ? '已归档（产品）'
        : '已归档（SKU）'
      : '进行中',
    currentStage: item.currentStage,
    ownerUserName: item.ownerUserName,
    versionNo: item.versionNo,
    updatedAt: item.abandonedAt || item.releasedAt || '',
    sourceStatus: item.status,
    abandoned: isAbandonedProject(item),
    source: item
  }))
)

const skuProductCards = computed(() =>
  archivedProductRows.value.filter((product) => getSkuCountForProduct(product) > 0)
)

const skuActiveProduct = computed(() =>
  skuProductCards.value.find((item) => item.productId === skuActiveProductId.value) || null
)

const skuCurrentSkuRows = computed(() => {
  const search = skuKeyword.value.trim().toLowerCase()
  if (!skuActiveProductId.value) return []
  return archivedSkuRows.value.filter((item) => {
    const activeProductCode = skuActiveProduct.value?.productCode || ''
    const activeProductLineCode = skuActiveProduct.value ? getDisplayProductLineCode(skuActiveProduct.value) : ''
    const belongsTo =
      item.parentProductId === skuActiveProductId.value ||
      (Boolean(activeProductCode) &&
        (item.productCode.startsWith(activeProductCode) || Boolean(item.finishedProductCode?.startsWith(activeProductCode)))) ||
      (Boolean(activeProductLineCode) &&
        (item.productCode.startsWith(activeProductLineCode) || Boolean(item.finishedProductCode?.startsWith(activeProductLineCode))))
    const keywordMatched =
      !search ||
      item.productCode.toLowerCase().includes(search) ||
      getDisplaySkuCode(item).toLowerCase().includes(search) ||
      item.productName.toLowerCase().includes(search) ||
      item.model.toLowerCase().includes(search) ||
      item.color.toLowerCase().includes(search)
    return belongsTo && keywordMatched
  })
})

const currentModuleCount = computed(() => {
  if (projectQuickTag.value === 'all_projects') return allProjectRows.value.length
  if (projectQuickTag.value === 'in_progress') return runningProjects.value.length
  if (projectQuickTag.value === 'archived_product') return archivedProductRows.value.length
  if (projectQuickTag.value === 'archived_sku') return archivedSkuRows.value.length
  return abandonedProjectRows.value.length
})

const currentModuleTitle = computed(() => {
  return projectQuickTags.find((item) => item.value === projectQuickTag.value)?.label || '全部项目'
})

const currentModuleDescription = computed(() => {
  if (projectQuickTag.value === 'all_projects') return '汇总进行中、已归档和已停止项目，可快速打开项目概览。'
  if (projectQuickTag.value === 'in_progress') return '展示正在推进的新产品线和新型号线项目，可按关键节点查看当前环节。'
  if (projectQuickTag.value === 'archived_product') return '只展示已完成并已发布 / 已归档的新产品线产品，详情弹窗用于追溯最终版本资料和流程结果。'
  if (projectQuickTag.value === 'archived_sku') return '按产品卡片进入已归档 SKU 列表与详情，仍通过 Product 对象承载。'
  return '已停止项目永久保留，数据来自后端 Product 停止状态。'
})

const detailBomItems = computed<ProductBomItemRow[]>(() => {
  if (!detailPresentation.value || !detailBomVersion.value) return []
  return detailPresentation.value.bomItemsByVersion[detailBomVersion.value] || []
})

const isProductDetailDialog = computed(() => detailTarget.value?.productType === 'product_line')
const hasDetailColorSummary = computed(() =>
  Boolean(
    isProductDetailDialog.value &&
    detailTarget.value?.colorSummary &&
    ((detailTarget.value.colorSummary.skuColors?.length || 0) > 0 ||
      (detailTarget.value.colorSummary.productionColors?.length || 0) > 0)
  )
)
const detailDialogTitle = computed(() => {
  if (detailTarget.value?.productType === 'product_line') return '产品详情'
  if (detailTarget.value?.productType === 'model_variant') return '新型号详情'
  return 'SKU 详情'
})
const detailObjectLabel = computed(() => {
  if (detailTarget.value?.productType === 'product_line') return '产品'
  if (detailTarget.value?.productType === 'model_variant') return '新型号'
  return 'SKU'
})

const activeDetailSections = computed(() =>
  (isProductDetailDialog.value ? productDetailSections : skuDetailSections).filter(section=>section.key!=='cost'||user.hasPermission('finance:read'))
)

const activeProductFlowNode = computed<TimelinePresentationNode | null>(() => {
  const nodes = (detailPresentation.value?.timeline || []) as TimelinePresentationNode[]
  return nodes.find((item) => item.status === 'current') || nodes[nodes.length - 1] || null
})

const currentTimelineConfirmed = computed(() => Boolean(
  timelineCompleted.value || (activeProductFlowNode.value?.confirmed ?? timelineCurrentConfirmed.value)
))

const currentTimelineActionLabel = computed(() => {
  if (!activeProductFlowNode.value) return '暂无当前节点'
  if (timelineCompleted.value || activeProductFlowNode.value.status === 'completed') return '已完成'
  return currentTimelineConfirmed.value ? '可推进到下一节点' : '等待确认当前节点'
})

const canAdvanceCurrentTimelineNode = computed(() => {
  if (!activeProductFlowNode.value) return false
  if (activeProductFlowNode.value.status !== 'current') return false
  const nodes = detailPresentation.value?.timeline || []
  const currentIndex = nodes.findIndex((node) => node.nodeKey === activeProductFlowNode.value?.nodeKey)
  return currentTimelineConfirmed.value && currentIndex >= 0 && currentIndex < nodes.length - 1
})

function stageMatchesNode(stage: ProjectTimelineDefinition, node: ProductTimelineNode, stepNo: number) {
  const expectedStageCode = stage.stageCode || timelineStageCodeByKey[stage.nodeKey]
  if (expectedStageCode && node.stageCode) return node.stageCode === expectedStageCode
  const phaseMatched = node.phaseName ? node.phaseName === stage.phase : false
  const nameMatched = stage.childNodes.some((childName) => node.nodeName.includes(childName) || childName.includes(node.nodeName))
  const stepMatched = !node.phaseName && !nameMatched && stage.childStepNos.includes(stepNo)
  return phaseMatched || nameMatched || stepMatched
}

function buildFlowStages(timelineNodes: ProductTimelineNode[], definitions: ProjectTimelineDefinition[]) {
  return definitions.map((stage, stageIndex) => {
    const childNodes = timelineNodes
      .map((node, index) => ({ node, stepNo: index + 1 }))
      .filter(({ node, stepNo }) => stageMatchesNode(stage, node, stepNo))

    const representativeNode =
      childNodes.find(({ node }) => node.status === 'current')?.node ||
      childNodes.find(({ node }) => node.status === 'rejected')?.node ||
      childNodes[childNodes.length - 1]?.node ||
      null

    const currentStageIndex = definitions.findIndex((item) =>
      timelineNodes.some((node, index) => node.status === 'current' && stageMatchesNode(item, node, index + 1))
    )

    let status: ProductFlowStageStatus = 'pending'
    if (childNodes.some(({ node }) => node.status === 'rejected')) {
      status = 'rejected'
    } else if (childNodes.some(({ node }) => node.status === 'current')) {
      status = 'current'
    } else if (childNodes.length && childNodes.every(({ node }) => node.status === 'completed')) {
      status = 'completed'
    } else if (currentStageIndex >= 0 && stageIndex < currentStageIndex) {
      status = 'completed'
    }

    return {
      stageKey: stage.nodeKey,
      stageName: stage.title,
      phaseName: stage.phase,
      status,
      summary: representativeNode?.experienceSummary || representativeNode?.summary || stage.hint,
      receiverRole: representativeNode?.receiverRole,
      receiverUserName: representativeNode?.receiverUserName,
      receivedAt: representativeNode?.receivedAt || representativeNode?.actualDate,
      promoterRole: representativeNode?.promoterRole || representativeNode?.ownerRole,
      promoterUserName: representativeNode?.promoterUserName,
      promotedAt: representativeNode?.promotedAt || representativeNode?.actualDate,
      nextAction: representativeNode?.nextAction || (status === 'completed' ? '已完成' : '待推进'),
      riskNote: representativeNode?.riskNote,
      childNodes:
        childNodes.length > 0
          ? childNodes.map(({ node, stepNo }) => ({
              stepNo,
              nodeKey: node.nodeKey,
              nodeCode: node.nodeKey,
              nodeName: node.nodeName,
              status: node.status,
              actionLabel: node.nextAction,
              processConfirmation: isProcessConfirmationNode({
                nodeKey: node.nodeKey,
                nodeCode: node.nodeKey,
                nodeName: node.nodeName
              })
            }))
          : stage.childNodes.map((nodeName, index) => ({
              stepNo: stage.childStepNos[index] || index + 1,
              nodeKey: `${stage.nodeKey}-${index}`,
              nodeCode: `${stage.nodeKey}-${index}`,
              nodeName,
              status: (status === 'completed' ? 'completed' : 'pending') as ProductFlowStageStatus,
              processConfirmation: isProcessConfirmationNode({
                nodeKey: `${stage.nodeKey}-${index}`,
                nodeCode: `${stage.nodeKey}-${index}`,
                nodeName
              })
            }))
    }
  })
}

const productFlowStages = computed<ProductFlowStage[]>(() => {
  if (timelineFlowStages.value?.length) return timelineFlowStages.value
  const timelineNodes = detailPresentation.value?.timeline || []
  return buildFlowStages(timelineNodes, newProductLineTimeline)
})

const isMoldTransferNode = computed(() =>
  activeProductFlowNode.value?.nodeKey === 'PRODUCT_LINE_MOLD_TRANSFER' ||
  activeProductFlowNode.value?.nodeKey === 'MODEL_VARIANT_MOLD_TRANSFER'
)

const activeProductFlowStage = computed(() => {
  return (
    productFlowStages.value.find((stage) => stage.stageKey === activeProductFlowStageKey.value) ||
    productFlowStages.value.find((stage) => stage.status === 'current') ||
    productFlowStages.value[0] ||
    null
  )
})

const skuProjectFlowStages = computed<ProductFlowStage[]>(() => {
  if (timelineFlowStages.value?.length) return timelineFlowStages.value
  const timelineNodes = detailPresentation.value?.timeline || []
  return buildFlowStages(timelineNodes, modelVariantTimeline)
})

const skuProjectFlowRows = computed<SkuProjectFlowRow[]>(() => {
  const timelineNodes = detailPresentation.value?.timeline || []
  return timelineNodes.map((node, index) => {
    const stage = modelVariantTimeline.find((item) => stageMatchesNode(item, node, index + 1))
    return {
      seqNo: index + 1,
      stageKey: stage?.nodeKey || node.phaseName || node.nodeKey,
      stageName: stage?.title || node.phaseName || '新型号线流程',
      nodeKey: node.nodeKey,
      nodeName: node.nodeName,
      phaseName: node.phaseName || stage?.phase || '--',
      status: node.status,
      experienceSummary: node.experienceSummary || node.summary || '--',
      receiverRole: node.receiverRole,
      receiverUserName: node.receiverUserName,
      receivedAt: node.receivedAt || node.actualDate,
      promoterRole: node.promoterRole || node.ownerRole,
      promoterUserName: node.promoterUserName,
      promotedAt: node.promotedAt || node.actualDate,
      nextAction: node.nextAction,
      riskNote: node.riskNote,
      gateLabel: node.gateLabel,
      documentCount: node.documentCount
    }
  })
})

const currentSkuProjectFlowRow = computed(() =>
  skuProjectFlowRows.value.find((row) => row.status === 'current') || skuProjectFlowRows.value[0] || null
)

const activeSkuFlowStage = computed(() => {
  return (
    skuProjectFlowStages.value.find((stage) => stage.stageKey === activeSkuFlowStageKey.value) ||
    skuProjectFlowStages.value.find((stage) => stage.status === 'current') ||
    skuProjectFlowStages.value[0] ||
    null
  )
})

const canEditDetailTarget = computed(() => {
  if (!detailTarget.value) return false
  return detailTarget.value.lockStatus !== 'abandoned'
})

const canFreezeDetailProject = computed(() =>
  Boolean(detailTarget.value && detailTarget.value.status !== 'archived')
)
const canPublishDetailProject = computed(() =>
  Boolean(isProductDetailDialog.value && detailTarget.value && !['released', 'archived'].includes(detailTarget.value.status))
)
const canStopDetailProject = computed(() =>
  Boolean(detailTarget.value && !['released', 'archived'].includes(detailTarget.value.status))
)
const canArchiveDetailProject = computed(() =>
  Boolean(detailTarget.value?.status !== 'archived')
)

const activeBomVersionSummary = computed<BomCompareRow | null>(() => {
  return (
    detailPresentation.value?.bomCompareRows.find((item) => item.versionNo === detailBomVersion.value) ||
    null
  )
})

const processDetailRows = computed<ProductProcessDetailRow[]>(() =>
  (detailPresentation.value?.processRoutes || []).map((row) => ({
    sequenceNo: row.sequenceNo,
    processCode: row.processCode,
    processName: row.processName,
    processType: row.processType,
    workstationName: row.workstationName,
    supplierName: row.supplierName,
    confirmerName: getProcessConfirmerName(row),
    confirmerRole: getProcessConfirmerRole(row),
    processParamSummary: row.summary || row.inventoryName || '--',
    qualityRequirement: row.qualityRequirement || '--',
    unitProcessCost: getProcessCost(row),
    tags: getProcessTags(row)
  }))
)

const filteredProcessDetailRows = computed(() => {
  const keyword = processDetailKeyword.value.trim().toLowerCase()
  return processDetailRows.value.filter((row) => {
    const filterMatched =
      processDetailFilter.value === 'all' ||
      row.tags.includes(processDetailFilter.value === 'key' ? 'key' : 'changed')
    const keywordMatched =
      !keyword ||
      row.processCode.toLowerCase().includes(keyword) ||
      row.processName.toLowerCase().includes(keyword) ||
      String(row.workstationName || '').toLowerCase().includes(keyword) ||
      String(row.supplierName || '').toLowerCase().includes(keyword)
    return filterMatched && keywordMatched
  })
})

const productionDocuments = computed(() =>
  (detailPresentation.value?.documents || []).filter((item) => item.stageKey === 'production' || item.category === '生产资料')
)

const detailDocumentStats = computed(() => {
  const documents = detailPresentation.value?.documents || []
  return {
    total: documents.length,
    production: productionDocuments.value.length,
    frozen: documents.filter((item) => item.status === '已冻结' || item.status === '已归档').length
  }
})

function getProjectTypeLabel(row: ProductSummary) {
  if (row.productType === 'product_line') return '新产品线'
  if (row.productType === 'sku') return 'SKU'
  return '新型号线'
}

function getMoldActionLabel(row: ProductSummary) {
  if (row.productType === 'product_line') return '完整开模链路'
  if (row.moldAction === 'modify') return '改模'
  if (row.moldAction === 'new') return '新开模'
  if (row.moldAction === 'none') return '无需模具变更'
  return '待判断'
}

function getNextGate(row: ProductSummary) {
  return row.gateSummary || (row.productType === 'product_line' ? '关注签样、小批量和 MX 关口。' : '关注差异验证、版本冻结与子版本发布。')
}

function getRecentUpdate(row: ProductSummary) {
  return formatDate(row.releasedAt || undefined)
}

function getProjectTagType(tag: string) {
  if (tag === '进行中') return 'warning'
  if (tag === '已停止') return 'danger'
  if (tag.includes('SKU')) return 'success'
  return 'info'
}

function getSkuCountForProduct(product: ProductSummary) {
  const productLineCode = getDisplayProductLineCode(product)
  return archivedSkuRows.value.filter(
    (item) =>
      item.parentProductId === product.productId ||
      item.productCode.startsWith(product.productCode) ||
      Boolean(item.finishedProductCode?.startsWith(product.productCode)) ||
      item.productCode.startsWith(productLineCode) ||
      Boolean(item.finishedProductCode?.startsWith(productLineCode))
  ).length
}

function getDisplayProductLineCode(product: ProductSummary) {
  const productCode = product.productCode || ''
  if (product.productType !== 'product_line' || !productCode.startsWith('PRD-')) {
    return productCode
  }
  const productSpecificCode = product.productSpecificCode?.trim().toUpperCase()
  return productSpecificCode ? `N${productSpecificCode}4030` : productCode
}

function getDisplaySkuCode(product: ProductSummary) {
  return product.finishedProductCode || product.productCode || ''
}

function getDetailDisplayCode(product: ProductSummary) {
  if (product.productType === 'sku') return getDisplaySkuCode(product)
  if (product.productType === 'product_line') return getDisplayProductLineCode(product)
  return product.productCode
}

function getColorUsageLabel(color: { colorCode?: string | null; colorName: string }) {
  return color.colorCode ? `${color.colorCode} ${color.colorName}` : color.colorName
}

function selectTimelineNode(node: ProjectTimelineNode) {
  selectedTimelineNode.value = selectedTimelineNode.value?.nodeKey === node.nodeKey ? null : node
}

function selectProjectQuickTag(tag: ProjectQuickTag) {
  selectedTimelineNode.value = null
  if (tag === 'all_projects') {
    router.push({ path: '/projects', query: { tab: 'all_projects' } })
    return
  }
  if (tag === 'in_progress') {
    router.push({ path: '/projects', query: { tab: 'in_progress' } })
    return
  }
  if (tag === 'archived_product') {
    router.push({ path: '/projects', query: { tab: 'archived', archiveView: 'product' } })
    return
  }
  if (tag === 'archived_sku') {
    router.push({ path: '/projects', query: { tab: 'archived', archiveView: 'sku' } })
    return
  }
  router.push({ path: '/projects', query: { tab: 'abandoned' } })
}

function selectFlow(value: ProjectFlowFilter) {
  activeFlow.value = value
  selectedTimelineNode.value = null
}

function isProductSummary(row: ProductSummary | AllProjectRow): row is ProductSummary {
  return 'productType' in row
}

function openProjectOverview(row: ProductSummary | AllProjectRow) {
  if (isProductSummary(row)) {
    overviewProject.value = {
      productId: row.productId,
      productCode: row.productCode,
      productName: row.productName,
      projectType: row.productType === 'product_line' ? '产品' : 'SKU',
    projectTag: isAbandonedProject(row) ? '已停止' : ['released', 'archived'].includes(row.status) ? '已归档' : '进行中',
      currentStage: row.currentStage,
      ownerUserName: row.ownerUserName,
      versionNo: row.versionNo,
      updatedAt: row.abandonedAt || row.releasedAt || '',
      sourceStatus: row.status,
      abandoned: isAbandonedProject(row),
      source: row
    }
  } else {
    overviewProject.value = row
  }
  overviewVisible.value = true
}

function openProduct(productId: number) {
  const target = rows.value.find((item) => item.productId === productId)
  if (target) {
    openDetail(target)
    return
  }
  router.push(toArchivedProductRoute(productId))
}

function openArchiveImport(type: 'product' | 'sku') {
  importType.value = type
  resetArchiveImportState()
  importVisible.value = true
}

function resetArchiveImportState() {
  archiveImportFile.value = null
  archiveImportInputKey.value += 1
  archiveImportPreview.value = null
  archiveImportLoading.value = false
}

function closeArchiveImport() {
  importVisible.value = false
  resetArchiveImportState()
}

function handleArchiveImportFileChange(event: Event) {
  archiveImportFile.value = (event.target as HTMLInputElement).files?.[0] || null
  archiveImportPreview.value = null
}

async function submitArchiveImport() {
  if (!archiveImportFile.value) {
    ElMessage.warning('请先选择要导入的数据文件')
    return
  }

  archiveImportLoading.value = true
  try {
    const preview = await previewImport('product', archiveImportFile.value)
    archiveImportPreview.value = preview

    if (preview.failCount > 0) {
      ElMessage.warning(`导入预览发现 ${preview.failCount} 条异常，请修正文件后重新导入`)
      return
    }

    const result = await commitImport(preview.importToken)
    archiveImportPreview.value = result
    if (result.failCount > 0) {
      ElMessage.warning(`导入完成，成功 ${result.successCount} 条，失败 ${result.failCount} 条`)
    } else {
      ElMessage.success(`导入成功，共导入 ${result.successCount} 条数据`)
      closeArchiveImport()
    }
    await loadData()
  } catch (error) {
    ElMessage.error(getErrorMessage(error))
  } finally {
    archiveImportLoading.value = false
  }
}

function skuOpenSkuList(productId: number) {
  skuActiveProductId.value = productId
  skuKeyword.value = ''
  skuPageStage.value = 'sku-list'
}

function skuBackToProductHome() {
  skuActiveProductId.value = null
  skuKeyword.value = ''
  skuPageStage.value = 'product-home'
}

function getTimelineActionLabel(action?: string | null) {
  if (action === 'confirm') return '已确认当前节点'
  if (action === 'advance') return '已推进到下一节点'
  if (action === 'return') return '已退回处理'
  return '暂无动作'
}

function getErrorMessage(error: unknown) {
  if (typeof error === 'object' && error && 'response' in error) {
    const response = (error as { response?: { data?: { message?: string } } }).response
    if (response?.data?.message) return response.data.message
  }
  if (error instanceof Error) return error.message
  return '操作失败，请稍后重试'
}

function mapTimelineToPresentationNodes(timeline: TimelineDetailVO): TimelinePresentationNode[] {
  return mapTimelineSteps(timeline).map((step) => ({
    nodeKey: step.nodeKey,
    nodeName: step.stepName,
    status: step.status,
    ownerRole: step.source.ownerRole,
    summary: step.source.summary,
    nextAction: step.source.nextAction,
    riskNote: step.source.riskNote,
    gateLabel: step.source.gateLabel,
    detailLines: step.source.detailLines,
    receiverRole: step.source.receiverRole,
    receiverUserName: step.source.receiverUserName,
    receivedAt: step.source.receivedAt,
    promoterRole: step.source.promoterRole,
    promoterUserName: step.source.promoterUserName,
    promotedAt: step.source.promotedAt,
    experienceSummary: step.source.experienceSummary,
    documentCount: step.documentCount,
    phaseName: step.phaseName,
    stageCode: step.stageCode,
    stageName: step.stageName,
    requiredFileCategory: step.requiredFileCategory,
    confirmed: step.confirmed,
    canAdvance: step.status === 'current' && step.confirmed,
    canReject: step.status === 'current'
  }))
}

function mapTimelineStageToProductFlowStage(stage: TimelineStageView): ProductFlowStage {
  const current = stage.steps.find((step) => step.isCurrent)
    || stage.steps.find((step) => step.status === 'rejected')
    || stage.steps[stage.steps.length - 1]
  return {
    stageKey: stage.stageCode,
    stageName: stage.stageName,
    phaseName: stage.phaseName,
    status: stage.status,
    summary: current?.source.experienceSummary || current?.source.summary || stage.stageName,
    receiverRole: current?.source.receiverRole,
    receiverUserName: current?.source.receiverUserName,
    receivedAt: current?.source.receivedAt,
    promoterRole: current?.source.promoterRole || current?.source.ownerRole,
    promoterUserName: current?.source.promoterUserName,
    promotedAt: current?.source.promotedAt,
    nextAction: current?.source.nextAction || (stage.status === 'completed' ? '已完成' : '待推进'),
    riskNote: current?.source.riskNote,
    childNodes: stage.steps.map((step) => ({
      stepNo: step.stepNo,
      nodeKey: step.nodeKey,
      nodeCode: step.nodeKey,
      nodeName: step.stepName,
      status: step.status,
      actionLabel: step.source.nextAction,
      documentCount: step.documentCount,
      visualStatus: step.visualStatus,
      processConfirmation: isProcessConfirmationNode({
        nodeKey: step.nodeKey,
        nodeCode: step.nodeKey,
        nodeName: step.stepName
      })
    }))
  }
}

function applyTimelineMetadata(timeline: TimelineDetailVO) {
  timelineStarted.value = timeline.started
  timelineStartBlockReason.value = timeline.startBlockReason || null
  timelineCompleted.value = Boolean(timeline.timelineCompleted)
  timelineCurrentConfirmed.value = timeline.currentConfirmed ?? null
  timelineLastAction.value = timeline.lastAction || null
  timelineLastReason.value = timeline.lastReason || null
  timelineLastOperatedAt.value = timeline.lastOperatedAt || null
  timelineLastOperatorUserName.value = timeline.lastOperatorUserName || null
  applyMoldTransferExpress(timeline.moldTransferExpress || null)
}

function applyMoldTransferExpress(express: MoldTransferExpressVO | null) {
  moldTransferExpress.value = express
  moldTransferForm.trackingNo = express?.trackingNo || ''
  moldTransferForm.shippedAt = express?.shippedAt || ''
}

function buildPresentationFallback(row: ProductSummary): ProductDetailPresentation {
  return {
    productId: row.productId,
    title: row.productName,
    flowLabel: row.productType === 'model_variant' ? '新型号线' : '新产品线',
    currentNode: row.currentStage || '--',
    nextNode: row.nextAction || '--',
    summary: `${row.productCode} / ${row.seriesName || '--'}`,
    costPanel: { showEstimated: false, actualTotal: 0, actualLines: [] },
    timeline: [],
    bomCompareRows: [],
    bomItems: [],
    bomItemsByVersion: {},
    toolingSummary: { totalCount: 0, availableCount: 0, trialCount: 0, toolingNames: [] },
    materialCategories: [],
    suppliers: [],
    documents: [],
    qualityRecords: [],
    processRoutes: []
  }
}

async function refreshProjectTimeline(projectId: number) {
  if (!detailPresentation.value) return
  const timeline = await getProjectTimeline(projectId)
  applyTimelineMetadata(timeline)
  const nodes = mapTimelineToPresentationNodes(timeline)
  const currentNode = nodes.find((node) => node.status === 'current')
  const displayNode = currentNode || (timeline.timelineCompleted ? nodes[nodes.length - 1] : null)
  const currentStep = findCurrentTimelineStep(timeline)
  timelineFlowStages.value = mapTimelineStages(timeline).map(mapTimelineStageToProductFlowStage)
  detailPresentation.value = {
    ...detailPresentation.value,
    currentNode: displayNode?.nodeName || timeline.currentNode || detailPresentation.value.currentNode,
    nextNode: displayNode?.nextAction || (timeline.timelineCompleted ? '已完成' : detailPresentation.value.nextNode),
    timeline: timeline.started === false ? [] : nodes.length ? nodes : detailPresentation.value.timeline
  }
  if (detailTarget.value) {
    detailTarget.value = {
      ...detailTarget.value,
      currentStage: displayNode?.nodeName || detailTarget.value.currentStage,
      currentStepNo: timeline.currentStepNo
    }
  }
  activeProductFlowStageKey.value = currentStep?.stageCode || displayNode?.stageCode || timelineFlowStages.value[0]?.stageKey || activeProductFlowStageKey.value
  activeSkuFlowStageKey.value = currentStep?.stageCode || displayNode?.stageCode || timelineFlowStages.value[0]?.stageKey || activeSkuFlowStageKey.value
}

async function handleM4AttachmentChanged() {
  if (!detailTarget.value) return
  await refreshProjectTimeline(detailTarget.value.productId)
}

async function refreshDetailAfterChildChange() {
  if (!detailTarget.value) return
  try {
    const projectDetail = await getProjectDetail(detailTarget.value.productId)
    detailTarget.value = { ...detailTarget.value, ...projectDetail }
    await loadData()
  } catch {
    // 子页面已完成保存，详情刷新失败时保留当前页面数据。
  }
}

async function handleLifecycleChanged() {
  if (!detailTarget.value) return
  await refreshProjectTimeline(detailTarget.value.productId)
  await loadData()
}

async function handleProductionConfirmationConfirmed() {
  if (!detailTarget.value) return
  const projectId = detailTarget.value.productId
  const shouldCompleteModelVariant = productionConfirmationMode.value === 'colors'
    && detailTarget.value.productType === 'model_variant'
    && activeProductFlowNode.value?.nodeKey === 'MODEL_VARIANT_MOLD_TRANSFER'
  try {
    if (shouldCompleteModelVariant) {
      timelineActionLoading.value = 'confirm'
      await confirmTimelineNode(projectId, 'MODEL_VARIANT_MOLD_TRANSFER', '投产颜色已确认，移交并创建 SKU')
      ElMessage.success('新型号已完成，正在移交钉钉审批')
    }
    await refreshDetailAfterChildChange()
    await refreshProjectTimeline(projectId)
  } catch (error) {
    ElMessage.error(shouldCompleteModelVariant
      ? `SKU 已创建，但最终节点确认失败：${getErrorMessage(error)}`
      : getErrorMessage(error))
  } finally {
    timelineActionLoading.value = false
  }
}

function applyDetailLifecycleResult(result: { status: ProductSummary['status']; lockStatus?: string | null; releasedAt?: string | null }) {
  if (!detailTarget.value) return
  detailTarget.value = {
    ...detailTarget.value,
    status: result.status,
    lockStatus: result.lockStatus ?? detailTarget.value.lockStatus,
    releasedAt: result.releasedAt ?? detailTarget.value.releasedAt
  }
}

async function handleDetailFreezeProject() {
  if (!detailTarget.value || detailLifecycleLoading.value || !canFreezeDetailProject.value) return
  try {
    await ElMessageBox.confirm('冻结会锁定当前 Product 资料状态，用于发布前版本留痕。', '冻结项目版本', {
      confirmButtonText: '冻结',
      cancelButtonText: '取消',
      type: 'warning'
    })
    detailLifecycleLoading.value = 'freeze'
    const result = await freezeProject(detailTarget.value.productId, { reason: '项目详情头部冻结' })
    applyDetailLifecycleResult(result)
    await handleLifecycleChanged()
    ElMessage.success('项目版本已冻结')
  } catch (error) {
    if (error !== 'cancel' && error !== 'close') ElMessage.error(getErrorMessage(error))
  } finally {
    detailLifecycleLoading.value = false
  }
}

async function handleDetailPublishProject() {
  if (!detailTarget.value || detailLifecycleLoading.value || !canPublishDetailProject.value) return
  try {
    const gate = await checkProjectReleaseGate(detailTarget.value.productId)
    const blocking = Boolean(gate.blocking || (!gate.passed && !gate.confirmRequired))
    if (blocking) {
      ElMessage.error('当前流程尚未满足发布条件，请先完成基础流程')
      return
    }
    await ElMessageBox.confirm(
      buildReleaseConfirmationMessage(gate),
      gate.confirmRequired ? '确认带风险发布' : '发布 Product',
      {
      confirmButtonText: '发布',
      cancelButtonText: '取消',
      type: 'warning'
      }
    )
    detailLifecycleLoading.value = 'publish'
    const result = await publishProject(detailTarget.value.productId, {
      reason: '项目详情头部发布',
      riskConfirmed: Boolean(gate.confirmRequired)
    })
    applyDetailLifecycleResult(result)
    await handleLifecycleChanged()
    ElMessage.success('Product 已发布')
  } catch (error) {
    const gateFromError = getReleaseGateFromError(error)
    if (gateFromError) {
      ElMessage.error(
        getReleaseGateErrorCode(error) === 40308
          ? '检测到发布资料风险，请确认后重试'
          : '当前流程尚未满足发布条件'
      )
      return
    }
    if (error !== 'cancel' && error !== 'close') ElMessage.error(getErrorMessage(error))
  } finally {
    detailLifecycleLoading.value = false
  }
}

function getReleaseGateFromError(error: unknown): ProductReleaseGateCheckVO | null {
  const responseData = (error as { response?: { data?: { code?: number; data?: ProductReleaseGateCheckVO } } })
    ?.response?.data
  if ((responseData?.code === 40307 || responseData?.code === 40308) && responseData.data) return responseData.data
  return null
}

function getReleaseGateErrorCode(error: unknown) {
  return (error as { response?: { data?: { code?: number } } })?.response?.data?.code
}

function buildReleaseConfirmationMessage(gate: ProductReleaseGateCheckVO) {
  const risks = (gate.missingItems || [])
    .filter((item) => item.severity === 'warning' || !item.severity)
    .map((item) => `• ${item.message}`)
    .join('\n')
  if (!risks) return '发布后 Product 将进入 released 状态，已发布版本不允许直接编辑。'
  return `当前产品存在资料缺口，发布后仍会进入 released 状态：\n${risks}\n\n确认继续发布？`
}

async function handleDetailArchiveProject() {
  if (!detailTarget.value || detailLifecycleLoading.value || !canArchiveDetailProject.value) return
  try {
    const { value } = await ElMessageBox.prompt('请输入归档原因，便于后续追溯。', '归档项目', {
      confirmButtonText: '归档',
      cancelButtonText: '取消',
      inputPlaceholder: '例如：发布版本停用，进入历史归档'
    })
    detailLifecycleLoading.value = 'archive'
    const result = await archiveProject(detailTarget.value.productId, { reason: String(value || '').trim() || '项目详情头部归档' })
    applyDetailLifecycleResult(result)
    await handleLifecycleChanged()
    ElMessage.success('项目已归档')
  } catch (error) {
    if (error !== 'cancel' && error !== 'close') ElMessage.error(getErrorMessage(error))
  } finally {
    detailLifecycleLoading.value = false
  }
}

async function handleDetailStopProject() {
  if (!detailTarget.value || detailLifecycleLoading.value || !canStopDetailProject.value) return
  try {
    const { value } = await ElMessageBox.prompt('请输入停止原因。停止后项目会进入已停止/归档，并同步关闭关联 Order。', '停止项目', {
      confirmButtonText: '确认停止',
      cancelButtonText: '取消',
      inputPlaceholder: '例如：客户取消需求，项目停止推进',
      inputValidator: (value) => Boolean(String(value || '').trim()) || '请填写停止原因'
    })
    detailLifecycleLoading.value = 'abandon'
    const result = await abandonProject(detailTarget.value.productId, { reason: String(value || '').trim() })
    applyDetailLifecycleResult(result)
    await handleLifecycleChanged()
    ElMessage.success('项目已停止并归档')
  } catch (error) {
    if (error !== 'cancel' && error !== 'close') ElMessage.error(getErrorMessage(error))
  } finally {
    detailLifecycleLoading.value = false
  }
}

async function saveCurrentMoldTransferExpress() {
  if (!detailTarget.value || !activeProductFlowNode.value) return
  if (!moldTransferForm.trackingNo.trim()) {
    ElMessage.warning('请填写快递单号')
    return
  }
  moldTransferLoading.value = true
  try {
    const saved = await saveMoldTransferExpress(detailTarget.value.productId, activeProductFlowNode.value.nodeKey, {
      trackingNo: moldTransferForm.trackingNo.trim(),
      shippedAt: moldTransferForm.shippedAt || undefined
    })
    applyMoldTransferExpress(saved)
    await refreshProjectTimeline(detailTarget.value.productId)
    ElMessage.success('运模快递单号已保存')
  } catch (error) {
    ElMessage.error(getErrorMessage(error))
  } finally {
    moldTransferLoading.value = false
  }
}

async function handleConfirmCurrentNode() {
  if (!detailTarget.value || !activeProductFlowNode.value || timelineActionLoading.value) return
  try {
    const { value } = await ElMessageBox.prompt('可填写确认备注，留空则只确认当前节点。', '确认当前节点', {
      confirmButtonText: '确认',
      cancelButtonText: '取消',
      inputPlaceholder: '例如：资料已检查，进入可推进状态'
    })
    timelineActionLoading.value = 'confirm'
    await confirmTimelineNode(detailTarget.value.productId, activeProductFlowNode.value.nodeKey, String(value || ''))
    await refreshProjectTimeline(detailTarget.value.productId)
    await loadData()
    ElMessage.success('节点已确认')
  } catch (error) {
    if (error !== 'cancel' && error !== 'close') ElMessage.error(getErrorMessage(error))
  } finally {
    timelineActionLoading.value = false
  }
}

async function handleAdvanceCurrentNode() {
  if (!detailTarget.value || !activeProductFlowNode.value || timelineActionLoading.value) return
  if (!canAdvanceCurrentTimelineNode.value) {
    ElMessage.warning(currentTimelineConfirmed.value ? '最后一个节点不能继续推进' : '请先确认当前节点')
    return
  }
  try {
    await ElMessageBox.confirm('推进后项目会进入下一节点，新节点会回到未确认状态。', '推进下一节点', {
      confirmButtonText: '推进',
      cancelButtonText: '取消',
      type: 'warning'
    })
    timelineActionLoading.value = 'confirm'
    await confirmTimelineNode(detailTarget.value.productId, activeProductFlowNode.value.nodeKey)
    await refreshProjectTimeline(detailTarget.value.productId)
    await loadData()
    ElMessage.success('已推进到下一节点')
  } catch (error) {
    if (error !== 'cancel' && error !== 'close') ElMessage.error(getErrorMessage(error))
  } finally {
    timelineActionLoading.value = false
  }
}

async function handleReturnCurrentNode(returnToPrevious: boolean) {
  if (!detailTarget.value || !activeProductFlowNode.value || timelineActionLoading.value) return
  try {
    const { value } = await ElMessageBox.prompt(
      returnToPrevious ? '请输入退回上一节点的原因。' : '请输入退回当前节点修改的原因。',
      returnToPrevious ? '退回上一节点' : '退回当前节点修改',
      {
        confirmButtonText: '退回',
        cancelButtonText: '取消',
        inputPlaceholder: '必须填写，例如：图纸资料需补充',
        inputValidator: (value) => Boolean(String(value || '').trim()),
        inputErrorMessage: '请填写退回原因'
      }
    )
    timelineActionLoading.value = 'return'
    await returnTimelineNode(
      detailTarget.value.productId,
      activeProductFlowNode.value.nodeKey,
      String(value || ''),
      returnToPrevious
    )
    await refreshProjectTimeline(detailTarget.value.productId)
    await loadData()
    ElMessage.success('已退回处理')
  } catch (error) {
    if (error !== 'cancel' && error !== 'close') ElMessage.error(getErrorMessage(error))
  } finally {
    timelineActionLoading.value = false
  }
}

function handleReturnCommand(command: string | number | object) {
  handleReturnCurrentNode(command === 'previous')
}

async function openDetail(row: ProductSummary) {
  detailPresentation.value = null
  detailBomVersion.value = ''
  detailTarget.value = row
  basicInfoEditing.value = false
  basicInfoExtra.value = null
  applyBasicInfoToForm(buildBasicInfoFromTarget())
  const routeSection = String(route.query.section || '')
  activeDetailSection.value = activeDetailSections.value.some((section) => section.key === routeSection)
    ? (routeSection as DetailSectionKey)
    : 'project_flow'
  activeProductFlowStageKey.value = ''
  activeSkuFlowStageKey.value = ''
  processDetailFilter.value = 'all'
  processDetailKeyword.value = ''
  timelineCurrentConfirmed.value = null
  timelineStarted.value = null
  timelineStartBlockReason.value = null
  timelineCompleted.value = false
  timelineLastAction.value = null
  timelineLastReason.value = null
  timelineLastOperatedAt.value = null
  timelineLastOperatorUserName.value = null
  timelineFlowStages.value = null
  detailVisible.value = true
  detailLoading.value = true
  try {
    try {
      const projectDetail = await getProjectDetail(row.productId)
      detailTarget.value = { ...row, ...projectDetail }
      normalizeProjectDetailRoute(detailTarget.value)
    } catch {
      detailTarget.value = row
      normalizeProjectDetailRoute(detailTarget.value)
    }
    let presentation = buildPresentationFallback(row)
    try {
      presentation = await getProductPresentation(row.productId)
    } catch {
      presentation = buildPresentationFallback(row)
    }
    detailPresentation.value = presentation
    const timeline = await getProjectTimeline(row.productId)
    applyTimelineMetadata(timeline)
    const nodes = mapTimelineToPresentationNodes(timeline)
    const currentNode = nodes.find((node) => node.status === 'current')
    const displayNode = currentNode || (timeline.timelineCompleted ? nodes[nodes.length - 1] : null)
    const currentStep = findCurrentTimelineStep(timeline)
    timelineFlowStages.value = mapTimelineStages(timeline).map(mapTimelineStageToProductFlowStage)
    detailPresentation.value = {
      ...presentation,
      currentNode: displayNode?.nodeName || timeline.currentNode || presentation.currentNode,
      nextNode: displayNode?.nextAction || (timeline.timelineCompleted ? '已完成' : presentation.nextNode),
      timeline: timeline.started === false ? [] : nodes.length ? nodes : presentation.timeline
    }
    activeProductFlowStageKey.value = currentStep?.stageCode || displayNode?.stageCode || timelineFlowStages.value[0]?.stageKey || ''
    activeSkuFlowStageKey.value = currentStep?.stageCode || displayNode?.stageCode || timelineFlowStages.value[0]?.stageKey || ''
    detailBomVersion.value =
      detailPresentation.value.defaultBomVersion ||
      detailPresentation.value.bomCompareRows.find((item) => item.statusLabel === '当前')?.versionNo ||
      detailPresentation.value.bomCompareRows[0]?.versionNo ||
      ''
  } catch {
    detailPresentation.value = null
    detailBomVersion.value = ''
  } finally {
    detailLoading.value = false
  }
}

function openDetailEdit() {
  if (!detailTarget.value || !canEditDetailTarget.value) return
  activeDetailSection.value = 'project_flow'
  basicInfoEditing.value = true
  void loadBasicInfoForEdit()
}

function getBomRemark(row: ProductBomItemRow) {
  if (row.changeType === 'new') return '新增物料'
  if (row.changeType === 'replace') return '替代料'
  if (row.changeType === 'remove') return '本版本移除'
  if (row.changeType === 'inherit') return '沿用父产品'
  return '--'
}

function getBomLineCost(row: ProductBomItemRow) {
  return Number(row.unitCost || 0) * Number(row.quantity || 0)
}

function getDocumentStatusType(status?: string) {
  if (status === '已冻结' || status === '已归档') return 'success'
  if (status === '草稿') return 'warning'
  return 'info'
}

function getFlowStatusLabel(status: ProductFlowStageStatus) {
  if (status === 'completed') return '已完成'
  if (status === 'current') return '进行中'
  if (status === 'rejected') return '已驳回'
  return '待开始'
}

function getFlowStatusType(status: ProductFlowStageStatus) {
  if (status === 'completed') return 'success'
  if (status === 'current') return 'warning'
  if (status === 'rejected') return 'danger'
  return 'info'
}

function getProcessTypeLabel(type: string) {
  if (type === 'quality_gate') return '质量门禁'
  if (type === 'packaging') return '包装'
  if (type === 'outsourced') return '外协'
  return '工序'
}

function getProcessConfirmerName(row: SkuProcessRouteRow) {
  if (row.processType === 'quality_gate') return '王质'
  if (row.supplierName) return '李采'
  if (row.processName.includes('包装')) return '陈包'
  return '刘浩'
}

function applyBasicInfoToForm(info: Partial<ProductBasicInfo>) {
  basicInfoForm.productName = info.productName || ''
  basicInfoForm.seriesName = info.seriesName || ''
  basicInfoForm.ownerUserName = info.ownerUserName || detailTarget.value?.ownerUserName || 'system'
  basicInfoForm.model = info.model || ''
  basicInfoForm.color = info.color || ''
  basicInfoForm.material = info.material || ''
  basicInfoForm.packageType = info.packageType || ''
  basicInfoForm.surfaceProcess = info.surfaceProcess || ''
  basicInfoForm.coreProcess = info.coreProcess || ''
  basicInfoForm.composition = info.composition || ''
  basicInfoForm.expectedReleaseDate = info.expectedReleaseDate || ''
  basicInfoForm.expectedArrivalAt = info.expectedArrivalAt || ''
  basicInfoForm.actualArrivalAt = info.actualArrivalAt || ''
  basicInfoForm.networkType = info.networkType || ''
  basicInfoForm.holeType = info.holeType || ''
  basicInfoForm.mobileFunction = info.mobileFunction || ''
  basicInfoForm.tipo = info.tipo || ''
  basicInfoForm.priority = info.priority || ''
  basicInfoForm.manufacturingLocation = info.manufacturingLocation || ''
  basicInfoForm.moldMarking = info.moldMarking || ''
  basicInfoForm.referenceUrl = info.referenceUrl || ''
  basicInfoForm.requirementType = info.requirementType || ''
  basicInfoForm.customerRequirement = info.customerRequirement || ''
}

function buildBasicInfoFromTarget(): Partial<ProductBasicInfo> {
  const target = detailTarget.value
  if (!target) return {}
  return {
    productName: target.productName,
    seriesName: target.seriesName,
    ownerUserName: target.ownerUserName,
    model: target.model,
    color: target.color,
    material: target.material,
    expectedArrivalAt: target.expectedArrivalAt || null,
    actualArrivalAt: target.actualArrivalAt || null
  }
}

async function loadBasicInfoForEdit() {
  if (!detailTarget.value) return
  const fallback = buildBasicInfoFromTarget()
  applyBasicInfoToForm({ ...fallback, ...(basicInfoExtra.value || {}) })
  try {
    const detail = await getProductBasicDetail(detailTarget.value.productId)
    basicInfoExtra.value = detail.basicInfo
    applyBasicInfoToForm({ ...fallback, ...detail.basicInfo })
  } catch {
    // 项目详情已有基础字段，完整 Product 详情暂时不可用时仍允许编辑当前可见信息。
  }
}

function applySavedBasicInfo(info: ProductBasicInfo) {
  basicInfoExtra.value = info
  if (!detailTarget.value) return
  detailTarget.value = {
    ...detailTarget.value,
    productName: info.productName || detailTarget.value.productName,
    seriesName: info.seriesName || detailTarget.value.seriesName,
    model: info.model || detailTarget.value.model,
    color: info.color || detailTarget.value.color,
    material: info.material || detailTarget.value.material,
    expectedArrivalAt: info.expectedArrivalAt || detailTarget.value.expectedArrivalAt,
    actualArrivalAt: info.actualArrivalAt || detailTarget.value.actualArrivalAt
  }
}

async function saveBasicInfo() {
  if (!detailTarget.value || basicInfoSaving.value) return
  if (!basicInfoForm.productName.trim()) {
    ElMessage.warning(`${detailObjectLabel.value}名称不能为空`)
    return
  }
  basicInfoSaving.value = true
  try {
    const saved = await updateProductBasicInfo(detailTarget.value.productId, {
      productName: basicInfoForm.productName,
      seriesName: basicInfoForm.seriesName,
      ownerUserName: basicInfoForm.ownerUserName || detailTarget.value.ownerUserName || 'system',
      model: basicInfoForm.model,
      color: basicInfoForm.color,
      material: basicInfoForm.material,
      packageType: basicInfoForm.packageType,
      surfaceProcess: basicInfoForm.surfaceProcess,
      coreProcess: basicInfoForm.coreProcess,
      composition: basicInfoForm.composition,
      expectedReleaseDate: basicInfoForm.expectedReleaseDate,
      expectedArrivalAt: basicInfoForm.expectedArrivalAt || null,
      actualArrivalAt: basicInfoForm.actualArrivalAt || null,
      networkType: basicInfoForm.networkType,
      holeType: basicInfoForm.holeType,
      mobileFunction: basicInfoForm.mobileFunction,
      tipo: basicInfoForm.tipo,
      priority: basicInfoForm.priority,
      manufacturingLocation: basicInfoForm.manufacturingLocation,
      moldMarking: basicInfoForm.moldMarking,
      referenceUrl: basicInfoForm.referenceUrl,
      requirementType: basicInfoForm.requirementType,
      customerRequirement: basicInfoForm.customerRequirement
    })
    applySavedBasicInfo(saved.basicInfo)
    basicInfoEditing.value = false
    await refreshDetailAfterChildChange()
    applySavedBasicInfo(saved.basicInfo)
    ElMessage.success('基础信息已保存')
  } catch (error) {
    ElMessage.error(getErrorMessage(error))
  } finally {
    basicInfoSaving.value = false
  }
}

function cancelBasicInfoEdit() {
  basicInfoEditing.value = false
  applyBasicInfoToForm({ ...buildBasicInfoFromTarget(), ...(basicInfoExtra.value || {}) })
}

function getProcessConfirmerRole(row: SkuProcessRouteRow) {
  if (row.processType === 'quality_gate') return '品质确认'
  if (row.supplierName) return '采购确认'
  if (row.processName.includes('包装')) return '包装确认'
  return '工程确认'
}

function getProcessCost(row: SkuProcessRouteRow) {
  if (row.processType === 'quality_gate') return 0.4
  if (row.processName.includes('包装')) return 0.3
  if (row.processName.includes('喷') || row.processName.includes('表面')) return 1.2
  if (row.supplierName) return 1.6
  return 0.8
}

function getProcessTags(row: SkuProcessRouteRow): ProductProcessDetailTag[] {
  const tags: ProductProcessDetailTag[] = []
  if (row.processType === 'quality_gate' || row.processName.includes('磁铁') || row.processName.includes('镜面')) tags.push('key')
  if (row.processName.includes('改') || row.processName.includes('黑色') || row.processName.includes('表面')) tags.push('changed')
  if (row.supplierName) tags.push('outsourced')
  return tags
}

function openProductionDocPreview(file: { fileId?: string; fileName: string; category: string; versionNo: string; owner?: string; updatedAt: string; status?: string; previewUrl?: string; downloadUrl?: string }) {
  activeProductionDoc.value = {
    fileId: file.fileId || '',
    fileName: file.fileName,
    category: file.category,
    versionNo: file.versionNo,
    owner: file.owner,
    updatedAt: file.updatedAt,
    status: file.status,
    previewUrl: file.previewUrl,
    downloadUrl: file.downloadUrl
  }
  productionPreviewVisible.value = true
}

function syncTabFromRoute() {
  const routeTab = String(route.query.tab || 'in_progress')
  activeTab.value = ['all_projects', 'in_progress', 'archived', 'abandoned'].includes(routeTab)
    ? (routeTab as ProjectTab)
    : 'in_progress'
}

async function loadData() {
  loading.value = true
  try {
    const archivedProductParams = { page: 1, size: 200, status: 'archived', productType: 'product_line' }
    const releasedProductParams = { page: 1, size: 200, status: 'released', productType: 'product_line' }
    const archivedSkuParams = { page: 1, size: 200, status: 'archived', productType: 'model_variant' }
    const results = await Promise.allSettled([
      getProjects({ page: 1, size: 200 }),
      getProjects({ page: 1, size: 200, status: 'released' }),
      getProjects({ page: 1, size: 200, status: 'archived' }),
      loadAllProjectPages(releasedProductParams),
      loadAllProjectPages(archivedProductParams),
      loadAllProjectPages(archivedSkuParams)
    ])
    const mergedRows = new Map<number, ProductSummary>()
    results.forEach((result) => {
      if (result.status === 'fulfilled' && Array.isArray(result.value)) {
        result.value.forEach((item) => mergedRows.set(item.productId, item))
      }
    })
    rows.value = Array.from(mergedRows.values())
  } finally {
    loading.value = false
  }
}

async function loadAllProjectPages(params: { page: number; size: number; status?: string; productType?: string }) {
  const size = params.size
  const values: ProductSummary[] = []
  for (let page = params.page; page <= 30; page += 1) {
    const pageRows = await getProjects({ ...params, page, size })
    if (!Array.isArray(pageRows) || pageRows.length === 0) break
    values.push(...pageRows)
    if (pageRows.length < size) break
  }
  return values
}

watch(() => route.query.tab, syncTabFromRoute, { immediate: true })

watch(activeFlow, () => {
  selectedTimelineNode.value = null
})

watch(
  () => route.query.archiveView,
  () => {
    skuPageStage.value = 'product-home'
    skuActiveProductId.value = null
  }
)

watch(
  () => [route.query.archiveView, route.query.productId, route.query.skuId, route.query.section, rows.value.length],
  async () => {
    const productId = Number(route.query.productId || 0)
    if (productId) {
      const target = (archiveView.value === 'product' ? archivedProductRows.value : rows.value).find((item) => item.productId === productId)
        || rows.value.find((item) => item.productId === productId)
      if (target) {
        openDetail(target)
      } else if (!routeDetailLoading.value && detailTarget.value?.productId !== productId) {
        routeDetailLoading.value = true
        try {
          const detail = await getProjectDetail(productId)
          normalizeProjectDetailRoute(detail)
          openDetail(detail)
        } catch (error) {
          ElMessage.error(getErrorMessage(error))
        } finally {
          routeDetailLoading.value = false
        }
      }
      return
    }

    const skuId = Number(route.query.skuId || 0)
    if (skuId && archiveView.value === 'sku') {
      const target = archivedSkuRows.value.find((item) => item.productId === skuId) || rows.value.find((item) => item.productId === skuId)
      if (target) openDetail(target)
    }
  },
  { immediate: true }
)

onMounted(loadData)
</script>

<template>
  <PageContainer
    title="项目管理"
    description="项目管理以 Product 作为承载对象，按全部项目、进行中、已归档和已停止组织。"
  >
    <section class="project-filter-bar" aria-label="项目筛选">
      <nav class="project-tag-bar" aria-label="项目视图">
        <button
          v-for="tag in projectQuickTags"
          :key="tag.value"
          class="project-tag-bar__item"
          :class="{ 'is-active': projectQuickTag === tag.value }"
          type="button"
          @click="selectProjectQuickTag(tag.value)"
        >
          {{ tag.label }}
        </button>
      </nav>
      <el-input v-model="keyword" clearable class="project-filter-search" placeholder="搜索项目编码 / 名称 / 系列 / 负责人" />
    </section>

    <section class="project-module-panel">
      <header class="project-module-panel__header">
        <div>
          <div class="project-current-heading">
            <strong>{{ currentModuleTitle }}</strong>
            <span class="project-current-count">{{ currentModuleCount }} 个</span>
          </div>
          <p class="project-module-panel__desc">{{ currentModuleDescription }}</p>
        </div>
        <div class="project-module-panel__actions">
          <el-button v-if="projectQuickTag === 'archived_product'" type="primary" @click="openArchiveImport('product')">导入数据</el-button>
          <el-button v-if="projectQuickTag === 'archived_sku'" type="primary" @click="openArchiveImport('sku')">导入数据</el-button>
        </div>
      </header>

      <div class="project-module-panel__body">
        <template v-if="activeTab === 'all_projects'">
          <section class="project-list-shell" v-loading="loading">
            <FixedTableViewport v-slot="{ tableHeight }" :refresh-key="allProjectRows">
            <el-table :data="allProjectRows" :height="tableHeight" border stripe>
              <el-table-column label="概览" width="88" fixed="left">
                <template #default="{ row }">
                  <el-button link type="primary" @click.stop="openProjectOverview(row)">概览</el-button>
                </template>
              </el-table-column>
              <el-table-column prop="productCode" label="项目编码" min-width="170" />
              <el-table-column prop="productName" label="项目名称" min-width="220" />
              <el-table-column prop="projectType" label="类型" width="110" />
              <el-table-column label="标签" width="150">
                <template #default="{ row }">
                  <el-tag :type="getProjectTagType(row.projectTag)" effect="light">{{ row.projectTag }}</el-tag>
                </template>
              </el-table-column>
              <el-table-column prop="currentStage" label="当前阶段" min-width="170" />
              <el-table-column prop="ownerUserName" label="负责人" width="110" />
              <el-table-column prop="versionNo" label="版本" width="100" />
              <el-table-column label="最近更新时间" width="140">
                <template #default="{ row }">{{ formatDate(row.updatedAt) }}</template>
              </el-table-column>
            </el-table>
            </FixedTableViewport>
          </section>
        </template>

        <template v-else-if="activeTab === 'in_progress'">
          <section class="flow-filter-bar" aria-label="进行中项目类型">
            <button
              v-for="item in flowFilters"
              :key="item.value"
              class="flow-filter-bar__item"
              :class="{ 'is-active': activeFlow === item.value }"
              type="button"
              @click="selectFlow(item.value)"
            >
              {{ item.label }}
            </button>
          </section>

          <div v-if="activeFlow === 'all'" class="list-context-bar">
            <strong>全部进行中项目</strong>
            <span class="subtle-text">选择新产品线或新型号线后，会展示对应的重要节点时间轴。</span>
          </div>

          <template v-if="activeFlow !== 'all'">
            <section class="project-timeline-panel">
              <div class="toolbar-row">
                <h3 class="section-title">{{ activeFlow === 'product_line' ? '新产品线' : '新型号线' }}重要节点</h3>
              </div>
              <div class="timeline-row">
                <button
                  v-for="node in flowTimeline"
                  :key="node.nodeKey"
                  class="timeline-node"
                  :class="{
                    'is-selected': selectedTimelineNode?.nodeKey === node.nodeKey,
                    'is-gate': node.gate,
                    'is-empty': node.count === 0
                  }"
                  type="button"
                  @click="selectTimelineNode(node)"
                >
                  <strong>{{ node.title }}</strong>
                  <span class="timeline-node__phase">{{ node.phase }}</span>
                  <span class="timeline-node__hint">{{ node.hint }}</span>
                  <span class="timeline-node__children">包含：{{ node.childNodes.join('、') }}</span>
                  <span class="timeline-node__count">{{ node.count }} 个项目</span>
                </button>
              </div>
            </section>

            <div class="selected-node-bar" v-if="selectedTimelineNode">
              <strong>{{ selectedTimelineNode.title }} / 第 {{ selectedTimelineNode.childStepNos.join('、') }} 步</strong>
              <span class="subtle-text">当前在这个环节的项目：{{ timelineProjects.length }} 个</span>
            </div>
          </template>

          <section class="project-list-shell" v-loading="loading">
            <FixedTableViewport v-if="timelineProjects.length" v-slot="{ tableHeight }" :refresh-key="[activeFlow, selectedTimelineNode, timelineProjects]">
            <el-table :data="timelineProjects" :height="tableHeight" border stripe>
              <el-table-column prop="productCode" label="产品编码" min-width="170" />
              <el-table-column label="项目对象" min-width="240">
                <template #default="{ row }">
                  <div class="cell-stack">
                    <strong>{{ row.productName }}</strong>
                    <span class="subtle-text">{{ row.seriesName }} / {{ row.ownerUserName }}</span>
                  </div>
                </template>
              </el-table-column>
              <el-table-column label="流程类型" width="130">
                <template #default="{ row }">
                  <el-tag :type="row.productType === 'product_line' ? 'primary' : 'success'" effect="light">
                    {{ getProjectTypeLabel(row) }}
                  </el-tag>
                </template>
              </el-table-column>
              <el-table-column label="模具策略" width="140">
                <template #default="{ row }">{{ getMoldActionLabel(row) }}</template>
              </el-table-column>
              <el-table-column label="当前节点" min-width="180">
                <template #default="{ row }">
                  <div class="cell-stack">
                    <strong>第 {{ row.currentStepNo || '--' }} 步</strong>
                    <span class="subtle-text">{{ row.currentStage }}</span>
                  </div>
                </template>
              </el-table-column>
              <el-table-column label="下一关口" min-width="220">
                <template #default="{ row }">{{ getNextGate(row) }}</template>
              </el-table-column>
              <el-table-column label="状态" width="120">
                <template #default="{ row }"><StatusTag :status="row.status" object-type="product" /></template>
              </el-table-column>
              <el-table-column label="完成度" min-width="160">
                <template #default="{ row }">
                  <el-progress :percentage="Math.round(row.completionRate * 100)" :stroke-width="8" />
                </template>
              </el-table-column>
              <el-table-column label="操作" width="96" fixed="right">
                <template #default="{ row }">
                  <el-button link type="primary" @click.stop="openDetail(row)">详情</el-button>
                </template>
              </el-table-column>
            </el-table>
            </FixedTableViewport>
            <el-empty v-else description="暂无匹配的项目" />
          </section>
        </template>

        <template v-else-if="activeTab === 'archived'">
          <template v-if="archiveView === 'overview'">
            <div class="list-context-bar">
              <strong>已归档汇总</strong>
              <span class="subtle-text">通过顶部标签进入已归档产品或已归档 SKU 明细。</span>
            </div>
            <section class="metric-grid">
              <div class="metric-card"><p class="metric-card__label">已归档总数</p><p class="metric-card__value">{{ archiveSummary.total }}</p></div>
              <div class="metric-card"><p class="metric-card__label">产品</p><p class="metric-card__value">{{ archiveSummary.products }}</p></div>
              <div class="metric-card"><p class="metric-card__label">SKU</p><p class="metric-card__value">{{ archiveSummary.skus }}</p></div>
            </section>
          </template>

          <template v-else-if="archiveView === 'product'">
            <div class="list-context-bar">
              <strong>产品管理</strong>
              <span class="subtle-text">只展示已归档的新产品线产品，详情弹窗按 SKU 详情形式展示。</span>
              <el-button type="primary" @click="openArchiveImport('product')">导入数据</el-button>
            </div>
            <section class="project-list-shell" v-loading="loading">
              <FixedTableViewport v-slot="{ tableHeight }" :refresh-key="archivedProductRows">
              <el-table :data="archivedProductRows" :height="tableHeight" border stripe>
                <el-table-column prop="productCode" label="产品编码" min-width="180" />
                <el-table-column prop="productName" label="产品名称" min-width="220" />
                <el-table-column prop="seriesName" label="系列" width="140" />
                <el-table-column prop="ownerUserName" label="负责人" width="110" />
                <el-table-column prop="versionNo" label="版本" width="100" />
                <el-table-column label="状态" width="120">
                  <template #default="{ row }"><StatusTag :status="row.status" object-type="product" /></template>
                </el-table-column>
                <el-table-column prop="activeBomVersion" label="BOM 主版本" width="130" />
                <el-table-column label="资料完整率" min-width="160">
                  <template #default="{ row }"><el-progress :percentage="Math.round(row.completionRate * 100)" :stroke-width="8" /></template>
                </el-table-column>
                <el-table-column label="操作" width="100" fixed="right">
                  <template #default="{ row }"><el-button link type="primary" @click="openDetail(row)">详情</el-button></template>
                </el-table-column>
              </el-table>
              </FixedTableViewport>
            </section>
          </template>

          <template v-else>
            <section v-if="skuPageStage === 'product-home'" class="page-panel sku-product-home">
              <div class="toolbar-row sku-product-home__head">
                <div>
                  <h3 class="section-title">SKU 管理</h3>
                  <p class="page-panel-desc">先按产品卡片定位，再进入该产品下的 SKU 列表。</p>
                </div>
                <el-button type="primary" @click="openArchiveImport('sku')">导入数据</el-button>
              </div>
              <div class="sku-product-grid" v-loading="loading">
                <button
                  v-for="product in skuProductCards"
                  :key="product.productId"
                  class="sku-product-card"
                  type="button"
                  @click="skuOpenSkuList(product.productId)"
                >
                  <div class="sku-product-card__image"><span>{{ product.seriesName }}</span></div>
                  <div class="toolbar-row">
                    <strong>{{ product.productName }}</strong>
                    <StatusTag :status="product.status" object-type="product" />
                  </div>
                  <p class="subtle-text">{{ getDisplayProductLineCode(product) }}</p>
                  <p class="sku-product-card__series">{{ product.seriesName }}</p>
                  <div class="sku-product-card__meta">
                    <span>{{ getSkuCountForProduct(product) }} 个 SKU</span>
                    <span class="subtle-text">{{ getRecentUpdate(product) }}</span>
                  </div>
                </button>
              </div>
            </section>

            <section v-else class="page-panel sku-list-panel" v-loading="loading">
              <div class="toolbar-row sku-list-panel__head">
                <div>
                  <el-button link type="primary" @click="skuBackToProductHome">返回产品卡片</el-button>
                  <h3 class="section-title">{{ skuActiveProduct?.productName }} / SKU 列表</h3>
                  <p class="page-panel-desc">查看当前产品下的 SKU 信息、版本状态和归档资料。</p>
                </div>
                <div class="sku-list-panel__actions">
                  <el-input v-model="skuKeyword" clearable class="sku-list-panel__search" placeholder="搜索编码 / 名称 / 型号 / 颜色" />
                  <el-button type="primary" @click="openArchiveImport('sku')">导入数据</el-button>
                </div>
              </div>
              <FixedTableViewport v-slot="{ tableHeight }" :refresh-key="skuCurrentSkuRows">
              <el-table :data="skuCurrentSkuRows" :height="tableHeight" border stripe>
                <el-table-column label="示例图" min-width="130">
                  <template #default="{ row }">
                    <div class="sku-image-cell"><div class="sku-image-cell__thumb"><span>{{ row.model }}</span></div></div>
                  </template>
                </el-table-column>
                <el-table-column label="SKU 编码" min-width="180">
                  <template #default="{ row }">{{ getDisplaySkuCode(row) }}</template>
                </el-table-column>
                <el-table-column prop="productName" label="SKU 名称" min-width="220" />
                <el-table-column prop="model" label="型号" width="140" />
                <el-table-column label="单位" width="80"><template #default>pcs</template></el-table-column>
                <el-table-column label="项目来源" min-width="140"><template #default>历史归档</template></el-table-column>
                <el-table-column prop="color" label="颜色" width="120" />
                <el-table-column prop="versionNo" label="版本" width="100" />
                <el-table-column label="状态" width="120">
                  <template #default="{ row }"><StatusTag :status="row.status" object-type="product" /></template>
                </el-table-column>
                <el-table-column label="最近更新时间" width="140">
                  <template #default="{ row }">{{ getRecentUpdate(row) }}</template>
                </el-table-column>
                <el-table-column label="操作" width="80" fixed="right">
                  <template #default="{ row }"><el-button link type="primary" @click="openDetail(row)">详情</el-button></template>
                </el-table-column>
              </el-table>
              </FixedTableViewport>
            </section>
          </template>
        </template>

        <template v-else>
          <div class="list-context-bar">
            <strong>已停止项目</strong>
            <span class="subtle-text">已停止项目永久保留，列表来自后端 Product 停止字段。</span>
          </div>
          <section class="project-list-shell" v-loading="loading">
            <FixedTableViewport v-slot="{ tableHeight }" :refresh-key="abandonedProjectRows">
            <el-table :data="abandonedProjectRows" :height="tableHeight" border stripe>
              <el-table-column prop="productCode" label="项目编码" min-width="170" />
              <el-table-column prop="productName" label="项目对象" min-width="220" />
              <el-table-column prop="currentStage" label="停止阶段" min-width="140" />
              <el-table-column prop="ownerUserName" label="负责人" width="110" />
              <el-table-column label="停止时间" width="150">
                <template #default="{ row }">{{ formatDate(row.abandonedAt) }}</template>
              </el-table-column>
              <el-table-column label="停止人" width="120">
                <template #default="{ row }">{{ row.abandonedBy || '--' }}</template>
              </el-table-column>
              <el-table-column label="停止原因" min-width="220">
                <template #default="{ row }">{{ row.abandonReason || '后端未返回停止原因' }}</template>
              </el-table-column>
            </el-table>
            </FixedTableViewport>
          </section>
        </template>
      </div>
    </section>

    <el-dialog v-model="overviewVisible" title="项目概览" width="640px" destroy-on-close>
      <template v-if="overviewProject">
        <div class="project-overview-dialog">
          <div class="project-overview-dialog__title">
            <strong>{{ overviewProject.productName }}</strong>
            <el-tag :type="getProjectTagType(overviewProject.projectTag)" effect="light">{{ overviewProject.projectTag }}</el-tag>
          </div>
          <dl class="project-overview-grid">
            <div><dt>项目编码</dt><dd>{{ overviewProject.productCode }}</dd></div>
            <div><dt>项目类型</dt><dd>{{ overviewProject.projectType }}</dd></div>
            <div><dt>当前阶段</dt><dd>{{ overviewProject.currentStage }}</dd></div>
            <div><dt>负责人</dt><dd>{{ overviewProject.ownerUserName }}</dd></div>
            <div><dt>版本</dt><dd>{{ overviewProject.versionNo }}</dd></div>
            <div><dt>最近更新时间</dt><dd>{{ formatDate(overviewProject.updatedAt) }}</dd></div>
          </dl>
          <section class="project-overview-block">
            <p class="subtle-text">说明</p>
            <strong>
              {{
                overviewProject.abandoned
                  ? '该项目已停止，保留原因与可复用资产用于后续追溯。'
                  : getNextGate(overviewProject.source!)
              }}
            </strong>
          </section>
        </div>
      </template>
      <template #footer>
        <el-button @click="overviewVisible = false">关闭</el-button>
        <el-button
          v-if="overviewProject && !overviewProject.abandoned"
          type="primary"
          @click="openProduct(overviewProject.productId)"
        >
          进入详情
        </el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="detailVisible" width="1080px" destroy-on-close>
      <template #header>
        <div class="detail-dialog-header">
          <div>
            <strong class="detail-dialog-header__title">
              {{ detailDialogTitle }}
            </strong>
            <div class="detail-dialog-header__meta" v-if="detailTarget">
              <span>{{ getDetailDisplayCode(detailTarget) }}</span>
              <span v-if="!isProductDetailDialog">型号 {{ detailTarget.model }} / {{ detailTarget.color }}</span>
              <span>系列 {{ detailTarget.seriesName }}</span>
              <span>版本 {{ detailTarget.versionNo }}</span>
            </div>
          </div>
          <div class="detail-dialog-header__actions">
            <StatusTag :status="detailTarget?.status || 'draft'" object-type="product" />
            <template v-if="detailTarget">
              <el-button
                size="small"
                :loading="detailLifecycleLoading === 'freeze'"
                :disabled="Boolean(detailLifecycleLoading) || !canFreezeDetailProject"
                @click="handleDetailFreezeProject"
              >
                冻结项目
              </el-button>
              <el-button
                v-if="isProductDetailDialog"
                size="small"
                type="primary"
                :loading="detailLifecycleLoading === 'publish'"
                :disabled="Boolean(detailLifecycleLoading) || !canPublishDetailProject"
                @click="handleDetailPublishProject"
              >
                发布 Product
              </el-button>
              <el-button
                size="small"
                type="danger"
                plain
                :loading="detailLifecycleLoading === 'abandon'"
                :disabled="Boolean(detailLifecycleLoading) || !canStopDetailProject"
                @click="handleDetailStopProject"
              >
                停止项目
              </el-button>
              <el-button
                size="small"
                :loading="detailLifecycleLoading === 'archive'"
                :disabled="Boolean(detailLifecycleLoading) || !canArchiveDetailProject"
                @click="handleDetailArchiveProject"
              >
                归档项目
              </el-button>
            </template>
          </div>
        </div>
      </template>
      <div v-if="detailTarget" v-loading="detailLoading" class="detail-dialog">
        <nav class="detail-breadcrumb" aria-label="详情分区">
          <button
            v-for="section in activeDetailSections"
            :key="section.key"
            class="detail-breadcrumb__item"
            :class="{ 'is-active': activeDetailSection === section.key }"
            type="button"
            @click="activeDetailSection = section.key"
          >
            {{ section.label }}
          </button>
        </nav>

        <section v-if="activeDetailSection === 'project_flow'" class="detail-section">
          <el-alert
            v-if="timelineStarted === false"
            type="info"
            :closable="false"
            show-icon
            :title="timelineStartBlockReason || '当前项目时间轴尚未启动。'"
          />
          <template v-if="timelineStarted !== false">
          <div class="product-node-hero">
            <div>
              <p class="subtle-text">当前节点</p>
              <h4 class="product-node-hero__title">{{ activeProductFlowNode?.nodeName || detailTarget.currentStage }}</h4>
              <p class="page-panel-desc">{{ activeProductFlowNode?.experienceSummary || activeProductFlowNode?.summary || detailPresentation?.summary || '暂无当前节点说明。' }}</p>
            </div>
            <div class="product-node-hero__actions">
              <StatusTag :status="detailTarget.status" object-type="product" />
            </div>
          </div>

          <div class="timeline-action-panel">
            <div class="timeline-action-panel__status">
              <el-tag :type="currentTimelineConfirmed ? 'success' : 'warning'" effect="light">
                {{ currentTimelineConfirmed ? '已确认' : '未确认' }}
              </el-tag>
              <span>{{ currentTimelineActionLabel }}</span>
            </div>
            <div class="timeline-action-panel__buttons">
              <el-button
                v-if="activeProductFlowNode && !currentTimelineConfirmed"
                data-test="project-timeline-confirm"
                type="primary"
                :loading="timelineActionLoading === 'confirm'"
                :disabled="Boolean(timelineActionLoading)"
                @click="handleConfirmCurrentNode"
              >
                确认当前节点
              </el-button>
              <el-button
                v-if="activeProductFlowNode && currentTimelineConfirmed && canAdvanceCurrentTimelineNode"
                data-test="project-timeline-advance"
                type="primary"
                :loading="timelineActionLoading === 'confirm'"
                :disabled="Boolean(timelineActionLoading) || !canAdvanceCurrentTimelineNode"
                @click="handleAdvanceCurrentNode"
              >
                推进下一节点
              </el-button>
              <el-dropdown
                v-if="activeProductFlowNode"
                data-test="project-timeline-return"
                :disabled="Boolean(timelineActionLoading)"
                @command="handleReturnCommand"
              >
                <el-button :loading="timelineActionLoading === 'return'">退回</el-button>
                <template #dropdown>
                  <el-dropdown-menu>
                    <el-dropdown-item command="current">退回当前节点修改</el-dropdown-item>
                    <el-dropdown-item command="previous">退回上一节点</el-dropdown-item>
                  </el-dropdown-menu>
                </template>
              </el-dropdown>
            </div>
          </div>

          <section v-if="isMoldTransferNode" class="mold-transfer-panel">
            <div class="detail-section__head">
              <div>
                <h4 class="section-title">运模快递登记</h4>
                <p class="page-panel-desc">当前运模节点只登记快递单号和发运时间，不再查询或展示物流轨迹。</p>
              </div>
              <el-tag effect="light" :type="moldTransferExpress?.trackingNo ? 'success' : 'warning'">
                {{ moldTransferExpress?.trackingNo ? '已登记单号' : '待登记单号' }}
              </el-tag>
            </div>
            <div class="mold-transfer-form mold-transfer-form--simple">
              <el-input v-model="moldTransferForm.trackingNo" placeholder="快递单号" maxlength="128" />
              <el-date-picker
                v-model="moldTransferForm.shippedAt"
                type="datetime"
                value-format="YYYY-MM-DDTHH:mm:ss"
                placeholder="发运时间"
              />
              <el-button type="primary" :loading="moldTransferLoading" @click="saveCurrentMoldTransferExpress">保存</el-button>
            </div>
            <div v-if="moldTransferExpress?.trackingNo" class="mold-transfer-summary">
              <div class="info-card">
                <span class="subtle-text">快递单号</span>
                <strong>{{ moldTransferExpress.trackingNo }}</strong>
              </div>
              <div class="info-card">
                <span class="subtle-text">发运时间</span>
                <strong>{{ moldTransferExpress.shippedAt ? formatDate(moldTransferExpress.shippedAt, 'YYYY-MM-DD HH:mm') : '--' }}</strong>
              </div>
            </div>
          </section>

          <div class="detail-grid">
            <div class="info-card">
              <span class="subtle-text">确认状态</span>
              <strong>{{ currentTimelineConfirmed ? '已确认' : '未确认' }}</strong>
            </div>
            <div class="info-card">
              <span class="subtle-text">最近动作</span>
              <strong>{{ getTimelineActionLabel(timelineLastAction) }}</strong>
              <span class="subtle-text">{{ timelineLastOperatedAt ? formatDate(timelineLastOperatedAt) : '--' }}</span>
            </div>
            <div class="info-card">
              <span class="subtle-text">最近操作人</span>
              <strong>{{ timelineLastOperatorUserName || '--' }}</strong>
            </div>
            <div class="info-card">
              <span class="subtle-text">最近退回原因</span>
              <strong>{{ timelineLastReason || '--' }}</strong>
            </div>
            <div class="info-card">
              <span class="subtle-text">下一步动作</span>
              <strong>{{ activeProductFlowNode?.nextAction || detailTarget.nextAction || detailPresentation?.nextNode || '--' }}</strong>
            </div>
            <div class="info-card">
              <span class="subtle-text">接收人 / 时间</span>
              <strong>{{ activeProductFlowNode?.receiverUserName || activeProductFlowNode?.receiverRole || '--' }}</strong>
              <span class="subtle-text">{{ activeProductFlowNode?.receivedAt || '--' }}</span>
            </div>
            <div class="info-card">
              <span class="subtle-text">推动人 / 时间</span>
              <strong>{{ activeProductFlowNode?.promoterUserName || activeProductFlowNode?.promoterRole || activeProductFlowNode?.ownerRole || '--' }}</strong>
              <span class="subtle-text">{{ activeProductFlowNode?.promotedAt || (activeProductFlowNode?.status === 'current' ? '推进中' : '--') }}</span>
            </div>
            <div class="info-card">
              <span class="subtle-text">下一接收方</span>
              <strong>{{ activeProductFlowNode?.nextReceiverUserName || activeProductFlowNode?.nextReceiverRole || '--' }}</strong>
            </div>
          </div>

          <div v-if="activeProductFlowNode?.riskNote || activeProductFlowNode?.detailLines?.length" class="product-node-checks">
            <el-alert v-if="activeProductFlowNode?.riskNote" type="warning" show-icon :closable="false" :title="activeProductFlowNode.riskNote" />
            <ul v-if="activeProductFlowNode?.detailLines?.length" class="node-check-list">
              <li v-for="line in activeProductFlowNode.detailLines" :key="line">{{ line }}</li>
            </ul>
          </div>

          <ProjectReleaseGatePanel
            v-if="isProductDetailDialog"
            :project-id="detailTarget.productId"
            :product-status="detailTarget.status"
            @changed="handleLifecycleChanged"
          />
          </template>
        </section>

        <section v-if="activeDetailSection === 'basic'" class="detail-section">
          <div class="detail-section__head">
            <div>
              <h4 class="section-title">基础信息</h4>
            </div>
            <div v-if="canEditDetailTarget" class="toolbar-actions">
              <template v-if="basicInfoEditing">
                <el-button :disabled="basicInfoSaving" @click="cancelBasicInfoEdit">取消</el-button>
                <el-button type="primary" :loading="basicInfoSaving" @click="saveBasicInfo">保存</el-button>
              </template>
              <el-button v-else type="primary" plain size="small" @click="openDetailEdit">编辑基础信息</el-button>
            </div>
          </div>

          <el-form v-if="basicInfoEditing" label-position="top" class="basic-info-form">
            <div class="detail-grid">
              <el-form-item :label="`${detailObjectLabel}名称`">
                <el-input v-model="basicInfoForm.productName" />
              </el-form-item>
              <el-form-item label="系列">
                <el-input v-model="basicInfoForm.seriesName" />
              </el-form-item>
              <el-form-item label="负责人">
                <el-input v-model="basicInfoForm.ownerUserName" />
              </el-form-item>
              <el-form-item label="型号">
                <el-input v-model="basicInfoForm.model" />
              </el-form-item>
              <el-form-item label="颜色">
                <el-input v-model="basicInfoForm.color" />
              </el-form-item>
              <el-form-item label="材质">
                <el-input v-model="basicInfoForm.material" />
              </el-form-item>
              <el-form-item label="包装方式">
                <el-input v-model="basicInfoForm.packageType" />
              </el-form-item>
              <el-form-item label="表面工艺">
                <el-input v-model="basicInfoForm.surfaceProcess" />
              </el-form-item>
              <el-form-item label="预计发布时间">
                <el-date-picker v-model="basicInfoForm.expectedReleaseDate" type="date" value-format="YYYY-MM-DD" style="width: 100%" />
              </el-form-item>
              <el-form-item label="预计到达时间">
                <el-date-picker v-model="basicInfoForm.expectedArrivalAt" type="datetime" value-format="YYYY-MM-DDTHH:mm:ss" style="width: 100%" />
              </el-form-item>
              <el-form-item label="实际到达时间">
                <el-date-picker v-model="basicInfoForm.actualArrivalAt" type="datetime" value-format="YYYY-MM-DDTHH:mm:ss" style="width: 100%" />
              </el-form-item>
              <template v-if="detailTarget.productType === 'model_variant'">
                <el-form-item label="4G/5G">
                  <el-input v-model="basicInfoForm.networkType" />
                </el-form-item>
                <el-form-item label="大孔或精孔">
                  <el-input v-model="basicInfoForm.holeType" />
                </el-form-item>
                <el-form-item label="Tipo 类型">
                  <el-input v-model="basicInfoForm.tipo" />
                </el-form-item>
                <el-form-item label="紧急度">
                  <el-input v-model="basicInfoForm.priority" />
                </el-form-item>
                <el-form-item label="制造地">
                  <el-input v-model="basicInfoForm.manufacturingLocation" />
                </el-form-item>
                <el-form-item label="模具印字">
                  <el-input v-model="basicInfoForm.moldMarking" />
                </el-form-item>
                <el-form-item label="订单类型">
                  <el-select v-model="basicInfoForm.requirementType" clearable style="width: 100%">
                    <el-option label="客户订单" value="customer_requirement" />
                    <el-option label="市场需求" value="market_requirement" />
                  </el-select>
                </el-form-item>
                <el-form-item label="钉钉链接">
                  <el-input v-model="basicInfoForm.referenceUrl" />
                </el-form-item>
                <el-form-item label="手机功能">
                  <el-input v-model="basicInfoForm.mobileFunction" type="textarea" :rows="3" />
                </el-form-item>
                <el-form-item label="客户要求">
                  <el-input v-model="basicInfoForm.customerRequirement" type="textarea" :rows="3" />
                </el-form-item>
              </template>
              <el-form-item label="核心工艺">
                <el-input v-model="basicInfoForm.coreProcess" type="textarea" :rows="3" />
              </el-form-item>
              <el-form-item label="组成说明">
                <el-input v-model="basicInfoForm.composition" type="textarea" :rows="3" />
              </el-form-item>
            </div>
          </el-form>

          <div v-else class="detail-grid">
            <div class="info-card"><span class="subtle-text">{{ detailObjectLabel }}编码</span><strong>{{ getDetailDisplayCode(detailTarget) }}</strong></div>
            <div class="info-card"><span class="subtle-text">{{ detailObjectLabel }}名称</span><strong>{{ detailTarget.productName }}</strong></div>
            <div v-if="detailTarget.productType === 'sku'" class="info-card"><span class="subtle-text">Product 编码</span><strong>{{ detailTarget.productCode }}</strong></div>
            <div class="info-card"><span class="subtle-text">系列</span><strong>{{ detailTarget.seriesName }}</strong></div>
            <div v-if="isProductDetailDialog" class="info-card"><span class="subtle-text">产品类型</span><strong>{{ getProjectTypeLabel(detailTarget) }}</strong></div>
            <div v-if="detailTarget.productType === 'model_variant' || detailTarget.productType === 'sku'" class="info-card"><span class="subtle-text">产品特定编码</span><strong>{{ detailTarget.productSpecificCode || '--' }}</strong></div>
            <div v-if="detailTarget.productType === 'model_variant' || detailTarget.productType === 'sku'" class="info-card"><span class="subtle-text">手机型号编码</span><strong>{{ detailTarget.phoneModelCode || '--' }}</strong></div>
            <div v-if="detailTarget.productType === 'model_variant' || detailTarget.productType === 'sku'" class="info-card"><span class="subtle-text">颜色编码</span><strong>{{ detailTarget.colorCode || '--' }}</strong></div>
            <div class="info-card"><span class="subtle-text">版本</span><strong>{{ detailTarget.versionNo }}</strong></div>
            <div class="info-card"><span class="subtle-text">型号</span><strong>{{ detailTarget.model || '--' }}</strong></div>
            <div v-if="detailTarget.productType === 'model_variant'" class="info-card"><span class="subtle-text">模具编码</span><strong>{{ detailTarget.moldCodes || '--' }}</strong></div>
            <div v-if="detailTarget.productType === 'model_variant'" class="info-card"><span class="subtle-text">运模时间</span><strong>{{ detailTarget.moldTransferAt ? formatDate(detailTarget.moldTransferAt, 'YYYY-MM-DD HH:mm') : '--' }}</strong></div>
            <div v-if="detailTarget.productType === 'model_variant'" class="info-card"><span class="subtle-text">预计到达时间</span><strong>{{ detailTarget.expectedArrivalAt ? formatDate(detailTarget.expectedArrivalAt, 'YYYY-MM-DD HH:mm') : '--' }}</strong></div>
            <div v-if="detailTarget.productType === 'model_variant'" class="info-card"><span class="subtle-text">实际到达时间</span><strong>{{ detailTarget.actualArrivalAt ? formatDate(detailTarget.actualArrivalAt, 'YYYY-MM-DD HH:mm') : '--' }}</strong></div>
            <div class="info-card"><span class="subtle-text">颜色</span><strong>{{ formatScalarOrArray(detailTarget.color) }}</strong></div>
            <div v-if="isProductDetailDialog" class="info-card"><span class="subtle-text">材质</span><strong>{{ formatScalarOrArray(detailTarget.material) }}</strong></div>
            <div v-if="isProductDetailDialog" class="info-card"><span class="subtle-text">客户来源</span><strong>{{ detailTarget.customerName || '内部立项' }}</strong></div>
            <div v-if="isProductDetailDialog" class="info-card"><span class="subtle-text">负责人</span><strong>{{ formatOwnerName(detailTarget.ownerUserName) }}</strong></div>
            <div class="info-card"><span class="subtle-text">状态</span><StatusTag :status="detailTarget.status" object-type="product" /></div>
            <div class="info-card"><span class="subtle-text">当前阶段</span><strong>{{ detailTarget.currentStage }}</strong></div>
            <div v-if="isProductDetailDialog" class="info-card"><span class="subtle-text">资料完整率</span><strong>{{ Math.round(detailTarget.completionRate * 100) }}%</strong></div>
            <div v-if="isProductDetailDialog && user.hasPermission('finance:read')" class="info-card"><span class="subtle-text">预算与费用</span><el-button link @click="activeDetailSection='cost'">按原币核对</el-button></div>
            <template v-if="detailTarget.productType === 'model_variant' && basicInfoExtra">
              <div class="info-card"><span class="subtle-text">4G/5G</span><strong>{{ basicInfoExtra.networkType || '--' }}</strong></div>
              <div class="info-card"><span class="subtle-text">大孔或精孔</span><strong>{{ basicInfoExtra.holeType || '--' }}</strong></div>
              <div class="info-card"><span class="subtle-text">Tipo 类型</span><strong>{{ basicInfoExtra.tipo || '--' }}</strong></div>
              <div class="info-card"><span class="subtle-text">紧急度</span><strong>{{ basicInfoExtra.priority || '--' }}</strong></div>
              <div class="info-card"><span class="subtle-text">制造地</span><strong>{{ basicInfoExtra.manufacturingLocation || '--' }}</strong></div>
              <div class="info-card"><span class="subtle-text">模具印字</span><strong>{{ basicInfoExtra.moldMarking || '--' }}</strong></div>
              <div class="info-card"><span class="subtle-text">客户要求</span><strong>{{ basicInfoExtra.customerRequirement || '--' }}</strong></div>
            </template>
          </div>

          <section v-if="hasDetailColorSummary" class="product-color-summary">
            <div class="detail-section__head">
              <div>
                <h4 class="section-title">颜色归档</h4>
                <p class="page-panel-desc">按真实产品线汇总 SKU 实际颜色与 BOM/生产决策颜色。</p>
              </div>
            </div>
            <div class="product-color-summary__groups">
              <div class="product-color-summary__group">
                <span class="subtle-text">SKU 实际颜色 {{ detailTarget.colorSummary?.skuColorCount || 0 }} 个</span>
                <div class="product-color-tags">
                  <el-tag
                    v-for="color in detailTarget.colorSummary?.skuColors || []"
                    :key="`sku-${color.colorCode || color.colorName}`"
                    effect="light"
                  >
                    {{ getColorUsageLabel(color) }} · {{ color.skuCount }} SKU
                  </el-tag>
                </div>
              </div>
              <div class="product-color-summary__group">
                <span class="subtle-text">BOM/生产决策颜色 {{ detailTarget.colorSummary?.productionColorCount || 0 }} 个</span>
                <div class="product-color-tags">
                  <el-tag
                    v-for="color in detailTarget.colorSummary?.productionColors || []"
                    :key="`production-${color.colorCode || color.colorName}`"
                    type="success"
                    effect="light"
                  >
                    {{ getColorUsageLabel(color) }}
                  </el-tag>
                </div>
              </div>
            </div>
            <el-alert
              v-if="detailTarget.colorSummary?.skuOnlyColors?.length || detailTarget.colorSummary?.productionOnlyColors?.length"
              class="product-color-summary__diff"
              type="warning"
              show-icon
              :closable="false"
              :title="`颜色差异：仅 SKU 层 ${detailTarget.colorSummary?.skuOnlyColors?.map(getColorUsageLabel).join('、') || '无'}；仅 BOM/生产决策层 ${detailTarget.colorSummary?.productionOnlyColors?.map(getColorUsageLabel).join('、') || '无'}`"
            />
          </section>
        </section>

        <section v-if="isProductDetailDialog && activeDetailSection === 'project_flow' && timelineStarted !== false" class="detail-section">
          <div class="detail-section__head">
            <div>
              <h4 class="section-title">项目流程</h4>
              <p class="page-panel-desc">展示每个环节经历了什么、由谁接收、由谁推动以及推动时间。</p>
            </div>
          </div>
          <section class="product-flow-board">
            <aside class="product-flow-board__stages">
              <button
                v-for="stage in productFlowStages"
                :key="stage.stageKey"
                class="flow-stage-card"
                :class="{ 'is-active': stage.stageKey === activeProductFlowStage?.stageKey }"
                type="button"
                @click="activeProductFlowStageKey = stage.stageKey"
              >
                <span class="flow-stage-card__name">{{ stage.stageName }}</span>
                <span class="flow-stage-card__phase">{{ stage.phaseName }}</span>
                <el-tag size="small" effect="light" :type="getFlowStatusType(stage.status)">
                  {{ getFlowStatusLabel(stage.status) }}
                </el-tag>
              </button>
            </aside>

            <main v-if="activeProductFlowStage" class="product-flow-board__detail">
              <div class="flow-stage-summary">
                <div>
                  <h4>{{ activeProductFlowStage.stageName }}</h4>
                  <p>{{ activeProductFlowStage.summary }}</p>
                </div>
                <el-tag :type="getFlowStatusType(activeProductFlowStage.status)" effect="light">
                  {{ getFlowStatusLabel(activeProductFlowStage.status) }}
                </el-tag>
              </div>

              <div class="flow-stage-meta-grid">
                <div class="info-card">
                  <span class="subtle-text">责任角色</span>
                  <strong>{{ activeProductFlowStage.receiverRole || '--' }}</strong>
                </div>
                <div class="info-card">
                  <span class="subtle-text">接收人 / 时间</span>
                  <strong>{{ activeProductFlowStage.receiverUserName || '--' }}</strong>
                  <span class="subtle-text">{{ activeProductFlowStage.receivedAt || '--' }}</span>
                </div>
                <div class="info-card">
                  <span class="subtle-text">推动人 / 时间</span>
                  <strong>{{ activeProductFlowStage.promoterUserName || activeProductFlowStage.promoterRole || '--' }}</strong>
                  <span class="subtle-text">{{ activeProductFlowStage.promotedAt || '--' }}</span>
                </div>
                <div class="info-card">
                  <span class="subtle-text">下一步</span>
                  <strong>{{ activeProductFlowStage.nextAction || '--' }}</strong>
                </div>
                <div class="info-card">
                  <span class="subtle-text">风险提示</span>
                  <strong>{{ activeProductFlowStage.riskNote || '暂无风险' }}</strong>
                </div>
              </div>

              <div class="flow-child-node-list">
                <div v-for="node in activeProductFlowStage.childNodes" :key="node.nodeKey" class="flow-child-node">
                  <strong>第 {{ node.stepNo }} 步：{{ node.nodeName }}</strong>
                  <div>
                    <span v-if="node.actionLabel" class="subtle-text">{{ node.actionLabel }}</span>
                    <el-button v-if="node.processConfirmation || isProcessConfirmationNode(node)" size="small" type="primary" plain @click="openProductionConfirmation('operations')">敲定投产工序</el-button>
                    <el-button v-if="node.nodeKey === 'PRODUCT_LINE_PRODUCTION_DECISION_STEP'" size="small" type="primary" @click="openProductionConfirmation('colors')">确认批量投产颜色</el-button>
                    <el-tag v-if="node.documentCount" size="small" type="success" effect="light">
                      已上传 {{ node.documentCount }} 个
                    </el-tag>
                    <el-tag size="small" effect="light" :type="getFlowStatusType(node.status)">
                      {{ getFlowStatusLabel(node.status) }}
                    </el-tag>
                  </div>
                </div>
              </div>
            </main>
          </section>
        </section>

        <section v-if="isProductDetailDialog && activeDetailSection === 'bom_manage'" class="detail-section">
          <ProjectBomPanel
            :project-id="detailTarget.productId"
          />
        </section>

        <section v-if="isProductDetailDialog && activeDetailSection === 'process_detail'" class="detail-section">
          <ProjectProcessRoutePanel
            :project-id="detailTarget.productId"
            :product-code="detailTarget.productCode"
            :product-name="detailTarget.productName"
            :product-type="detailTarget.productType"
            :product-specific-code="detailTarget.productSpecificCode || undefined"
            :phone-model-code="detailTarget.phoneModelCode || undefined"
            :color-code="detailTarget.colorCode || undefined"
            :auto-create="route.query.createProcessRoute === '1'"
          />
        </section>

        <section v-if="isProductDetailDialog && activeDetailSection === 'materials'" class="detail-section">
          <TimelineAttachmentPanel
            :project-id="detailTarget.productId"
            @changed="handleM4AttachmentChanged"
          />
        </section>

        <section v-if="isProductDetailDialog && activeDetailSection === 'business'" class="detail-section">
          <h4 class="section-title">商务区</h4>
          <el-button v-if="user.hasPermission('finance:read')" @click="activeDetailSection='cost'">打开统一费用归集（按原币，不混加）</el-button>
          <el-table :data="detailPresentation?.suppliers || []" border stripe size="small">
            <el-table-column prop="supplierName" label="供应商" min-width="160" />
            <el-table-column prop="role" label="角色" width="140" />
            <el-table-column prop="statusLabel" label="状态" width="120" />
            <el-table-column prop="note" label="说明" min-width="220" />
          </el-table>
        </section>

        <section v-if="isProductDetailDialog && activeDetailSection === 'quality'" class="detail-section">
          <h4 class="section-title">质量区</h4>
          <el-table :data="detailPresentation?.qualityRecords || []" border stripe size="small">
            <el-table-column prop="testItem" label="测试项目" min-width="150" />
            <el-table-column prop="resultLabel" label="测试结果" width="120" />
            <el-table-column prop="owner" label="负责人" width="140" />
            <el-table-column prop="testedAt" label="测试时间" width="130" />
            <el-table-column prop="note" label="结论说明" min-width="260" />
          </el-table>
          <el-empty v-if="!detailPresentation?.qualityRecords?.length" description="暂无质量记录" />
        </section>

        <section v-if="activeDetailSection === 'cost' && user.hasPermission('finance:read')" class="detail-section">
          <ProjectCostPanel :project-id="detailTarget.productId" @changed="refreshDetailAfterChildChange" />
        </section>

        <section v-if="activeDetailSection === 'bom'" class="detail-section">
          <ProjectBomPanel
            :project-id="detailTarget.productId"
          />
        </section>

        <section v-if="activeDetailSection === 'process'" class="detail-section">
          <ProjectProcessRoutePanel
            :project-id="detailTarget.productId"
            :product-code="detailTarget.productCode"
            :product-name="detailTarget.productName"
            :product-type="detailTarget.productType"
            :product-specific-code="detailTarget.productSpecificCode || undefined"
            :phone-model-code="detailTarget.phoneModelCode || undefined"
            :color-code="detailTarget.colorCode || undefined"
            :auto-create="route.query.createProcessRoute === '1'"
          />
        </section>

        <section v-if="!isProductDetailDialog && activeDetailSection === 'project_flow' && timelineStarted !== false" class="detail-section">
          <div class="detail-section__head">
            <div>
              <h4 class="section-title">项目流程</h4>
              <p class="page-panel-desc">SKU 对应新型号线流程，展示差异扩展从需求确认到版本发布的接收、推动与时间记录。</p>
            </div>
          </div>

          <section v-if="skuProjectFlowStages.length" class="product-flow-board">
            <aside class="product-flow-board__stages">
              <button
                v-for="stage in skuProjectFlowStages"
                :key="stage.stageKey"
                class="flow-stage-card"
                :class="{ 'is-active': stage.stageKey === activeSkuFlowStage?.stageKey }"
                type="button"
                @click="activeSkuFlowStageKey = stage.stageKey"
              >
                <span class="flow-stage-card__name">{{ stage.stageName }}</span>
                <span class="flow-stage-card__phase">{{ stage.phaseName }}</span>
                <el-tag size="small" effect="light" :type="getFlowStatusType(stage.status)">
                  {{ getFlowStatusLabel(stage.status) }}
                </el-tag>
              </button>
            </aside>

            <main v-if="activeSkuFlowStage" class="product-flow-board__detail">
              <div class="flow-stage-summary">
                <div>
                  <h4>{{ activeSkuFlowStage.stageName }}</h4>
                  <p>{{ activeSkuFlowStage.summary }}</p>
                </div>
                <el-tag :type="getFlowStatusType(activeSkuFlowStage.status)" effect="light">
                  {{ getFlowStatusLabel(activeSkuFlowStage.status) }}
                </el-tag>
              </div>

              <div class="flow-stage-meta-grid">
                <div class="info-card">
                  <span class="subtle-text">责任角色</span>
                  <strong>{{ activeSkuFlowStage.receiverRole || '--' }}</strong>
                </div>
                <div class="info-card">
                  <span class="subtle-text">接收人 / 时间</span>
                  <strong>{{ activeSkuFlowStage.receiverUserName || '--' }}</strong>
                  <span class="subtle-text">{{ activeSkuFlowStage.receivedAt || '--' }}</span>
                </div>
                <div class="info-card">
                  <span class="subtle-text">推动人 / 时间</span>
                  <strong>{{ activeSkuFlowStage.promoterUserName || activeSkuFlowStage.promoterRole || '--' }}</strong>
                  <span class="subtle-text">{{ activeSkuFlowStage.promotedAt || '--' }}</span>
                </div>
                <div class="info-card">
                  <span class="subtle-text">下一步</span>
                  <strong>{{ activeSkuFlowStage.nextAction || '--' }}</strong>
                </div>
                <div class="info-card">
                  <span class="subtle-text">风险提示</span>
                  <strong>{{ activeSkuFlowStage.riskNote || '暂无风险' }}</strong>
                </div>
              </div>

              <div class="flow-child-node-list">
                <div v-for="node in activeSkuFlowStage.childNodes" :key="node.nodeKey" class="flow-child-node">
                  <strong>第 {{ node.stepNo }} 步：{{ node.nodeName }}</strong>
                  <div>
                    <span v-if="node.actionLabel" class="subtle-text">{{ node.actionLabel }}</span>
                    <el-button v-if="node.processConfirmation || isProcessConfirmationNode(node)" size="small" type="primary" plain @click="openProductionConfirmation('operations')">敲定投产工序</el-button>
                    <el-button v-if="node.nodeKey === 'MODEL_VARIANT_MOLD_TRANSFER'" size="small" type="primary" @click="openProductionConfirmation('colors')">确认批量投产并创建 SKU</el-button>
                    <el-tag v-if="node.documentCount" size="small" type="success" effect="light">
                      已上传 {{ node.documentCount }} 个
                    </el-tag>
                    <el-tag size="small" effect="light" :type="getFlowStatusType(node.status)">
                      {{ getFlowStatusLabel(node.status) }}
                    </el-tag>
                  </div>
                </div>
              </div>

              <el-collapse v-model="skuFlowTableExpanded" class="sku-flow-table-collapse">
                <el-collapse-item name="detail">
                  <template #title>
                    <span>查看明细记录（{{ skuProjectFlowRows.length }} 条）</span>
                  </template>
                  <el-table :data="skuProjectFlowRows" border stripe size="small">
                    <el-table-column prop="seqNo" label="顺序" width="70" />
                    <el-table-column prop="stageName" label="新型号线阶段" min-width="140" />
                    <el-table-column prop="nodeName" label="环节" min-width="140" />
                    <el-table-column prop="phaseName" label="阶段" min-width="110" />
                    <el-table-column prop="experienceSummary" label="经历内容" min-width="200" />
                    <el-table-column label="接收人" width="110">
                      <template #default="{ row }">{{ row.receiverUserName || row.receiverRole || '--' }}</template>
                    </el-table-column>
                    <el-table-column label="接收时间" width="110">
                      <template #default="{ row }">{{ row.receivedAt || '--' }}</template>
                    </el-table-column>
                    <el-table-column label="推动人" width="110">
                      <template #default="{ row }">{{ row.promoterUserName || row.promoterRole || '--' }}</template>
                    </el-table-column>
                    <el-table-column label="推动时间" width="110">
                      <template #default="{ row }">{{ row.promotedAt || '--' }}</template>
                    </el-table-column>
                    <el-table-column label="状态" width="100">
                      <template #default="{ row }">
                        <el-tag :type="getFlowStatusType(row.status)" effect="light" size="small">
                          {{ getFlowStatusLabel(row.status) }}
                        </el-tag>
                      </template>
                    </el-table-column>
                    <el-table-column label="下一步" min-width="160">
                      <template #default="{ row }">{{ row.nextAction || '--' }}</template>
                    </el-table-column>
                    <el-table-column label="资料数" width="80">
                      <template #default="{ row }">{{ row.documentCount ?? 0 }}</template>
                    </el-table-column>
                  </el-table>
                </el-collapse-item>
              </el-collapse>
            </main>
          </section>
          <el-empty v-else description="暂无项目流程" />
        </section>

        <section v-if="!isProductDetailDialog && activeDetailSection === 'production_docs'" class="detail-section">
          <TimelineAttachmentPanel
            :project-id="detailTarget.productId"
            @changed="handleM4AttachmentChanged"
          />
        </section>
      </div>
      <template #footer>
        <el-button @click="detailVisible = false">关闭</el-button>
      </template>

      <!-- 生产资料预览 -->
      <FilePreview
        v-model="productionPreviewVisible"
        :file="activeProductionDoc"
      />
  </el-dialog>
  <ProductionConfirmationDialog
    v-if="detailTarget"
    v-model="productionConfirmationVisible"
    :project-id="detailTarget.productId"
    :mode="productionConfirmationMode"
    :default-product-bom-route-id="productionConfirmationDefaultRouteId"
    @confirmed="handleProductionConfirmationConfirmed"
  />

    <el-dialog
      v-model="importVisible"
      :title="importType === 'product' ? '导入产品数据' : '导入 SKU 数据'"
      width="640px"
      @closed="resetArchiveImportState"
    >
      <el-alert type="info" show-icon :closable="false" title="用于导入历史归档数据，导入后仍按 Product 对象保存和追溯。" />
      <div class="archive-upload">
        <input
          :key="archiveImportInputKey"
          data-test="archive-import-file"
          type="file"
          accept=".xlsx,.xls,.csv"
          :disabled="archiveImportLoading"
          @change="handleArchiveImportFileChange"
        />
        <div class="el-upload__tip">支持 xlsx / xls / csv；SKU 导入仍按 Product 主数据导入，文件需包含 SKU 类型字段。</div>
      </div>
      <el-alert
        v-if="archiveImportPreview"
        class="archive-import-preview"
        :type="archiveImportPreview.failCount > 0 ? 'warning' : 'success'"
        show-icon
        :closable="false"
        :title="`预览结果：共 ${archiveImportPreview.totalCount} 条，成功 ${archiveImportPreview.successCount} 条，失败 ${archiveImportPreview.failCount} 条`"
      />
      <template #footer>
        <el-button :disabled="archiveImportLoading" @click="closeArchiveImport">取消</el-button>
        <el-button type="primary" :loading="archiveImportLoading" @click="submitArchiveImport">开始导入</el-button>
      </template>
    </el-dialog>
  </PageContainer>
</template>

<style scoped>
.project-filter-bar { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 14px; padding: 8px 10px; border: 1px solid #e5e7eb; border-radius: 8px; background: #fff; }
.project-filter-search { flex: 0 0 320px; max-width: 360px; }

.project-module-panel { overflow: hidden; border: 1px solid #e5e7eb; border-radius: 8px; background: #fff; }
.project-module-panel__header { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; padding: 14px 16px; border-bottom: 1px solid #e5e7eb; background: #fff; }
.project-module-panel__body { padding: 12px 16px 16px; background: #fff; }
.project-module-panel__desc { margin: 6px 0 0; color: #64748b; font-size: 13px; }

.project-tag-bar { display: flex; flex-wrap: wrap; gap: 6px; margin: 0; padding: 0; border: 0; background: transparent; }
.flow-filter-bar { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 16px; padding: 10px; border: 1px solid #e5e7eb; border-radius: 8px; background: #fff; }

.project-tag-bar__item,
.flow-filter-bar__item {
  padding: 7px 14px;
  border: 0;
  border-radius: 6px;
  background: transparent;
  color: #64748b;
  cursor: pointer;
}

.project-tag-bar__item.is-active,
.flow-filter-bar__item.is-active {
  background: #eff6ff;
  color: #1d4ed8;
  font-weight: 600;
}

.list-context-bar,
.selected-node-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 10px 14px;
  border-radius: 8px;
  background: rgba(37, 99, 235, 0.05);
  margin-bottom: 14px;
}

.project-timeline-panel {
  margin: 16px 0;
  padding: 16px;
  border: 1px solid rgba(37, 99, 235, 0.18);
  border-radius: 8px;
  background: #fff;
}

.timeline-row {
  display: grid;
  grid-template-columns: repeat(6, minmax(0, 1fr));
  gap: 10px;
}

.timeline-node {
  display: flex;
  min-height: 180px;
  flex-direction: column;
  gap: 6px;
  padding: 12px;
  border: 1px solid rgba(148, 163, 184, 0.24);
  border-radius: var(--plm-radius-base);
  background: #fff;
  text-align: left;
  cursor: pointer;
  transition: border-color 0.16s, box-shadow 0.16s;
}

.timeline-node:hover {
  border-color: #2563eb;
  box-shadow: 0 4px 12px rgba(37, 99, 235, 0.1);
}

.timeline-node.is-selected {
  border-color: #2563eb;
  background: rgba(37, 99, 235, 0.05);
  box-shadow: 0 4px 12px rgba(37, 99, 235, 0.12);
}

.timeline-node.is-gate {
  border-left: 3px solid #2563eb;
}

.timeline-node.is-empty {
  opacity: 0.58;
}

.timeline-node__phase,
.timeline-node__hint,
.timeline-node__children {
  color: #64748b;
  font-size: 12px;
}

.timeline-node__children {
  color: #94a3b8;
}

.timeline-node__count {
  margin-top: auto;
  color: #2563eb;
  font-size: 13px;
  font-weight: 600;
}

.project-list-shell {
  margin-top: 14px;
}

.cell-stack,
.detail-dialog,
.detail-section {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.sku-product-home__head {
  margin-bottom: 14px;
}

.sku-product-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 14px;
}

.sku-product-card {
  display: flex;
  min-height: 220px;
  flex-direction: column;
  gap: 10px;
  padding: 16px;
  border: 1px solid var(--plm-color-border-light);
  border-radius: var(--plm-radius-base);
  background: #fff;
  text-align: left;
  cursor: pointer;
  transition: border-color 0.16s, box-shadow 0.16s, transform 0.16s;
}

.sku-product-card:hover {
  border-color: var(--plm-color-primary);
  box-shadow: var(--plm-shadow-md);
  transform: translateY(-1px);
}

.sku-product-card__image,
.sku-image-cell__thumb {
  display: grid;
  place-items: center;
  border-radius: 8px;
  background: linear-gradient(135deg, #e9eef8 0%, #f8fafc 100%);
  color: #3b4a63;
  font-weight: 600;
}

.sku-product-card__image {
  min-height: 100px;
}

.sku-product-card__series {
  margin: 0;
  font-size: 18px;
  font-weight: 600;
}

.sku-product-card__meta,
.sku-list-panel__actions,
.sku-image-cell {
  display: flex;
  align-items: center;
  gap: 12px;
}

.sku-product-card__meta {
  justify-content: space-between;
  margin-top: auto;
}

.sku-list-panel__head {
  align-items: flex-start;
  margin-bottom: 14px;
}

.sku-list-panel__search {
  width: 260px;
}

.sku-image-cell__thumb {
  width: 52px;
  height: 52px;
  font-size: 11px;
}

.detail-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
}

.product-color-summary {
  display: flex;
  flex-direction: column;
  gap: 12px;
  margin-top: 18px;
}

.product-color-summary__groups {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px;
}

.product-color-summary__group {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 10px;
}

.product-color-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.product-color-summary__diff {
  margin-top: 2px;
}

.detail-cost-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
}

.product-node-hero {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  padding: 16px;
  border: 1px solid rgba(37, 99, 235, 0.16);
  border-radius: 8px;
  background: #f8fafc;
}

.product-node-hero__title {
  margin: 4px 0 6px;
  color: #0f172a;
  font-size: 18px;
  line-height: 1.35;
}

.product-node-hero__actions {
  display: flex;
  flex: 0 0 auto;
  align-items: center;
  gap: 10px;
}

.product-node-checks {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.node-check-list {
  margin: 0;
  padding: 12px 16px 12px 28px;
  border: 1px solid rgba(148, 163, 184, 0.18);
  border-radius: 8px;
  background: #fff;
  color: #334155;
  line-height: 1.7;
}

.product-flow-board {
  display: grid;
  grid-template-columns: 240px minmax(0, 1fr);
  gap: 14px;
}

.product-flow-board__stages,
.product-flow-board__detail {
  border: 1px solid rgba(148, 163, 184, 0.2);
  border-radius: 8px;
  background: #fff;
}

.product-flow-board__stages {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 10px;
}

.product-flow-board__detail {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 12px;
  padding: 14px;
}

.flow-stage-card {
  display: flex;
  min-height: 82px;
  flex-direction: column;
  align-items: flex-start;
  gap: 6px;
  padding: 10px;
  border: 1px solid transparent;
  border-radius: 8px;
  background: #f8fafc;
  color: #334155;
  text-align: left;
  cursor: pointer;
  transition: border-color 0.16s, background 0.16s, box-shadow 0.16s;
}

.flow-stage-card:hover,
.flow-stage-card.is-active {
  border-color: #2563eb;
  background: #eff6ff;
  box-shadow: 0 4px 12px rgba(37, 99, 235, 0.1);
}

.flow-stage-card__name {
  color: #0f172a;
  font-weight: 600;
}

.flow-stage-card__phase {
  color: #64748b;
  font-size: 12px;
}

.flow-stage-summary {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  padding-bottom: 12px;
  border-bottom: 1px solid rgba(148, 163, 184, 0.18);
}

.flow-stage-summary h4 {
  margin: 0 0 6px;
  color: #0f172a;
  font-size: 17px;
}

.flow-stage-summary p {
  margin: 0;
  color: #475569;
  line-height: 1.6;
}

.flow-stage-meta-grid {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 10px;
}

.flow-child-node-list {
  display: grid;
  gap: 8px;
}

.flow-child-node {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 10px 12px;
  border: 1px solid rgba(148, 163, 184, 0.18);
  border-radius: 8px;
  background: #f8fafc;
}

.flow-child-node > div {
  display: inline-flex;
  flex: 0 0 auto;
  align-items: center;
  gap: 8px;
}

.bom-version-select-panel {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 12px;
  border: 1px solid rgba(148, 163, 184, 0.18);
  border-radius: 8px;
  background: #f8fafc;
}

.bom-summary-row {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  color: #334155;
  font-size: 13px;
}

.bom-summary-row span {
  padding: 6px 10px;
  border-radius: 6px;
  background: #eef2ff;
}

.process-detail-tools {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: flex-end;
  gap: 10px;
}

.process-tag-list {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}

.detail-dialog-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  padding-bottom: 12px;
  border-bottom: 1px solid #e5e7eb;
}

.detail-dialog-header__title {
  color: #0f172a;
  font-size: 17px;
  font-weight: 600;
}

.detail-dialog-header__meta {
  display: flex;
  flex-wrap: wrap;
  gap: 6px 12px;
  margin-top: 6px;
  color: #64748b;
  font-size: 13px;
}

.detail-dialog-header__actions {
  display: inline-flex;
  align-items: center;
  justify-content: flex-end;
  gap: 10px;
  flex-wrap: wrap;
  flex-shrink: 0;
}

.sku-flow-table-collapse {
  margin-top: 2px;
  border-top: 1px solid rgba(148, 163, 184, 0.18);
  padding-top: 10px;
}

.detail-breadcrumb {
  display: flex;
  align-items: center;
  gap: 4px;
  padding-bottom: 12px;
  border-bottom: 1px solid #e5e7eb;
}

.detail-breadcrumb__item {
  padding: 4px 8px;
  border: 0;
  border-radius: 4px;
  background: transparent;
  color: #64748b;
  font-size: 13px;
  cursor: pointer;
}

.detail-breadcrumb__item:hover {
  background: #f8fafc;
  color: #334155;
}

.detail-breadcrumb__item.is-active {
  color: #0f172a;
  font-weight: 600;
}

.project-overview-dialog {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.project-overview-dialog__title {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding-bottom: 12px;
  border-bottom: 1px solid rgba(148, 163, 184, 0.2);
}

.project-overview-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px 18px;
  margin: 0;
}

.project-overview-grid div,
.project-overview-block {
  padding: 12px;
  border: 1px solid rgba(148, 163, 184, 0.18);
  border-radius: 8px;
  background: #f8fafc;
}

.project-overview-grid dt {
  margin-bottom: 6px;
  color: #64748b;
  font-size: 12px;
}

.project-overview-grid dd {
  margin: 0;
  color: #0f172a;
  font-weight: 600;
}

.archive-upload {
  margin-top: 16px;
}

.archive-import-preview {
  margin-top: 12px;
}

.project-current-heading {
  display: inline-flex;
  align-items: center;
  gap: 10px;
}

.project-current-count {
  color: #94a3b8;
  font-size: 13px;
  font-weight: 400;
}

.timeline-action-panel {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin: 14px 0;
  padding: 12px;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  background: #f8fafc;
}

.timeline-action-panel__status,
.timeline-action-panel__buttons {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.current-node-attachment-panel {
  margin: 14px 0;
  padding: 14px;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  background: #fff;
}

.mold-transfer-panel {
  padding: 12px 0;
  border-bottom: 1px solid #e5e7eb;
}

.mold-transfer-form {
  display: grid;
  grid-template-columns: minmax(220px, 1fr) 220px auto;
  gap: 10px;
  align-items: start;
}

.mold-transfer-summary {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
  margin-top: 12px;
}

@media (max-width: 1280px) {
  .timeline-row,
  .sku-product-grid,
  .detail-grid,
  .product-color-summary__groups {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .flow-stage-meta-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .mold-transfer-form {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .sku-flow-stage-strip {
    grid-template-columns: repeat(3, minmax(120px, 1fr));
  }
}

@media (max-width: 768px) {
  .timeline-row,
  .sku-product-grid,
  .detail-grid,
  .product-color-summary__groups,
  .detail-cost-grid,
  .product-flow-board,
  .flow-stage-meta-grid,
  .sku-flow-stage-strip,
  .project-overview-grid {
    grid-template-columns: 1fr;
  }

  .project-filter-bar,
  .list-context-bar,
  .selected-node-bar,
  .sku-list-panel__actions,
  .flow-stage-summary,
  .flow-child-node,
  .sku-flow-current,
  .timeline-action-panel,
  .bom-version-select-panel {
    align-items: stretch;
    flex-direction: column;
  }

  .mold-transfer-form,
  .mold-transfer-summary {
    grid-template-columns: 1fr;
  }

  .project-filter-search,
  .sku-list-panel__search,
  .process-detail-tools,
  .process-detail-tools :deep(.el-input) {
    width: 100%;
    max-width: none;
  }
}
</style>
