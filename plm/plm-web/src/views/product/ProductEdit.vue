<script setup lang="ts">
import { computed, nextTick, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, type FormInstance } from 'element-plus'

import { createProduct, getProductDetail, getProductPage, updateProduct, updateProductBasicInfo } from '@/api/modules/product'
import { getCollaborationItem, linkCollaborationProjects } from '@/api/modules/collaboration'
import { useUserStore } from '@/stores/user'
import PageContainer from '@/components/PageContainer/index.vue'
import type { MoldAction } from '@/types/common'
import type { ProcessTemplateOption } from '@/types/process'
import type { ProductFormPayload, ProductSummary, ProductTestItem } from '@/types/product'
import { toArchivedProductRoute } from '@/utils/projectRoute'
import { rules } from '@/utils/validate'

const route = useRoute()
const router = useRouter()
const collaborationItemId = computed(() => Number(route.query.collaborationItemId || 0))
const createdCollaborationProjectId = ref<number | null>(null)

const formRef = ref<FormInstance>()
const loading = ref(false)
const submitting = ref(false)
const productOptions = ref<ProductSummary[]>([])
const detailStatus = ref<ProductSummary['status'] | null>(null)

const productId = computed(() => Number(route.params.id || 0))
const isEdit = computed(() => Boolean(productId.value))
const isModelVariant = computed(() => form.productType === 'model_variant')
const isProductLine = computed(() => form.productType === 'product_line')
const isReleasedBasicInfoEdit = computed(() => isEdit.value && ['released', 'archived'].includes(detailStatus.value || ''))

const lineStageOptions = [
  '产品立项（含立项说明书）',
  '确认立项',
  '画图查看',
  '供应商确认外观图纸',
  '申请开模',
  '制作模具',
  '测试模具',
  '签样确认',
  '加工艺（工艺分类）',
  '敲定工序',
  '确认组件',
  '确认组件成品',
  '最终外观确认样',
  '红样测试',
  '整理生产资料（SIP/SOP）',
  '黄样',
  '小批量测试',
  '运模（选择物流）',
  'MX 验收',
  '测试验证（品质、数量）',
  'MX 小批量测试',
  '根据结果决定投产或继续优化'
]

const variantStageOptions = [
  '新型号需求确认',
  'Product 子版本建立',
  '图纸与外观差异确认',
  '开模/改模申请',
  '制作/修改模具',
  '测试模具',
  '组件与工艺差异确认',
  '样品确认',
  '差异测试验证',
  '生产资料整理',
  '小批量测试',
  '运模',
  'MX 验收',
  '墨西哥小批量生产验证',
  '版本冻结',
  '正式发布'
]

const defaultLineTests: ProductTestItem[] = [
  { name: '跌落测试', method: '1.2m 六面各两次', owner: '质量', frequency: '红样', result: '待执行', dueDate: '2026-06-20' },
  { name: '酒精测试', method: '95% 酒精 500 次', owner: '质量', frequency: '红样', result: '待执行', dueDate: '2026-06-21' },
  { name: '百格测试', method: '标准百格与胶带剥离', owner: '质量', frequency: '红样', result: '待执行', dueDate: '2026-06-22' },
  { name: '小批量跑线验证', method: '100-300 件产线节拍验证', owner: '工程 / 生产', frequency: '小批量', result: '待执行', dueDate: '2026-06-24' }
]

const defaultVariantTests: ProductTestItem[] = [
  { name: '孔位匹配验证', method: '新机型治具试装确认', owner: '工程 / 质量', frequency: '差异测试', result: '待执行', dueDate: '2026-06-20' },
  { name: '按键手感验证', method: '按键回弹和压力确认', owner: '质量', frequency: '差异测试', result: '待执行', dueDate: '2026-06-21' },
  { name: '颜色外观验证', method: '色板比对与外观确认', owner: '工程', frequency: '样品确认', result: '待执行', dueDate: '2026-06-22' }
]

const moldActionOptions: Array<{ label: string; value: MoldAction }> = [
  { label: '改模', value: 'modify' },
  { label: '新开模', value: 'new' },
  { label: '无需模具变更', value: 'none' }
]

const processTemplates: ProcessTemplateOption[] = []

