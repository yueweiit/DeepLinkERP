<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { useRoute, useRouter } from 'vue-router'

import { getFoundationProducts, getProductPresentation } from '@/api/modules/foundation'
import FilePreview from '@/components/FilePreview/index.vue'
import PageContainer from '@/components/PageContainer/index.vue'
import StatusTag from '@/components/StatusTag/index.vue'
import ProductBomViewer from './components/ProductBomViewer.vue'
import { useUserStore } from '@/stores/user'
import type {
  FoundationProductRef,
  BomCompareRow,
  ProductBomItemRow,
  ProductDetailPresentation,
  ProductDocumentSummary,
  ProductTimelineNode,
  ProductionDocumentPreviewFile
} from '@/types/foundation'
import { formatAmount, formatDate } from '@/utils/format'
import { toArchivedSkuRoute } from '@/utils/projectRoute'

type TimelineActionMode = 'advance' | 'force' | 'reject'
type DetailSectionKey = 'basic' | 'timeline' | 'materials' | 'business' | 'quality'
type MaterialSectionKey = 'bom' | 'files' | 'tooling'

const route = useRoute()
const router = useRouter()
const userStore = useUserStore()

const loading = ref(false)
const product = ref<FoundationProductRef | null>(null)
const presentation = ref<ProductDetailPresentation | null>(null)
const expandedCost = ref<'estimated' | 'actual' | null>('actual')
const selectedBomVersion = ref('')
const bomDetailVisible = ref(false)
const bomDetailVersion = ref('')
const activeTimelineNodeKey = ref('')
const activeSection = ref<DetailSectionKey>('timeline')
const activeMaterialSection = ref<MaterialSectionKey>('bom')

/* 生产资料预览 */
const productionPreviewVisible = ref(false)
const activeProductionDoc = ref<ProductionDocumentPreviewFile | null>(null)

function openProductionDocPreview(doc: ProductDocumentSummary) {
  activeProductionDoc.value = {
    fileId: doc.fileId || '',
    fileName: doc.fileName,
    category: doc.category,
    versionNo: doc.versionNo,
    owner: doc.owner,
    updatedAt: doc.updatedAt,
    status: doc.status,
    previewUrl: doc.previewUrl,
    downloadUrl: doc.downloadUrl
  }
  productionPreviewVisible.value = true
}

const dialogState = reactive({
  visible: false,
  mode: 'advance' as TimelineActionMode,
  nodeKey: '',
  note: '',
  confirmed: false,
  rejectTo: ''
})

const sectionOptions = [
  { label: '基础信息', value: 'basic' },
  { label: '项目流程', value: 'timeline' },
  { label: '资料区', value: 'materials' },
  { label: '商务区', value: 'business' },
  { label: '质量区', value: 'quality' }
] as const

const materialSectionOptions = [
  { label: 'BOM', value: 'bom' },
  { label: '图纸 / 文件', value: 'files' },
  { label: '模具治具', value: 'tooling' }
] as const

const productId = computed(() => Number(route.params.id))
const roleName = computed(() => userStore.profile?.roleName || '')
const isSuperAdmin = computed(() => roleName.value === '超级管理员' || userStore.hasPermission('admin:force-advance'))

const topMetrics = computed(() => {
  if (!product.value || !presentation.value) return []

  return [
    { label: '流程类型', value: presentation.value.flowLabel, hint: '区分新产品线与新型号线的推进方式。' },
    { label: '当前节点', value: presentation.value.currentNode, hint: `下一步：${presentation.value.nextNode}` },
    { label: '版本 / 状态', value: product.value.versionNo, hint: product.value.status },
    { label: '实际成本', value: formatAmount(presentation.value.costPanel.actualTotal), hint: '可在商务区展开查看成本结构。' }
  ]
})

const activeTimelineNode = computed<ProductTimelineNode | null>(() => {
  if (!presentation.value) return null
  return presentation.value.timeline.find((item) => item.nodeKey === activeTimelineNodeKey.value) || presentation.value.timeline[0] || null
})

const dialogNode = computed<ProductTimelineNode | null>(() => {
  if (!presentation.value) return null
  return presentation.value.timeline.find((item) => item.nodeKey === dialogState.nodeKey) || null
})

const timelineRejectOptions = computed(() => {
  const nodes = presentation.value?.timeline || []
  const currentIndex = nodes.findIndex((item) => item.nodeKey === dialogState.nodeKey)
  if (currentIndex <= 0) return []
  return nodes.slice(0, currentIndex).map((item) => ({ label: item.nodeName, value: item.nodeKey }))
})


const bomDetailRow = computed<BomCompareRow | null>(() => {
  if (!presentation.value) return null
  const version = bomDetailVersion.value || selectedBomVersion.value || presentation.value.defaultBomVersion || ''
  return presentation.value.bomCompareRows.find((item) => item.versionNo === version) || null
})

