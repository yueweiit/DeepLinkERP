<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'

import {
  abandonProject,
  archiveProject,
  checkProjectReleaseGate,
  freezeProject,
  publishProject,
  type ProductReleaseGateCheckVO
} from '@/api/modules/project'

interface Props {
  projectId: number
  productStatus: string
}

const props = defineProps<Props>()
const emit = defineEmits<{
  changed: []
}>()

const loading = ref(false)
const actionLoading = ref<false | 'freeze' | 'publish' | 'archive' | 'abandon'>(false)
const gate = ref<ProductReleaseGateCheckVO | null>(null)
const expandedRiskPanels = ref<string[]>([])

const isArchived = computed(() => props.productStatus === 'archived')
const isReleased = computed(() => props.productStatus === 'released')
const isLifecycleReadonly = computed(() => isArchived.value)
const sopOrSipCount = computed(() => Number(gate.value?.sopFileCount || 0) + Number(gate.value?.sipFileCount || 0))
const hasBlockingIssues = computed(() => Boolean(
  gate.value && (
    gate.value.blocking ||
    (!gate.value.passed && !gate.value.confirmRequired)
  )
))
const canPublish = computed(() =>
  !isReleased.value &&
  !isLifecycleReadonly.value &&
  Boolean(gate.value?.currentNodeConfirmed) &&
  !hasBlockingIssues.value
)
const hasReleaseRisks = computed(() => Boolean(gate.value?.confirmRequired))
const visibleMissingItems = computed(() => gate.value?.missingItems || [])
const isRiskDetailExpanded = computed(() => expandedRiskPanels.value.includes('risk'))
const riskSummaryText = computed(() => {
  if (!gate.value) return '预检中'
  if (isReleased.value) return '已发布'
  if (hasBlockingIssues.value) return `阻塞 ${visibleMissingItems.value.length}`
  if (hasReleaseRisks.value) return `待确认 ${visibleMissingItems.value.length}`
  return '资料齐备'
})
const riskSummaryType = computed(() => {
  if (!gate.value || isReleased.value) return 'success'
  if (hasBlockingIssues.value) return 'danger'
  if (hasReleaseRisks.value) return 'warning'
  return 'success'
})

function getErrorMessage(error: unknown, fallback: string) {
  if (error instanceof Error) return error.message
  const responseMessage = (error as { response?: { data?: { message?: string } } })?.response?.data?.message
  return responseMessage || fallback
}

function getReleaseGateFromError(error: unknown): ProductReleaseGateCheckVO | null {
  const responseData = (error as { response?: { data?: { code?: number; data?: ProductReleaseGateCheckVO } } })
    ?.response?.data
  if ((responseData?.code === 40307 || responseData?.code === 40308) && responseData.data) return responseData.data
  return null
}

function releaseConfirmMessage() {
  const risks = (gate.value?.missingItems || [])
    .filter((item) => item.severity === 'warning' || !item.severity)
    .map((item) => `• ${item.message}`)
    .join('\n')
  if (!risks) return '发布后 Product 将进入 released 状态，已发布版本不允许直接编辑。'
  return `当前产品存在资料缺口，发布后仍会进入 released 状态：\n${risks}\n\n确认继续发布？`
}

async function loadReleaseGate() {
  loading.value = true
  try {
    gate.value = await checkProjectReleaseGate(props.projectId)
  } catch (error) {
    ElMessage.error(getErrorMessage(error, '发布门禁预检失败'))
  } finally {
    loading.value = false
  }
}

async function handleFreeze() {
  if (actionLoading.value || isLifecycleReadonly.value) return
  try {
    await ElMessageBox.confirm('冻结会锁定当前 Product 资料状态，用于发布前版本留痕。', '确认冻结', {
      confirmButtonText: '冻结',
      cancelButtonText: '取消',
      type: 'warning'
    })
    actionLoading.value = 'freeze'
    await freezeProject(props.projectId, { reason: '前端项目中心冻结' })
    ElMessage.success('冻结成功')
    emit('changed')
    await loadReleaseGate()
  } catch (error) {
    if (error !== 'cancel' && error !== 'close') ElMessage.error(getErrorMessage(error, '冻结失败'))
  } finally {
    actionLoading.value = false
  }
}