const form = reactive<ProductFormPayload>({
  parentProductId: null,
  productCode: '',
  productName: '',
  productSpecificCode: null,
  phoneModelCode: null,
  colorCode: null,
  finishedProductCode: null,
  importShortCode: null,
  seriesName: '',
  productType: 'product_line',
  ownerUserName: '',
  versionNo: 'A',
  material: '',
  packageType: '',
  surfaceProcess: '',
  coreProcess: '',
  composition: '',
  customerName: '',
  currentStage: lineStageOptions[0],
  currentStepNo: 1,
  expectedReleaseDate: '',
  expectedArrivalAt: null,
  actualArrivalAt: null,
  networkType: null,
  holeType: null,
  mobileFunction: null,
  tipo: null,
  priority: null,
  manufacturingLocation: null,
  moldMarking: null,
  referenceUrl: null,
  requirementType: null,
  customerRequirement: null,
  model: '--',
  color: '--',
  estimatedCost: 0,
  estimatedCostCurrency: 'CNY',
  actualCost: 0,
  rdCost: 0,
  productCost: 0,
  totalCost: 0,
  moldAction: null,
  costBreakdown: [
    { category: '研发成本', amount: 0, ratio: 0, note: '模具、打样、测试等一次性投入' },
    { category: '成品成本', amount: 0, ratio: 0, note: 'BOM、工艺和包装汇总口径' },
    { category: '包装成本', amount: 0, ratio: 0, note: '彩盒、标签、说明书' },
    { category: '工艺损耗', amount: 0, ratio: 0, note: '加工损耗和过程检验成本' }
  ],
  testItems: structuredClone(defaultLineTests)
})

const processTemplateKey = ref('magnetic-case-standard')
const processNotes = ref('')
const differenceProcessNotes = ref('')

const parentProduct = computed(() => productOptions.value.find((item) => item.productId === form.parentProductId) || null)
const selectedTemplate = computed(() => processTemplates.find((item) => item.templateKey === processTemplateKey.value) || null)
const currentStageOptions = computed(() => (isProductLine.value ? lineStageOptions : variantStageOptions))

const formRules = {
  productCode: [rules.required('产品编码')],
  productName: [rules.required('产品名称')],
  seriesName: [rules.required('系列名称')],
  productType: [rules.required('产品类型', 'change')],
  ownerUserName: [rules.required('负责人', 'change')],
  versionNo: [rules.required('版本号'), rules.versionNo()],
  currentStage: [rules.required('当前阶段', 'change')],
  estimatedCost: [rules.required('预计成本', 'change')]
}

const totalCost = computed(() => form.costBreakdown.reduce((sum, item) => sum + Number(item.amount || 0), 0))

function syncStageStep() {
  const index = currentStageOptions.value.findIndex((item) => item === form.currentStage)
  form.currentStepNo = index >= 0 ? index + 1 : 1
}

function syncCostBreakdown() {
  const total = totalCost.value
  form.estimatedCost = Number(total.toFixed(2))
  form.totalCost = Number(total.toFixed(2))
  form.rdCost = Number((form.costBreakdown[0]?.amount || 0).toFixed(2))
  form.productCost = Number(
    ((form.costBreakdown[1]?.amount || 0) + (form.costBreakdown[2]?.amount || 0) + (form.costBreakdown[3]?.amount || 0)).toFixed(2)
  )
  form.actualCost = Number((form.rdCost + form.productCost).toFixed(2))

  const denominator = total || 1
  form.costBreakdown.forEach((item) => {
    item.ratio = Number((Number(item.amount || 0) / denominator).toFixed(4))
  })
}

