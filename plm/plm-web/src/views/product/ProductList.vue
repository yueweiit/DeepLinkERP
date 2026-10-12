<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { getProductList } from '@/api/modules/product'
import FixedTableViewport from '@/components/FixedTableViewport/index.vue'
import PageContainer from '@/components/PageContainer/index.vue'
import SearchBar from '@/components/SearchBar/index.vue'
import StatusTag from '@/components/StatusTag/index.vue'
import { useTable } from '@/composables/useTable'
import type { SearchField } from '@/types/common'
import type { ProductSummary } from '@/types/product'
import { formatAmount } from '@/utils/format'
import { toArchivedProductRoute, toArchivedSkuRoute, toInProgressProjectRoute } from '@/utils/projectRoute'

type LifecycleKey = 'all' | 'initiation' | 'design' | 'tooling' | 'sampling' | 'process' | 'pilot' | 'mx' | 'release'

interface LifecycleOption {
  key: LifecycleKey
  label: string
  hint: string
}

const router = useRouter()
const route = useRoute()
const rows = ref<ProductSummary[]>([])
const loading = ref(false)
const loadError = ref('')

const lifecycleOptions: LifecycleOption[] = [
  { key: 'all', label: '全部产品', hint: '统一查看新产品线、新型号线与已发布版本。' },
  { key: 'initiation', label: '立项确认', hint: '需求来源、立项入口、子版本建立与责任人确认。' },
  { key: 'design', label: '设计差异', hint: '图纸、外观、差异结构与供应商可行性确认。' },
  { key: 'tooling', label: '模具处理', hint: '开模、改模、试模与模具风险收口。' },
  { key: 'sampling', label: '样品签核', hint: '签样、红样、差异样与样品确认。' },
  { key: 'process', label: '工艺 / BOM', hint: '工艺路线、组件、BOM、资料整理与冻结准备。' },
  { key: 'pilot', label: '小批验证', hint: '小批量、产线节拍、不良率与量产准备。' },
  { key: 'mx', label: 'MX 验证', hint: '运模、MX 验收、墨西哥端小批验证。' },
  { key: 'release', label: '冻结发布', hint: '版本冻结、正式发布与历史追溯。' }
]

const lifecycleTitleMap: Record<LifecycleKey, { title: string; description: string }> = {
  all: {
    title: '产品管理',
    description: '按产品线与型号线统一查看当前研发池，详情页承接流程、BOM、质量、文件、版本与日志。'
  },
  initiation: {
    title: '立项确认阶段',
    description: '关注新产品线立项与新型号线需求确认，确保入口判断和责任归属正确。'
  },
  design: {
    title: '设计差异阶段',
    description: '关注结构图纸、外观差异、供应商可行性反馈，以及父产品继承边界。'
  },
  tooling: {
    title: '模具处理阶段',
    description: '区分新产品线完整开模和新型号线改模 / 新开模 / 跳过三种分支。'
  },
  sampling: {
    title: '样品签核阶段',
    description: '聚焦签样、红样、差异样与关键验证节点。'
  },
  process: {
    title: '工艺与 BOM 阶段',
    description: '聚焦工艺路线、组件确认、BOM、SIP / SOP 与冻结前准备。'
  },
  pilot: {
    title: '小批验证阶段',
    description: '聚焦产线跑通、节拍、不良率、治具与工人熟练度。'
  },
  mx: {
    title: 'MX 验证阶段',
    description: '聚焦运模、MX 验收、墨西哥端试产与小批量验证。'
  },
  release: {
    title: '冻结发布阶段',
    description: '统一查看版本冻结、正式发布和历史沉淀版本。'
  }
}

const searchFields: SearchField[] = [
  { prop: 'keyword', label: '关键词', type: 'input', placeholder: '编码 / 名称 / 系列 / 机型 / 颜色 / 负责人' },
  {
    prop: 'productType',
    label: '产品类型',
    type: 'select',
    options: [
      { label: '全部', value: '' },
      { label: '新产品线', value: 'product_line' },
      { label: '新型号线', value: 'model_variant' }
    ]
  },
  {
    prop: 'status',
    label: '状态',
    type: 'select',
    options: [
      { label: '全部', value: '' },
      { label: '开发中', value: 'developing' },
      { label: '已发布', value: 'released' }
    ]
  }
]

function getLifecycle(item: ProductSummary): LifecycleKey {
  if (item.lifecycle) return item.lifecycle
  if (item.status === 'released') return 'release'
  return 'initiation'
}

function getFlowLabel(item: ProductSummary) {
  return item.productType === 'product_line' ? '新产品线' : '新型号线'
}

function getFlowHint(item: ProductSummary) {
  return item.productType === 'product_line' ? '完整 22 步研发链路' : '基于父产品的 16 步差异链路'
}

