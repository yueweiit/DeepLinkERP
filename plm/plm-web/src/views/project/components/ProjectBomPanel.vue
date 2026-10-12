<script setup lang="ts">
import { Delete, DocumentCopy, Plus, Promotion, Refresh, Upload } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { computed, reactive, ref, watch } from 'vue'

import {
  copyBomVersion,
  cancelCurrentBomConfirmation,
  confirmCurrentBomVersion as confirmCurrentBomVersionApi,
  createProjectBom,
  deleteBomVersion,
  getBomWorkbench,
  getProjectBoms,
  recalculateBomCosts,
  saveBomRoutes,
  submitBomReview,
  type ProductBomVO
} from '@/api/modules/bom'
import { getProjectProcessRoutes, type ProcessRouteVO } from '@/api/modules/process'
import type { BomRoute, BomWorkbench } from '@/types/bom'
import { useUserStore } from '@/stores/user'

import BomImportDialog from './BomImportDialog.vue'
import BomRouteEditor from './BomRouteEditor.vue'

const props = defineProps<{ projectId: number }>()
const emit = defineEmits<{
  (event: 'changed'): void
}>()
const user = useUserStore()

const loading = ref(false)
const actionLoading = ref(false)
const loadError = ref('')
const boms = ref<ProductBomVO[]>([])
const processRoutes = ref<ProcessRouteVO[]>([])
const selectedBomId = ref<number | null>(null)
const workbench = ref<BomWorkbench | null>(null)
const importVisible = ref(false)
const routeEditorVisible = ref(false)
const createVisible = ref(false)
const createForm = reactive({
  bomName: '',
  bomType: 'mbom',
  versionNo: '',
  processId: null as number | null,
  remark: ''
})

const candidateBoms = computed(() => boms.value.filter((bom) => bom.bomType !== 'test' && bom.status !== 'archived'))
const selectedBom = computed(() => boms.value.find((bom) => bom.productBomId === selectedBomId.value) || null)
const selectedStatus = computed(() => selectedBom.value?.status || workbench.value?.status)
const isReadOnly = computed(() => ['released','frozen','archived'].includes(selectedStatus.value || ''))
const canWriteBom = computed(() => user.hasPermission('bom:write'))
const canReadMoney = computed(() => user.hasPermission('finance:read'))
const canWriteMoney = computed(() => canReadMoney.value && user.hasPermission('finance:write'))
const canReviewBom = computed(() => canWriteBom.value && selectedStatus.value === 'draft')
const blocksDeletionStatus = computed(() => ['frozen', 'released', 'archived'].includes(selectedBom.value?.status || ''))
const bomRiskSummary = computed(() => {
  const items = workbench.value?.routes.flatMap(route => route.items) || []
  return {
    manualRows: items.filter(item => item.materialSource === 'manual' || item.unmatchedFlag === 1).length,
    supplierMissing: items.filter(item => !item.supplierName).length,
    costMissing: items.filter(item => item.unitCost == null || item.lineCost == null).length
  }
})
const hasBomRisks = computed(() =>
  bomRiskSummary.value.manualRows > 0
  || bomRiskSummary.value.supplierMissing > 0
  || (canReadMoney.value && bomRiskSummary.value.costMissing > 0)
)
const canConfirmCurrentBom = computed(() =>
  Boolean(
    selectedBomId.value
    && workbench.value?.routes.length
    && workbench.value.routes.every(route => route.colors.length && route.items.length)
    && ['reviewing','frozen'].includes(selectedStatus.value || '') && user.hasPermission('bom:publish')
    && !selectedBom.value?.currentFormal
  )
)
const canCancelCurrentBom = computed(() =>
  Boolean(selectedBom.value?.currentFormal && !isReadOnly.value && canWriteBom.value)
)
const canDeleteSelectedBom = computed(() =>
  Boolean(selectedBom.value && !blocksDeletionStatus.value && !selectedBom.value.currentFormal && canWriteBom.value)
)

function errorMessage(error: unknown) {
  return error instanceof Error ? error.message : 'BOM 数据加载失败'
}

