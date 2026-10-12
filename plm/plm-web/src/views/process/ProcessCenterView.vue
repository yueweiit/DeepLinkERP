<script setup lang="ts">
import { ArrowLeft, ArrowRight, Plus, Refresh } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import {
  confirmProcessOperationMaster,
  createProcessOperationMaster,
  getProcessCenterSnapshot,
  getProcessOperationMasters,
  getProcessRouteRelations,
  getProcessRouteTemplates,
  type ProcessOperationMasterSavePayload,
  type ProcessOperationMasterVO,
  type ProcessRouteTemplateOperationVO,
  type ProcessRouteTemplateVO
} from '@/api/modules/process'
import FixedTableViewport from '@/components/FixedTableViewport/index.vue'
import PageContainer from '@/components/PageContainer/index.vue'
import ProjectTimeRangeFilter, { type ProjectTimeRangeValue } from '@/components/ProjectTimeRangeFilter/index.vue'
import SearchBar from '@/components/SearchBar/index.vue'
import StatusTag from '@/components/StatusTag/index.vue'
import { useTable } from '@/composables/useTable'
import type { SearchField } from '@/types/common'
import type {
  ProcessAttachmentSummary,
  ProcessCenterSnapshot,
  ProcessCenterViewMode,
  ProcessOperationRecord,
  ProcessRouteDetail,
  ProcessRouteListItem,
  ProcessRouteRelation
} from '@/types/process'
import { formatAmount } from '@/utils/format'
import { normalizeLegacyProductTarget } from '@/utils/projectRoute'

type DetailSectionKey = 'overview' | 'operations' | 'attachments' | 'changes' | 'impacts'

const route = useRoute()
const router = useRouter()
const loading = ref(false)
const snapshot = ref<ProcessCenterSnapshot | null>(null)
const activeManagementTab = ref<'operation-master' | 'route-template' | 'project-route'>(
  route.query.routeId ? 'project-route' : 'operation-master'
)
const viewMode = ref<ProcessCenterViewMode>('route')
const activeSection = ref<DetailSectionKey>('overview')
const timeRange = ref<ProjectTimeRangeValue>('all')
const operationKeyword = ref('')
const activeImpactLabel = ref('')
const operationMasterLoading = ref(false)
const operationMasterRows = ref<ProcessOperationMasterVO[]>([])
const routeTemplateLoading = ref(false)
const routeTemplateRows = ref<ProcessRouteTemplateVO[]>([])
const operationMasterDialogVisible = ref(false)
const relationDrawerVisible = ref(false)
const relationLoading = ref(false)
const activeRelation = ref<ProcessRouteRelation | null>(null)
const operationMasterForm = reactive<ProcessOperationMasterSavePayload>({
  processCode: '',
  processName: '',
  processCategory: '',
  operationType: '加工',
  operationCraftCode: '',
  defaultStandardTimeMins: 0,
  defaultQualityRequirement: '',
  defaultProcessParamJson: '{}',
  needWorkstation: false,
  workstationType: '',
  remark: ''
})

const processTabOptions = [
  { label: '工序库', value: 'operation-master' },
  { label: '标准工艺路线', value: 'route-template' },
  { label: '项目工艺路线', value: 'project-route' }
] as const

function isWithinTimeRange(dateText: string | undefined, range: ProjectTimeRangeValue) {
  if (!dateText || range === 'all') return true
  const end = new Date('2026-06-11')
  const current = new Date(dateText)
  if (Number.isNaN(current.getTime())) return true
  const diffDays = Math.floor((end.getTime() - current.getTime()) / (1000 * 60 * 60 * 24))
  if (range === '3d') return diffDays <= 3
  if (range === '7d') return diffDays <= 7
  if (range === '30d') return diffDays <= 30
  return diffDays <= 180
}

function resetOperationMasterForm() {
  operationMasterForm.processCode = ''
  operationMasterForm.processName = ''
  operationMasterForm.processCategory = ''
  operationMasterForm.operationType = '加工'
  operationMasterForm.operationCraftCode = ''
  operationMasterForm.defaultStandardTimeMins = 0
  operationMasterForm.defaultQualityRequirement = ''
  operationMasterForm.defaultProcessParamJson = '{}'
  operationMasterForm.needWorkstation = false
  operationMasterForm.workstationType = ''
  operationMasterForm.remark = ''
}

async function loadOperationMasterRows() {
  operationMasterLoading.value = true
  try {
    operationMasterRows.value = await getProcessOperationMasters()
  } finally {
    operationMasterLoading.value = false
  }
}

async function loadRouteTemplateRows() {
  routeTemplateLoading.value = true
  try {
    routeTemplateRows.value = await getProcessRouteTemplates()
  } finally {
    routeTemplateLoading.value = false
  }
}

function openOperationMasterCreate() {
  resetOperationMasterForm()
  operationMasterDialogVisible.value = true
}

function validateOperationMasterForm() {
  if (!operationMasterForm.processCode.trim() || !operationMasterForm.processName.trim()) return '请填写工序编码和工序名称'
  if (!operationMasterForm.processCategory.trim() || !operationMasterForm.operationType.trim()) return '请填写工序分类和工序类型'
  if (operationMasterForm.defaultStandardTimeMins != null && operationMasterForm.defaultStandardTimeMins < 0) return '默认工时不能小于 0'
  try {
    const parsed = JSON.parse(operationMasterForm.defaultProcessParamJson || '{}')
    if (!parsed || Array.isArray(parsed) || typeof parsed !== 'object') return '默认参数必须是 JSON 对象'
  } catch {
    return '默认参数 JSON 格式不正确'
  }
  return ''
}

