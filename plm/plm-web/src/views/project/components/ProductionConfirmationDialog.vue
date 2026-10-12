<script setup lang="ts">
import { ElMessage } from 'element-plus'
import { computed, ref, watch } from 'vue'

import { confirmProductionColors, confirmProductionRoutes, getBomWorkbench, getProductionConfirmation, getProjectBoms, type ProductionConfirmation } from '@/api/modules/bom'
import { getProjectProcessRoutes, type ProcessRouteVO } from '@/api/modules/process'
import type { BomRoute, BomWorkbench, ProductionRouteSelection } from '@/types/bom'

const props = defineProps<{
  modelValue: boolean
  projectId: number
  mode: 'operations' | 'colors'
  defaultProductBomRouteId?: number | null
}>()
const emit = defineEmits<{ (event: 'update:modelValue', value: boolean): void; (event: 'confirmed'): void }>()

const loading = ref(false)
const workbenches = ref<BomWorkbench[]>([])
const processRoutes = ref<ProcessRouteVO[]>([])
const confirmation = ref<ProductionConfirmation | null>(null)
const selectedRouteIds = ref<Record<number, number[]>>({})
const selectedOperationIds = ref<Record<number, number[]>>({})
const selectedApplicableColorCodes = ref<Record<number, string[]>>({})
const selectedColors = ref<string[]>([])

type RouteCandidate = BomRoute & {
  productBomId: number
  versionNo: string
  bomStatus: string
}

const routes = computed<RouteCandidate[]>(() => workbenches.value.flatMap((bom) =>
  bom.routes.map((route) => ({
    ...route,
    productBomId: bom.productBomId,
    versionNo: bom.versionNo,
    bomStatus: bom.status
  }))
))

const routeGroups = computed(() => processRoutes.value.map((process) => ({
  process,
  candidates: routes.value.filter((route) => route.processId === process.processId)
})).filter((group) => group.candidates.length))

const formalRouteSelections = computed<ProductionRouteSelection[]>(() => confirmation.value?.routeSelections || [])

const formalRouteRows = computed(() => formalRouteSelections.value
  .map((selection) => ({
    selection,
    route: routes.value.find((route) => route.productBomRouteId === selection.productBomRouteId)
  }))
  .filter((row): row is { selection: ProductionRouteSelection; route: RouteCandidate } => Boolean(row.route)))

type ColorSource = {
  codeItemId?: number | null
  codeValue?: string | null
  codeName?: string | null
  colorCode?: string | null
  colorName?: string | null
}

type NormalizedColor = {
  codeItemId: number
  codeValue: string
  codeName: string
  colorKey: string
}

type ColorOption = NormalizedColor & {
  route: RouteCandidate
}

function normalizeColor(source: ColorSource): NormalizedColor | null {
  const codeItemId = Number(source.codeItemId || 0)
  const codeValue = String(source.codeValue || source.colorCode || '').trim()
  const codeName = String(source.codeName || source.colorName || codeValue).trim()
  if (!codeItemId && !codeValue && !codeName) return null
  const normalizedCode = codeValue || codeName
  const normalizedName = codeName || codeValue
  return {
    codeItemId,
    codeValue: normalizedCode,
    codeName: normalizedName,
    colorKey: `${codeItemId || 'NO_ID'}|${normalizedCode || normalizedName}`
  }
}

const colorOptions = computed<ColorOption[]>(() => {
  const values = new Map<string, ColorOption>()
  formalRouteRows.value.forEach(({ selection, route }) => {
    const colors = selection.applicableColors?.length ? selection.applicableColors : (route.colorItems || [])
    colors.forEach((source) => {
      const color = normalizeColor(source)
      if (!color) return
      const key = `${route.productBomRouteId || route.productBomId}|${color.colorKey}`
      if (!values.has(key)) values.set(key, { ...color, route })
    })
  })
  return [...values.values()]
})

function colorLabel(item: ColorOption) {
  const code = item.codeValue || '--'
  const name = item.codeName || item.codeValue || '--'
  return code === name ? name : `${code} · ${name}`
}

function routeLabel(route: RouteCandidate) {
  return route.routeName || route.versionNo || `BOM ${route.productBomId}`
}

async function load() {
  loading.value = true
  try {
    const [boms, processes, current] = await Promise.all([
      getProjectBoms(props.projectId),
      getProjectProcessRoutes(props.projectId),
      getProductionConfirmation(props.projectId)
    ])
    workbenches.value = await Promise.all(
      boms.filter((bom) => bom.bomType !== 'test' && bom.status === 'released')
        .map((bom) => getBomWorkbench(bom.productBomId))
    )
    processRoutes.value = processes
    confirmation.value = current
    initializeSelections(current)
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '投产方案加载失败')
  } finally {
    loading.value = false
  }
}

