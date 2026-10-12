<script setup lang="ts">
import { ArrowDown, ArrowUp, Delete, DocumentCopy, Edit, Plus, Refresh } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { computed, reactive, ref, watch } from 'vue'

import {
  createProcessRoute,
  deleteProcessRoute,
  getProcessOperationMasters,
  getProcessRouteTemplates,
  getProjectProcessRoutes,
  updateProcessRoute,
  type ProcessOperationMasterVO,
  type ProcessOperationSavePayload,
  type ProcessRouteSavePayload,
  type ProcessRouteTemplateVO,
  type ProcessRouteVO
} from '@/api/modules/process'

const props = defineProps<{
  projectId: number
  productCode?: string
  productName?: string
  productType?: 'product_line' | 'model_variant' | 'sku'
  productSpecificCode?: string
  phoneModelCode?: string
  colorCode?: string
  autoCreate?: boolean
}>()
const emit = defineEmits<{ (event: 'changed'): void }>()

const loading = ref(false)
const templateLoading = ref(false)
const actionLoading = ref(false)
const loadError = ref('')
const routes = ref<ProcessRouteVO[]>([])
const templates = ref<ProcessRouteTemplateVO[]>([])
const operationMasterOptions = ref<ProcessOperationMasterVO[]>([])
const operationMasterLoading = ref(false)
const selectedProcessId = ref<number | null>(null)
const selectedTemplateCode = ref('')
const dialogVisible = ref(false)
const editing = ref(false)
const creatingVersion = ref(false)
const editingProcessId = ref<number | null>(null)

const routeForm = reactive<ProcessRouteSavePayload>({
  processName: '',
  versionNo: 'V1',
  routeTemplateCode: '',
  routeTemplateVersion: '',
  copyTemplateOperations: true,
  applicableModel: '',
  applicableColor: '',
  linkedBomVersionNo: '',
  finalSelected: false,
  remark: '',
  operations: []
})

const selectedRoute = computed(() =>
  routes.value.find((item) => item.processId === selectedProcessId.value) || null
)
const isReadonlyRoute = computed(() =>
  selectedRoute.value != null && !['draft', 'confirmed'].includes(selectedRoute.value.status)
)
const routeStatusTagType = computed(() => {
  const status = selectedRoute.value?.status
  if (status === 'locked' || status === 'confirmed') return 'success'
  if (status === 'archived') return 'info'
  return 'warning'
})
const routeStatusLabel = computed(() => {
  const status = selectedRoute.value?.status
  if (status === 'locked') return '已锁定'
  if (status === 'confirmed') return '已确认'
  if (status === 'archived') return '已归档'
  if (status === 'changed') return '已变更'
  return '草稿'
})
const canDeleteSelectedRoute = computed(() =>
  Boolean(selectedRoute.value && ['draft', 'confirmed'].includes(selectedRoute.value.status))
)
const selectedTemplate = computed(() =>
  templates.value.find((item) => item.routeTemplateCode === selectedTemplateCode.value) || null
)
const isProductLineRoute = computed(() => props.productType !== 'model_variant' && props.productType !== 'sku')
const generatedCodePreview = computed(() => {
  const productCode = props.productCode || 'PRODUCT'
  const templateCode = routeForm.routeTemplateCode || 'CUSTOM'
  const versionNo = routeForm.versionNo || 'V1'
  return `${productCode}-${templateCode}-${versionNo}`.replace(/[^A-Za-z0-9_-]/g, '-').replace(/-{2,}/g, '-').toUpperCase()
})

const materialStatusOptions = [
  { label: 'TPU / 10', value: '10' },
  { label: 'PC / 20', value: '20' },
  { label: '半成品 / 30', value: '30' }
]

const operationCraftCodeMap: Record<string, string> = {
  PROC_INJECTION: '1010',
  PROC_TPU_FORMING: '1010',
  PROC_BASE_FORMING: '1010',
  PROC_PUNCHING: '1020',
  PROC_TRIMMING: '1020',
  PROC_PRINTING: '1020',
  PROC_COATING: '1020',
  PROC_SPRAYING: '1020',
  PROC_ASSEMBLY: '4030',
  PROC_FINAL_INSPECTION: '4030',
  PROC_PACKING: '4030',
  PROC_CNC: '1020',
  PROC_MAGNET: '1020',
  PROC_MAGNET_ATTACH: '1020'
}

interface NodeCheckRow {
  displayOrder: number
  operationCode: string
  operationCraftCode: string
  businessOperationCode: string
  operationName: string
  predecessorNodeNames: string[]
  successorNodeNames: string[]
  backendPersisted: boolean
}

const formNodeCheckRows = computed(() => buildNodeCheckRows(routeForm.operations, false))
const selectedRouteNodeCheckRows = computed(() =>
  buildNodeCheckRows(
    selectedRoute.value?.operations.map((item) => ({
      sequenceNo: item.sequenceNo,
      operationMasterProcessId: item.operationMasterProcessId ?? null,
      operationCode: item.operationCraftCode || item.businessOperationCode || item.operationCode || item.processCode || `OP-${item.sequenceNo}`,
      operationCraftCode: item.operationCraftCode || '',
      materialStatusCode: item.materialStatusCode || '',
      finishedProductFlag: Boolean(item.finishedProductFlag),
      businessOperationCode: item.businessOperationCode || '',
      businessOperationCodeManualFlag: Boolean(item.businessOperationCodeManualFlag),
      productSpecificCode: item.productSpecificCode || '',
      phoneModelCode: item.phoneModelCode || '',
      colorCode: item.colorCode || '',
      generatedFinishedProductCode: item.generatedFinishedProductCode || '',
      codeGenerationContext: item.codeGenerationContext || '',
      processName: item.processName,
      processParamJson: item.processParamJson || '',
      standardTimeMins: item.standardTimeMins ?? 0,
      qualityRequirement: item.qualityRequirement,
      remark: item.remark || ''
    })) || [],
    true
  )
)