async function saveOperationMaster() {
  const validationError = validateOperationMasterForm()
  if (validationError) {
    ElMessage.warning(validationError)
    return
  }
  const created = await createProcessOperationMaster({
    ...operationMasterForm,
    processCode: operationMasterForm.processCode.trim(),
    processName: operationMasterForm.processName.trim(),
    processCategory: operationMasterForm.processCategory.trim(),
    operationType: operationMasterForm.operationType.trim(),
    operationCraftCode: operationMasterForm.operationCraftCode?.trim().toUpperCase() || null,
    defaultQualityRequirement: operationMasterForm.defaultQualityRequirement?.trim() || null,
    defaultProcessParamJson: operationMasterForm.defaultProcessParamJson?.trim() || '{}',
    workstationType: operationMasterForm.workstationType?.trim() || null,
    remark: operationMasterForm.remark?.trim() || null
  })
  await confirmProcessOperationMaster(created.processId)
  operationMasterDialogVisible.value = false
  await loadOperationMasterRows()
  ElMessage.success('工序已加入工序库')
}

const rows = computed(() => (snapshot.value?.routes || []).filter((item) => isWithinTimeRange(item.updatedAt, timeRange.value)))
const activeRouteId = computed(() => Number(route.query.routeId || 0) || null)
const isDetailMode = computed(() => Boolean(activeRouteId.value))

const sectionOptions = [
  { label: '概览', value: 'overview' },
  { label: '工序明细', value: 'operations' },
  { label: '资料挂接', value: 'attachments' },
  { label: '版本变更', value: 'changes' },
  { label: '联动影响', value: 'impacts' }
] as const

const searchFields: SearchField[] = [
  {
    prop: 'keyword',
    label: '关键词',
    type: 'input',
    placeholder: '路线编码 / 名称 / 产品编码 / 负责人'
  },
  {
    prop: 'routeType',
    label: '路线类型',
    type: 'select',
    options: [
      { label: '全部', value: '' },
      { label: '新产品线', value: 'new_product_line' },
      { label: '新型号线', value: 'new_model_variant' }
    ]
  },
  {
    prop: 'status',
    label: '状态',
    type: 'select',
    options: [
      { label: '全部', value: '' },
      { label: '草稿', value: 'draft' },
      { label: '已确认', value: 'confirmed' },
      { label: '已锁定', value: 'locked' },
      { label: '已发布', value: 'released' }
    ]
  },
  {
    prop: 'templateSource',
    label: '来源',
    type: 'select',
    options: [
      { label: '全部', value: '' },
      { label: '标准模板', value: 'standard' },
      { label: '继承差异', value: 'inherited' },
      { label: '手工调整', value: 'manual' }
    ]
  }
]

const table = useTable(rows, ['routeCode', 'routeName', 'productCode', 'productName', 'owner'], (row, filters) => {
  const routeType = String(filters.routeType || '')
  const status = String(filters.status || '')
  const templateSource = String(filters.templateSource || '')

  if (routeType && row.routeType !== routeType) return false
  if (status && row.status !== status) return false
  if (templateSource && row.templateSource !== templateSource) return false
  return true
})

const activeDetail = computed<ProcessRouteDetail | null>(() => {
  if (!snapshot.value || !activeRouteId.value) return null
  return snapshot.value.routeDetails[activeRouteId.value] || null
})

const activeRouteRow = computed<ProcessRouteListItem | null>(() => {
  if (!activeRouteId.value) return null
  return snapshot.value?.routes.find((item) => item.routeId === activeRouteId.value) || null
})

const overviewItems = computed(() => {
  const detail = activeDetail.value
  if (!detail) return []

  return [
    { label: '工序数量', value: `${detail.operations.length} 道` },
    { label: '工艺成本', value: formatAmount(detail.totalCost) },
    { label: '差异工序', value: `${detail.differenceOperationCount} 道` },
    { label: '当前门禁', value: detail.currentGate, emphasis: true },
    { label: '路线类型', value: routeTypeLabel(detail.routeType) },
    { label: '模板来源', value: templateSourceLabel(detail.templateSource) },
    { label: '负责人', value: detail.owner },
    { label: '继承来源', value: detail.inheritedFrom || '无继承来源' },
    { label: '锁定状态', value: detail.isLocked ? '已锁定' : '未锁定' },
    { label: '门禁结果', value: detail.passedGate ? '已通过' : '待补齐', emphasis: true }
  ]
})

const activeImpact = computed(() => {
  const impacts = activeDetail.value?.impacts || []
  return impacts.find((item) => item.label === activeImpactLabel.value) || impacts[0] || null
})