async function handlePublish() {
  if (actionLoading.value || !canPublish.value) {
    if (isReleased.value) ElMessage.info('产品已发布，无需重复发布，可按需归档')
    return
  }
  try {
    if (hasBlockingIssues.value) {
      ElMessage.error('当前流程尚未满足发布条件，请先完成基础流程')
      return
    }
    await ElMessageBox.confirm(releaseConfirmMessage(), hasReleaseRisks.value ? '确认带风险发布' : '确认发布', {
      confirmButtonText: '发布',
      cancelButtonText: '取消',
      type: 'warning'
    })
    actionLoading.value = 'publish'
    const result = await publishProject(props.projectId, {
      reason: '前端项目中心发布',
      riskConfirmed: hasReleaseRisks.value
    })
    ElMessage.success(`发布成功，当前状态：${result.status}`)
    emit('changed')
    await loadReleaseGate()
  } catch (error) {
    const gateFromError = getReleaseGateFromError(error)
    if (gateFromError) {
      gate.value = gateFromError
      ElMessage.error(
        getReleaseGateFromErrorCode(error) === 40308
          ? '检测到发布资料风险，请确认后重试'
          : '当前流程尚未满足发布条件'
      )
      return
    }
    if (error !== 'cancel' && error !== 'close') ElMessage.error(getErrorMessage(error, '发布失败'))
  } finally {
    actionLoading.value = false
  }
}

function getReleaseGateFromErrorCode(error: unknown) {
  return (error as { response?: { data?: { code?: number } } })?.response?.data?.code
}

async function handleArchive() {
  if (actionLoading.value || isArchived.value) return
  try {
    const { value } = await ElMessageBox.prompt('请输入归档原因，便于后续追溯。', '归档项目', {
      confirmButtonText: '归档',
      cancelButtonText: '取消',
      inputPlaceholder: '例如：发布版本已停用，进入历史归档'
    })
    actionLoading.value = 'archive'
    await archiveProject(props.projectId, { reason: String(value || '').trim() || '前端项目中心归档' })
    ElMessage.success('归档成功')
    emit('changed')
  } catch (error) {
    if (error !== 'cancel' && error !== 'close') ElMessage.error(getErrorMessage(error, '归档失败'))
  } finally {
    actionLoading.value = false
  }
}

async function handleAbandon() {
  if (actionLoading.value || isReleased.value || isArchived.value) return
  try {
    const { value } = await ElMessageBox.prompt('请输入停止原因。停止后项目会进入已停止/归档，并同步关闭关联 Order。', '停止项目', {
      confirmButtonText: '确认停止',
      cancelButtonText: '取消',
      inputPlaceholder: '例如：客户取消需求，项目停止推进',
      inputValidator: (value) => Boolean(value?.trim()) || '请填写停止原因'
    })
    actionLoading.value = 'abandon'
    await abandonProject(props.projectId, { reason: value.trim() })
    ElMessage.success('项目已停止并归档')
    emit('changed')
  } catch (error) {
    if (error !== 'cancel' && error !== 'close') ElMessage.error(getErrorMessage(error, '停止失败'))
  } finally {
    actionLoading.value = false
  }
}

onMounted(loadReleaseGate)

watch(
  () => props.projectId,
  () => {
    gate.value = null
    expandedRiskPanels.value = []
    loadReleaseGate()
  }
)
</script>