async function load(preferredBomId?: number) {
  loading.value = true
  loadError.value = ''
  try {
    const [projectBoms, routes] = await Promise.all([
      getProjectBoms(props.projectId),
      getProjectProcessRoutes(props.projectId)
    ])
    boms.value = projectBoms
    processRoutes.value = routes
    const candidates = projectBoms.filter((bom) => bom.bomType !== 'test')
    selectedBomId.value = candidates.some((bom) => bom.productBomId === preferredBomId)
      ? preferredBomId || null
      : candidates[0]?.productBomId || null
    workbench.value = selectedBomId.value ? await getBomWorkbench(selectedBomId.value) : null
  } catch (error) {
    loadError.value = errorMessage(error)
  } finally {
    loading.value = false
  }
}

async function changeVersion() {
  workbench.value = selectedBomId.value ? await getBomWorkbench(selectedBomId.value) : null
}

function selectBom(row: ProductBomVO) {
  selectedBomId.value = row.productBomId
  void changeVersion()
}

function openCreateBom() {
  if (!canWriteBom.value) return
  const next = candidateBoms.value.length + 1
  createForm.bomName = `候选 BOM V${next}`
  createForm.versionNo = `V${next}`
  createForm.bomType = 'mbom'
  createForm.processId = null
  createForm.remark = '工作台新建候选 BOM'
  createVisible.value = true
}

async function submitCreateBom() {
  if (!createForm.processId) {
    ElMessage.warning('请选择关联工艺路线')
    return
  }
  actionLoading.value = true
  try {
    const result = await createProjectBom(props.projectId, {
      bomName: createForm.bomName,
      bomType: createForm.bomType,
      versionNo: createForm.versionNo,
      processId: createForm.processId,
      remark: createForm.remark
    })
    createVisible.value = false
    await load(result.productBomId)
    emit('changed')
    ElMessage.success('候选 BOM 已创建')
  } finally {
    actionLoading.value = false
  }
}

async function saveRoutes(routes: BomRoute[]) {
  if (!selectedBomId.value || isReadOnly.value || !canWriteBom.value) return
  actionLoading.value = true
  try {
    await saveBomRoutes(selectedBomId.value, routes, { moneyEditable: canWriteMoney.value })
    routeEditorVisible.value = false
    await changeVersion()
    emit('changed')
    ElMessage.success('工艺路线与 BOM 已保存')
  } finally {
    actionLoading.value = false
  }
}

async function lifecycle(action: 'cost' | 'review' | 'copy') {
  if (!selectedBomId.value || !workbench.value) return
  if (!canWriteBom.value || (action !== 'copy' && isReadOnly.value) || (action === 'review' && !canReviewBom.value)) return
  if (action === 'cost' && !canWriteMoney.value) return
  actionLoading.value = true
  try {
    if (action === 'cost') await recalculateBomCosts(selectedBomId.value, workbench.value.routes)
    if (action === 'review') await submitBomReview(selectedBomId.value)
    if (action === 'copy') {
      const proposed = await ElMessageBox.prompt('为复制出的可编辑草稿填写新版本编号。正式源版本及 ERP 发布快照保持不变。','复制为新版本',{inputValue:`${workbench.value.versionNo}-COPY`,inputValidator:value => !!value?.trim() && !boms.value.some(b => b.versionNo === value.trim()) || '请填写未使用的新版本编号'}).catch(() => undefined)
      if (!proposed) return
      const colors = workbench.value.routes.flatMap((route) => route.colors)
      const copied = await copyBomVersion(selectedBomId.value, { versionNo: proposed.value.trim(), selectedColors: colors })
      await load(copied.productBomId);emit('changed');ElMessage.success('已复制为可编辑的新草稿，原正式版本不变');return
    }
    await load(selectedBomId.value)
    emit('changed')
    ElMessage.success(action === 'review' ? '已提交审核，尚未正式发布或推送 ERP' : 'BOM 成本已更新')
  } finally {
    actionLoading.value = false
  }
}

async function deleteSelectedBomVersion() {
  if (!selectedBom.value || !canDeleteSelectedBom.value) return
  await ElMessageBox.confirm(
    `确认删除 BOM ${selectedBom.value.bomCode}（${selectedBom.value.versionNo}）吗？删除后仅做软删除，不再出现在当前版本列表中。`,
    '删除 BOM 版本',
    {
      confirmButtonText: '删除',
      cancelButtonText: '取消',
      type: 'warning'
    }
  )
  actionLoading.value = true
  try {
    await deleteBomVersion(selectedBom.value.productBomId)
    await load()
    emit('changed')
    ElMessage.success('BOM 版本已删除')
  } finally {
    actionLoading.value = false
  }
}