const activeImpactSummaryItems = computed(() => {
  const detail = activeDetail.value
  const impact = activeImpact.value
  if (!detail || !impact) return []

  if (impact.label.includes('产品')) {
    return [
      { label: '产品编码', value: detail.productCode },
      { label: '产品名称', value: detail.productName },
      { label: '工艺版本', value: detail.versionNo },
      { label: '当前状态', value: detail.status },
      { label: '当前进程', value: detail.currentGate }
    ]
  }

  if (impact.label.includes('质量')) {
    const qualityConfirmation = detail.confirmations.find((item) => item.roleName.includes('质量'))
    const qualitySpecCount = detail.attachments.reduce((sum, item) => sum + item.qualitySpecCount, 0)
    return [
      { label: '门禁结果', value: detail.passedGate ? '已通过' : '待补齐' },
      { label: '质量确认', value: qualityConfirmation?.status === 'approved' ? '已确认' : qualityConfirmation?.status === 'blocked' ? '阻塞' : '待确认' },
      { label: '质量负责人', value: qualityConfirmation?.ownerName || '--' },
      { label: '检验标准', value: `${qualitySpecCount} 份` },
      { label: '差异工序', value: `${detail.differenceOperationCount} 道` }
    ]
  }

  if (impact.label.includes('文件')) {
    const attachmentTotal = detail.attachments.reduce(
      (sum, item) => sum + item.sopCount + item.sipCount + item.parameterSheetCount + item.qualitySpecCount,
      0
    )
    const missingCount = detail.attachments.filter((item) => item.status === 'missing').length
    const sortedUpdatedAt = detail.attachments.map((item) => item.updatedAt).sort()
    const latestUpdatedAt = sortedUpdatedAt[sortedUpdatedAt.length - 1] || '--'
    return [
      { label: '资料总数', value: `${attachmentTotal} 份` },
      { label: '缺失工序', value: `${missingCount} 个` },
      { label: '最近更新', value: latestUpdatedAt },
      { label: '路线版本', value: detail.versionNo },
      { label: '锁定状态', value: detail.isLocked ? '已锁定' : '未锁定' }
    ]
  }

  return [
    { label: '关联对象', value: impact.label },
    { label: '摘要', value: impact.summary },
    { label: '产品', value: detail.productName },
    { label: '版本', value: detail.versionNo },
    { label: '进程', value: detail.currentGate }
  ]
})

const filteredOperationRows = computed(() => {
  const detail = activeDetail.value
  if (!detail) return []

  let operations = detail.operations
  if (viewMode.value === 'operation') {
    operations = operations.filter((item) => item.isKeyProcess || item.isDifferenceOperation)
  } else if (viewMode.value === 'change') {
    operations = operations.filter((item) => item.changedInCurrentVersion || item.isDifferenceOperation)
  }

  const keyword = operationKeyword.value.trim().toLowerCase()
  if (!keyword) return operations

  return operations.filter((item) => {
    const fields = [
      getOperationCode(item),
      item.operationName,
      item.operationType,
      item.workstationName,
      item.supplierName || '',
      item.confirmerName || '',
      item.confirmerRole || ''
    ]
    return fields.some((field) => field.toLowerCase().includes(keyword))
  })
})

async function loadSnapshot() {
  loading.value = true
  try {
    snapshot.value = await getProcessCenterSnapshot()
    table.setQuery({
      keyword: String(route.query.keyword || ''),
      routeType: String(route.query.routeType || ''),
      status: String(route.query.status || ''),
      templateSource: String(route.query.templateSource || '')
    })
    const mode = String(route.query.mode || 'route') as ProcessCenterViewMode
    viewMode.value = ['route', 'operation', 'change'].includes(mode) ? mode : 'route'
  } catch {
    snapshot.value = null
  } finally {
    loading.value = false
  }
}

async function openRouteRelation(row: ProcessRouteListItem) {
  relationDrawerVisible.value = true
  relationLoading.value = true
  activeRelation.value = null
  try {
    activeRelation.value = await getProcessRouteRelations(row.processId || row.routeId)
  } catch (error) {
    relationDrawerVisible.value = false
    ElMessage.error(error instanceof Error ? error.message : '工艺路线详情加载失败')
  } finally {
    relationLoading.value = false
  }
}

async function openRouteSkus(row: ProcessRouteListItem) {
  await openRouteRelation(row)
}

function backToList() {
  const nextQuery = { ...route.query }
  delete nextQuery.routeId
  activeSection.value = 'overview'
  operationKeyword.value = ''
  router.push({ path: '/processes', query: nextQuery })
}

function syncViewMode(mode: ProcessCenterViewMode) {
  viewMode.value = mode
}

function openTarget(path: string) {
  router.push(normalizeLegacyProductTarget(path))
}

function routeTypeLabel(type: ProcessRouteListItem['routeType']) {
  return type === 'new_product_line' ? '新产品线' : '新型号线'
}

function templateSourceLabel(source: ProcessRouteListItem['templateSource']) {
  if (source === 'standard') return '标准模板'
  if (source === 'inherited') return '继承差异'
  return '手工调整'
}

function attachmentStatusLabel(status: string) {
  if (status === 'complete') return '齐套'
  if (status === 'partial') return '待补'
  return '缺失'
}

function getOperationTypeLabel(type: string) {
  if (type === 'semi_finished') return '半成品'
  if (type === 'finished') return '成品'
  return type
}

function getOperationCode(operation: ProcessOperationRecord) {
  if (operation.operationCode) return operation.operationCode
  const prefix = activeDetail.value?.routeCode || 'PROC'
  return `${prefix}-${String(operation.sequenceNo).padStart(3, '0')}`
}

function previewAttachment(row: ProcessAttachmentSummary) {
  if (!row.previewPath) {
    ElMessage.info('当前工序暂无可预览资料')
    return
  }
  ElMessage.info(`预览 ${row.operationName} 的资料`)
}

function addAttachment(row: ProcessAttachmentSummary) {
  if (row.canAdd === false) {
    ElMessage.info('当前状态暂不能添加资料')
    return
  }
  ElMessage.info(`为 ${row.operationName} 添加资料`)
}

function applyChange() {
  ElMessage.info('变更申请入口已预留')
}

function finalizeChange() {
  ElMessage.info('敲定入口已预留')
}