function getMoldActionLabel(item: ProductSummary) {
  if (item.productType === 'product_line') return '完整开模'
  if (item.moldAction === 'modify') return '改模'
  if (item.moldAction === 'new') return '新开模'
  if (item.moldAction === 'none') return '无需模具变更'
  return '--'
}

function matchesLifecycle(item: ProductSummary, lifecycle: LifecycleKey) {
  if (lifecycle === 'all') return true
  return getLifecycle(item) === lifecycle
}

const table = useTable(
  rows,
  ['productCode', 'productName', 'seriesName', 'customerName', 'model', 'color', 'ownerUserName'],
  (row, filters) => {
    const status = String(filters.status || '')
    const frozen = String(filters.frozen || '')
    const productType = String(filters.productType || '')
    const lifecycle = String(filters.lifecycle || 'all') as LifecycleKey

    if (status && row.status !== status) return false
    if (productType && row.productType !== productType) return false
    if (frozen === 'unfrozen' && row.frozenFlag) return false
    if (frozen === 'frozen' && !row.frozenFlag) return false
    if (!matchesLifecycle(row, lifecycle)) return false
    return true
  }
)

const currentLifecycle = computed(() => {
  const value = String(table.query.lifecycle || 'all') as LifecycleKey
  return lifecycleOptions.find((item) => item.key === value) || lifecycleOptions[0]
})

const filteredRows = computed(() => table.filteredRows.value as unknown as ProductSummary[])

const lifecycleCounters = computed<Record<LifecycleKey, number>>(() => {
  const source = rows.value
  return lifecycleOptions.reduce(
    (acc, item) => {
      acc[item.key] = source.filter((row) => matchesLifecycle(row, item.key)).length
      return acc
    },
    {
      all: source.length,
      initiation: 0,
      design: 0,
      tooling: 0,
      sampling: 0,
      process: 0,
      pilot: 0,
      mx: 0,
      release: 0
    } as Record<LifecycleKey, number>
  )
})

const stageStats = computed(() => {
  const list = filteredRows.value
  return {
    total: list.length,
    productLines: list.filter((item) => item.productType === 'product_line').length,
    modelVariants: list.filter((item) => item.productType === 'model_variant').length,
    pendingFreeze: list.filter((item) => !item.frozenFlag && item.status !== 'released').length,
    avgCost: list.length ? list.reduce((sum, item) => sum + (item.totalCost || item.estimatedCost), 0) / list.length : 0
  }
})

const highlightedRows = computed(() =>
  filteredRows.value
    .slice()
    .sort((a, b) => {
      return (b.currentStepNo || 0) - (a.currentStepNo || 0)
    })
    .slice(0, 4)
)

function buildQueryFromRoute() {
  table.setQuery({
    keyword: String(route.query.keyword || ''),
    status: String(route.query.status || ''),
    frozen: String(route.query.frozen || ''),
    productType: String(route.query.productType || ''),
    lifecycle: (String(route.query.lifecycle || 'all') as LifecycleKey) || 'all'
  })
}

function setLifecycle(lifecycle: LifecycleKey) {
  router.push({
    path: '/products',
    query: {
      ...route.query,
      lifecycle
    }
  })
}

function setProductType(type: '' | 'product_line' | 'model_variant') {
  table.setQuery({
    ...table.query,
    productType: type
  })
}

function openProduct(productId: number) {
  router.push(toArchivedProductRoute(productId))
}

watch(
  () => route.query,
  () => buildQueryFromRoute(),
  { deep: true }
)