function buildNodeCheckRows(operations: ProcessOperationSavePayload[], persisted: boolean): NodeCheckRow[] {
  const sorted = [...operations].sort((left, right) => left.sequenceNo - right.sequenceNo)
  return sorted.map((operation, index) => {
    const operationCode = normalizeOperationCraftCode(operation.operationCraftCode)
      || operation.businessOperationCode
      || operation.operationCode
      || `OP-${operation.sequenceNo}`
    const operationCraftCode = normalizeOperationCraftCode(operation.operationCraftCode) || operation.operationCode || `OP-${operation.sequenceNo}`
    const businessOperationCode = operation.businessOperationCode || operation.generatedFinishedProductCode || '--'
    return {
      displayOrder: index + 1,
      operationCode,
      operationCraftCode,
      businessOperationCode,
      operationName: operation.processName,
      predecessorNodeNames: index > 0 ? [sorted[index - 1].processName || '上一道工序'] : [],
      successorNodeNames: index < sorted.length - 1 ? [sorted[index + 1].processName || '下一道工序'] : [],
      backendPersisted: persisted
    }
  })
}

function newOperation(sequenceNo: number): ProcessOperationSavePayload {
  return {
    sequenceNo,
    operationMasterProcessId: null,
    operationSource: 'manual_snapshot',
    operationCode: '',
    operationCraftCode: '',
    materialStatusCode: '',
    finishedProductFlag: false,
    businessOperationCode: '',
    businessOperationCodeManualFlag: false,
    productSpecificCode: deriveProductSpecificCode(),
    phoneModelCode: '',
    colorCode: '',
    generatedFinishedProductCode: '',
    codeGenerationContext: isProductLineRoute.value ? 'product_line_route' : '',
    processName: '',
    processParamJson: '{}',
    standardTimeMins: 0,
    qualityRequirement: '',
    remark: ''
  }
}

function errorMessage(error: unknown) {
  return error instanceof Error ? error.message : '请求失败，请稍后重试'
}

function deriveProductSpecificCode() {
  const explicit = props.productSpecificCode?.trim().toUpperCase()
  if (explicit) return explicit.replace(/[^A-Z0-9]/g, '')
  return ''
}

function normalizeBusinessCode(value: string | undefined | null, fallback: string) {
  const normalized = value?.trim().toUpperCase().replace(/[^A-Z0-9]/g, '') || ''
  return normalized || fallback
}

function normalizeOperationCraftCode(value: string | undefined | null) {
  const normalized = value?.trim().toUpperCase() || ''
  if (normalized === '10') return '1010'
  if (['20', '30', '51', '52'].includes(normalized)) return '1020'
  if (normalized === '40') return '4030'
  return normalized
}

function findOperationCraftCode(operation: ProcessOperationSavePayload) {
  const explicit = normalizeOperationCraftCode(operation.operationCraftCode)
  if (explicit) return explicit
  const master = operationMasterOptions.value.find((item) => item.processId === operation.operationMasterProcessId)
  const masterCraftCode = normalizeOperationCraftCode(master?.operationCraftCode)
  if (masterCraftCode) return masterCraftCode
  const operationCode = (operation.operationCode || master?.processCode || '').trim().toUpperCase()
  return operationCraftCodeMap[operationCode] || ''
}

function currentCodeGenerationContext() {
  if (props.productType === 'sku') return 'sku_route'
  if (props.productType === 'model_variant') return 'model_variant_route'
  return 'product_line_route'
}

function appendSuffixIfMissing(value: string, suffix: string) {
  if (!value || !suffix) return value
  return value.endsWith(suffix) ? value : `${value}${suffix}`
}

function baseBusinessOperationCode(operation: ProcessOperationSavePayload, manualPreferred = true) {
  const manualCode = normalizeBusinessCode(operation.businessOperationCode, '')
  if (manualPreferred && manualCode) return manualCode
  const productSpecificCode = normalizeBusinessCode(operation.productSpecificCode || props.productSpecificCode || deriveProductSpecificCode(), '')
  const operationCraftCode = findOperationCraftCode(operation)
  if (!productSpecificCode || !operationCraftCode) return ''
  return `N${productSpecificCode}${operationCraftCode}`.toUpperCase()
}

function stagedBusinessOperationCode(operation: ProcessOperationSavePayload, manualPreferred = true) {
  const baseCode = baseBusinessOperationCode(operation, manualPreferred)
  if (!baseCode) return ''
  const context = currentCodeGenerationContext()
  if (context === 'product_line_route') return baseCode
  const phoneModelCode = normalizeBusinessCode(operation.phoneModelCode || props.phoneModelCode, '')
  if (!phoneModelCode) return baseCode
  const modelCode = appendSuffixIfMissing(baseCode, phoneModelCode)
  if (context === 'model_variant_route') return modelCode
  const colorCode = normalizeBusinessCode(operation.colorCode || props.colorCode, '')
  return colorCode ? appendSuffixIfMissing(modelCode, colorCode) : modelCode
}