watch(
  () => activeDetail.value?.routeId,
  () => {
    activeImpactLabel.value = activeDetail.value?.impacts[0]?.label || ''
  },
  { immediate: true }
)

onMounted(async () => {
  await Promise.all([loadOperationMasterRows(), loadRouteTemplateRows(), loadSnapshot()])
})
</script>

<template>
  <PageContainer
    title="工艺管理"
    description="集中维护工序库、标准工艺路线，并查看项目工艺路线、工序结构、资料挂接和版本追溯。"
  >
    <section class="process-management-tabs">
      <el-segmented v-model="activeManagementTab" :options="processTabOptions" />
    </section>

    <section v-if="activeManagementTab === 'operation-master'" class="page-panel route-table-panel" v-loading="operationMasterLoading">
      <div class="toolbar-row route-table-panel__header">
        <div>
          <h3 class="section-title">工序库</h3>
          <p class="page-panel-desc">工序名称由基础资料维护，工作台和项目中心只能选择这里已确认的工序。</p>
        </div>
        <div class="header-actions">
          <el-button :icon="Refresh" circle title="刷新工序库" @click="loadOperationMasterRows" />
          <el-button type="primary" :icon="Plus" @click="openOperationMasterCreate">新增工序</el-button>
        </div>
      </div>

      <FixedTableViewport v-slot="{ tableHeight }" :refresh-key="operationMasterRows">
      <el-table :data="operationMasterRows" :height="tableHeight" border stripe>
        <el-table-column prop="processCode" label="工序编码" min-width="150" />
        <el-table-column prop="processName" label="工序名称" min-width="150" />
        <el-table-column prop="processCategory" label="工序分类" min-width="120" />
        <el-table-column prop="operationType" label="工序类型" min-width="120" />
        <el-table-column prop="operationCraftCode" label="工艺编码" width="100">
          <template #default="{ row }">{{ row.operationCraftCode || '--' }}</template>
        </el-table-column>
        <el-table-column prop="defaultStandardTimeMins" label="默认工时" width="110" />
        <el-table-column prop="defaultQualityRequirement" label="默认质量要求" min-width="220" show-overflow-tooltip />
        <el-table-column label="需要工位" width="100">
          <template #default="{ row }">{{ row.needWorkstation ? '是' : '否' }}</template>
        </el-table-column>
        <el-table-column prop="workstationType" label="工位类型" min-width="120">
          <template #default="{ row }">{{ row.workstationType || '--' }}</template>
        </el-table-column>
        <el-table-column label="状态" width="110">
          <template #default="{ row }">
            <StatusTag :status="row.status" object-type="process" />
          </template>
        </el-table-column>
      </el-table>
      </FixedTableViewport>
    </section>

    <section v-else-if="activeManagementTab === 'route-template'" class="page-panel route-table-panel" v-loading="routeTemplateLoading">
      <div class="toolbar-row route-table-panel__header">
        <div>
          <h3 class="section-title">标准工艺路线</h3>
          <p class="page-panel-desc">标准路线由工序库组合而成，工作台编写项目路线时可按模板复制。</p>
        </div>
        <el-button :icon="Refresh" circle title="刷新标准工艺路线" @click="loadRouteTemplateRows" />
      </div>

      <FixedTableViewport v-slot="{ tableHeight }" :refresh-key="routeTemplateRows">
      <el-table :data="routeTemplateRows" :height="tableHeight" border stripe>
        <el-table-column prop="routeTemplateCode" label="路线编码" min-width="170" />
        <el-table-column prop="routeTemplateName" label="路线名称" min-width="180" />
        <el-table-column prop="versionNo" label="版本" width="90" />
        <el-table-column prop="productCode" label="适用产品" min-width="130">
          <template #default="{ row }">{{ row.productCode || '通用' }}</template>
        </el-table-column>
        <el-table-column label="默认" width="90">
          <template #default="{ row }"><el-tag v-if="row.defaultTemplate" type="success" effect="light">默认</el-tag><span v-else>--</span></template>
        </el-table-column>
        <el-table-column label="工序数" width="100">
          <template #default="{ row }">{{ row.operations?.length || 0 }}</template>
        </el-table-column>
        <el-table-column label="工序组合" min-width="320" show-overflow-tooltip>
          <template #default="{ row }">
            {{ row.operations?.map((item: ProcessRouteTemplateOperationVO) => item.processName).join(' / ') || '--' }}
          </template>
        </el-table-column>
        <el-table-column label="状态" width="110">
          <template #default="{ row }">
            <StatusTag :status="row.status || 'confirmed'" object-type="process" />
          </template>
        </el-table-column>
      </el-table>
      </FixedTableViewport>
    </section>

    <SearchBar
      v-if="activeManagementTab === 'project-route' && !isDetailMode"
      :fields="searchFields"
      :model-value="table.query"
      @search="table.setQuery"
      @reset="table.resetQuery({ keyword: '', routeType: '', status: '', templateSource: '' })"
    >
      <template #extra>
        <ProjectTimeRangeFilter v-model="timeRange" />
      </template>
    </SearchBar>

    <section v-if="activeManagementTab === 'project-route' && !isDetailMode" class="page-panel route-table-panel" v-loading="loading">
      <div class="toolbar-row route-table-panel__header">
        <div>
          <h3 class="section-title">项目工艺路线</h3>
          <p class="page-panel-desc">先找到项目工艺路线，再在右侧抽屉查看适用颜色、关联 SKU 和工序明细。</p>
        </div>
        <el-tag effect="light">共 {{ table.filteredRows.value.length }} 条</el-tag>
      </div>

      <FixedTableViewport v-slot="{ tableHeight }" :refresh-key="table.filteredRows.value">
      <el-table :data="table.filteredRows.value" :height="tableHeight" border stripe class="route-table">
        <el-table-column prop="routeCode" label="路线编号" min-width="170" />
        <el-table-column label="所属项目" min-width="230"><template #default="{ row }"><strong>{{ row.productName }}</strong></template></el-table-column>
        <el-table-column prop="routeName" label="工序名称" min-width="230" />
        <el-table-column label="适用颜色" min-width="180">
          <template #default="{ row }">
            <div v-if="row.colors?.length" class="tag-wrap">
              <el-tag v-for="color in row.colors.slice(0, 3)" :key="`${row.routeId}-${color.colorCode || color.colorName}`" size="small" effect="light">{{ color.colorName }}</el-tag>
              <el-tag v-if="row.colors.length > 3" size="small" effect="plain">+{{ row.colors.length - 3 }}</el-tag>
            </div>
            <span v-else class="subtle-text">尚未关联颜色</span>
          </template>
        </el-table-column>
        <el-table-column label="关联 SKU" width="120">
          <template #default="{ row }">
            <el-button data-test="process-route-skus" link type="primary" @click="openRouteSkus(row)">{{ row.skuCount || 0 }} 个 SKU</el-button>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="120">
          <template #default="{ row }">
            <StatusTag :status="row.status" object-type="process" />
          </template>
        </el-table-column>
        <el-table-column prop="currentGate" label="进程" min-width="170" />
        <el-table-column prop="versionNo" label="版本" width="90" />
        <el-table-column label="操作" width="110" fixed="right">
          <template #default="{ row }">
            <el-button data-test="process-route-detail" link type="primary" @click="openRouteRelation(row)">详情</el-button>
          </template>
        </el-table-column>
      </el-table>
      </FixedTableViewport>
    </section>

    <article v-else-if="activeManagementTab === 'project-route' && activeDetail" class="page-panel detail-panel">
      <div class="detail-topline">
        <el-button link type="primary" :icon="ArrowLeft" @click="backToList">返回列表</el-button>
      </div>

      <div class="toolbar-row detail-header">
        <div>
          <h3 class="section-title">{{ activeDetail.routeName }}</h3>
          <div class="detail-breadcrumb">
            <span>工艺管理</span>
            <span>{{ activeDetail.productName }}</span>
            <span>{{ activeDetail.routeCode }}</span>
            <span>版本 {{ activeDetail.versionNo }}</span>
          </div>
        </div>
        <div class="header-actions">
          <StatusTag :status="activeDetail.status" object-type="process" />
          <el-button link type="primary" @click="openTarget(`/products/${activeDetail.productId}`)">产品详情</el-button>
        </div>
      </div>

      <section class="section-nav">
        <el-segmented v-model="activeSection" :options="sectionOptions" class="section-switcher" />
      </section>

      <section v-if="activeSection === 'overview'" class="page-stack detail-section">
        <section class="split-grid overview-detail-grid">
          <article class="page-panel inner-panel">
            <div class="toolbar-row">
              <h3 class="section-title">工序视图</h3>
            </div>
            <p class="page-panel-desc">概览区收纳原有数据板信息，具体工序在“工序明细”里查看和搜索。</p>
          </article>

          <article class="page-panel inner-panel">
            <h3 class="section-title">当前对象</h3>
            <div class="object-lines">
              <span>{{ activeDetail.productCode }}</span>
              <strong>{{ activeDetail.productName }}</strong>
              <span>{{ activeRouteRow ? routeTypeLabel(activeRouteRow.routeType) : routeTypeLabel(activeDetail.routeType) }}</span>
            </div>
          </article>
        </section>

        <section class="overview-panel">
          <div class="summary-box summary-box--note">
            <span class="subtle-text">概览</span>
            <strong>{{ activeDetail.overviewNote }}</strong>
          </div>

          <div class="overview-grid">
            <div v-for="item in overviewItems" :key="item.label" class="overview-item">
              <span class="subtle-text">{{ item.label }}</span>
              <strong :class="{ 'is-emphasis': item.emphasis }">{{ item.value }}</strong>
            </div>
          </div>
        </section>
      </section>

      <section v-else-if="activeSection === 'operations'" class="page-stack detail-section">
        <div class="toolbar-row">
          <div>
            <h3 class="section-title">工序明细</h3>
            <p class="page-panel-desc">按工序查看参数、质量要求、责任确认人和关键标记。</p>
          </div>
          <div class="operation-toolbar">
            <el-segmented
              :model-value="viewMode"
              :options="[
                { label: '全部工序', value: 'route' },
                { label: '关键工序', value: 'operation' },
                { label: '变更工序', value: 'change' }
              ]"
              @change="(value: string | number) => syncViewMode(value as ProcessCenterViewMode)"
            />
            <el-input v-model="operationKeyword" clearable placeholder="搜索工序 / 位置 / 供应商" class="operation-search" />
          </div>
        </div>

        <el-table :data="filteredOperationRows" border stripe>
          <el-table-column prop="sequenceNo" label="顺序" width="80" />
          <el-table-column label="工序编码" min-width="150">
            <template #default="{ row }">
              {{ getOperationCode(row) }}
            </template>
          </el-table-column>
          <el-table-column prop="operationName" label="工序名称" min-width="150" />
          <el-table-column label="工序类型" min-width="120">
            <template #default="{ row }">
              {{ getOperationTypeLabel(row.operationType) }}
            </template>
          </el-table-column>
          <el-table-column prop="workstationName" label="执行位置" min-width="170" />
          <el-table-column prop="supplierName" label="供应商" min-width="140">
            <template #default="{ row }">{{ row.supplierName || '--' }}</template>
          </el-table-column>
          <el-table-column label="确认人" min-width="140">
            <template #default="{ row }">
              <div class="cell-stack">
                <strong>{{ row.confirmerName || '--' }}</strong>
                <span class="subtle-text">{{ row.confirmerRole || '未指定' }}</span>
              </div>
            </template>
          </el-table-column>
          <el-table-column prop="parameterSummary" label="核心参数摘要" min-width="220" />
          <el-table-column prop="qualityRequirement" label="质量要求" min-width="180" />
          <el-table-column label="单工序成本" width="130">
            <template #default="{ row }">{{ formatAmount(row.unitCost) }}</template>
          </el-table-column>
          <el-table-column label="标记" min-width="170">
            <template #default="{ row }">
              <div class="tag-wrap">
                <el-tag v-if="row.isKeyProcess" type="warning" effect="light">关键工序</el-tag>
                <el-tag v-if="row.isExternalOperation" type="success" effect="light">外协</el-tag>
                <el-tag v-if="row.isDifferenceOperation" type="info" effect="light">差异</el-tag>
                <el-tag v-if="row.changedInCurrentVersion" type="danger" effect="light">本版变更</el-tag>
              </div>
            </template>
          </el-table-column>
        </el-table>
      </section>

      <section v-else-if="activeSection === 'attachments'" class="page-stack detail-section">
        <div class="toolbar-row">
          <div>
            <h3 class="section-title">资料挂接</h3>
            <p class="page-panel-desc">按工序查看 SOP、SIP、参数表和检验标准是否齐套。</p>
          </div>
        </div>

        <el-table :data="activeDetail.attachments" border stripe>
          <el-table-column prop="operationName" label="工序" min-width="150" />
          <el-table-column prop="sopCount" label="SOP" width="70" />
          <el-table-column prop="sipCount" label="SIP" width="70" />
          <el-table-column prop="parameterSheetCount" label="参数表" width="90" />
          <el-table-column prop="qualitySpecCount" label="检验标准" width="90" />
          <el-table-column label="状态" width="100">
            <template #default="{ row }">
              <el-tag :type="row.status === 'complete' ? 'success' : row.status === 'partial' ? 'warning' : 'danger'" effect="light">
                {{ attachmentStatusLabel(row.status) }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="updatedAt" label="最近更新" width="140" />
          <el-table-column label="操作" width="150" fixed="right">
            <template #default="{ row }">
              <div class="table-actions">
                <el-button link type="primary" @click="previewAttachment(row)">预览</el-button>
                <el-button link type="success" :disabled="row.canAdd === false" @click="addAttachment(row)">添加</el-button>
              </div>
            </template>
          </el-table-column>
        </el-table>
      </section>

      <section v-else-if="activeSection === 'changes'" class="page-stack detail-section">
        <div class="toolbar-row">
          <div>
            <h3 class="section-title">版本变更</h3>
            <p class="page-panel-desc">聚焦这条路线的版本变化、原因和影响。</p>
          </div>
          <div class="header-actions">
            <el-button plain :disabled="activeDetail.canApplyChange === false" @click="applyChange">变更申请</el-button>
            <el-button type="primary" :disabled="activeDetail.canFinalize === false" @click="finalizeChange">敲定</el-button>
          </div>
        </div>

        <div class="page-stack">
          <div v-for="item in activeDetail.changes" :key="`${item.versionNo}-${item.changedAt}`" class="change-card">
            <div class="toolbar-row">
              <strong>版本 {{ item.versionNo }} / {{ item.changeType }}</strong>
              <span>{{ item.changedAt }}</span>
            </div>
            <p class="page-panel-desc">{{ item.changeReason }}</p>
            <p class="subtle-text">涉及工序：{{ item.affectedOperations.join('、') }}</p>
            <div class="route-meta route-meta--compact">
              <span>成本变化 {{ formatAmount(item.costDelta) }}</span>
              <span>交期变化 {{ item.leadDayDelta }} 天</span>
              <span>责任人 {{ item.ownerName }}</span>
            </div>
          </div>
        </div>
      </section>

      <section v-else class="page-stack detail-section">
        <div class="toolbar-row">
          <div>
            <h3 class="section-title">联动影响</h3>
            <p class="page-panel-desc">点击左侧联动项，在右侧查看当前路线相关摘要。</p>
          </div>
        </div>

        <div class="impact-preview-layout">
          <div class="page-stack impact-list">
            <button
              v-for="item in activeDetail.impacts"
              :key="item.label"
              class="impact-card"
              :class="{ 'is-active': activeImpact?.label === item.label }"
              type="button"
              @click="activeImpactLabel = item.label"
            >
              <div class="toolbar-row">
                <strong>{{ item.label }}</strong>
                <el-icon><ArrowRight /></el-icon>
              </div>
              <p class="page-panel-desc">{{ item.summary }}</p>
            </button>
          </div>

          <article v-if="activeImpact" class="impact-preview-panel">
            <div class="toolbar-row">
              <div>
                <h3 class="section-title">{{ activeImpact.label }}</h3>
                <p class="page-panel-desc">{{ activeImpact.summary }}</p>
              </div>
              <el-button link type="primary" @click="openTarget(activeImpact.targetPath)">查看完整页面</el-button>
            </div>

            <div class="impact-summary-grid">
              <div v-for="item in activeImpactSummaryItems" :key="item.label" class="overview-item">
                <span class="subtle-text">{{ item.label }}</span>
                <strong>{{ item.value }}</strong>
              </div>
            </div>
          </article>
        </div>
      </section>
    </article>

    <el-dialog v-model="operationMasterDialogVisible" title="新增工序" width="min(720px, 94vw)" append-to-body>
      <el-form label-width="112px" class="operation-master-form">
        <el-form-item label="工序编码" required>
          <el-input v-model="operationMasterForm.processCode" maxlength="80" placeholder="例如 PROC_LAMINATION" />
        </el-form-item>
        <el-form-item label="工序名称" required>
          <el-input v-model="operationMasterForm.processName" maxlength="100" placeholder="例如 压合" />
        </el-form-item>
        <el-form-item label="工序分类" required>
          <el-select v-model="operationMasterForm.processCategory" filterable allow-create default-first-option placeholder="选择或输入分类">
            <el-option label="成型" value="成型" />
            <el-option label="后处理" value="后处理" />
            <el-option label="表面处理" value="表面处理" />
            <el-option label="组装" value="组装" />
            <el-option label="包装" value="包装" />
            <el-option label="质检" value="质检" />
          </el-select>
        </el-form-item>
        <el-form-item label="工序类型" required>
          <el-select v-model="operationMasterForm.operationType">
            <el-option label="加工" value="加工" />
            <el-option label="检验" value="检验" />
            <el-option label="包装" value="包装" />
            <el-option label="外协" value="外协" />
          </el-select>
        </el-form-item>
        <el-form-item label="工艺编码">
          <el-input v-model="operationMasterForm.operationCraftCode" maxlength="20" placeholder="如 10 / 20 / 30" />
        </el-form-item>
        <el-form-item label="默认工时">
          <el-input-number v-model="operationMasterForm.defaultStandardTimeMins" :min="0" :precision="2" controls-position="right" />
        </el-form-item>
        <el-form-item label="需要工位">
          <el-switch v-model="operationMasterForm.needWorkstation" />
        </el-form-item>
        <el-form-item label="工位类型">
          <el-input v-model="operationMasterForm.workstationType" maxlength="80" placeholder="例如 注塑机 / 组装工位" />
        </el-form-item>
        <el-form-item label="质量要求" class="operation-master-form__wide">
          <el-input v-model="operationMasterForm.defaultQualityRequirement" maxlength="500" type="textarea" :rows="2" />
        </el-form-item>
        <el-form-item label="默认参数" class="operation-master-form__wide">
          <el-input v-model="operationMasterForm.defaultProcessParamJson" type="textarea" :rows="3" placeholder='例如 {"temperature":"按工艺卡"}' />
        </el-form-item>
        <el-form-item label="备注" class="operation-master-form__wide">
          <el-input v-model="operationMasterForm.remark" maxlength="500" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="operationMasterDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="saveOperationMaster">保存并确认</el-button>
      </template>
    </el-dialog>

    <el-drawer
      v-model="relationDrawerVisible"
      :title="`工艺路线详情：${activeRelation?.processName || ''}`"
      size="min(920px, 96vw)"
      append-to-body
    >
      <div v-loading="relationLoading" class="relation-drawer">
        <template v-if="activeRelation">
          <section class="relation-section">
            <h3 class="section-title">路线信息</h3>
            <dl class="relation-facts">
              <div><dt>路线编号</dt><dd>{{ activeRelation.processCode }}</dd></div>
              <div><dt>工序名称</dt><dd>{{ activeRelation.processName }}</dd></div>
              <div><dt>所属产品</dt><dd>{{ activeRelation.productName }}</dd></div>
              <div><dt>版本</dt><dd>{{ activeRelation.versionNo }}</dd></div>
              <div><dt>状态</dt><dd><StatusTag :status="activeRelation.status" object-type="process" /></dd></div>
            </dl>
          </section>

          <section class="relation-section">
            <h3 class="section-title">适用颜色</h3>
            <div v-if="activeRelation.colors.length" class="tag-wrap">
              <el-tag v-for="color in activeRelation.colors" :key="color.colorCode || color.colorName" effect="light">{{ color.colorName }}</el-tag>
            </div>
            <el-empty v-else description="尚未关联适用颜色" />
          </section>

          <section class="relation-section">
            <h3 class="section-title">关联 SKU</h3>
            <el-table :data="activeRelation.skus" border stripe empty-text="暂无关联 SKU">
              <el-table-column prop="skuCode" label="SKU 编码" min-width="160" />
              <el-table-column prop="productName" label="产品" min-width="150" />
              <el-table-column prop="phoneModel" label="手机型号" min-width="150" />
              <el-table-column prop="color" label="颜色" width="110" />
              <el-table-column label="状态" width="110">
                <template #default="{ row }"><StatusTag :status="row.status" object-type="product" /></template>
              </el-table-column>
            </el-table>
          </section>

          <section class="relation-section">
            <h3 class="section-title">工序明细</h3>
            <el-table :data="activeRelation.operations" border stripe empty-text="暂无工序明细">
              <el-table-column prop="sequenceNo" label="顺序" width="80" />
              <el-table-column prop="processName" label="工序名称" min-width="150" />
              <el-table-column label="工艺编码" min-width="130">
                <template #default="{ row }">{{ row.operationCraftCode || row.operationCode || row.processCode || '--' }}</template>
              </el-table-column>
              <el-table-column prop="qualityRequirement" label="质量要求" min-width="220" />
            </el-table>
          </section>
        </template>
      </div>
    </el-drawer>
  </PageContainer>
</template>

<style scoped>
.process-management-tabs {
  margin-bottom: 14px;
}

.operation-master-form {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px 12px;
}

.operation-master-form__wide {
  grid-column: 1 / -1;
}

.route-table-panel,
.detail-panel {
  min-height: 0;
}

.route-table-panel__header {
  margin-bottom: 14px;
}

.route-table {
  width: 100%;
}

.detail-topline {
  margin-bottom: 10px;
}

.detail-header {
  align-items: flex-start;
  gap: 16px;
}

.detail-breadcrumb {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  margin-top: 8px;
  color: var(--plm-color-text-secondary);
  font-size: var(--plm-font-size-sm);
}

.detail-breadcrumb span + span::before {
  content: '/';
  margin-right: 8px;
  color: var(--plm-color-text-placeholder);
}

.header-actions,
.operation-toolbar,
.table-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}