onMounted(async () => {
  buildQueryFromRoute()
  loading.value = true
  loadError.value = ''
  try {
    rows.value = await getProductList()
  } catch (error) {
    rows.value = []
    loadError.value = error instanceof Error ? error.message : '产品列表接口未接入'
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <PageContainer :title="lifecycleTitleMap[currentLifecycle.key].title" :description="lifecycleTitleMap[currentLifecycle.key].description">
    <template #actions>
      <el-button @click="router.push(toArchivedSkuRoute())">归档 SKU</el-button>
      <el-button type="primary" @click="router.push(toInProgressProjectRoute())">新项目</el-button>
    </template>

    <section class="metric-grid product-summary-grid">
      <div class="metric-card product-summary-card">
        <p class="metric-card__label">当前队列</p>
        <p class="metric-card__value">{{ stageStats.total }}</p>
        <span class="metric-card__trend">当前阶段筛选结果</span>
      </div>
      <button class="metric-card summary-button product-summary-card" type="button" @click="setProductType('product_line')">
        <p class="metric-card__label">新产品线</p>
        <p class="metric-card__value">{{ stageStats.productLines }}</p>
        <span class="metric-card__trend">完整 22 步研发流程</span>
      </button>
      <button class="metric-card summary-button product-summary-card" type="button" @click="setProductType('model_variant')">
        <p class="metric-card__label">新型号线</p>
        <p class="metric-card__value">{{ stageStats.modelVariants }}</p>
        <span class="metric-card__trend">基于父产品的 16 步差异流程</span>
      </button>
      <div class="metric-card product-summary-card">
        <p class="metric-card__label">待冻结资料</p>
        <p class="metric-card__value">{{ stageStats.pendingFreeze }}</p>
        <span class="metric-card__trend">图纸 / SOP / SIP / 质量资料缺口</span>
      </div>
      <div class="metric-card product-summary-card">
        <p class="metric-card__label">平均总成本</p>
        <p class="metric-card__value metric-card__value--small">{{ formatAmount(stageStats.avgCost) }}</p>
        <span class="metric-card__trend">按当前队列口径展示</span>
      </div>
    </section>

    <section class="page-panel lifecycle-panel">
      <div class="toolbar-row">
        <div>
          <h3 class="section-title">阶段入口</h3>
          <p class="page-panel-desc">{{ currentLifecycle.hint }}</p>
        </div>
        <el-tag type="info" effect="light">后端数据</el-tag>
      </div>

      <div class="lifecycle-grid">
        <button
          v-for="item in lifecycleOptions"
          :key="item.key"
          class="lifecycle-button"
          :class="{ 'is-active': currentLifecycle.key === item.key }"
          type="button"
          @click="setLifecycle(item.key)"
        >
          <span class="lifecycle-button__label">{{ item.label }}</span>
          <strong class="lifecycle-button__value">{{ lifecycleCounters[item.key] }}</strong>
          <span class="subtle-text">{{ item.hint }}</span>
        </button>
      </div>
    </section>

    <SearchBar
      :fields="searchFields"
      :model-value="table.query"
      @search="table.setQuery"
      @reset="table.resetQuery({ keyword: '', status: '', frozen: '', productType: '', lifecycle: currentLifecycle.key })"
    />

    <section class="split-grid product-grid">
      <article class="page-panel highlight-panel">
        <div class="toolbar-row">
          <div>
            <h3 class="section-title">当前重点对象</h3>
            <p class="page-panel-desc">优先推进开发中、接近关口或资料缺口明显的产品。</p>
          </div>
        </div>
        <div class="page-stack">
          <button
            v-for="item in highlightedRows"
            :key="item.productId"
            class="highlight-card"
            type="button"
            @click="openProduct(item.productId)"
          >
            <div class="toolbar-row">
              <div class="cell-stack">
                <strong>{{ item.productName }}</strong>
                <span class="subtle-text">{{ item.productCode }}</span>
              </div>
              <StatusTag :status="item.status" object-type="product" />
            </div>
            <div class="detail-row">
              <span>{{ getFlowLabel(item) }}</span>
              <span>第 {{ item.currentStepNo || '--' }} 步</span>
            </div>
            <div class="detail-row">
              <span class="subtle-text">{{ item.currentStage }}</span>
              <span class="subtle-text">{{ getMoldActionLabel(item) }}</span>
            </div>
            <el-progress :percentage="Math.round(item.completionRate * 100)" :stroke-width="8" />
            <div class="detail-row">
              <span class="subtle-text">{{ item.ownerUserName }} / {{ item.activeBomVersion }}</span>
              <span class="subtle-text">{{ formatAmount(item.totalCost || item.estimatedCost, item.estimatedCostCurrency) }}</span>
            </div>
          </button>
        </div>
      </article>

      <article class="page-panel table-panel" v-loading="loading">
        <el-alert
          v-if="loadError"
          :title="loadError"
          type="info"
          show-icon
          :closable="false"
          style="margin-bottom: 12px"
        />
        <div class="toolbar-row">
          <div>
            <h3 class="section-title">产品队列表</h3>
            <p class="page-panel-desc">列表聚焦流程推进，详情页承接时间轴、BOM、质量、文件、版本与日志。</p>
          </div>
        </div>
        <FixedTableViewport v-slot="{ tableHeight }" :refresh-key="table.pagedRows.value">
        <el-table :data="table.pagedRows.value" :height="tableHeight" border stripe>
          <el-table-column prop="productCode" label="产品编码" min-width="180" />
          <el-table-column label="产品信息" min-width="250">
            <template #default="{ row }">
              <div class="cell-stack">
                <strong>{{ row.productName }}</strong>
                <span class="subtle-text">{{ row.seriesName }} / {{ row.model }} / {{ row.color }}</span>
              </div>
            </template>
          </el-table-column>
          <el-table-column label="流程类型" width="150">
            <template #default="{ row }">
              <div class="cell-stack compact-stack">
                <el-tag :type="row.productType === 'product_line' ? 'primary' : 'success'" effect="light">
                  {{ getFlowLabel(row) }}
                </el-tag>
                <span class="subtle-text">{{ getFlowHint(row) }}</span>
              </div>
            </template>
          </el-table-column>
          <el-table-column label="阶段" width="140">
            <template #default="{ row }">
              <el-tag effect="light">{{ lifecycleOptions.find((item) => item.key === getLifecycle(row))?.label || '全部产品' }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="当前节点" min-width="190">
            <template #default="{ row }">
              <div class="cell-stack">
                <strong>第 {{ row.currentStepNo || '--' }} 步</strong>
                <span class="subtle-text">{{ row.currentStage }}</span>
              </div>
            </template>
          </el-table-column>
          <el-table-column label="模具策略" width="130">
            <template #default="{ row }">
              <span class="subtle-text">{{ getMoldActionLabel(row) }}</span>
            </template>
          </el-table-column>
          <el-table-column prop="activeBomVersion" label="BOM 主版本" width="130" />
          <el-table-column label="总成本" width="140">
            <template #default="{ row }">{{ formatAmount(row.totalCost || row.estimatedCost, row.estimatedCostCurrency) }}</template>
          </el-table-column>
          <el-table-column label="资料完整率" min-width="180">
            <template #default="{ row }">
              <el-progress :percentage="Math.round(row.completionRate * 100)" :stroke-width="8" />
            </template>
          </el-table-column>
          <el-table-column label="状态" width="120">
            <template #default="{ row }">
              <StatusTag :status="row.status" object-type="product" />
            </template>
          </el-table-column>
          <el-table-column prop="ownerUserName" label="负责人" width="110" />
          <el-table-column label="操作" width="160" fixed="right">
            <template #default="{ row }">
              <el-button link type="primary" @click="openProduct(row.productId)">详情</el-button>
              <el-button link @click="router.push(toArchivedProductRoute(row.productId))">查看归档</el-button>
            </template>
          </el-table-column>
        </el-table>
        </FixedTableViewport>
      </article>
    </section>
  </PageContainer>
</template>

<style scoped>
.lifecycle-panel {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.lifecycle-grid {
  display: grid;
  grid-template-columns: repeat(9, minmax(0, 1fr));
  gap: 12px;
}

.lifecycle-button,
.summary-button,
.highlight-card {
  width: 100%;
  border: 1px solid var(--plm-color-border-light);
  border-radius: var(--plm-radius-base);
  background: #fff;
  text-align: left;
  cursor: pointer;
  transition: border-color 0.16s ease, box-shadow 0.16s ease, transform 0.16s ease;
}

.lifecycle-button:hover,
.summary-button:hover,
.highlight-card:hover {
  border-color: var(--plm-color-primary);
  box-shadow: var(--plm-shadow-md);
  transform: translateY(-1px);
}

.lifecycle-button {
  display: flex;
  min-height: 136px;
  flex-direction: column;
  justify-content: space-between;
  gap: 8px;
  padding: 14px;
}

.lifecycle-button.is-active {
  border-color: var(--plm-color-primary);
  background: rgba(37, 99, 235, 0.06);
  box-shadow: var(--plm-shadow-sm);
}

.lifecycle-button__label {
  font-weight: 600;
}

.lifecycle-button__value {
  font-size: 24px;
  line-height: 1;
}

.metric-card__value--small {
  font-size: 20px;
}

.product-summary-grid {
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 12px;
}

.product-summary-card {
  min-height: 104px;
  padding: 14px 16px;
}

.product-summary-card .metric-card__label {
  margin-bottom: 8px;
}

.product-summary-card .metric-card__value {
  font-size: 18px;
  line-height: 1.1;
}

.product-summary-card .metric-card__trend {
  display: block;
  margin-top: 6px;
}

.product-grid {
  grid-template-columns: minmax(320px, 0.85fr) minmax(0, 1.55fr);
}

.highlight-panel,
.table-panel {
  min-height: 100%;
}

.highlight-card {
  padding: 14px;
}

.cell-stack {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.compact-stack {
  gap: 6px;
}

.detail-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-top: 10px;
  color: var(--plm-color-text-secondary);
  font-size: var(--plm-font-size-sm);
}

@media (max-width: 1600px) {
  .product-summary-grid,
  .lifecycle-grid {
    grid-template-columns: repeat(5, minmax(0, 1fr));
  }
}

@media (max-width: 1200px) {
  .product-summary-grid,
  .lifecycle-grid {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
}

@media (max-width: 960px) {
  .product-summary-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .product-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 640px) {
  .product-summary-grid,
  .lifecycle-grid {
    grid-template-columns: 1fr;
  }
}
</style>