function previewBusinessOperationCode(operation: ProcessOperationSavePayload) {
  return stagedBusinessOperationCode(operation, false)
}

function refreshBusinessOperationCode(operation: ProcessOperationSavePayload) {
  operation.operationCraftCode = findOperationCraftCode(operation)
  operation.productSpecificCode = normalizeBusinessCode(operation.productSpecificCode || props.productSpecificCode || deriveProductSpecificCode(), '')
  if (isProductLineRoute.value) {
    operation.phoneModelCode = ''
    operation.colorCode = ''
    if (!operation.businessOperationCodeManualFlag || !operation.businessOperationCode?.trim()) {
      operation.businessOperationCode = previewBusinessOperationCode(operation)
      operation.businessOperationCodeManualFlag = false
    }
    operation.generatedFinishedProductCode = ''
    operation.codeGenerationContext = 'product_line_route'
    return
  }
  operation.phoneModelCode = normalizeBusinessCode(operation.phoneModelCode || props.phoneModelCode, '')
  operation.colorCode = currentCodeGenerationContext() === 'sku_route'
    ? normalizeBusinessCode(operation.colorCode || props.colorCode, '')
    : ''
  if (operation.businessOperationCodeManualFlag && operation.businessOperationCode?.trim()) {
    operation.businessOperationCode = stagedBusinessOperationCode(operation)
  } else {
    operation.businessOperationCode = previewBusinessOperationCode(operation)
    operation.businessOperationCodeManualFlag = false
  }
  operation.generatedFinishedProductCode = operation.operationCraftCode === '4030' ? operation.businessOperationCode : ''
  operation.codeGenerationContext = currentCodeGenerationContext()
}

function handleMaterialStatusChange(operation: ProcessOperationSavePayload) {
  refreshBusinessOperationCode(operation)
}

function handleBusinessOperationCodeInput(operation: ProcessOperationSavePayload) {
  operation.businessOperationCode = operation.businessOperationCode?.trim().toUpperCase() || ''
  operation.businessOperationCodeManualFlag = Boolean(operation.businessOperationCode)
}

async function loadTemplates() {
  templateLoading.value = true
  try {
    templates.value = await getProcessRouteTemplates({ productCode: props.productCode })
  } finally {
    templateLoading.value = false
  }
}

async function loadOperationMasters(keyword = '') {
  operationMasterLoading.value = true
  try {
    const rows = await getProcessOperationMasters({ keyword: keyword.trim() || undefined })
    operationMasterOptions.value = rows.filter((item) => ['confirmed', 'locked'].includes(item.status))
  } finally {
    operationMasterLoading.value = false
  }
}

async function loadRoutes(preferredProcessId?: number) {
  loading.value = true
  loadError.value = ''
  try {
    const result = await getProjectProcessRoutes(props.projectId)
    routes.value = result
    const preferred = preferredProcessId ?? selectedProcessId.value
    selectedProcessId.value = result.some((item) => item.processId === preferred)
      ? preferred
      : result[0]?.processId ?? null
  } catch (error) {
    loadError.value = errorMessage(error)
  } finally {
    loading.value = false
  }
}

function applyTemplate(template: ProcessRouteTemplateVO | null) {
  if (!template) return
  selectedTemplateCode.value = template.routeTemplateCode
  routeForm.routeTemplateCode = template.routeTemplateCode
  routeForm.routeTemplateVersion = template.versionNo
  routeForm.processName = template.routeTemplateName
  routeForm.versionNo = template.versionNo || 'V1'
  routeForm.copyTemplateOperations = true
  routeForm.operations.splice(
    0,
    routeForm.operations.length,
    ...template.operations.map((operation) => ({
      sequenceNo: operation.sequenceNo,
      operationMasterProcessId: operation.operationMasterProcessId ?? null,
      operationCode: operation.operationCode,
      operationCraftCode: operation.operationCraftCode || '',
      materialStatusCode: operation.materialStatusCode || '',
      finishedProductFlag: Boolean(operation.finishedProductFlag),
      businessOperationCode: operation.businessOperationCode || '',
      businessOperationCodeManualFlag: Boolean(operation.businessOperationCodeManualFlag),
      productSpecificCode: operation.productSpecificCode || '',
      phoneModelCode: operation.phoneModelCode || '',
      colorCode: operation.colorCode || '',
      generatedFinishedProductCode: operation.generatedFinishedProductCode || '',
      codeGenerationContext: operation.codeGenerationContext || '',
      processName: operation.processName,
      processParamJson: operation.processParamJson || '{}',
      standardTimeMins: operation.standardTimeMins ?? 0,
      qualityRequirement: operation.qualityRequirement,
      remark: operation.remark || ''
    }))
  )
  routeForm.operations.forEach(refreshBusinessOperationCode)
}