function initializeSelections(current: ProductionConfirmation) {
  const routesByProcess = new Map<number, ProductionRouteSelection[]>()
  for (const selection of current.routeSelections || []) {
    const selections = routesByProcess.get(selection.processId) || []
    selections.push(selection)
    routesByProcess.set(selection.processId, selections)
  }
  const routeValues: Record<number, number[]> = {}
  const operationValues: Record<number, number[]> = {}
  const colorValues: Record<number, string[]> = {}
  for (const group of routeGroups.value) {
    const existing = routesByProcess.get(group.process.processId) || []
    const preferred = group.candidates.find(candidate => candidate.productBomRouteId === props.defaultProductBomRouteId)
    const existingRouteIds = new Set(existing.map((selection) => selection.productBomRouteId))
    const selectedRoutes = preferred
      ? [preferred]
      : group.candidates.filter((candidate) => existingRouteIds.has(candidate.productBomRouteId!))
    const defaults = selectedRoutes.length ? selectedRoutes : group.candidates.slice(0, 1)
    routeValues[group.process.processId] = defaults.map((route) => route.productBomRouteId!)
    const confirmedOperationIds = existing.flatMap((selection) => selection.operationProcessIds || [])
    operationValues[group.process.processId] = confirmedOperationIds.length
      ? [...new Set(confirmedOperationIds)]
      : group.process.operations.map((operation) => operation.processId)
    for (const route of defaults) {
      const selection = existing.find((value) => value.productBomRouteId === route.productBomRouteId)
      colorValues[route.productBomRouteId!] = selection?.applicableColors?.length
        ? selection.applicableColors.map((color) => color.colorCode)
        : (route.colorItems || []).map((color) => color.codeValue)
    }
  }
  selectedRouteIds.value = routeValues
  selectedOperationIds.value = operationValues
  selectedApplicableColorCodes.value = colorValues
  const confirmedColorNames = new Set(current.colors || [])
  selectedColors.value = confirmedColorNames.size
    ? colorOptions.value.filter((value) =>
      confirmedColorNames.has(value.codeName)
      || confirmedColorNames.has(value.codeValue)
      || confirmedColorNames.has(value.colorKey)
    ).map((value) => value.colorKey)
    : colorOptions.value.map((value) => value.colorKey)
}

function selectedRoutes(processId: number) {
  const routeIds = new Set(selectedRouteIds.value[processId] || [])
  return routes.value.filter((route) => routeIds.has(route.productBomRouteId!))
}

function selectedRouteColorItems(productBomRouteId: number) {
  return routes.value.find((route) => route.productBomRouteId === productBomRouteId)?.colorItems || []
}

function syncApplicableColors(processId: number) {
  const colorValues = { ...selectedApplicableColorCodes.value }
  for (const route of selectedRoutes(processId)) {
    const routeId = route.productBomRouteId!
    if (!colorValues[routeId]) {
      colorValues[routeId] = (route.colorItems || []).map((color) => color.codeValue)
    }
  }
  selectedApplicableColorCodes.value = {
    ...colorValues
  }
}

async function confirm() {
  loading.value = true
  try {
    if (props.mode === 'operations') {
      const hasEmptyRouteGroup = routeGroups.value.some((group) => !(selectedRouteIds.value[group.process.processId] || []).length)
      const payloadRoutes = routeGroups.value.flatMap((group) => {
        const operationProcessIds = (selectedOperationIds.value[group.process.processId] || [])
          .filter((operationId) => group.process.operations.some((operation) => operation.processId === operationId))
        const selectedRouteIdsForGroup = selectedRoutes(group.process.processId)
        return selectedRouteIdsForGroup.map((route) => {
          const selectedColorCodes = new Set(selectedApplicableColorCodes.value[route.productBomRouteId!] || [])
          const applicableColors = (route.colorItems || [])
            .filter((color) => selectedColorCodes.has(color.codeValue))
            .map((color) => ({
              codeItemId: color.codeItemId,
              colorCode: color.codeValue,
              colorName: color.codeName
            }))
          return {
            processId: group.process.processId,
            productBomId: route.productBomId,
            productBomRouteId: route.productBomRouteId!,
            operationProcessIds,
            applicableColors
          }
        })
      })
      if (hasEmptyRouteGroup || !payloadRoutes.length || payloadRoutes.some((route) => !route.operationProcessIds.length || !route.applicableColors.length)) {
        ElMessage.warning('请先为每条工序选择使用 BOM，并至少选择一个适用颜色')
        return
      }
      await confirmProductionRoutes(props.projectId, { routes: payloadRoutes, remark: '确认工序、使用 BOM 与适用颜色' })
      ElMessage.success('工序、使用 BOM 与适用颜色已确认')
    } else {
      const colors = colorOptions.value.filter((value) => selectedColors.value.includes(value.colorKey)).map((value) => ({
        codeItemId: value.codeItemId,
        colorCode: value.codeValue,
        colorName: value.codeName,
        productBomId: value.route.productBomId,
        productBomRouteId: value.route.productBomRouteId!
      }))
      if (!colors.length) {
        ElMessage.warning('请至少选择一个批量投产颜色')
        return
      }
      const result = await confirmProductionColors(props.projectId, { colors })
      ElMessage.success(result.createdSkuCount ? `已创建 ${result.createdSkuCount} 个 SKU` : '正式投产颜色已确认')
    }
    emit('confirmed')
    emit('update:modelValue', false)
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '投产方案确认失败')
  } finally {
    loading.value = false
  }
}