async function confirmCurrentBomVersion() {
  if (!canConfirmCurrentBom.value || !selectedBomId.value) {
    ElMessage.warning('请先提交审核，并选择已完整维护路线、颜色和明细的待发布 BOM')
    return
  }
  const confirmed = await ElMessageBox.confirm('正式发布后资料不可原地编辑，变更必须复制新版本。正式 BOM 会进入 ERP 同步队列，入队不代表 ERP 已接收。','发布并确认当前 BOM',{confirmButtonText:'确认正式发布',cancelButtonText:'返回核对'}).catch(() => false)
  if (!confirmed) return
  actionLoading.value = true
  try {
    await confirmCurrentBomVersionApi(selectedBomId.value)
    await load(selectedBomId.value)
    emit('changed')
    ElMessage.success('当前 BOM 已正式确认；请在集成监控核对 ERP 同步结果')
  } finally {
    actionLoading.value = false
  }
}

async function cancelCurrentBomVersion() {
  if (!selectedBomId.value || !selectedBom.value?.currentFormal) return
  await ElMessageBox.confirm(
    `确认取消 BOM ${selectedBom.value.bomCode}（${selectedBom.value.versionNo}）的当前正式确认吗？`,
    '取消确认',
    {
      confirmButtonText: '取消确认',
      cancelButtonText: '返回',
      type: 'warning'
    }
  )
  actionLoading.value = true
  try {
    await cancelCurrentBomConfirmation(selectedBomId.value)
    await load(selectedBomId.value)
    emit('changed')
    ElMessage.success('当前 BOM 版本已取消确认')
  } finally {
    actionLoading.value = false
  }
}

watch(() => props.projectId, () => load(), { immediate: true })
</script>