function resetForm(route?: ProcessRouteVO) {
  selectedTemplateCode.value = route?.routeTemplateCode || ''
  routeForm.processName = route?.processName || ''
  routeForm.versionNo = route?.versionNo || 'V1'
  routeForm.routeTemplateCode = route?.routeTemplateCode || ''
  routeForm.routeTemplateVersion = route?.routeTemplateVersion || ''
  routeForm.copyTemplateOperations = !route
  routeForm.applicableModel = route?.applicableModel || ''
  routeForm.applicableColor = route?.applicableColor || ''
  routeForm.linkedBomVersionNo = route?.linkedBomVersionNo || ''
  routeForm.finalSelected = Boolean(route?.finalSelected)
  routeForm.remark = route?.remark || ''
  routeForm.operations.splice(
    0,
    routeForm.operations.length,
    ...(route?.operations.map((item) => ({
      sequenceNo: item.sequenceNo,
      operationMasterProcessId: item.operationMasterProcessId ?? null,
      operationSource: item.operationSource || (item.remark?.includes('历史存档导入') ? 'imported_snapshot' : 'manual_snapshot'),
      operationCode: item.operationCode || item.processCode || `OP-${item.sequenceNo}`,
      operationCraftCode: item.operationCraftCode || '',
      materialStatusCode: item.materialStatusCode || '',
      finishedProductFlag: Boolean(item.finishedProductFlag),
      businessOperationCode: item.businessOperationCode || '',
      businessOperationCodeManualFlag: Boolean(item.businessOperationCodeManualFlag),
      productSpecificCode: item.productSpecificCode || '',
      phoneModelCode: item.phoneModelCode || '',
      colorCode: item.colorCode || '',
      generatedFinishedProductCode: item.generatedFinishedProductCode || '',
      codeGenerationContext: item.codeGenerationContext || '',
      processName: item.processName,
      processParamJson: item.processParamJson || '{}',
      standardTimeMins: item.standardTimeMins ?? 0,
      qualityRequirement: item.qualityRequirement,
      remark: item.remark || ''
    })) || [])
  )
  routeForm.operations.forEach(refreshBusinessOperationCode)
}

function openCreate() {
  editing.value = false
  creatingVersion.value = false
  editingProcessId.value = null
  resetForm()
  applyTemplate(templates.value.find((item) => item.defaultTemplate) || templates.value[0] || null)
  if (!routeForm.operations.length) routeForm.operations.push(newOperation(10))
  dialogVisible.value = true
}

function openEdit() {
  if (!selectedRoute.value || isReadonlyRoute.value) return
  editing.value = true
  creatingVersion.value = false
  editingProcessId.value = selectedRoute.value.processId
  resetForm(selectedRoute.value)
  dialogVisible.value = true
}

function nextVersionNo() {
  const versions = new Set(routes.value.map((route) => route.versionNo))
  const current = selectedRoute.value?.versionNo || 'V1'
  const match = current.match(/^(.*?)(\d+)$/)
  if (match) {
    let number = Number(match[2]) + 1
    let candidate = `${match[1]}${number}`
    while (versions.has(candidate)) candidate = `${match[1]}${++number}`
    return candidate
  }
  let charCode = current.length === 1 ? current.charCodeAt(0) + 1 : 2
  let candidate = current.length === 1 ? String.fromCharCode(charCode) : `V${charCode}`
  while (versions.has(candidate)) candidate = `V${++charCode}`
  return candidate
}

function openCreateVersion() {
  if (!selectedRoute.value) return
  editing.value = false
  creatingVersion.value = true
  editingProcessId.value = null
  resetForm(selectedRoute.value)
  routeForm.versionNo = nextVersionNo()
  routeForm.finalSelected = false
  routeForm.remark = `${routeForm.remark ? `${routeForm.remark}；` : ''}基于确认路线创建新版本`
  dialogVisible.value = true
}

function handleTemplateChange(code: string) {
  applyTemplate(templates.value.find((item) => item.routeTemplateCode === code) || null)
}

function applyOperationMaster(operation: ProcessOperationSavePayload, processId: number | null) {
  const master = operationMasterOptions.value.find((item) => item.processId === processId)
  if (!master) {
    operation.operationMasterProcessId = null
    operation.operationSource = operation.operationSource === 'imported_snapshot' ? 'imported_snapshot' : 'manual_snapshot'
    refreshBusinessOperationCode(operation)
    return
  }
  operation.operationMasterProcessId = master.processId
  operation.operationSource = 'master'
  operation.operationCode = master.processCode
  operation.operationCraftCode = master.operationCraftCode || operationCraftCodeMap[master.processCode] || ''
  operation.processName = master.processName
  operation.standardTimeMins = master.defaultStandardTimeMins ?? 0
  operation.qualityRequirement = master.defaultQualityRequirement || ''
  operation.processParamJson = master.defaultProcessParamJson || '{}'
  refreshBusinessOperationCode(operation)
}

function addOperationRow() {
  const nextSequence = routeForm.operations.length
    ? Math.max(...routeForm.operations.map((item) => item.sequenceNo)) + 10
    : 10
  routeForm.operations.push(newOperation(nextSequence))
}

function removeOperationRow(index: number) {
  if (routeForm.operations.length === 1) {
    ElMessage.warning('工艺路线至少保留一道工序')
    return
  }
  routeForm.operations.splice(index, 1)
}

function moveOperation(index: number, offset: -1 | 1) {
  const targetIndex = index + offset
  if (targetIndex < 0 || targetIndex >= routeForm.operations.length) return
  const current = routeForm.operations[index]
  routeForm.operations[index] = routeForm.operations[targetIndex]
  routeForm.operations[targetIndex] = current
  routeForm.operations.forEach((item, itemIndex) => {
    item.sequenceNo = (itemIndex + 1) * 10
  })
}