const bomDetailItems = computed<ProductBomItemRow[]>(() => {
  if (!presentation.value) return []
  const version = bomDetailVersion.value || selectedBomVersion.value || presentation.value.defaultBomVersion || ''
  return presentation.value.bomItemsByVersion[version] || []
})

const bomDetailTitle = computed(() => {
  const version = bomDetailVersion.value || selectedBomVersion.value || presentation.value?.defaultBomVersion || ''
  return version && presentation.value ? `${presentation.value.title} - ${version} BOM 详情` : 'BOM 详情'
})

const bomCostSummaryRows = computed(() => {
  if (!presentation.value?.bomCostSummary) return []
  const summary = presentation.value.bomCostSummary
  return [
    { label: '材料成本', value: summary.materialCost },
    { label: '工艺成本', value: summary.processCost },
    { label: '包装成本', value: summary.packageCost },
    { label: '人工成本', value: summary.laborCost },
    { label: '模具分摊', value: summary.toolingCost },
    { label: '损耗成本', value: summary.lossCost }
  ]
})

const dialogTitle = computed(() => {
  if (dialogState.mode === 'force') return '强制推进确认'
  if (dialogState.mode === 'reject') return '节点驳回确认'
  return '节点推进确认'
})

function toggleCostPanel(type: 'estimated' | 'actual') {
  expandedCost.value = expandedCost.value === type ? null : type
}

function selectTimelineNode(nodeKey: string) {
  activeTimelineNodeKey.value = nodeKey
}

function selectBomVersion(versionNo: string) {
  selectedBomVersion.value = versionNo
}

function handleBomVersionRowClick(row: BomCompareRow) {
  selectBomVersion(row.versionNo)
}

function openBomDetail(versionNo: string) {
  selectBomVersion(versionNo)
  bomDetailVersion.value = versionNo
  bomDetailVisible.value = true
}

function getNodeStatusLabel(status: ProductTimelineNode['status']) {
  if (status === 'completed') return '已完成'
  if (status === 'current') return '进行中'
  return '待开始'
}

function getNodeStatusType(status: ProductTimelineNode['status']) {
  if (status === 'completed') return 'success'
  if (status === 'current') return 'warning'
  return 'info'
}

function canSubmitNormalAdvance(node: ProductTimelineNode) {
  return node.status === 'current' && Boolean(node.canAdvance) && ['项目经理', '工程', '管理层', '超级管理员'].includes(roleName.value)
}

function canRejectNode(node: ProductTimelineNode) {
  return node.status === 'current' && ['项目经理', '工程', '管理层', '超级管理员'].includes(roleName.value)
}

function getAdvanceDisabledReason(node: ProductTimelineNode) {
  if (node.status !== 'current') return '只有当前节点才允许执行推进动作。'
  if (!['项目经理', '工程', '管理层', '超级管理员'].includes(roleName.value)) return '当前角色仅可查看节点，不可执行推进。'
  if (!node.canAdvance) return node.riskNote || '当前节点前置资料或门禁未满足，请先补齐。'
  return ''
}

function canShowForceAdvance(node: ProductTimelineNode) {
  return isSuperAdmin.value && node.status !== 'completed'
}

function openActionDialog(node: ProductTimelineNode, mode: TimelineActionMode) {
  dialogState.mode = mode
  dialogState.nodeKey = node.nodeKey
  dialogState.note = ''
  dialogState.confirmed = false
  dialogState.rejectTo = timelineRejectOptions.value[0]?.value || ''
  dialogState.visible = true
}

function submitAction() {
  if (!dialogNode.value) return

  if (!dialogState.confirmed) {
    ElMessage.warning(
      dialogState.mode === 'force'
        ? '请先确认已经了解强制推进带来的风险。'
        : dialogState.mode === 'reject'
          ? '请先确认当前节点需要驳回处理。'
          : '请先确认当前节点的推进前检查项已完成。'
    )
    return
  }

  if (dialogState.mode === 'force' && !dialogState.note.trim()) {
    ElMessage.warning('强制推进必须填写原因，便于后续审计追踪。')
    return
  }

  if (dialogState.mode === 'reject') {
    if (!dialogState.rejectTo) {
      ElMessage.warning('请选择驳回到的目标节点。')
      return
    }
    if (!dialogState.note.trim()) {
      ElMessage.warning('驳回时请填写驳回原因和需要补齐的内容。')
      return
    }
  }

  const successText =
    dialogState.mode === 'force'
      ? `已模拟强制推进 ${dialogNode.value.nodeName}`
      : dialogState.mode === 'reject'
        ? `已模拟驳回 ${dialogNode.value.nodeName}`
        : `已模拟确认推进 ${dialogNode.value.nodeName}`

  ElMessage.success(successText)
  dialogState.visible = false
}

