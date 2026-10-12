<script setup lang="ts">
import { ElMessage } from 'element-plus'
import { onMounted, reactive, ref, watch } from 'vue'
import { confirmRequirementForm, getRequirementForm, saveRequirementForm, type RequirementFormPayload, type RequirementFormVO } from '@/api/modules/order'

const props = defineProps<{ projectId: number }>()
const emit = defineEmits<{ confirmed: [value: RequirementFormVO] }>()
const loading = ref(false); const saving = ref(false); const form = reactive<Partial<RequirementFormVO>>({ colors: [] })
async function load(){
  loading.value=true
  try {
    Object.assign(form, {
      colors: [],
      model: '',
      networkType: undefined,
      holeType: undefined,
      mobileFunction: undefined,
      tipo: undefined,
      priority: undefined,
      manufacturingLocation: undefined,
      moldMarking: undefined,
      referenceUrl: undefined,
      remark: undefined,
      expectedDeliveryDate: undefined,
      requirementType: undefined,
      customerRequirement: undefined,
      status: 'draft'
    })
    Object.assign(form, await getRequirementForm(props.projectId))
  } finally {
    loading.value=false
  }
}
function payload(): RequirementFormPayload { return { model: form.model || '', networkType: form.networkType, holeType: form.holeType, mobileFunction: form.mobileFunction, tipo: form.tipo, priority: form.priority, manufacturingLocation: form.manufacturingLocation, moldMarking: form.moldMarking, referenceUrl: form.referenceUrl, remark: form.remark, expectedDeliveryDate: form.expectedDeliveryDate, requirementType: form.requirementType, customerRequirement: form.customerRequirement, selectedVariantColorIds: (form.colors || []).filter(item => item.selected).map(item => item.variantColorId) } }
async function save(confirm=false){
  saving.value=true
  try {
    const value = confirm ? await confirmRequirementForm(props.projectId, payload()) : await saveRequirementForm(props.projectId, payload())
    Object.assign(form, value)
    ElMessage.success(confirm ? '信息已确认并进入项目时间轴' : '草稿已保存')
    if(confirm) emit('confirmed', value)
  } finally {
    saving.value=false
  }
}
watch(() => props.projectId, () => { void load() })
onMounted(load)
</script>

<template>
  <section v-loading="loading" class="requirement-form page-panel">
    <div><h4>新型号项目信息完善表</h4><p class="page-panel-desc">核对钉钉信息，补充订单类型和客户要求，再确认进入下一步。</p></div>
    <el-form label-position="top">
      <div class="form-grid">
        <el-form-item label="钉钉审批单号"><el-input data-test="approval-no" :model-value="form.dingTalkApprovalNo" readonly /></el-form-item>
        <el-form-item label="手机型号"><el-input v-model="form.model" /></el-form-item>
        <el-form-item label="4G/5G"><el-input v-model="form.networkType" /></el-form-item>
        <el-form-item label="大孔或精孔"><el-input v-model="form.holeType" /></el-form-item>
        <el-form-item label="Tipo 类型"><el-input v-model="form.tipo" /></el-form-item>
        <el-form-item label="紧急度"><el-input v-model="form.priority" /></el-form-item>
        <el-form-item label="制造地"><el-input v-model="form.manufacturingLocation" /></el-form-item>
        <el-form-item label="模具印字"><el-input v-model="form.moldMarking" /></el-form-item>
        <el-form-item label="产品特定编码"><el-input :model-value="form.productSpecificCode || '--'" readonly /></el-form-item>
        <el-form-item label="手机型号编码"><el-input :model-value="form.phoneModelCode || '--'" readonly /></el-form-item>
        <el-form-item label="材质编码"><el-input :model-value="form.materialCodes || '--'" readonly /></el-form-item>
        <el-form-item label="模具编码"><el-input :model-value="form.moldCodes || '--'" readonly /></el-form-item>
        <el-form-item label="期望交付时间"><el-date-picker v-model="form.expectedDeliveryDate" value-format="YYYY-MM-DD" /></el-form-item>
        <el-form-item label="订单类型" required><el-select v-model="form.requirementType"><el-option label="客户订单" value="customer_requirement" /><el-option label="市场需求" value="market_requirement" /></el-select></el-form-item>
      </div>
      <el-form-item v-if="form.moldMatches?.length" label="模具编码匹配结果">
        <div class="mold-list">
          <div v-for="match in form.moldMatches" :key="match.moldCode" class="mold-item">
            <strong>{{ match.moldCode }}</strong>
            <el-tag size="small" :type="match.matchStatus === 'linked_existing' ? 'success' : 'warning'">{{ match.matchStatus === 'linked_existing' ? '已关联已有模具' : '已创建待开模' }}</el-tag>
            <span>{{ match.productSpecificCode }} / {{ match.materialCode }} / {{ match.phoneModelCode }}</span>
          </div>
        </div>
      </el-form-item>
      <el-form-item label="手机功能"><el-input v-model="form.mobileFunction" type="textarea" /></el-form-item>
      <el-form-item label="客户要求" :required="form.requirementType === 'customer_requirement'"><el-input v-model="form.customerRequirement" type="textarea" /></el-form-item>
      <el-form-item label="其他备注"><el-input v-model="form.remark" type="textarea" /></el-form-item>
      <el-form-item label="正式确认批量生产颜色（默认全选，可取消）">
        <div class="color-list"><label v-for="color in form.colors" :key="color.variantColorId" class="color-item"><input v-model="color.selected" type="checkbox" />{{ color.colorCode }} - {{ color.colorName }}</label></div>
      </el-form-item>
      <div class="actions" v-if="form.status !== 'confirmed'"><el-button :loading="saving" @click="save(false)">保存草稿</el-button><el-button type="primary" :loading="saving" @click="save(true)">确认并进入下一步</el-button></div>
      <el-alert v-else type="success" :closable="false" title="信息已确认，项目时间轴已启动。" />
    </el-form>
  </section>
</template>

<style scoped>.requirement-form{margin:16px 0}.form-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:0 16px}.color-list,.mold-list{display:flex;gap:12px;flex-wrap:wrap}.color-item,.mold-item{border:1px solid var(--el-border-color);padding:8px 12px;border-radius:6px}.mold-item{display:flex;align-items:center;gap:8px}.actions{display:flex;justify-content:flex-end;gap:8px}@media(max-width:800px){.form-grid{grid-template-columns:1fr}.mold-item{width:100%;align-items:flex-start;flex-direction:column}}</style>