function validateForm() {
  if (!routeForm.processName.trim() || !routeForm.versionNo.trim()) {
    return '请填写工艺路线名称和版本号'
  }
  if (!routeForm.operations.length) return '工艺路线至少需要一道工序'
  const sequenceSet = new Set<number>()
  const businessOperationCodeSet = new Set<string>()
  for (const operation of routeForm.operations) {
    const businessOperationCode = stagedBusinessOperationCode(operation)
    if (operation.sequenceNo <= 0) return '工序顺序必须大于 0'
    if (sequenceSet.has(operation.sequenceNo)) return `工序顺序 ${operation.sequenceNo} 重复`
    sequenceSet.add(operation.sequenceNo)
    if (operation.materialStatusCode === '40') return '材料/状态不能选择成品，请使用成品勾选'
    if (!operation.processName.trim()) return `顺序 ${operation.sequenceNo} 的工序名称不能为空`
    const operationCraftCode = normalizeOperationCraftCode(operation.operationCraftCode)
    if (!operationCraftCode) return `顺序 ${operation.sequenceNo} 的基础工序编码不能为空`
    if (!/^[A-Z0-9_-]{1,20}$/.test(operationCraftCode)) return `顺序 ${operation.sequenceNo} 的基础工序编码格式不正确`
    if (!businessOperationCode) return `顺序 ${operation.sequenceNo} 的产品工序编码不能为空`
    if (!/^[A-Z0-9]{2,80}$/.test(businessOperationCode)) return `顺序 ${operation.sequenceNo} 的产品工序编码格式不正确`
    if (!businessOperationCode.startsWith('N')) return `顺序 ${operation.sequenceNo} 的产品工序编码必须以 N 开头`
    const context = currentCodeGenerationContext()
    const phoneModelCode = normalizeBusinessCode(operation.phoneModelCode || props.phoneModelCode, '')
    const colorCode = normalizeBusinessCode(operation.colorCode || props.colorCode, '')
    if (context === 'model_variant_route') {
      if (!/^[A-Z0-9]{4}$/.test(phoneModelCode)) return `顺序 ${operation.sequenceNo} 的手机型号编码必须为 4 位`
      if (!businessOperationCode.endsWith(phoneModelCode)) return `顺序 ${operation.sequenceNo} 的产品工序编码必须追加手机型号编码 ${phoneModelCode}`
    }
    if (context === 'sku_route') {
      if (!/^[A-Z0-9]{4}$/.test(phoneModelCode)) return `顺序 ${operation.sequenceNo} 的手机型号编码必须为 4 位`
      if (!/^[A-Z0-9]{2}$/.test(colorCode)) return `顺序 ${operation.sequenceNo} 的颜色编码必须为 2 位`
      if (!businessOperationCode.endsWith(`${phoneModelCode}${colorCode}`)) return `顺序 ${operation.sequenceNo} 的产品工序编码必须追加手机型号编码 ${phoneModelCode} 和颜色编码 ${colorCode}`
    }
    if (businessOperationCodeSet.has(businessOperationCode)) return `产品工序编码 ${businessOperationCode} 重复`
    businessOperationCodeSet.add(businessOperationCode)
    if (!operation.qualityRequirement.trim()) return `顺序 ${operation.sequenceNo} 的质量要求不能为空`
    if (operation.standardTimeMins != null && operation.standardTimeMins < 0) return '标准工时不能小于 0'
    if (operation.processParamJson?.trim()) {
      try {
        const parsed = JSON.parse(operation.processParamJson)
        if (!parsed || Array.isArray(parsed) || typeof parsed !== 'object') return `顺序 ${operation.sequenceNo} 的参数 JSON 必须是对象`
      } catch {
        return `顺序 ${operation.sequenceNo} 的参数 JSON 格式不正确`
      }
    }
  }
  return ''
}

async function saveRoute() {
  const validationError = validateForm()
  if (validationError) {
    ElMessage.warning(validationError)
    return
  }
  actionLoading.value = true
  try {
    const payload: ProcessRouteSavePayload = {
      processName: routeForm.processName.trim(),
      versionNo: routeForm.versionNo.trim(),
      routeTemplateCode: routeForm.routeTemplateCode?.trim() || undefined,
      routeTemplateVersion: routeForm.routeTemplateVersion?.trim() || undefined,
      copyTemplateOperations: Boolean(routeForm.copyTemplateOperations),
      linkedBomVersionNo: routeForm.linkedBomVersionNo?.trim() || undefined,
      finalSelected: Boolean(routeForm.finalSelected),
      remark: routeForm.remark?.trim() || undefined,
      operations: routeForm.operations.map((item) => ({
        ...item,
        operationMasterProcessId: item.operationMasterProcessId ?? null,
        operationSource: item.operationMasterProcessId
          ? 'master'
          : item.operationSource === 'imported_snapshot'
            ? 'imported_snapshot'
            : 'manual_snapshot',
        operationCode: item.operationCode?.trim().toUpperCase() || undefined,
        operationCraftCode: normalizeOperationCraftCode(item.operationCraftCode) || undefined,
        materialStatusCode: item.materialStatusCode?.trim().toUpperCase() || undefined,
        finishedProductFlag: Boolean(item.finishedProductFlag),
        businessOperationCode: stagedBusinessOperationCode(item) || undefined,
        businessOperationCodeManualFlag: Boolean(item.businessOperationCodeManualFlag),
        productSpecificCode: item.productSpecificCode?.trim().toUpperCase() || props.productSpecificCode?.trim().toUpperCase() || deriveProductSpecificCode() || undefined,
        phoneModelCode: currentCodeGenerationContext() === 'product_line_route'
          ? undefined
          : item.phoneModelCode?.trim().toUpperCase() || props.phoneModelCode?.trim().toUpperCase() || undefined,
        colorCode: currentCodeGenerationContext() === 'sku_route'
          ? item.colorCode?.trim().toUpperCase() || props.colorCode?.trim().toUpperCase() || undefined
          : undefined,
        generatedFinishedProductCode: normalizeOperationCraftCode(item.operationCraftCode) === '4030'
          ? stagedBusinessOperationCode(item) || undefined
          : undefined,
        codeGenerationContext: currentCodeGenerationContext(),
        processName: item.processName.trim(),
        qualityRequirement: item.qualityRequirement.trim(),
        processParamJson: item.processParamJson?.trim() || '{}',
        remark: item.remark?.trim() || undefined
      }))
    }
    const result = editing.value && editingProcessId.value
      ? await updateProcessRoute(editingProcessId.value, payload)
      : await createProcessRoute(props.projectId, payload)
    dialogVisible.value = false
    await loadRoutes(result.processId)
    emit('changed')
    ElMessage.success(editing.value ? '工艺路线已更新' : creatingVersion.value ? '工艺路线新版本已创建' : '工艺路线已创建')
  } finally {
    actionLoading.value = false
  }
}