function applyModeDefaults(force = false) {
  if (isProductLine.value) {
    form.parentProductId = null
    form.model = '--'
    form.color = '--'
    form.moldAction = null
    form.currentStage = lineStageOptions[0]
    processTemplateKey.value = 'magnetic-case-standard'
    if (force) {
      form.testItems = structuredClone(defaultLineTests)
      form.surfaceProcess = '按模板生成后补充表面工艺'
      form.coreProcess = '按标准模板生成完整工艺路线'
      form.costBreakdown = [
        { category: '研发成本', amount: 0, ratio: 0, note: '模具、打样、测试等一次性投入' },
        { category: '成品成本', amount: 0, ratio: 0, note: 'BOM、工艺和包装汇总口径' },
        { category: '包装成本', amount: 0, ratio: 0, note: '彩盒、标签、说明书' },
        { category: '工艺损耗', amount: 0, ratio: 0, note: '加工损耗和过程检验成本' }
      ]
      syncCostBreakdown()
    }
    syncStageStep()
    return
  }

  form.currentStage = variantStageOptions[0]
  form.model = form.model === '--' ? '' : form.model
  form.color = form.color === '--' ? '' : form.color
  form.moldAction = form.moldAction || 'modify'
  if (force) {
    form.testItems = structuredClone(defaultVariantTests)
    form.surfaceProcess = '继承父产品表面工艺，仅补充差异说明'
    form.coreProcess = '继承父产品工艺路线，仅记录差异工序'
    form.costBreakdown = [
      { category: '差异研发成本', amount: 0, ratio: 0, note: '改模、差异样、差异测试投入' },
      { category: '差异物料成本', amount: 0, ratio: 0, note: '新机型或新颜色带来的替代料成本' },
      { category: '差异包装成本', amount: 0, ratio: 0, note: '渠道包装和版本标签增量成本' },
      { category: '差异工艺损耗', amount: 0, ratio: 0, note: '新增工艺和差异检验损耗' }
    ]
    syncCostBreakdown()
  }
  syncStageStep()
}

watch(
  () => form.productType,
  (value, oldValue) => {
    if (value !== oldValue) applyModeDefaults(true)
  }
)

watch(
  () => form.currentStage,
  () => syncStageStep()
)

watch(
  () => form.parentProductId,
  () => {
    if (!isModelVariant.value || !parentProduct.value) return
    form.seriesName = parentProduct.value.seriesName
    form.material = form.material || parentProduct.value.material
    form.customerName = form.customerName || parentProduct.value.customerName
    differenceProcessNotes.value =
      differenceProcessNotes.value ||
      `继承 ${parentProduct.value.productName} 的基础工艺、BOM 和测试框架，只补充新机型/颜色的差异工序。`
  }
)

async function loadOptions() {
  try {
    productOptions.value = (await getProductPage({ productType: 'product_line', page: 1, size: 100 })).content
  } catch {
    productOptions.value = []
  }
}

async function loadDetail() {
  if (!isEdit.value) {
    applyModeDefaults(true)
    return
  }

  loading.value = true
  try {
    const detail = await getProductDetail(productId.value)
    detailStatus.value = detail.basicInfo.status
    form.productCode = detail.basicInfo.productCode
    form.productName = detail.basicInfo.productName
    form.productSpecificCode = detail.basicInfo.productSpecificCode
    form.phoneModelCode = detail.basicInfo.phoneModelCode
    form.colorCode = detail.basicInfo.colorCode
    form.finishedProductCode = detail.basicInfo.finishedProductCode
    form.importShortCode = detail.basicInfo.importShortCode
    form.seriesName = detail.basicInfo.seriesName
    form.productType = detail.basicInfo.productFlowMode === 'new_model_variant' ? 'model_variant' : 'product_line'
    form.ownerUserName = detail.basicInfo.ownerUserName
    form.versionNo = detail.basicInfo.versionNo
    form.material = detail.basicInfo.material
    form.packageType = detail.basicInfo.packageType
    form.surfaceProcess = detail.basicInfo.surfaceProcess
    form.coreProcess = detail.basicInfo.coreProcess
    form.composition = detail.basicInfo.composition
    form.customerName = detail.basicInfo.customerName
    form.currentStage = detail.basicInfo.currentStage
    form.currentStepNo = detail.basicInfo.currentStepNo || 1
    form.expectedReleaseDate = detail.basicInfo.expectedReleaseDate || ''
    form.expectedArrivalAt = detail.basicInfo.expectedArrivalAt || null
    form.actualArrivalAt = detail.basicInfo.actualArrivalAt || null
    form.networkType = detail.basicInfo.networkType || null
    form.holeType = detail.basicInfo.holeType || null
    form.mobileFunction = detail.basicInfo.mobileFunction || null
    form.tipo = detail.basicInfo.tipo || null
    form.priority = detail.basicInfo.priority || null
    form.manufacturingLocation = detail.basicInfo.manufacturingLocation || null
    form.moldMarking = detail.basicInfo.moldMarking || null
    form.referenceUrl = detail.basicInfo.referenceUrl || null
    form.requirementType = detail.basicInfo.requirementType || null
    form.customerRequirement = detail.basicInfo.customerRequirement || null
    form.model = detail.basicInfo.model
    form.color = detail.basicInfo.color
    form.estimatedCost = detail.basicInfo.estimatedCost
    form.estimatedCostCurrency = detail.basicInfo.estimatedCostCurrency
    form.actualCost = detail.basicInfo.actualCost || 0
    form.rdCost = detail.basicInfo.rdCost || 0
    form.productCost = detail.basicInfo.productCost || 0
    form.totalCost = detail.basicInfo.totalCost || 0
    form.moldAction = detail.basicInfo.moldAction || null
    form.costBreakdown = structuredClone(detail.costBreakdown)
    form.testItems = structuredClone(detail.testItems)
    form.parentProductId = productOptions.value.find((item) => item.productName === detail.basicInfo.parentProductName)?.productId || null

    if (form.productType === 'product_line') {
      processNotes.value = detail.basicInfo.coreProcess
    } else {
      differenceProcessNotes.value = detail.basicInfo.inheritedSummary || detail.basicInfo.coreProcess
    }

    syncStageStep()
    syncCostBreakdown()
  } catch (error) {
    ElMessage.info(error instanceof Error ? error.message : '产品详情接口未接入')
    router.replace('/products')
  } finally {
    loading.value = false
  }
}