<template>
  <section class="bom-workbench" v-loading="loading">
    <header class="bom-workbench__header">
      <div>
        <h4>BOM 工作台</h4>
        <p>草稿维护 → 提交审核 → 显式正式发布并确认。已发布版本不可原地编辑，变更通过复制新版本；ERP 同步结果独立核对。</p>
      </div>
      <div class="command-row">
        <el-tooltip content="刷新"><el-button :icon="Refresh" circle @click="load(selectedBomId || undefined)" /></el-tooltip>
        <el-button v-if="canWriteBom" data-test="bom-create" type="primary" :icon="Plus" @click="openCreateBom">新建 BOM</el-button>
      </div>
    </header>

    <el-alert v-if="loadError" type="error" :title="loadError" show-icon :closable="false" />

    <div v-if="candidateBoms.length" class="mode-panel">
      <div class="formal-toolbar">
        <el-select v-model="selectedBomId" aria-label="选择候选 BOM 版本" @change="changeVersion">
          <el-option v-for="bom in candidateBoms" :key="bom.productBomId" :label="`${bom.versionNo} - ${bom.bomName}`" :value="bom.productBomId" />
        </el-select>
        <el-tag v-if="selectedBom?.currentFormal" type="success" effect="light">当前正式</el-tag>
        <el-tag v-else effect="light">候选</el-tag>
        <el-tag v-if="selectedBom?.routeName" effect="plain">{{ selectedBom.routeName }}</el-tag>
        <div class="command-row command-row--push">
          <el-button :icon="Upload" :disabled="!selectedBomId || isReadOnly || !canWriteBom" @click="importVisible = true">导入 XLSX</el-button>
          <el-button data-test="bom-edit" :disabled="!selectedBomId || isReadOnly || !canWriteBom" @click="routeEditorVisible = true">维护 BOM 明细</el-button>
          <el-button data-test="bom-item-add" :disabled="!selectedBomId || isReadOnly || !canWriteBom" @click="routeEditorVisible = true">添加明细</el-button>
          <el-button
            v-if="selectedBom?.currentFormal && !isReadOnly"
            data-test="bom-cancel-confirmation"
            type="warning"
            plain
            :loading="actionLoading"
            :disabled="!canCancelCurrentBom"
            @click="cancelCurrentBomVersion"
          >
            取消确认
          </el-button>
          <el-button
            v-else-if="!['released','archived'].includes(selectedStatus || '')"
            data-test="bom-confirm-current"
            type="primary"
            :loading="actionLoading"
            :disabled="!canConfirmCurrentBom"
            @click="confirmCurrentBomVersion"
          >
            发布并确认当前 BOM
          </el-button>
        </div>
      </div>

      <el-alert v-if="hasBomRisks" :key="canReadMoney ? 'financial-risk-summary' : 'engineering-risk-summary'" class="bom-risk-alert" type="warning" show-icon :closable="false">
        <template #title>
          <span>候选 BOM 仍有待确认项：</span>
          <el-tag size="small" type="warning">人工物料 {{ bomRiskSummary.manualRows }}</el-tag>
          <el-tag size="small" type="danger">供应商缺失 {{ bomRiskSummary.supplierMissing }}</el-tag>
          <el-tag v-if="canReadMoney" size="small" type="danger">成本缺失 {{ bomRiskSummary.costMissing }}</el-tag>
        </template>
      </el-alert>

      <div v-if="workbench && canReadMoney" class="cost-metric-grid">
        <div><span>研发总成本</span><strong>{{ workbench.rdTotalCost ?? '--' }}</strong></div>
        <div><span>正式版本平均单个成本</span><strong>{{ workbench.formalAverageUnitCost ?? '--' }}</strong></div>
        <div><span>该 BOM 单个 SKU 成本</span><strong>{{ workbench.currentBomSkuUnitCost ?? '--' }}</strong></div>
      </div>

      <el-table :data="candidateBoms" class="candidate-table" size="small" @row-click="selectBom">
        <el-table-column prop="versionNo" label="版本" width="90" />
        <el-table-column prop="bomName" label="BOM 名称" min-width="150" />
        <el-table-column prop="routeName" label="关联工艺路线" min-width="150" />
        <el-table-column label="候选状态" width="110">
          <template #default="{ row }">{{ ({draft:'草稿',reviewing:'审核中（未发布）',released:'正式已发布',frozen:'冻结',archived:'已归档'} as Record<string,string>)[row.candidateStatus || row.status] || row.status }}</template>
        </el-table-column>
        <el-table-column label="物料数" width="90">
          <template #default="{ row }">{{ row.materialCount ?? row.items?.length ?? 0 }}</template>
        </el-table-column>
        <el-table-column v-if="canReadMoney" label="试算成本" width="120">
          <template #default="{ row }">{{ row.totalCost ?? '--' }}</template>
        </el-table-column>
        <el-table-column label="正式关系" width="110">
          <template #default="{ row }">
            <el-tag v-if="row.currentFormal" type="success" size="small">当前正式</el-tag>
            <span v-else>候选</span>
          </template>
        </el-table-column>
      </el-table>

      <div v-if="workbench?.routes.length" class="route-list">
        <article v-for="route in workbench.routes" :key="route.productBomRouteId || route.routeVariantNo" class="route-row">
          <div class="route-row__identity"><strong>{{ route.variantName || route.routeName }}</strong><code>{{ route.routeCode }} / {{ route.routeVariantNo || 'BASE' }}</code></div>
          <div class="color-list"><el-tag v-for="color in route.colors" :key="color" size="small">{{ color }}</el-tag></div>
          <span>{{ route.items.length }} 项物料</span>
          <strong v-if="canReadMoney">{{ route.costSnapshot ? `${route.costSnapshot.currencyCode} ${route.skuUnitCost ?? route.costSnapshot.totalCost}` : '待计算' }}</strong>
        </article>
      </div>
      <el-empty v-else description="当前候选 BOM 尚未维护工艺路线明细" />

      <footer class="lifecycle-bar">
        <el-button v-if="canReadMoney" data-test="bom-refresh-cost" :loading="actionLoading" :disabled="isReadOnly || !canWriteBom || !canWriteMoney" @click="lifecycle('cost')">刷新成本</el-button>
        <el-button data-test="bom-submit-review" :icon="Promotion" :disabled="!canReviewBom" @click="lifecycle('review')">{{ selectedStatus==='reviewing'?'审核中（未发布）':'提交审核' }}</el-button>
        <el-button data-test="bom-copy-version" :icon="DocumentCopy" :disabled="!canWriteBom" @click="lifecycle('copy')">复制为新版本</el-button>
        <el-button type="danger" plain :icon="Delete" :disabled="!canDeleteSelectedBom" @click="deleteSelectedBomVersion">删除版本</el-button>
      </footer>
      <p class="bom-workbench__note">提交审核不等于正式发布，也不会推 ERP。已正式发布的版本只读；如需变更，请复制新版本，不修改历史发布内容。</p>
      <p v-if="!canWriteMoney" class="bom-workbench__note">内部成本仅向财务授权账号展示与维护；当前用料保存不提交金额，已保存价格由服务端保留。</p>
    </div>
    <el-empty v-else description="当前项目还没有 BOM" />

    <el-dialog v-model="createVisible" title="新建候选 BOM" width="520px" destroy-on-close>
      <p class="create-dialog__hint">关联工艺路线决定这份候选 BOM 后续在哪条路线下参与成本试算和正式敲定。</p>
      <el-form label-width="110px">
        <el-form-item label="BOM 名称">
          <el-input v-model="createForm.bomName" placeholder="例如：候选 BOM V1" />
        </el-form-item>
        <el-form-item label="BOM 类型">
          <el-select v-model="createForm.bomType">
            <el-option label="MBOM" value="mbom" />
            <el-option label="EBOM" value="ebom" />
            <el-option label="包装 BOM" value="pack" />
          </el-select>
        </el-form-item>
        <el-form-item label="版本号">
          <el-input v-model="createForm.versionNo" placeholder="例如：V1" />
        </el-form-item>
        <el-form-item label="关联工艺路线" required>
          <el-select data-test="bom-route-select" v-model="createForm.processId" placeholder="请选择关联工艺路线" filterable>
            <el-option v-for="route in processRoutes" :key="route.processId" :label="route.processName" :value="route.processId" />
          </el-select>
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="createForm.remark" type="textarea" :rows="2" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createVisible = false">取消</el-button>
        <el-button data-test="bom-create-submit" type="primary" :loading="actionLoading" @click="submitCreateBom">保存候选 BOM</el-button>
      </template>
    </el-dialog>

    <BomImportDialog v-model="importVisible" :product-id="projectId" :bom-id="selectedBomId" @committed="load(selectedBomId || undefined)" />
    <BomRouteEditor
      v-if="routeEditorVisible && workbench"
      v-model="routeEditorVisible"
      :routes="workbench.routes"
      :process-routes="processRoutes"
      :loading="actionLoading"
      :money-readable="canReadMoney"
      :money-editable="canWriteMoney"
      @save="saveRoutes"
    />
  </section>