async function deleteRoute() {
  if (!selectedRoute.value || !canDeleteSelectedRoute.value) return
  await ElMessageBox.confirm(
    `确认删除工艺路线 ${selectedRoute.value.processCode}（${selectedRoute.value.versionNo}）吗？删除后仅做软删除，不再出现在当前路线列表中。`,
    '删除工艺路线版本',
    {
      confirmButtonText: '删除',
      cancelButtonText: '取消',
      type: 'warning'
    }
  )
  actionLoading.value = true
  try {
    await deleteProcessRoute(selectedRoute.value.processId)
    await loadRoutes()
    emit('changed')
    ElMessage.success('工艺路线版本已删除')
  } finally {
    actionLoading.value = false
  }
}

watch(
  () => [props.projectId, props.productCode],
  async () => {
    await Promise.all([loadTemplates(), loadOperationMasters(), loadRoutes()])
    if (props.autoCreate && !dialogVisible.value) openCreate()
  },
  { immediate: true }
)
</script>

<template>
  <div class="m4-panel" v-loading="loading">
    <div class="m4-panel__toolbar">
      <div>
        <h4 class="section-title">工艺路线</h4>
        <p class="page-panel-desc">从标准路线模板新建结构化 Process，保存后以节点核对表确认真实后端工序关系。</p>
      </div>
      <div class="m4-panel__actions">
        <el-button :icon="Refresh" circle title="刷新工艺路线" @click="loadRoutes()" />
        <el-button data-test="process-create" type="primary" :icon="Plus" @click="openCreate">新建工艺路线</el-button>
      </div>
    </div>

    <el-alert v-if="loadError" :title="loadError" type="error" show-icon :closable="false" />

    <template v-else-if="selectedRoute">
      <div class="m4-panel__selector">
        <el-select v-model="selectedProcessId" class="m4-panel__select" aria-label="选择工艺路线">
          <el-option
            v-for="route in routes"
            :key="route.processId"
            :label="`${route.processName} / ${route.versionNo}`"
            :value="route.processId"
          />
        </el-select>
        <el-tag :type="routeStatusTagType" effect="light">{{ routeStatusLabel }}</el-tag>
        <el-tag v-if="selectedRoute.finalSelected" type="success" effect="light">最终确认</el-tag>
        <span class="m4-panel__code">{{ selectedRoute.processCode }}</span>
        <div class="m4-panel__actions m4-panel__actions--right">
          <el-button v-if="!isReadonlyRoute" data-test="process-edit" :icon="Edit" @click="openEdit">编辑路线</el-button>
          <el-button v-else data-test="process-edit" :icon="Edit" disabled>当前状态只读</el-button>
          <el-button
            v-if="isReadonlyRoute"
            data-test="process-create-version"
            type="primary"
            plain
            :icon="DocumentCopy"
            @click="openCreateVersion"
          >创建新版本</el-button>
          <el-button data-test="process-delete" type="danger" plain :icon="Delete" :disabled="!canDeleteSelectedRoute" @click="deleteRoute">删除版本</el-button>
        </div>
      </div>

      <div class="route-meta-strip">
        <span>模板：{{ selectedRoute.routeTemplateCode || '手工路线' }}</span>
        <span>BOM：{{ selectedRoute.linkedBomVersionNo || '--' }}</span>
        <span v-if="selectedRoute.finalSelected">最终确认路线</span>
      </div>

      <h5 class="route-check-title">节点配置核对表</h5>
      <el-table :data="selectedRouteNodeCheckRows" border stripe size="small" class="m4-panel__table">
        <el-table-column prop="displayOrder" label="顺序" width="72" />
        <el-table-column prop="businessOperationCode" label="产品工序编码" min-width="180" />
        <el-table-column prop="operationCraftCode" label="基础工序编码" min-width="150" />
        <el-table-column prop="operationName" label="工序名称" min-width="150" />
        <el-table-column label="前置节点" min-width="180">
          <template #default="{ row }">
            <span data-test="node-check-predecessor">{{ row.predecessorNodeNames.join('、') || '--' }}</span>
          </template>
        </el-table-column>
        <el-table-column label="后置节点" min-width="180">
          <template #default="{ row }">
            <span data-test="node-check-successor">{{ row.successorNodeNames.join('、') || '--' }}</span>
          </template>
        </el-table-column>
        <el-table-column label="保存状态" width="100"><template #default="{ row }"><el-tag size="small" :type="row.backendPersisted ? 'success' : 'info'">{{ row.backendPersisted ? '已落库' : '草稿' }}</el-tag></template></el-table-column>
      </el-table>
    </template>

    <el-empty v-else description="当前项目还没有工艺路线">
      <el-button data-test="process-create-empty" type="primary" :icon="Plus" @click="openCreate">新建工艺路线</el-button>
    </el-empty>

    <el-dialog v-model="dialogVisible" width="min(1080px, 94vw)" append-to-body>
      <template #header>
        <div class="process-dialog-title">
          <span>{{ editing ? '编辑工艺路线' : creatingVersion ? '创建工艺路线新版本' : '新建工艺路线' }}</span>
          <el-tag v-if="productName || productCode" effect="plain">{{ productName || productCode }}</el-tag>
        </div>
      </template>
      <el-form label-width="108px" class="route-form-head">
        <el-form-item label="路线模板">
          <el-select
            v-model="selectedTemplateCode"
            data-test="process-template-select"
            :loading="templateLoading"
            filterable
            placeholder="选择标准工艺路线"
            @change="handleTemplateChange"
          >
            <el-option
              v-for="template in templates"
              :key="template.routeTemplateCode"
              :label="`${template.routeTemplateName} / ${template.versionNo}`"
              :value="template.routeTemplateCode"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="路线名称" required>
          <div data-test="process-route-name-input">
            <el-input v-model="routeForm.processName" maxlength="100" />
          </div>
        </el-form-item>
        <el-form-item label="版本号" required>
          <div data-test="process-route-version-input">
            <el-input v-model="routeForm.versionNo" maxlength="50" />
          </div>
        </el-form-item>
        <el-form-item label="编码预览"><el-input :model-value="generatedCodePreview" disabled /></el-form-item>
        <el-form-item label="BOM 版本"><el-input v-model="routeForm.linkedBomVersionNo" maxlength="50" placeholder="后续最终确认时补齐" /></el-form-item>
        <el-form-item label="最终确认"><el-switch v-model="routeForm.finalSelected" /></el-form-item>
        <el-form-item label="备注" class="route-form-head__wide"><el-input v-model="routeForm.remark" maxlength="500" /></el-form-item>
      </el-form>

      <div class="operation-editor__head">
        <strong>工序明细</strong>
        <el-button type="primary" plain :icon="Plus" @click="addOperationRow">添加工序</el-button>
      </div>
      <div class="operation-editor" data-test="operation-editor">
        <div class="operation-editor__columns" data-test="operation-editor-columns" aria-hidden="true">
          <span>顺序</span>
          <span>产品工序编码</span>
          <span>工序名称</span>
          <span>基础工序编码</span>
          <span>工序库</span>
          <span>材料/状态</span>
          <span>成品</span>
          <span>标准工时</span>
          <span>工艺参数</span>
          <span>质量要求</span>
          <span>操作</span>
        </div>
        <div v-for="(operation, index) in routeForm.operations" :key="index" class="operation-row">
          <el-input-number v-model="operation.sequenceNo" :min="1" :step="10" controls-position="right" aria-label="工序顺序" />
          <div data-test="business-operation-code-input">
            <el-input
              v-model="operation.businessOperationCode"
              :placeholder="isProductLineRoute ? '可手工填写，如 NHD1010' : '系统追加机型/颜色编码，可人工修正'"
              maxlength="80"
              @input="() => handleBusinessOperationCodeInput(operation)"
              @change="() => handleBusinessOperationCodeInput(operation)"
            />
          </div>
          <div data-test="operation-name-input">
            <el-input v-model="operation.processName" placeholder="输入工序名称" maxlength="100" />
          </div>
          <div data-test="operation-craft-code-input">
            <el-input
              v-model="operation.operationCraftCode"
              placeholder="输入基础工序编码，如 1010"
              maxlength="20"
              @input="() => refreshBusinessOperationCode(operation)"
              @change="() => refreshBusinessOperationCode(operation)"
            />
          </div>
          <el-select
            v-model="operation.operationMasterProcessId"
            data-test="process-operation-master-select"
            :loading="operationMasterLoading"
            clearable
            filterable
            :placeholder="operation.operationSource === 'imported_snapshot' ? `${operation.processName} / 历史导入` : '可选：从工序库带入'"
            @visible-change="(visible: boolean) => visible && loadOperationMasters()"
            @change="(processId: number | null) => applyOperationMaster(operation, processId)"
          >
            <el-option
              v-for="item in operationMasterOptions"
              :key="item.processId"
              :label="`${item.processName} / ${item.processCode}`"
              :value="item.processId"
            />
          </el-select>
          <div data-test="material-status-select">
            <el-select
              v-model="operation.materialStatusCode"
              clearable
              placeholder="选择材料/状态"
              @change="() => handleMaterialStatusChange(operation)"
            >
              <el-option
                v-for="item in materialStatusOptions"
                :key="item.value"
                :label="item.label"
                :value="item.value"
              />
            </el-select>
          </div>
          <div data-test="finished-product-checkbox">
            <el-checkbox
              v-model="operation.finishedProductFlag"
            >
              成品
            </el-checkbox>
          </div>
          <el-input-number v-model="operation.standardTimeMins" :min="0" :precision="2" controls-position="right" aria-label="标准工时，单位分钟" />
          <el-input v-model="operation.processParamJson" placeholder='工艺参数 JSON，例如 {"pressure":30}' />
          <el-input v-model="operation.qualityRequirement" placeholder="填写该工序的质量要求" maxlength="500" />
          <div class="operation-row__actions">
            <el-button :icon="ArrowUp" circle :disabled="index === 0" title="上移" @click="moveOperation(index, -1)" />
            <el-button :icon="ArrowDown" circle :disabled="index === routeForm.operations.length - 1" title="下移" @click="moveOperation(index, 1)" />
            <el-button :icon="Delete" circle type="danger" plain title="删除工序" @click="removeOperationRow(index)" />
          </div>
        </div>
      </div>

      <h5 class="route-check-title">节点配置核对表</h5>
      <el-table :data="formNodeCheckRows" border stripe size="small" class="m4-panel__table">
        <el-table-column prop="displayOrder" label="顺序" width="72" />
        <el-table-column prop="businessOperationCode" label="产品工序编码" min-width="180" />
        <el-table-column prop="operationCraftCode" label="基础工序编码" min-width="150" />
        <el-table-column prop="operationName" label="工序名称" min-width="150" />
        <el-table-column label="前置节点" min-width="180">
          <template #default="{ row }">
            <span data-test="node-check-predecessor">{{ row.predecessorNodeNames.join('、') || '--' }}</span>
          </template>
        </el-table-column>
        <el-table-column label="后置节点" min-width="180">
          <template #default="{ row }">
            <span data-test="node-check-successor">{{ row.successorNodeNames.join('、') || '--' }}</span>
          </template>
        </el-table-column>
        <el-table-column label="保存状态" width="100"><template #default="{ row }"><el-tag size="small" :type="row.backendPersisted ? 'success' : 'info'">{{ row.backendPersisted ? '已落库' : '草稿' }}</el-tag></template></el-table-column>
      </el-table>

      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button data-test="process-route-save" type="primary" :loading="actionLoading" @click="saveRoute">{{ creatingVersion ? '保存新版本' : '保存完整路线' }}</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.m4-panel { min-width: 0; }