function addTestItem() {
  form.testItems.push({
    name: '',
    method: '',
    owner: isModelVariant.value ? '工程 / 质量' : '质量',
    frequency: isModelVariant.value ? '差异验证' : '发布前',
    result: '待执行',
    dueDate: ''
  })
}

function removeTestItem(index: number) {
  form.testItems.splice(index, 1)
}

async function handleSubmit() {
  syncStageStep()
  syncCostBreakdown()
  const valid = await formRef.value?.validate().catch(() => false)
  if (!valid) return

  if (isModelVariant.value && !form.parentProductId) {
    ElMessage.warning('新型号线必须先选择父产品线。')
    return
  }

  form.coreProcess = isProductLine.value
    ? `${selectedTemplate.value?.templateName || '标准工艺模板'}；${processNotes.value || '按模板生成完整工艺路线。'}`
    : `继承父产品基础工艺；${differenceProcessNotes.value || '只管理差异工序和差异测试。'}`

  submitting.value = true
  try {
    if (createdCollaborationProjectId.value) {
      const item = await getCollaborationItem(collaborationItemId.value)
      await linkCollaborationProjects(item.itemId, [createdCollaborationProjectId.value], true, undefined, true)
      router.replace('/collaboration-plans')
      return
    }
    if (isEdit.value) {
      if (isReleasedBasicInfoEdit.value) {
        await updateProductBasicInfo(productId.value, structuredClone(form))
        ElMessage.success('项目基础信息已更新')
      } else {
        await updateProduct(productId.value, structuredClone(form))
        ElMessage.success('产品已更新')
      }
      router.push(toArchivedProductRoute(productId.value))
      return
    }

    const created = await createProduct(structuredClone(form))
    if (collaborationItemId.value) {
      createdCollaborationProjectId.value = created.productId
      try {
        const item = await getCollaborationItem(collaborationItemId.value)
        await linkCollaborationProjects(item.itemId, [created.productId], true, undefined, true)
        ElMessage.success('项目已按原有校验创建，并关联协作档案')
        router.replace('/collaboration-plans')
      } catch {
        ElMessage.warning('项目已创建，关联尚未完成。再次提交只重试关联，不会重复创建项目。')
      }
      return
    }
    ElMessage.success('产品已创建')
    router.replace(toArchivedProductRoute(created.productId))
  } finally {
    submitting.value = false
  }
}