</template>

<style scoped>
.bom-workbench { min-width: 0; }
.bom-workbench__header, .formal-toolbar, .command-row, .lifecycle-bar { display: flex; align-items: center; gap: 10px; }
.bom-workbench__header { justify-content: space-between; margin-bottom: 14px; }
.bom-workbench__header h4, .bom-workbench__header p { margin: 0; }
.bom-workbench__header p { color: var(--plm-color-text-secondary); font-size: 13px; }
.bom-workbench__note { margin: 8px 0 0; color: var(--plm-color-text-secondary); font-size: 12px; text-align: right; }
.mode-panel { margin-top: 14px; }
.formal-toolbar { flex-wrap: wrap; margin-bottom: 12px; }
.formal-toolbar :deep(.el-select) { width: 260px; }
.command-row--push { margin-left: auto; }
.bom-risk-alert { margin-bottom: 12px; }
.bom-risk-alert :deep(.el-alert__title) { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; }
.cost-metric-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 10px; margin-bottom: 12px; }
.cost-metric-grid > div { display: grid; gap: 4px; padding: 10px; border: 1px solid var(--el-border-color-lighter); background: var(--el-fill-color-lighter); }
.cost-metric-grid span { color: var(--plm-color-text-secondary); font-size: 12px; }
.candidate-table { margin-bottom: 14px; }
.create-dialog__hint { margin: 0 0 12px; color: var(--plm-color-text-secondary); font-size: 13px; }
.route-list { border-top: 1px solid var(--el-border-color-lighter); }
.route-row { display: grid; grid-template-columns: minmax(170px, 1.2fr) minmax(180px, 1fr) 100px 110px; align-items: center; gap: 12px; min-height: 58px; border-bottom: 1px solid var(--el-border-color-lighter); }
.route-row__identity { display: grid; gap: 3px; }
.route-row code { color: var(--plm-color-text-secondary); font-size: 12px; }
.color-list { display: flex; flex-wrap: wrap; gap: 5px; }
.lifecycle-bar { justify-content: flex-end; flex-wrap: wrap; margin-top: 14px; }
@media (max-width: 760px) {
  .bom-workbench__header { align-items: flex-start; flex-direction: column; }
  .route-row { grid-template-columns: 1fr; padding: 10px 0; }
  .command-row--push { width: 100%; margin-left: 0; flex-wrap: wrap; }
}
</style>