<template>
  <section class="release-gate-panel">
    <div class="release-gate-panel__head">
      <div>
        <h4 class="release-gate-panel__title">项目发布风险</h4>
        <p class="release-gate-panel__desc">检查当前流程与资料完整度；仅硬门禁不通过时阻塞发布，资料缺口作为非阻塞提醒确认。</p>
      </div>
      <el-button size="small" :loading="loading" @click="loadReleaseGate">重新预检</el-button>
    </div>

    <el-alert
      v-if="isReleased"
      type="success"
      show-icon
      :closable="false"
      title="产品已发布，无需重复发布，可按需归档"
    />
    <el-alert
      v-else-if="gate && hasBlockingIssues"
      type="error"
      show-icon
      :closable="false"
      title="当前流程尚未满足发布条件"
    />
    <el-alert
      v-else-if="gate && hasReleaseRisks"
      type="warning"
      show-icon
      :closable="false"
      title="存在非阻塞提醒，确认后仍可发布"
    />
    <el-alert
      v-else-if="gate"
      type="success"
      show-icon
      :closable="false"
      title="资料齐备，可以发布"
    />
    <el-alert v-else type="info" show-icon :closable="false" title="正在读取发布门禁状态" />

    <el-collapse v-model="expandedRiskPanels" class="release-gate-panel__collapse" data-test="release-gate-risk-collapse">
      <el-collapse-item name="risk">
        <template #title>
          <div class="release-gate-panel__collapse-title">
            <span>风险明细</span>
            <el-tag size="small" :type="riskSummaryType" effect="light">{{ riskSummaryText }}</el-tag>
          </div>
        </template>

        <div v-if="isRiskDetailExpanded" class="release-gate-panel__risk-body" data-test="release-gate-risk-content">
          <ul v-if="visibleMissingItems.length" class="release-gate-panel__missing">
            <li v-for="item in visibleMissingItems" :key="item.code">
              <strong>{{ item.code }}</strong>
              <span>{{ item.message }}</span>
            </li>
          </ul>
          <el-empty v-else description="暂无发布风险" :image-size="64" />

          <div v-if="gate" class="release-gate-panel__stats">
            <span>BOM：{{ gate.frozenBomCount }}</span>
            <span>工艺路线：{{ gate.lockedProcessRouteCount }}</span>
            <span>图纸：{{ gate.drawingFileCount }}</span>
            <span>SOP/SIP：{{ sopOrSipCount }}</span>
            <span>测试资料：{{ gate.testingFileCount }}</span>
          </div>
        </div>
      </el-collapse-item>
    </el-collapse>

    <div class="release-gate-panel__actions">
      <el-button
        data-test="release-gate-freeze"
        :loading="actionLoading === 'freeze'"
        :disabled="Boolean(actionLoading) || isLifecycleReadonly"
        @click="handleFreeze"
      >
        冻结
      </el-button>
      <el-button
        data-test="release-gate-publish"
        type="primary"
        :loading="actionLoading === 'publish'"
        :disabled="Boolean(actionLoading) || !canPublish"
        @click="handlePublish"
      >
        {{ isReleased ? '已发布' : '发布 Product' }}
      </el-button>
      <el-button
        data-test="release-gate-archive"
        :loading="actionLoading === 'archive'"
        :disabled="Boolean(actionLoading) || isArchived"
        @click="handleArchive"
      >
        归档
      </el-button>
      <el-button
        data-test="release-gate-abandon"
        type="danger"
        plain
        :loading="actionLoading === 'abandon'"
        :disabled="Boolean(actionLoading) || isReleased || isArchived"
        @click="handleAbandon"
      >
        停止项目
      </el-button>
    </div>
  </section>
</template>

<style scoped>
.release-gate-panel {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 14px;
  border: 1px solid rgba(148, 163, 184, 0.2);
  border-radius: 8px;
  background: #fff;
}

.release-gate-panel__head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.release-gate-panel__title {
  margin: 0 0 4px;
  color: #0f172a;
  font-size: 16px;
}

.release-gate-panel__desc {
  margin: 0;
  color: #64748b;
  font-size: 13px;
}

.release-gate-panel__collapse {
  border-top: 1px solid rgba(148, 163, 184, 0.18);
  border-bottom: 1px solid rgba(148, 163, 184, 0.18);
}

.release-gate-panel__collapse-title,
.release-gate-panel__risk-body {
  display: flex;
  flex-direction: column;
  gap: 10px;
  min-width: 0;
}

.release-gate-panel__collapse-title {
  flex-direction: row;
  align-items: center;
  justify-content: space-between;
  width: 100%;
  padding-right: 12px;
  font-weight: 600;
}

.release-gate-panel__missing {
  display: grid;
  gap: 8px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.release-gate-panel__missing li {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  padding: 8px 10px;
  border-radius: 6px;
  background: #fff7ed;
  color: #9a3412;
  font-size: 13px;
}

.release-gate-panel__stats,
.release-gate-panel__actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}

.release-gate-panel__stats span {
  padding: 6px 10px;
  border-radius: 6px;
  background: #f1f5f9;
  color: #334155;
  font-size: 13px;
}

@media (max-width: 768px) {
  .release-gate-panel__head,
  .release-gate-panel__actions {
    align-items: stretch;
    flex-direction: column;
  }
}
</style>