watch(() => props.modelValue, (value) => { if (value) void load() }, { immediate: true })
</script>

<template>
  <el-dialog :model-value="modelValue" :title="mode === 'operations' ? '敲定工序：确认使用 BOM 与工序名称' : '确认批量投产颜色'" width="860px" destroy-on-close @close="emit('update:modelValue', false)">
    <div v-loading="loading" class="production-confirmation">
      <template v-if="mode === 'operations'">
        <article v-for="group in routeGroups" :key="group.process.processId" class="route-card">
          <header>
            <strong>{{ group.process.processName }}</strong>
            <span>{{ group.candidates.length }} 份候选 BOM</span>
          </header>
          <section>
            <p class="section-title">使用 BOM</p>
            <el-checkbox-group v-model="selectedRouteIds[group.process.processId]" class="candidate-list" @change="syncApplicableColors(group.process.processId)">
              <div v-for="route in group.candidates" :key="route.productBomRouteId" class="candidate-row">
                <el-checkbox :value="route.productBomRouteId" class="candidate-checkbox">
                  <span class="candidate-content">
                    <strong class="candidate-name">候选 BOM {{ route.versionNo }}</strong>
                    <span class="candidate-meta">{{ route.items.length }} 项物料</span>
                    <span class="candidate-meta">{{ route.costSnapshot?.currencyCode || 'CNY' }} {{ route.costSnapshot?.totalCost ?? '--' }}</span>
                  </span>
                </el-checkbox>
              </div>
            </el-checkbox-group>
          </section>
          <section>
            <p class="section-title">投产工序</p>
            <el-checkbox-group v-model="selectedOperationIds[group.process.processId]" class="operation-list">
              <div v-for="operation in group.process.operations" :key="operation.processId" class="operation-row">
                <el-checkbox :value="operation.processId" class="operation-checkbox">
                  <span class="operation-content">
                    <strong class="operation-name">{{ operation.sequenceNo }}. {{ operation.processName }}</strong>
                    <code v-if="operation.operationCode" class="operation-code">{{ operation.operationCode }}</code>
                  </span>
                </el-checkbox>
              </div>
            </el-checkbox-group>
            <div v-if="!group.process.operations.length" class="subtle-text">当前工艺路线暂无有效子工序</div>
          </section>
          <section>
            <p class="section-title">适用颜色</p>
            <div v-if="selectedRoutes(group.process.processId).length" class="applicable-route-list">
              <div v-for="route in selectedRoutes(group.process.processId)" :key="route.productBomRouteId" class="applicable-route-colors">
                <strong>BOM {{ route.versionNo }}</strong>
                <el-checkbox-group
                  v-if="selectedRouteColorItems(route.productBomRouteId!).length"
                  v-model="selectedApplicableColorCodes[route.productBomRouteId!]"
                  class="applicable-color-list"
                >
                  <el-checkbox
                    v-for="color in selectedRouteColorItems(route.productBomRouteId!)"
                    :key="color.codeItemId"
                    :value="color.codeValue"
                    class="applicable-color"
                  >
                    {{ color.codeValue }} · {{ color.codeName }}
                  </el-checkbox>
                </el-checkbox-group>
                <el-empty v-else description="当前使用 BOM 尚未维护适用颜色" />
              </div>
            </div>
            <el-empty v-else description="请至少选择一份使用 BOM" />
          </section>
        </article>
        <el-empty v-if="!routeGroups.length" description="当前项目还没有可敲定的候选 BOM 路线" />
      </template>
      <template v-else>
        <el-alert title="只展示已在“敲定工序”中确认使用 BOM 与适用颜色的路线颜色。" type="info" show-icon :closable="false" />
        <el-checkbox-group v-model="selectedColors" class="color-list">
          <el-checkbox
            v-for="item in colorOptions"
            :key="`${item.route.productBomRouteId}-${item.colorKey}`"
            :value="item.colorKey"
            class="color-row"
          >
            <span class="color-row__content">
              <strong class="color-label">{{ colorLabel(item) }}</strong>
              <span class="route-label">{{ routeLabel(item.route) }}</span>
              <code v-if="item.route.routeCode">{{ item.route.routeCode }}</code>
              <span v-else class="subtle-text">--</span>
              <span>{{ item.route.costSnapshot?.currencyCode || 'CNY' }} {{ item.route.costSnapshot?.totalCost ?? '--' }}</span>
            </span>
          </el-checkbox>
        </el-checkbox-group>
        <el-empty v-if="!colorOptions.length" description="请先在敲定工序中确认使用 BOM 与适用颜色" />
        <div class="selection-count">已选择 {{ selectedColors.length }} 个颜色</div>
      </template>
    </div>
    <template #footer>
      <el-button @click="emit('update:modelValue', false)">取消</el-button>
      <el-button :data-test="mode === 'colors' ? 'confirm-production-colors' : 'confirm-production-operations'" type="primary" :loading="loading" @click="confirm">{{ mode === 'colors' ? '确认批量投产并创建 SKU' : '确认使用 BOM 与适用颜色' }}</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.production-confirmation { min-height: 240px; }