onMounted(async () => {
  await loadOptions()
  await loadDetail()
  if (!isEdit.value && collaborationItemId.value) {
    try {
      const item = await getCollaborationItem(collaborationItemId.value)
      form.productType = 'model_variant'
      await nextTick()
      form.parentProductId = item.productLineId
      form.productName = `${item.styleName} ${item.compatibleModels}`.slice(0, 255)
      form.model = item.compatibleModels
      form.phoneModelCode = item.phoneModelCode
      form.productCode = '保存后由系统生成'
      form.ownerUserName = useUserStore().profile?.userName || ''
      form.moldAction = 'new'
      form.referenceUrl = item.referenceUrl
    } catch { ElMessage.error('协作档案读取失败，请返回协作计划核对') }
  }
})
</script>

<template>
  <PageContainer
    :title="isEdit ? '编辑产品' : '新建产品'"
    :description="isReleasedBasicInfoEdit ? '已发布 / 已归档项目仅开放基础信息维护，版本成果物请走变更流程。' : '把新产品线和新型号线分开建档，并把工艺配置改成模板继承与差异配置的业务入口。'"
  >
    <section class="page-panel" v-loading="loading">
      <el-form ref="formRef" :model="form" :rules="formRules" label-width="120px">
        <section class="mode-panel">
          <div class="toolbar-row">
            <div>
              <h3 class="section-title">流程模式</h3>
              <p class="page-panel-desc">
                {{ isProductLine ? '新产品线走完整研发流程。' : '新型号线继承父产品资产，只管理差异工序和差异测试。' }}
              </p>
            </div>
            <el-tag effect="light">{{ isProductLine ? '新产品线' : '新型号线' }}</el-tag>
          </div>

          <el-form-item label="产品类型" prop="productType">
            <el-segmented
              v-model="form.productType"
              :disabled="isReleasedBasicInfoEdit"
              :options="[
                { label: '新产品线', value: 'product_line' },
                { label: '新型号线', value: 'model_variant' }
              ]"
            />
          </el-form-item>

          <div class="mode-grid">
            <div class="guide-card">
              <strong>新产品线录入重点</strong>
              <ul>
                <li>立项说明、目标机型、预期工艺和成本边界</li>
                <li>完整 22 步开发流程与关键门禁</li>
                <li>工艺模板、完整测试套件和生产资料准备</li>
              </ul>
            </div>
            <div class="guide-card">
              <strong>新型号线录入重点</strong>
              <ul>
                <li>父产品继承边界、机型与颜色差异</li>
                <li>改模 / 新开模 / 无需模具变更三分支</li>
                <li>差异工艺、差异 BOM、差异测试与版本冻结</li>
              </ul>
            </div>
          </div>

          <el-form-item v-if="isModelVariant" label="父产品线" required>
            <el-select
              v-model="form.parentProductId"
              filterable
              placeholder="先选择父产品线"
              popper-class="product-line-select-popper"
              style="width: 100%"
            >
              <el-option
                v-for="item in productOptions"
                :key="item.productId"
                :label="`${item.productName} / ${item.productCode}`"
                :value="item.productId"
              >
                <div class="product-line-option" :title="`${item.productName} / ${item.productCode}`">
                  <span class="product-line-option__name">{{ item.productName }}</span>
                  <span class="product-line-option__code">{{ item.productCode }}</span>
                </div>
              </el-option>
            </el-select>
          </el-form-item>

          <el-form-item v-if="isModelVariant" label="模具策略">
            <el-radio-group v-model="form.moldAction">
              <el-radio-button v-for="item in moldActionOptions" :key="item.value" :label="item.value">
                {{ item.label }}
              </el-radio-button>
            </el-radio-group>
          </el-form-item>

          <div v-if="isModelVariant && parentProduct" class="inherit-card">
            <strong>继承基线</strong>
            <p class="page-panel-desc">
              父产品：{{ parentProduct.productName }} / {{ parentProduct.productCode }}。默认沿用父产品的基础工艺、BOM 结构、测试框架与文件模板，仅记录差异部分。
            </p>
          </div>
        </section>

        <div class="detail-grid">
          <div>
            <el-form-item label="产品编码" prop="productCode">
              <el-input v-model="form.productCode" :disabled="isEdit" placeholder="例如 PRD-SC30-0001" />
            </el-form-item>
            <el-form-item label="产品名称" prop="productName">
              <el-input v-model="form.productName" />
            </el-form-item>
            <el-form-item label="系列名称" prop="seriesName">
              <el-input v-model="form.seriesName" :disabled="isModelVariant && !!parentProduct" />
            </el-form-item>
            <el-form-item label="负责人" prop="ownerUserName">
              <el-input v-model="form.ownerUserName" placeholder="填写项目负责人" />
            </el-form-item>
            <el-form-item label="版本号" prop="versionNo">
              <el-input v-model="form.versionNo" :disabled="isReleasedBasicInfoEdit" />
            </el-form-item>
            <el-form-item label="客户来源">
              <el-input v-model="form.customerName" />
            </el-form-item>
          </div>

          <div>
            <el-form-item label="当前阶段" prop="currentStage">
              <el-select v-model="form.currentStage" :disabled="isReleasedBasicInfoEdit" style="width: 100%">
                <el-option v-for="item in currentStageOptions" :key="item" :label="item" :value="item" />
              </el-select>
            </el-form-item>
            <el-form-item label="当前步序">
              <el-input :model-value="String(form.currentStepNo || 1)" disabled />
            </el-form-item>
            <el-form-item :label="isModelVariant ? '适配机型' : '目标机型'">
              <el-input v-model="form.model" :disabled="!isModelVariant" placeholder="例如 iPhone18" />
            </el-form-item>
            <el-form-item :label="isModelVariant ? '适配颜色' : '主颜色'">
              <el-input v-model="form.color" :disabled="!isModelVariant" placeholder="例如 黑色" />
            </el-form-item>
            <el-form-item label="材料">
              <el-input v-model="form.material" />
            </el-form-item>
            <el-form-item label="包装方式">
              <el-input v-model="form.packageType" />
            </el-form-item>
            <el-form-item label="预计发布时间">
              <el-date-picker v-model="form.expectedReleaseDate" type="date" value-format="YYYY-MM-DD" style="width: 100%" />
            </el-form-item>
            <el-form-item label="预计到达时间">
              <el-date-picker v-model="form.expectedArrivalAt" type="datetime" value-format="YYYY-MM-DDTHH:mm:ss" style="width: 100%" />
            </el-form-item>
            <el-form-item label="实际到达时间">
              <el-date-picker v-model="form.actualArrivalAt" type="datetime" value-format="YYYY-MM-DDTHH:mm:ss" style="width: 100%" />
            </el-form-item>
          </div>
        </div>

        <section v-if="isModelVariant" class="form-block">
          <div class="toolbar-row">
            <div>
              <h3 class="section-title">新型号需求信息</h3>
            </div>
          </div>
          <div class="detail-grid">
            <div>
              <el-form-item label="4G/5G">
                <el-input v-model="form.networkType" />
              </el-form-item>
              <el-form-item label="大孔或精孔">
                <el-input v-model="form.holeType" />
              </el-form-item>
              <el-form-item label="Tipo 类型">
                <el-input v-model="form.tipo" />
              </el-form-item>
              <el-form-item label="紧急度">
                <el-input v-model="form.priority" />
              </el-form-item>
              <el-form-item label="制造地">
                <el-input v-model="form.manufacturingLocation" />
              </el-form-item>
            </div>
            <div>
              <el-form-item label="模具印字">
                <el-input v-model="form.moldMarking" />
              </el-form-item>
              <el-form-item label="订单类型">
                <el-select v-model="form.requirementType" clearable style="width: 100%">
                  <el-option label="客户订单" value="customer_requirement" />
                  <el-option label="市场需求" value="market_requirement" />
                </el-select>
              </el-form-item>
              <el-form-item label="钉钉链接">
                <el-input v-model="form.referenceUrl" />
              </el-form-item>
              <el-form-item label="手机功能">
                <el-input v-model="form.mobileFunction" type="textarea" :rows="3" />
              </el-form-item>
              <el-form-item label="客户要求">
                <el-input v-model="form.customerRequirement" type="textarea" :rows="3" />
              </el-form-item>
            </div>
          </div>
        </section>

        <section class="form-block">
          <div class="toolbar-row">
            <div>
              <h3 class="section-title">工艺配置</h3>
              <p class="page-panel-desc">
                {{ isProductLine ? '新产品线先选标准模板，再补充工艺说明。' : '新型号线显示父工艺继承摘要，并只录入差异工艺说明。' }}
              </p>
            </div>
            <el-button type="primary" plain @click="router.push('/processes')">查看工艺路线中心</el-button>
          </div>

          <div v-if="isProductLine" class="page-stack">
            <el-form-item label="工艺模板">
              <el-select v-model="processTemplateKey" style="width: 100%">
                <el-option
                  v-for="item in processTemplates"
                  :key="item.templateKey"
                  :label="`${item.templateName} / ${item.category}`"
                  :value="item.templateKey"
                />
              </el-select>
            </el-form-item>

            <div class="template-card" v-if="selectedTemplate">
              <div class="toolbar-row">
                <strong>{{ selectedTemplate.templateName }}</strong>
                <el-tag effect="light">{{ selectedTemplate.operationCount }} 道工序</el-tag>
              </div>
              <p class="page-panel-desc">{{ selectedTemplate.summary }}</p>
              <div class="tag-wrap">
                <el-tag v-for="step in selectedTemplate.highlightedSteps" :key="step" effect="light">{{ step }}</el-tag>
              </div>
            </div>

            <el-form-item label="工艺补充说明">
              <el-input v-model="processNotes" type="textarea" :rows="4" placeholder="补充模板之外的工艺约束、风险点和关键参数说明" />
            </el-form-item>
          </div>

          <div v-else class="page-stack">
            <div class="template-card">
              <div class="toolbar-row">
                <strong>{{ parentProduct ? `${parentProduct.productName} 工艺基线` : '待选择父产品线' }}</strong>
                <el-tag effect="light">{{ form.moldAction === 'modify' ? '改模分支' : form.moldAction === 'new' ? '新开模分支' : '无需模具变更' }}</el-tag>
              </div>
              <p class="page-panel-desc">
                {{ parentProduct ? '默认继承父产品标准工艺、SOP/SIP 和测试框架，只在当前子版本补录差异工序。' : '先选择父产品线后，再录入差异工艺说明。' }}
              </p>
            </div>

            <el-form-item label="差异工艺说明">
              <el-input
                v-model="differenceProcessNotes"
                type="textarea"
                :rows="5"
                placeholder="例如：iPhone18 孔位调整、黑色色母差异、改模判断、只需执行的差异测试等"
              />
            </el-form-item>
          </div>

          <div class="detail-grid">
            <div>
              <el-form-item label="表面工艺">
                <el-input v-model="form.surfaceProcess" />
              </el-form-item>
              <el-form-item label="核心工艺摘要">
                <el-input v-model="form.coreProcess" type="textarea" :rows="4" />
              </el-form-item>
            </div>
            <div>
              <el-form-item label="组成说明">
                <el-input v-model="form.composition" type="textarea" :rows="6" />
              </el-form-item>
            </div>
          </div>
        </section>

        <section class="form-block">
          <div class="toolbar-row">
            <div>
              <h3 class="section-title">成本结构</h3>
              <p class="page-panel-desc">
                {{ isModelVariant ? '新型号线只强调差异成本和增量投入。' : '新产品线记录完整研发成本和成品成本基线。' }}
              </p>
            </div>
            <el-tag effect="light">{{ form.estimatedCostCurrency }}</el-tag>
          </div>

          <div class="cost-grid">
            <div v-for="item in form.costBreakdown" :key="item.category" class="cost-card">
              <strong>{{ item.category }}</strong>
              <el-input-number
                v-model="item.amount"
                :min="0"
                :precision="2"
                :step="0.5"
                style="width: 100%"
                @change="syncCostBreakdown"
              />
              <el-input v-model="item.note" placeholder="补充说明" />
              <div class="subtle-text">占比 {{ Math.round(item.ratio * 100) }}%</div>
            </div>
          </div>

          <div class="cost-summary-grid">
            <div class="summary-pill">
              <span class="subtle-text">预计成本</span>
              <strong>{{ totalCost.toFixed(2) }} {{ form.estimatedCostCurrency }}</strong>
            </div>
            <div class="summary-pill">
              <span class="subtle-text">研发成本</span>
              <strong>{{ form.rdCost?.toFixed(2) || '0.00' }} {{ form.estimatedCostCurrency }}</strong>
            </div>
            <div class="summary-pill">
              <span class="subtle-text">成品成本</span>
              <strong>{{ form.productCost?.toFixed(2) || '0.00' }} {{ form.estimatedCostCurrency }}</strong>
            </div>
          </div>
        </section>

        <section class="form-block">
          <div class="toolbar-row">
            <div>
              <h3 class="section-title">{{ isModelVariant ? '差异测试配置' : '完整测试配置' }}</h3>
              <p class="page-panel-desc">
                {{ isModelVariant ? '新型号线只保留变化部分的测试计划。' : '新产品线保留完整测试套件和量产前验证计划。' }}
              </p>
            </div>
            <el-button type="primary" plain @click="addTestItem">新增测试项</el-button>
          </div>

          <div class="page-stack">
            <div v-for="(item, index) in form.testItems" :key="`${item.name}-${index}`" class="test-card">
              <div class="test-card__grid">
                <el-input v-model="item.name" placeholder="测试项名称" />
                <el-input v-model="item.method" placeholder="测试方法" />
                <el-input v-model="item.owner" placeholder="负责人" />
                <el-input v-model="item.frequency" placeholder="阶段" />
                <el-input v-model="item.result" placeholder="结果状态" />
                <el-date-picker v-model="item.dueDate" type="date" value-format="YYYY-MM-DD" placeholder="计划完成日" />
              </div>
              <div class="test-card__actions">
                <el-button text type="danger" @click="removeTestItem(index)">删除</el-button>
              </div>
            </div>
          </div>
        </section>

        <div class="toolbar-actions">
          <el-button @click="router.back()">取消</el-button>
          <el-button type="primary" :loading="submitting" @click="handleSubmit">保存</el-button>
        </div>
      </el-form>
    </section>
  </PageContainer>