async function loadData() {
  loading.value = true
  try {
    const [products, detail] = await Promise.all([getFoundationProducts(), getProductPresentation(productId.value)])
    product.value = products.find((item) => item.productId === productId.value) || products[0] || null
    presentation.value = detail
    selectedBomVersion.value = detail.defaultBomVersion || detail.bomCompareRows[0]?.versionNo || ''
    activeTimelineNodeKey.value = detail.timeline.find((item) => item.status === 'current')?.nodeKey || detail.timeline[0]?.nodeKey || ''
  } catch {
    product.value = null
    presentation.value = null
  } finally {
    loading.value = false
  }
}

onMounted(loadData)
</script>

<template>
  <PageContainer
    :title="presentation?.title || '产品详情'"
    :description="presentation?.summary || '聚焦项目推进、版本资料、模具治具、成本与质量记录。'"
  >
    <template #actions>
      <el-button @click="router.back()">返回</el-button>
      <el-button @click="router.push(toArchivedSkuRoute())">返回归档 SKU</el-button>
    </template>

    <section class="metric-grid" v-loading="loading">
      <div v-for="metric in topMetrics" :key="metric.label" class="metric-card">
        <p class="metric-card__label">{{ metric.label }}</p>
        <p class="metric-card__value metric-card__value--small">{{ metric.value }}</p>
        <span class="metric-card__trend">{{ metric.hint }}</span>
      </div>
    </section>

    <section v-if="product && presentation" class="page-stack">
      <section class="page-panel section-switch-panel">
        <div class="toolbar-row section-switch-panel__header">
          <div>
            <h3 class="section-title">详情板块</h3>
            <p class="page-panel-desc">产品详情按主任务拆成独立板块，先切到当前要处理的内容，再展开对应信息。</p>
          </div>
          <div class="toolbar-actions">
            <StatusTag :status="product.status" object-type="product" />
            <el-tag v-if="isSuperAdmin" type="danger" effect="light">管理员可强制推进</el-tag>
          </div>
        </div>

        <el-segmented v-model="activeSection" :options="sectionOptions" class="section-switcher" />
      </section>

      <section v-if="activeSection === 'basic'" class="page-panel detail-subpanel">
        <div class="toolbar-row">
          <div>
            <h3 class="section-title">基础信息</h3>
            <p class="page-panel-desc">先确认当前产品对象、版本状态、型号颜色和客户来源，避免在错误版本上继续推进。</p>
          </div>
        </div>

        <div class="detail-hero">
          <div class="detail-hero__image">
            <span>{{ product.seriesName }}</span>
          </div>

          <div class="detail-grid detail-hero__meta">
            <div class="info-card">
              <span class="subtle-text">产品线</span>
              <strong>{{ product.seriesName }}</strong>
            </div>
            <div class="info-card">
              <span class="subtle-text">型号 + 颜色</span>
              <strong>{{ product.model }} / {{ product.color }}</strong>
            </div>
            <div class="info-card">
              <span class="subtle-text">产品编码</span>
              <strong>{{ product.productCode }}</strong>
            </div>
            <div class="info-card">
              <span class="subtle-text">客户来源</span>
              <strong>{{ product.customerName }}</strong>
            </div>
            <div class="info-card">
              <span class="subtle-text">当前阶段</span>
              <strong>{{ product.currentStage }}</strong>
            </div>
            <div class="info-card">
              <span class="subtle-text">产品类型</span>
              <strong>{{ product.productType === 'product_line' ? '新产品线' : '新型号线' }}</strong>
            </div>
          </div>
        </div>
      </section>

      <section v-else-if="activeSection === 'timeline'" id="product-detail-timeline" class="page-panel detail-subpanel">
        <div class="toolbar-row">
          <div>
            <h3 class="section-title">项目流程</h3>
            <p class="page-panel-desc">查看每个环节的经历内容、接收人、推动人和推动时间，可在当前节点直接执行推进、驳回或强制推进。</p>
          </div>
        </div>

        <div class="timeline-shell">
          <div class="timeline-list">
            <section
              v-for="node in presentation.timeline"
              :key="node.nodeKey"
              class="timeline-card"
              :class="[`is-${node.status}`, { 'is-active': node.nodeKey === activeTimelineNodeKey }]"
            >
              <button class="timeline-card__body" type="button" @click="selectTimelineNode(node.nodeKey)">
                <div class="toolbar-row">
                  <strong>{{ node.nodeName }}</strong>
                  <div class="row-actions">
                    <el-tag :type="getNodeStatusType(node.status)" effect="light">{{ getNodeStatusLabel(node.status) }}</el-tag>
                    <el-tag v-if="node.gateLabel" type="danger" effect="light">{{ node.gateLabel }}</el-tag>
                  </div>
                </div>
                <div class="detail-row">
                  <span>{{ node.ownerRole }}</span>
                  <span>{{ node.actualDate || node.plannedDate || '--' }}</span>
                </div>
                <div class="detail-row" v-if="node.receiverUserName || node.promoterUserName">
                  <span v-if="node.receiverUserName">接收：{{ node.receiverUserName }}</span>
                  <span v-if="node.promoterUserName">推动：{{ node.promoterUserName }}</span>
                </div>
                <p class="page-panel-desc">{{ node.summary }}</p>
              </button>

              <div class="timeline-card__actions">
                <el-button size="small" @click="selectTimelineNode(node.nodeKey)">查看节点</el-button>
                <el-button v-if="canRejectNode(node)" size="small" type="danger" plain @click="openActionDialog(node, 'reject')">
                  驳回
                </el-button>
                <el-button
                  v-if="node.status === 'current'"
                  size="small"
                  type="primary"
                  :disabled="!canSubmitNormalAdvance(node)"
                  :title="getAdvanceDisabledReason(node)"
                  @click="openActionDialog(node, 'advance')"
                >
                  {{ node.canAdvance ? '确认推进' : '暂不可推进' }}
                </el-button>
                <el-button v-if="canShowForceAdvance(node)" size="small" type="warning" plain @click="openActionDialog(node, 'force')">
                  强制推进
                </el-button>
              </div>
            </section>
          </div>

          <div v-if="activeTimelineNode" class="timeline-detail">
            <div class="toolbar-row">
              <div>
                <h4 class="section-title">{{ activeTimelineNode.nodeName }}</h4>
                <p class="page-panel-desc">{{ activeTimelineNode.summary }}</p>
              </div>
              <el-tag :type="getNodeStatusType(activeTimelineNode.status)" effect="light">
                {{ getNodeStatusLabel(activeTimelineNode.status) }}
              </el-tag>
            </div>

            <div class="page-stack">
              <div v-if="activeTimelineNode.experienceSummary" class="info-card">
                <span class="subtle-text">经历内容</span>
                <strong>{{ activeTimelineNode.experienceSummary }}</strong>
              </div>
              <div class="detail-grid-2col">
                <div class="info-card">
                  <span class="subtle-text">责任角色</span>
                  <strong>{{ activeTimelineNode.ownerRole }}</strong>
                </div>
                <div v-if="activeTimelineNode.actualDate || activeTimelineNode.plannedDate" class="info-card">
                  <span class="subtle-text">计划 / 实际时间</span>
                  <strong>{{ activeTimelineNode.actualDate || activeTimelineNode.plannedDate || '--' }}</strong>
                </div>
              </div>
              <div class="detail-grid-2col">
                <div class="info-card">
                  <span class="subtle-text">接收人</span>
                  <strong>{{ activeTimelineNode.receiverUserName || activeTimelineNode.receiverRole || '--' }}</strong>
                  <span class="subtle-text" v-if="activeTimelineNode.receivedAt">接收时间：{{ activeTimelineNode.receivedAt }}</span>
                </div>
                <div class="info-card">
                  <span class="subtle-text">推动人</span>
                  <strong>{{ activeTimelineNode.promoterUserName || activeTimelineNode.promoterRole || activeTimelineNode.ownerRole }}</strong>
                  <span class="subtle-text" v-if="activeTimelineNode.promotedAt">推动时间：{{ activeTimelineNode.promotedAt }}</span>
                  <span class="subtle-text" v-else-if="activeTimelineNode.status === 'current'">当前节点推进中</span>
                </div>
              </div>
              <div v-if="activeTimelineNode.nextAction" class="info-card">
                <span class="subtle-text">下一步动作</span>
                <strong>{{ activeTimelineNode.nextAction }}</strong>
              </div>
              <div v-if="activeTimelineNode.nextReceiverRole" class="info-card">
                <span class="subtle-text">下一接收人</span>
                <strong>{{ activeTimelineNode.nextReceiverUserName || activeTimelineNode.nextReceiverRole }}</strong>
              </div>
              <div v-if="activeTimelineNode.riskNote" class="info-card">
                <span class="subtle-text">风险提示</span>
                <strong>{{ activeTimelineNode.riskNote }}</strong>
              </div>
              <div v-if="activeTimelineNode.detailLines?.length" class="info-card">
                <span class="subtle-text">节点检查项</span>
                <ul class="detail-list">
                  <li v-for="line in activeTimelineNode.detailLines" :key="line">{{ line }}</li>
                </ul>
              </div>
              <div v-if="activeTimelineNode.documentCount != null" class="info-card">
                <span class="subtle-text">关联资料</span>
                <strong>{{ activeTimelineNode.documentCount }} 份</strong>
              </div>
            </div>
          </div>
        </div>
      </section>

      <section v-else-if="activeSection === 'materials'" class="page-panel detail-subpanel">
        <div class="toolbar-row materials-header">
          <div>
            <h3 class="section-title">资料区</h3>
            <p class="page-panel-desc">把 BOM、图纸文件、模具治具拆开查看，减少信息堆叠，让版本核对更直观。</p>
          </div>
          <el-segmented v-model="activeMaterialSection" :options="materialSectionOptions" class="materials-switcher" />
        </div>

        <section v-if="activeMaterialSection === 'bom'" class="page-panel bom-detail-panel">
          <ProductBomViewer :product-id="productId" />
        </section>

        <section v-else-if="activeMaterialSection === 'files'" class="page-panel materials-section-panel">
          <div class="toolbar-row">
            <div>
              <h3 class="section-title">图纸 / 文件</h3>
              <p class="page-panel-desc">图纸、客户确认件和测试文件统一放在这里查看。</p>
            </div>
          </div>

          <div class="document-list">
            <div v-for="doc in presentation.documents" :key="doc.fileName" class="document-card">
              <div class="document-card__head">
                <strong>{{ doc.fileName }}</strong>
                <div class="row-actions">
                  <el-tag v-if="doc.status" size="small" effect="light" :type="doc.status === '已冻结' ? 'success' : doc.status === '已归档' ? 'info' : 'warning'">
                    {{ doc.status }}
                  </el-tag>
                </div>
              </div>
              <span class="subtle-text">{{ doc.category }} / 版本 {{ doc.versionNo }}</span>
              <span class="subtle-text" v-if="doc.owner">负责人：{{ doc.owner }}</span>
              <span class="subtle-text">更新：{{ formatDate(doc.updatedAt) }}</span>
              <div class="document-card__actions">
                <el-button link type="primary" size="small" @click="openProductionDocPreview(doc)">预览</el-button>
                <el-button link type="primary" size="small">下载</el-button>
              </div>
            </div>
          </div>
        </section>

        <section v-else class="page-panel materials-section-panel">
          <div class="toolbar-row">
            <div>
              <h3 class="section-title">模具治具</h3>
              <p class="page-panel-desc">把当前版本关联的模具治具单独展示，方便从资料区直接跳转查看。</p>
            </div>
            <el-button type="primary" plain @click="router.push(presentation.toolingSummary.targetPath || '/inventories')">
              查看模具治具
            </el-button>
          </div>

          <div class="tooling-summary tooling-summary--stacked">
            <div class="info-card tooling-summary__card">
              <span class="subtle-text">总数</span>
              <strong>{{ presentation.toolingSummary.totalCount }} 套</strong>
              <span class="subtle-text">可用 {{ presentation.toolingSummary.availableCount }} / 试模中 {{ presentation.toolingSummary.trialCount }}</span>
            </div>
            <div class="info-card tooling-summary__card tooling-summary__names">
              <span class="subtle-text">当前关联</span>
              <strong>{{ presentation.toolingSummary.toolingNames.join('') }}</strong>
            </div>
          </div>
        </section>
      </section>

      <section v-else-if="activeSection === 'business'" class="page-panel detail-subpanel">
        <div class="toolbar-row">
          <div>
            <h3 class="section-title">商务区</h3>
            <p class="page-panel-desc">成本和供应商信息单独查看，减少对项目主链路阅读的干扰。</p>
          </div>
        </div>

        <div class="business-layout">
          <div class="page-stack">
            <section
              v-if="presentation.costPanel.showEstimated"
              class="cost-card"
              :class="{ 'is-expanded': expandedCost === 'estimated' }"
            >
              <button class="cost-card__summary" type="button" @click="toggleCostPanel('estimated')">
                <div>
                  <strong>预计成本</strong>
                  <p class="subtle-text">立项与前期评估口径</p>
                </div>
                <div class="cost-card__summary-right">
                  <strong>{{ formatAmount(presentation.costPanel.estimatedTotal || 0) }}</strong>
                  <span class="subtle-text">{{ expandedCost === 'estimated' ? '收起' : '展开' }}</span>
                </div>
              </button>
              <div v-if="expandedCost === 'estimated'" class="cost-card__detail">
                <div v-for="line in presentation.costPanel.estimatedLines || []" :key="line.label" class="cost-line">
                  <div>
                    <strong>{{ line.label }}</strong>
                    <p class="subtle-text">{{ line.note }}</p>
                  </div>
                  <strong>{{ formatAmount(line.amount) }}</strong>
                </div>
              </div>
            </section>

            <section class="cost-card" :class="{ 'is-expanded': expandedCost === 'actual' }">
              <button class="cost-card__summary" type="button" @click="toggleCostPanel('actual')">
                <div>
                  <strong>实际成本</strong>
                  <p class="subtle-text">当前版本执行口径</p>
                </div>
                <div class="cost-card__summary-right">
                  <strong>{{ formatAmount(presentation.costPanel.actualTotal) }}</strong>
                  <span class="subtle-text">{{ expandedCost === 'actual' ? '收起' : '展开' }}</span>
                </div>
              </button>
              <div v-if="expandedCost === 'actual'" class="cost-card__detail">
                <div v-for="line in presentation.costPanel.actualLines" :key="line.label" class="cost-line">
                  <div>
                    <strong>{{ line.label }}</strong>
                    <p class="subtle-text">{{ line.note }}</p>
                  </div>
                  <strong>{{ formatAmount(line.amount) }}</strong>
                </div>
              </div>
            </section>
          </div>

          <div class="supplier-list">
            <div v-for="supplier in presentation.suppliers" :key="supplier.supplierName" class="supplier-card">
              <div class="toolbar-row">
                <strong>{{ supplier.supplierName }}</strong>
                <el-tag effect="light">{{ supplier.statusLabel }}</el-tag>
              </div>
              <span class="subtle-text">{{ supplier.role }}</span>
              <span class="subtle-text">{{ supplier.note }}</span>
            </div>
          </div>
        </div>
      </section>

      <section v-else class="page-panel detail-subpanel">
        <div class="toolbar-row">
          <div>
            <h3 class="section-title">质量区</h3>
            <p class="page-panel-desc">测试记录、问题处理和验证结论保持独立沉淀，方便回溯每个节点是否满足推进条件。</p>
          </div>
        </div>

        <div class="quality-list">
          <div v-for="record in presentation.qualityRecords" :key="`${record.testItem}-${record.testedAt}`" class="quality-card">
            <div class="toolbar-row">
              <strong>{{ record.testItem }}</strong>
              <el-tag :type="record.resultLabel === '通过' ? 'success' : record.resultLabel === '不通过' ? 'danger' : 'warning'" effect="light">
                {{ record.resultLabel }}
              </el-tag>
            </div>
            <span class="subtle-text">责任人：{{ record.owner }}</span>
            <span class="subtle-text">时间：{{ formatDate(record.testedAt) }}</span>
            <span class="subtle-text">{{ record.note }}</span>
          </div>
        </div>
      </section>
    </section>

    <el-dialog v-model="dialogState.visible" :title="dialogTitle" width="560px">
      <div v-if="dialogNode" class="page-stack">
        <div class="info-card">
          <span class="subtle-text">当前产品</span>
          <strong>{{ presentation?.title }}</strong>
        </div>
        <div class="info-card">
          <span class="subtle-text">当前节点</span>
          <strong>{{ dialogNode.nodeName }}</strong>
        </div>
        <div class="info-card">
          <span class="subtle-text">责任角色</span>
          <strong>{{ dialogNode.ownerRole }}</strong>
        </div>
        <div v-if="dialogNode.nextAction && dialogState.mode !== 'reject'" class="info-card">
          <span class="subtle-text">下一步动作</span>
          <strong>{{ dialogNode.nextAction }}</strong>
        </div>
        <div v-if="dialogNode.riskNote" class="info-card">
          <span class="subtle-text">风险 / 阻塞</span>
          <strong>{{ dialogNode.riskNote }}</strong>
        </div>
        <div v-if="dialogNode.detailLines?.length" class="info-card">
          <span class="subtle-text">{{ dialogState.mode === 'force' ? '越权前须知' : dialogState.mode === 'reject' ? '驳回前检查项' : '推进前检查项' }}</span>
          <ul class="detail-list">
            <li v-for="line in dialogNode.detailLines" :key="line">{{ line }}</li>
          </ul>
        </div>

        <div v-if="dialogState.mode === 'reject'" class="info-card">
          <span class="subtle-text">驳回到节点</span>
          <el-select v-model="dialogState.rejectTo" placeholder="请选择要驳回到的节点">
            <el-option v-for="item in timelineRejectOptions" :key="item.value" :label="item.label" :value="item.value" />
          </el-select>
        </div>

        <el-input
          v-model="dialogState.note"
          type="textarea"
          :rows="dialogState.mode === 'force' || dialogState.mode === 'reject' ? 4 : 3"
          :placeholder="
            dialogState.mode === 'force'
              ? '请填写强制推进原因、风险说明和后续补救动作。' 
              : dialogState.mode === 'reject'
                ? '请填写驳回原因、需补充的资料和责任提醒。' 
                : '可填写推进备注、交接说明或提醒事项。' 
          "
        />

        <el-checkbox v-model="dialogState.confirmed">
          {{
            dialogState.mode === 'force'
              ? '我已确认本次为管理员强制推进，系统应保留完整审计痕迹。' 
              : dialogState.mode === 'reject'
                ? '我已确认当前节点需要退回处理，并会通知相关责任人补齐资料。' 
                : '我已确认当前节点的推进前检查项已经完成。' 
          }}
        </el-checkbox>
      </div>

      <template #footer>
        <div class="drawer-actions">
          <el-button @click="dialogState.visible = false">取消</el-button>
          <el-button :type="dialogState.mode === 'reject' ? 'danger' : 'primary'" @click="submitAction">
            {{ dialogState.mode === 'force' ? '确认强制推进' : dialogState.mode === 'reject' ? '确认驳回' : '确认推进' }}
          </el-button>
        </div>
      </template>
    </el-dialog>

    <el-dialog v-model="bomDetailVisible" :title="bomDetailTitle" width="820px">
      <div v-if="presentation" class="page-stack bom-detail-dialog">
        <div class="bom-detail-dialog__summary">
          <div class="info-card">
            <span class="subtle-text">所属产品</span>
            <strong>{{ presentation.title }}</strong>
          </div>
          <div class="info-card">
            <span class="subtle-text">版本状态</span>
            <strong>{{ bomDetailRow?.statusLabel || '--' }}</strong>
          </div>
          <div class="info-card">
            <span class="subtle-text">总成本</span>
            <strong>{{ formatAmount(bomDetailRow?.totalCost || 0) }}</strong>
          </div>
          <div class="info-card">
            <span class="subtle-text">成本变化</span>
            <strong :class="(bomDetailRow?.delta || 0) > 0 ? 'text-danger' : (bomDetailRow?.delta || 0) < 0 ? 'text-success' : ''">
              {{ (bomDetailRow?.delta || 0) > 0 ? '+' : '' }}{{ formatAmount(bomDetailRow?.delta || 0) }}
            </strong>
          </div>
        </div>

        <div class="bom-detail-dialog__cost">
          <div class="info-card">
            <span class="subtle-text">材料成本</span>
            <strong>{{ formatAmount(bomDetailRow?.materialCost || 0) }}</strong>
          </div>
          <div class="info-card">
            <span class="subtle-text">工艺成本</span>
            <strong>{{ formatAmount(bomDetailRow?.processCost || 0) }}</strong>
          </div>
          <div class="info-card">
            <span class="subtle-text">当前页面成本汇总</span>
            <strong>{{ formatAmount(presentation.bomCostSummary?.totalCost || 0) }}</strong>
          </div>
        </div>

        <el-table :data="bomDetailItems" border stripe>
          <el-table-column prop="inventoryCode" label="物料编码" min-width="150" />
          <el-table-column prop="inventoryName" label="物料名称" min-width="180" />
          <el-table-column prop="quantity" label="用量" width="90" />
          <el-table-column prop="stockUom" label="单位" width="90" />
          <el-table-column prop="supplierName" label="供应商" min-width="160" />
          <el-table-column label="单价" width="120">
            <template #default="{ row }">{{ formatAmount(row.unitCost) }}</template>
          </el-table-column>
          <el-table-column label="差异标识" width="110">
            <template #default="{ row }">
              <el-tag
                :type="row.changeType === 'new' ? 'success' : row.changeType === 'replace' ? 'warning' : row.changeType === 'remove' ? 'danger' : 'info'"
                effect="light"
              >
                {{ row.changeType === 'new' ? '新增' : row.changeType === 'replace' ? '替换' : row.changeType === 'remove' ? '删除' : '沿用' }}
              </el-tag>
            </template>
          </el-table-column>
        </el-table>
      </div>
    </el-dialog>

    <!-- 生产资料预览 -->
    <FilePreview
      v-model="productionPreviewVisible"
      :file="activeProductionDoc"
    />
  </PageContainer>