.route-card { padding: 14px; border: 1px solid var(--el-border-color-lighter); border-radius: 8px; background: var(--el-bg-color); }
.route-card + .route-card { margin-top: 12px; }
.route-card header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px; }
.route-card header span, .section-title { color: var(--plm-color-text-secondary); font-size: 13px; }
.section-title { margin: 10px 0 6px; }
.candidate-list, .operation-list, .color-list { display: grid; border-top: 1px solid var(--el-border-color-lighter); }
.candidate-row, .operation-row, .color-row { display: grid; align-items: center; gap: 10px; min-height: 48px; border-bottom: 1px solid var(--el-border-color-lighter); color: var(--plm-color-text-primary, #1f2937); font-size: 14px; }
.candidate-row, .operation-row { display: block; padding: 8px 0; }
.candidate-checkbox, .operation-checkbox { width: 100%; margin-right: 0; }
.color-row { display: flex; width: 100%; align-items: center; justify-content: flex-start; padding: 8px 0; }
.color-row :deep(.el-checkbox__label) { flex: 1; min-width: 0; padding-left: 10px; }
.color-row__content { display: grid; grid-template-columns: minmax(160px, .8fr) minmax(180px, 1fr) minmax(90px, 110px) minmax(90px, 110px); align-items: center; gap: 10px; width: 100%; min-width: 0; color: var(--plm-color-text-primary, #1f2937); font-size: 14px; }
.candidate-content { display: grid; grid-template-columns: minmax(150px, 1fr) 100px 120px; align-items: center; gap: 10px; width: 100%; min-width: 0; color: var(--plm-color-text-primary, #1f2937); font-size: 14px; }
.candidate-checkbox :deep(.el-checkbox__label), .operation-checkbox :deep(.el-checkbox__label) { flex: 1; min-width: 0; color: var(--plm-color-text-primary, #1f2937); font-size: 14px; }
.candidate-checkbox :deep(.el-checkbox__input), .operation-checkbox :deep(.el-checkbox__input) { flex: 0 0 auto; }
.candidate-name, .candidate-meta { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.candidate-meta { color: var(--plm-color-text-secondary); font-size: 13px; }
.applicable-route-list { display: grid; gap: 12px; }
.applicable-route-colors { padding: 10px 0; border-bottom: 1px solid var(--el-border-color-lighter); }
.applicable-route-colors > strong { display: block; margin-bottom: 6px; font-size: 13px; }
.operation-row { grid-template-columns: 32px minmax(0, 1fr); padding: 8px 0; }
.operation-content { display: grid; gap: 4px; min-width: 0; }
.operation-content--route { grid-column: 1 / -1; }
.operation-main { display: flex; align-items: center; gap: 10px; min-width: 0; }
.operation-sequence { flex: 0 0 56px; color: var(--plm-color-text-secondary); font-variant-numeric: tabular-nums; }
.operation-name { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.operation-code { display: block; max-width: 100%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.applicable-color-list { display: flex; flex-wrap: wrap; gap: 8px 16px; padding: 10px 0 2px; border-top: 1px solid var(--el-border-color-lighter); }
.applicable-color { margin-right: 0; }
.color-label, .route-label { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.color-label { color: var(--plm-color-text-primary); font-weight: 700; }
.selection-count { margin-top: 12px; font-weight: 600; }
code { color: var(--plm-color-text-secondary); font-size: 12px; }
@media (max-width: 680px) {
  .candidate-row, .color-row { grid-template-columns: 32px 1fr; padding: 8px 0; }
  .candidate-row > :not(:first-child), .color-row > :not(:first-child) { grid-column: 2; }
  .operation-sequence { flex-basis: 42px; }
}
</style>