.process-dialog-title { display: flex; align-items: center; gap: 10px; }
.m4-panel__toolbar,
.m4-panel__selector,
.m4-panel__actions { display: flex; align-items: center; gap: 10px; }
.m4-panel__toolbar { justify-content: space-between; margin-bottom: 16px; }
.m4-panel__toolbar h4,
.m4-panel__toolbar p { margin-top: 0; }
.m4-panel__selector { flex-wrap: wrap; margin-bottom: 14px; }
.m4-panel__select { width: min(100%, 360px); }
.m4-panel__code { color: var(--plm-color-text-secondary); font-size: 13px; overflow-wrap: anywhere; }
.m4-panel__actions--right { margin-left: auto; }
.m4-panel__table { width: 100%; }
.route-meta-strip { display: flex; flex-wrap: wrap; gap: 8px 16px; margin: 0 0 12px; color: var(--plm-color-text-secondary); font-size: 13px; }
.route-check-title { margin: 16px 0 10px; font-size: 14px; }
.route-form-head { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; }
.route-form-head [data-test="process-route-name-input"],
.route-form-head [data-test="process-route-version-input"] { width: 100%; }
.route-form-head__wide { grid-column: span 2; }
.operation-editor__head { display: flex; align-items: center; justify-content: space-between; margin: 8px 0 12px; }
.operation-editor { max-height: 42vh; overflow: auto; font-size: 12px; }
.operation-editor__columns,
.operation-row { min-width: 1500px; display: grid; grid-template-columns: 88px minmax(158px, 1fr) minmax(150px, 1fr) minmax(122px, 0.8fr) minmax(150px, 1fr) 122px 70px 112px minmax(166px, 1.05fr) minmax(166px, 1.05fr) 104px; gap: 6px; align-items: center; }
.operation-editor__columns { position: sticky; top: 0; z-index: 1; padding: 8px 0; border-top: 1px solid var(--plm-color-border-light); border-bottom: 1px solid var(--plm-color-border-light); background: var(--plm-color-bg-container); color: var(--plm-color-text-secondary); font-size: 12px; font-weight: 600; }
.operation-row { padding: 6px 0; border-bottom: 1px solid var(--plm-color-border-light); }
.operation-row__actions { display: flex; gap: 4px; }
.operation-row__actions :deep(.el-button.is-circle) { width: 28px; height: 28px; }
.operation-editor :deep(.el-input__wrapper),
.operation-editor :deep(.el-select__wrapper) { min-height: 30px; padding-left: 8px; padding-right: 8px; }
.operation-editor :deep(.el-input-number) { width: 100%; }
.operation-editor :deep(.el-input-number__decrease),
.operation-editor :deep(.el-input-number__increase) { width: 28px; min-height: 28px; }
.operation-editor :deep(.el-input__inner),
.operation-editor :deep(.el-select__placeholder),
.operation-editor :deep(.el-select__selected-item),
.operation-editor :deep(.el-checkbox__label) { font-size: 12px; }
@media (max-width: 1100px) {
  .route-form-head { grid-template-columns: 1fr 1fr; }
  .operation-editor__columns { display: none; }
  .operation-row { grid-template-columns: 100px minmax(140px, 1fr); }
  .operation-row__actions,
  .route-form-head__wide { grid-column: 1 / -1; }
}
@media (max-width: 720px) {
  .m4-panel__toolbar { align-items: flex-start; flex-direction: column; }
  .m4-panel__actions--right { width: 100%; margin-left: 0; }
  .route-form-head { grid-template-columns: 1fr; }
}
</style>