</template>

<style scoped>
.metric-card__value--small {
  font-size: 20px;
}

.section-switch-panel {
  padding: 14px;
}

.section-switch-panel__header {
  margin-bottom: 12px;
}

.section-switcher,
.materials-switcher {
  width: 100%;
}

.materials-header {
  align-items: flex-start;
  gap: 16px;
}

.bom-summary-panel {
  display: flex;
  flex-direction: column;
  gap: 12px;
  margin-bottom: 16px;
}

.bom-summary-grid {
  display: grid;
  grid-template-columns: 1.2fr repeat(6, minmax(0, 1fr));
  gap: 12px;
}

.bom-summary-grid__total {
  min-height: 110px;
}

.bom-summary-grid__item {
  min-height: 110px;
}

.detail-hero {
  display: grid;
  grid-template-columns: minmax(240px, 0.8fr) minmax(0, 1.2fr);
  gap: 16px;
}

.detail-hero__image {
  display: grid;
  min-height: 220px;
  place-items: center;
  border-radius: var(--plm-radius-base);
  background: linear-gradient(135deg, #e9eef8 0%, #f8fafc 100%);
  color: #334155;
  font-size: 22px;
  font-weight: 700;
}

.timeline-shell {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(340px, 0.92fr);
  gap: 16px;
}

.business-layout {
  display: grid;
  grid-template-columns: minmax(0, 1.1fr) minmax(320px, 0.9fr);
  gap: 16px;
}

.timeline-list,
.document-list,
.supplier-list,
.quality-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.timeline-card,
.timeline-detail,
.document-card,
.supplier-card,
.quality-card,
.info-card,
.cost-card,
.bom-detail-panel,
.materials-section-panel {
  border: 1px solid var(--plm-color-border-light);
  border-radius: var(--plm-radius-base);
  background: #fff;
}

.timeline-card {
  overflow: hidden;
}

.timeline-card.is-active,
.timeline-card:hover {
  border-color: var(--plm-color-primary);
  box-shadow: var(--plm-shadow-sm);
}

.timeline-card.is-current {
  background: rgba(245, 158, 11, 0.1);
}

.timeline-card.is-completed {
  background: rgba(34, 197, 94, 0.08);
}

.timeline-card__body {
  width: 100%;
  padding: 14px;
  border: 0;
  background: transparent;
  text-align: left;
  cursor: pointer;
}

.timeline-card__actions,
.cost-card__summary,
.drawer-actions,
.row-actions,
.detail-row,
.tooling-summary {
  display: flex;
  align-items: center;
  gap: 12px;
}

.timeline-card__actions {
  justify-content: flex-end;
  flex-wrap: wrap;
  padding: 0 14px 14px;
}

.timeline-detail {
  padding: 14px;
}

.info-card {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 12px;
}

.tooling-summary {
  align-items: stretch;
  gap: 16px;
}

.tooling-summary--stacked {
  margin-top: 16px;
}

.tooling-summary__card {
  flex: 1;
}

.tooling-summary__names {
  min-width: 0;
}

.bom-compare-layout {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.bom-compare-layout__table {
  min-width: 0;
}

.bom-detail-dialog,
.bom-detail-dialog__summary,
.bom-detail-dialog__cost {
  display: grid;
  gap: 12px;
}

.bom-detail-dialog__summary {
  grid-template-columns: repeat(4, minmax(0, 1fr));
}

.bom-detail-dialog__cost {
  grid-template-columns: repeat(3, minmax(0, 1fr));
}

.detail-list {
  margin: 0;
  padding-left: 18px;
  color: var(--plm-color-text-secondary);
}

.document-card,
.supplier-card,
.quality-card {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 14px;
}

.document-card__head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.document-card__actions {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 4px;
}

.detail-grid-2col {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

.cost-card {
  overflow: hidden;
  transition: border-color 0.2s ease, box-shadow 0.2s ease, background 0.2s ease;
}

.cost-card.is-expanded {
  border-color: #2563eb;
  box-shadow: 0 12px 28px rgba(37, 99, 235, 0.14);
  background: #ffffff;
}

.cost-card__summary {
  justify-content: space-between;
  width: 100%;
  padding: 14px 16px;
  border: 0;
  background: #fff;
  text-align: left;
  cursor: pointer;
  transition: background 0.2s ease;
}

.cost-card.is-expanded .cost-card__summary {
  background: rgba(37, 99, 235, 0.08);
}

.cost-card__summary-right {
  display: flex;
  flex-direction: column;
  gap: 6px;
  align-items: flex-end;
}

.cost-card.is-expanded .cost-card__summary-right strong {
  color: #1d4ed8;
}

.cost-card__detail {
  padding: 12px 16px 16px;
  background: #f5f9ff;
  border-top: 1px solid rgba(37, 99, 235, 0.16);
}

.cost-line {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  padding-top: 14px;
  border-top: 1px solid var(--plm-color-border-light);
}

.row-actions,
.drawer-actions {
  flex-wrap: wrap;
}

.detail-row {
  justify-content: space-between;
  margin-top: 10px;
  color: var(--plm-color-text-secondary);
  font-size: var(--plm-font-size-sm);
}

.drawer-actions {
  justify-content: flex-end;
}

.text-danger {
  color: var(--el-color-danger);
}

.text-success {
  color: var(--el-color-success);
}

@media (max-width: 1280px) {
  .timeline-shell,
  .business-layout,
  .bom-summary-grid {
    grid-template-columns: 1fr;
  }

  .bom-detail-dialog__summary,
  .bom-detail-dialog__cost {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 960px) {
  .detail-hero,
  .tooling-summary,
  .materials-header {
    grid-template-columns: 1fr;
  }

  .tooling-summary,
  .materials-header {
    flex-direction: column;
  }
}
</style>