.operation-toolbar {
  flex-wrap: wrap;
  justify-content: flex-end;
}

.operation-search {
  width: 260px;
}

.overview-panel {
  display: grid;
  grid-template-columns: minmax(260px, 0.85fr) minmax(0, 1.6fr);
  gap: 14px;
  align-items: stretch;
}

.summary-box,
.overview-item,
.info-card,
.gate-card,
.change-card {
  padding: 14px;
  border: 1px solid var(--plm-color-border-light);
  border-radius: var(--plm-radius-base);
  background: #fff;
}

.summary-box {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.summary-box--note {
  background: linear-gradient(135deg, rgba(236, 253, 245, 0.86), rgba(255, 255, 255, 0.96));
}

.overview-grid {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 10px;
}

.overview-item {
  min-height: 74px;
  display: flex;
  flex-direction: column;
  justify-content: center;
  gap: 6px;
  background: rgba(248, 250, 252, 0.88);
}

.overview-item strong {
  color: var(--plm-color-text-primary);
}

.overview-item strong.is-emphasis {
  color: var(--plm-color-primary);
}

.section-nav {
  margin-top: 18px;
  padding-top: 2px;
}

.section-switcher {
  width: 100%;
}

.detail-section {
  margin-top: 16px;
}

.overview-detail-grid,
.inner-grid {
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.inner-panel {
  min-height: 100%;
}

.object-lines {
  display: flex;
  flex-direction: column;
  gap: 8px;
  color: var(--plm-color-text-secondary);
}

.object-lines strong {
  color: var(--plm-color-text-primary);
}

.cell-stack {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.route-meta {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-top: 10px;
  color: var(--plm-color-text-secondary);
  font-size: var(--plm-font-size-sm);
}

.route-meta--compact {
  justify-content: flex-start;
  flex-wrap: wrap;
}

.impact-preview-layout {
  display: grid;
  grid-template-columns: minmax(280px, 0.9fr) minmax(0, 1.1fr);
  gap: 16px;
  align-items: stretch;
}

.impact-list {
  max-width: none;
}

.impact-card {
  width: 100%;
  padding: 14px;
  border: 1px solid var(--plm-color-border-light);
  border-radius: var(--plm-radius-base);
  background: #fff;
  text-align: left;
  cursor: pointer;
  transition: border-color 0.16s ease, box-shadow 0.16s ease, transform 0.16s ease;
}

.impact-card:hover {
  border-color: var(--plm-color-primary);
  box-shadow: var(--plm-shadow-md);
  transform: translateY(-1px);
}

.impact-card.is-active {
  border-color: var(--plm-color-primary);
  background: rgba(37, 99, 235, 0.06);
  box-shadow: 0 10px 24px rgba(37, 99, 235, 0.1);
}

.impact-card.is-active strong {
  color: var(--plm-color-primary);
}

.impact-preview-panel {
  min-height: 260px;
  padding: 16px;
  border: 1px solid var(--plm-color-border-light);
  border-radius: var(--plm-radius-base);
  background: #fff;
}

.impact-summary-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
  margin-top: 16px;
}

.tag-wrap {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.relation-drawer {
  min-height: 240px;
}

.relation-section + .relation-section {
  margin-top: 18px;
}

.relation-facts {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px 18px;
  margin: 0;
}

.relation-facts div {
  min-width: 0;
  padding-bottom: 10px;
  border-bottom: 1px solid var(--plm-color-border-light);
}

.relation-facts dt {
  color: var(--plm-color-text-secondary);
  font-size: var(--plm-font-size-sm);
}

.relation-facts dd {
  margin: 5px 0 0;
  min-width: 0;
  overflow: hidden;
  color: var(--plm-color-text-primary);
  text-overflow: ellipsis;
  white-space: nowrap;
}

@media (max-width: 1280px) {
  .overview-panel,
  .overview-detail-grid,
  .inner-grid,
  .impact-preview-layout {
    grid-template-columns: 1fr;
  }

  .overview-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 720px) {
  .operation-master-form {
    grid-template-columns: 1fr;
  }

  .detail-header,
  .header-actions,
  .operation-toolbar {
    align-items: flex-start;
    flex-direction: column;
  }

  .operation-search {
    width: 100%;
  }

  .overview-grid {
    grid-template-columns: 1fr;
  }

  .impact-summary-grid {
    grid-template-columns: 1fr;
  }

  .relation-facts {
    grid-template-columns: 1fr;
  }
}
</style>