</template>

<style scoped>
.mode-panel {
  margin-bottom: 24px;
}

.mode-grid,
.cost-grid,
.test-card__grid,
.cost-summary-grid {
  display: grid;
  gap: 16px;
}

.mode-grid {
  grid-template-columns: repeat(2, minmax(0, 1fr));
  margin-bottom: 16px;
}

.guide-card,
.inherit-card,
.template-card,
.cost-card,
.test-card {
  padding: 14px;
  border: 1px solid var(--plm-color-border-light);
  border-radius: var(--plm-radius-base);
  background: #fff;
}

.guide-card ul {
  margin: 10px 0 0;
  padding-left: 18px;
  color: var(--plm-color-text-secondary);
  line-height: 1.7;
}

.inherit-card {
  background: rgba(37, 99, 235, 0.04);
}

.form-block {
  margin-top: 24px;
  padding-top: 20px;
  border-top: 1px solid var(--plm-color-border-light);
}

.cost-grid {
  grid-template-columns: repeat(4, minmax(0, 1fr));
}

.cost-card {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.cost-summary-grid {
  grid-template-columns: repeat(3, minmax(0, 1fr));
  margin-top: 16px;
}

.summary-pill {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 12px;
  border: 1px solid var(--plm-color-border-light);
  border-radius: var(--plm-radius-base);
  background: rgba(248, 250, 252, 0.9);
}

.test-card__grid {
  grid-template-columns: repeat(3, minmax(0, 1fr));
}

.test-card__actions {
  display: flex;
  justify-content: flex-end;
  margin-top: 8px;
}

.tag-wrap {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 10px;
}

.product-line-option {
  display: grid;
  gap: 2px;
  padding: 3px 0;
  white-space: normal;
  line-height: 1.35;
}

.product-line-option__name {
  color: #0f172a;
  font-weight: 600;
  overflow-wrap: anywhere;
}

.product-line-option__code {
  color: #64748b;
  font-size: 12px;
}

:global(.product-line-select-popper .el-select-dropdown__item) {
  height: auto;
  min-height: 36px;
  padding-top: 5px;
  padding-bottom: 5px;
}

@media (max-width: 1200px) {
  .mode-grid,
  .cost-grid,
  .test-card__grid,
  .cost-summary-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 768px) {
  .mode-grid,
  .cost-grid,
  .test-card__grid,
  .cost-summary-grid {
    grid-template-columns: 1fr;
  }
}
</style>
