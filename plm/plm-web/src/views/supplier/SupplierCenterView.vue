<script setup lang="ts">
import { ElMessage, type FormInstance, type FormRules } from 'element-plus'
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import {
  createInventorySupplier,
  getSupplierCenterSnapshot,
  updateInventorySupplier,
  type SupplierSupplySidePayload
} from '@/api/modules/supplier'
import FixedTableViewport from '@/components/FixedTableViewport/index.vue'
import PageContainer from '@/components/PageContainer/index.vue'
import StatusTag from '@/components/StatusTag/index.vue'
import type { SupplierCenterSnapshot, SupplierDetail, SupplierSupplyRecord } from '@/types/supplier'
import { formatAmount, formatDate } from '@/utils/format'
import { normalizeLegacyProductTarget, toArchivedProductRoute } from '@/utils/projectRoute'

interface SupplierCreateForm {
  supplierName: string
  shortName: string
  contactPerson: string
  contactPhone: string
  contactEmail: string
  region: string
  supplyCategories: string[]
  paymentTerm: string
  cooperationLevel: string
  deliveryRisk: string
  status: 'draft' | 'active' | 'inactive'
}

const router = useRouter()
const loading = ref(false)
const snapshot = ref<SupplierCenterSnapshot | null>(null)
const rows = computed(() => snapshot.value?.suppliers || [])

const searchModel = ref({
  keyword: '',
  category: '',
  status: ''
})

const filteredRows = computed(() => {
  const keyword = searchModel.value.keyword.trim().toLowerCase()
  return rows.value.filter((row) => {
    const keywordMatched =
      !keyword ||
      row.supplierCode.toLowerCase().includes(keyword) ||
      row.supplierName.toLowerCase().includes(keyword) ||
      row.contactPerson.toLowerCase().includes(keyword) ||
      row.region.toLowerCase().includes(keyword)

    const categoryMatched = !searchModel.value.category || row.supplyCategories.includes(searchModel.value.category)
    const statusMatched = !searchModel.value.status || row.status === searchModel.value.status

    return keywordMatched && categoryMatched && statusMatched
  })
})

function handleSupplierSearch() {
  // 搜索条件通过 v-model 实时生效，这里保留显式按钮以对齐 BOM 管理页交互。
}

function handleSupplierReset() {
  searchModel.value = { keyword: '', category: '', status: '' }
}

const createDialogVisible = ref(false)
const createFormRef = ref<FormInstance>()
const createSubmitting = ref(false)
const editDialogVisible = ref(false)
const editFormRef = ref<FormInstance>()
const editSubmitting = ref(false)
const editingSupplierCode = ref('')
const supplierDetailVisible = ref(false)
const detailSupplier = ref<SupplierDetail | null>(null)

function createEmptySupplierForm(): SupplierCreateForm {
  return {
    supplierName: '',
    shortName: '',
    contactPerson: '',
    contactPhone: '',
    contactEmail: '',
    region: '',
    supplyCategories: [],
    paymentTerm: '月结 30 天',
    cooperationLevel: '待评估',
    deliveryRisk: '中',
    status: 'draft'
  }
}

const createForm = ref<SupplierCreateForm>(createEmptySupplierForm())
const editForm = ref<SupplierCreateForm>(createEmptySupplierForm())

const createRules: FormRules<SupplierCreateForm> = {
  supplierName: [{ required: true, message: '请输入供应商名称', trigger: 'blur' }],
  contactPerson: [{ required: true, message: '请输入联系人', trigger: 'blur' }],
  contactPhone: [{ required: true, message: '请输入联系电话', trigger: 'blur' }],
  region: [{ required: true, message: '请输入所在区域', trigger: 'blur' }],
  supplyCategories: [{ required: true, message: '请选择供应品类', trigger: 'change' }]
}

function normalizeSupplierStatus(status: SupplierDetail['status']): SupplierCreateForm['status'] {
  if (status === 'active' || status === 'inactive' || status === 'draft') return status
  return 'draft'
}

function openCreateDialog() {
  resetCreateForm()
  createDialogVisible.value = true
}

function resetCreateForm() {
  createForm.value = createEmptySupplierForm()
}

function toSupplierPayload(form: SupplierCreateForm, supplierCode?: string): SupplierSupplySidePayload {
  return {
    supplierCode,
    supplierName: form.supplierName,
    shortName: form.shortName,
    contactPerson: form.contactPerson,
    contactPhone: form.contactPhone,
    contactEmail: form.contactEmail,
    region: form.region,
    supplyCategories: form.supplyCategories,
    paymentTerm: form.paymentTerm,
    cooperationLevel: form.cooperationLevel,
    deliveryRisk: form.deliveryRisk,
    status: form.status
  }
}

async function submitCreateForm() {
  const form = createFormRef.value
  if (!form) return

  await form.validate()
  createSubmitting.value = true
  try {
    await createInventorySupplier(toSupplierPayload(createForm.value))
    await loadSnapshot()
    createDialogVisible.value = false
    resetCreateForm()
    ElMessage.success('新增供应商成功')
  } finally {
    createSubmitting.value = false
  }
}

function openSupplierDetail(row: SupplierDetail) {
  detailSupplier.value = row
  supplierDetailVisible.value = true
}

function openEditSupplier(row: SupplierDetail) {
  editingSupplierCode.value = row.supplierCode
  editForm.value = {
    supplierName: row.supplierName,
    shortName: row.shortName,
    contactPerson: row.contactPerson,
    contactPhone: row.contactPhone,
    contactEmail: row.contactEmail,
    region: row.region,
    supplyCategories: [...row.supplyCategories],
    paymentTerm: row.paymentTerm,
    cooperationLevel: row.cooperationLevel,
    deliveryRisk: row.deliveryRisk,
    status: normalizeSupplierStatus(row.status)
  }
  editDialogVisible.value = true
}

async function submitEditSupplier() {
  const form = editFormRef.value
  const supplierCode = editingSupplierCode.value
  if (!form || !supplierCode) return

  await form.validate()
  editSubmitting.value = true
  try {
    const supplier = await updateInventorySupplier(supplierCode, toSupplierPayload(editForm.value, supplierCode))
    await loadSnapshot()
    detailSupplier.value = supplier
    editDialogVisible.value = false
    editingSupplierCode.value = ''
    ElMessage.success('供应商信息已更新')
  } finally {
    editSubmitting.value = false
  }
}

function openTarget(path: string) {
  router.push(normalizeLegacyProductTarget(path))
}

function supplyTypeLabel(type: SupplierSupplyRecord['supplyType']) {
  if (type === 'material') return '物料'
  if (type === 'tooling') return '模具 / 治具'
  return '包材'
}

async function loadSnapshot() {
  loading.value = true
  try {
    snapshot.value = await getSupplierCenterSnapshot()
  } catch {
    snapshot.value = null
  } finally {
    loading.value = false
  }
}

onMounted(loadSnapshot)
</script>

<template>
  <PageContainer
    title="供应商管理"
    description="以列表维护供应商基础资料，点击详情查看供应记录、参与项目与资质文件。"
  >
    <template #actions>
      <el-button type="primary" @click="openCreateDialog">新增供应商</el-button>
      <el-button @click="router.push('/inventories')">物料 / 模具</el-button>
      <el-button @click="router.push(toArchivedProductRoute())">关联归档产品</el-button>
    </template>

    <section class="page-panel supplier-toolbar">
      <el-form inline>
        <el-form-item label="供应商搜索">
          <el-input
            v-model="searchModel.keyword"
            placeholder="供应商编码 / 名称 / 联系人 / 区域"
            clearable
            style="width: 280px"
          />
        </el-form-item>
        <el-form-item label="供应品类">
          <el-select v-model="searchModel.category" clearable placeholder="请选择供应品类" style="width: 160px">
            <el-option label="全部" value="" />
            <el-option label="原材料" value="原材料" />
            <el-option label="功能件" value="功能件" />
            <el-option label="板材" value="板材" />
            <el-option label="包材" value="包材" />
            <el-option label="模具" value="模具" />
            <el-option label="治具" value="治具" />
          </el-select>
        </el-form-item>
        <el-form-item label="状态">
          <el-select v-model="searchModel.status" clearable placeholder="请选择状态" style="width: 140px">
            <el-option label="全部" value="" />
            <el-option label="启用" value="active" />
            <el-option label="草稿" value="draft" />
            <el-option label="停用" value="inactive" />
          </el-select>
        </el-form-item>
        <div class="supplier-toolbar__actions">
          <el-button type="primary" @click="handleSupplierSearch">搜索</el-button>
          <el-button @click="handleSupplierReset">重置</el-button>
        </div>
      </el-form>
    </section>

    <section class="page-panel" v-loading="loading">
      <div class="toolbar-row">
        <div>
          <h3 class="section-title">供应商列表</h3>
          <p class="page-panel-desc">按供应商查看基础资料、供应品类、联系人、状态和更新时间。</p>
        </div>
        <el-tag effect="light">{{ filteredRows.length }} 条</el-tag>
      </div>

      <div v-if="!filteredRows.length" class="empty-state">
        <strong>没有匹配的供应商记录</strong>
        <span class="subtle-text">调整搜索词、供应品类或状态后再试一次。</span>
      </div>

      <FixedTableViewport v-else v-slot="{ tableHeight }" :refresh-key="filteredRows">
      <el-table :data="filteredRows" :height="tableHeight" border stripe>
        <el-table-column prop="supplierCode" label="供应商编码" min-width="160" />
        <el-table-column prop="supplierName" label="供应商名称" min-width="180">
          <template #default="{ row }">
            <strong>{{ row.supplierName }}</strong>
          </template>
        </el-table-column>
        <el-table-column label="供应品类" min-width="190">
          <template #default="{ row }">
            <div class="tag-wrap">
              <el-tag v-for="item in row.supplyCategories" :key="item" effect="light" size="small">{{ item }}</el-tag>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="contactPerson" label="联系人" width="120" />
        <el-table-column prop="contactPhone" label="联系电话" min-width="140" />
        <el-table-column prop="region" label="区域" width="120" />
        <el-table-column label="状态" width="110">
          <template #default="{ row }">
            <StatusTag :status="row.status" object-type="customer" />
          </template>
        </el-table-column>
        <el-table-column label="更新时间" width="150">
          <template #default="{ row }">
            {{ formatDate(row.updatedAt, 'YYYY-MM-DD HH:mm') }}
          </template>
        </el-table-column>
        <el-table-column label="操作" width="100" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="openSupplierDetail(row)">详情</el-button>
          </template>
        </el-table-column>
      </el-table>
      </FixedTableViewport>
    </section>

    <el-dialog
      v-model="supplierDetailVisible"
      :title="detailSupplier?.supplierName || '供应商详情'"
      width="920px"
      destroy-on-close
    >
      <div v-if="detailSupplier" class="supplier-detail-dialog">
        <div class="supplier-detail-dialog__head">
          <p class="page-panel-desc">{{ detailSupplier.supplierCode }} / {{ detailSupplier.cooperationLevel }}</p>
          <div class="supplier-detail-dialog__actions"><StatusTag :status="detailSupplier.status" object-type="customer" /><el-button size="small" type="primary" plain @click="openEditSupplier(detailSupplier)">编辑</el-button></div>
        </div>

        <section class="supplier-detail-basic">
          <el-descriptions :column="3" border>
            <el-descriptions-item label="联系人">{{ detailSupplier.contactPerson }}</el-descriptions-item>
            <el-descriptions-item label="联系电话">{{ detailSupplier.contactPhone }}</el-descriptions-item>
            <el-descriptions-item label="区域">{{ detailSupplier.region }}</el-descriptions-item>
            <el-descriptions-item label="邮箱">{{ detailSupplier.contactEmail }}</el-descriptions-item>
            <el-descriptions-item label="付款条件">{{ detailSupplier.paymentTerm }}</el-descriptions-item>
            <el-descriptions-item label="更新时间">{{ formatDate(detailSupplier.updatedAt, 'YYYY-MM-DD HH:mm') }}</el-descriptions-item>
            <el-descriptions-item label="供应范围" :span="3">{{ detailSupplier.supplyCategories.join(' / ') }}</el-descriptions-item>
          </el-descriptions>
        </section>

        <el-tabs class="section-gap">
          <el-tab-pane label="供应记录">
            <el-table :data="detailSupplier.supplyRecords" border stripe>
              <el-table-column label="供应类型" width="110">
                <template #default="{ row }">{{ supplyTypeLabel(row.supplyType) }}</template>
              </el-table-column>
              <el-table-column prop="itemCode" label="编码" min-width="150" />
              <el-table-column prop="itemName" label="名称" min-width="180" />
              <el-table-column prop="relatedProduct" label="关联产品" min-width="180" />
              <el-table-column label="单价" width="120">
                <template #default="{ row }">{{ formatAmount(row.unitPrice, row.currency) }}</template>
              </el-table-column>
              <el-table-column prop="lastDeliveryDate" label="最近交付" width="120" />
              <el-table-column label="状态" width="110">
                <template #default="{ row }">
                  <StatusTag :status="row.status" object-type="inventory" />
                </template>
              </el-table-column>
            </el-table>
          </el-tab-pane>

          <el-tab-pane label="参与项目">
            <el-table :data="detailSupplier.relatedProjects" border stripe>
              <el-table-column prop="projectName" label="项目名称" min-width="200" />
              <el-table-column prop="projectCode" label="项目编码" min-width="170" />
              <el-table-column prop="stage" label="阶段" width="120" />
              <el-table-column prop="roleSummary" label="供应角色" min-width="200" />
              <el-table-column label="操作" width="90" fixed="right">
                <template #default="{ row }">
                  <el-button link type="primary" @click="openTarget(row.targetPath)">查看</el-button>
                </template>
              </el-table-column>
            </el-table>
          </el-tab-pane>

          <el-tab-pane label="资质文件">
            <el-table :data="detailSupplier.qualificationFiles" border stripe>
              <el-table-column prop="fileName" label="文件名" min-width="220" />
              <el-table-column prop="fileType" label="类型" width="130" />
              <el-table-column prop="validUntil" label="有效期" width="140" />
              <el-table-column prop="statusLabel" label="状态" width="120" />
            </el-table>
          </el-tab-pane>
        </el-tabs>
      </div>
    </el-dialog>

    <el-dialog v-model="createDialogVisible" title="新增供应商" width="720px">
      <el-form ref="createFormRef" :model="createForm" :rules="createRules" label-width="100px">
        <el-row :gutter="16">
          <el-col :span="12">
            <el-form-item label="供应商名称" prop="supplierName">
              <el-input v-model="createForm.supplierName" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="简称" prop="shortName">
              <el-input v-model="createForm.shortName" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="联系人" prop="contactPerson">
              <el-input v-model="createForm.contactPerson" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="联系电话" prop="contactPhone">
              <el-input v-model="createForm.contactPhone" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="联系邮箱" prop="contactEmail">
              <el-input v-model="createForm.contactEmail" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="区域" prop="region">
              <el-input v-model="createForm.region" />
            </el-form-item>
          </el-col>
          <el-col :span="24">
            <el-form-item label="供应品类" prop="supplyCategories">
              <el-select v-model="createForm.supplyCategories" multiple style="width: 100%">
                <el-option label="原材料" value="原材料" />
                <el-option label="功能件" value="功能件" />
                <el-option label="板材" value="板材" />
                <el-option label="包材" value="包材" />
                <el-option label="模具" value="模具" />
                <el-option label="治具" value="治具" />
              </el-select>
            </el-form-item>
          </el-col>
        </el-row>
      </el-form>

      <template #footer>
        <el-button @click="createDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="createSubmitting" @click="submitCreateForm">确认新增</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="editDialogVisible" title="编辑供应商" width="720px">
      <el-form ref="editFormRef" :model="editForm" :rules="createRules" label-width="100px">
        <el-row :gutter="16">
          <el-col :span="12">
            <el-form-item label="供应商名称" prop="supplierName">
              <el-input v-model="editForm.supplierName" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="简称" prop="shortName">
              <el-input v-model="editForm.shortName" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="联系人" prop="contactPerson">
              <el-input v-model="editForm.contactPerson" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="联系电话" prop="contactPhone">
              <el-input v-model="editForm.contactPhone" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="联系邮箱" prop="contactEmail">
              <el-input v-model="editForm.contactEmail" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="区域" prop="region">
              <el-input v-model="editForm.region" />
            </el-form-item>
          </el-col>
          <el-col :span="24">
            <el-form-item label="供应品类" prop="supplyCategories">
              <el-select v-model="editForm.supplyCategories" multiple style="width: 100%">
                <el-option label="原材料" value="原材料" />
                <el-option label="功能件" value="功能件" />
                <el-option label="板材" value="板材" />
                <el-option label="包材" value="包材" />
                <el-option label="模具" value="模具" />
                <el-option label="治具" value="治具" />
              </el-select>
            </el-form-item>
          </el-col>
        </el-row>
      </el-form>

      <template #footer>
        <el-button @click="editDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="editSubmitting" @click="submitEditSupplier">保存</el-button>
      </template>
    </el-dialog>
  </PageContainer>
</template>

<style scoped>
.supplier-toolbar {
  margin-bottom: 0;
}

.supplier-toolbar .el-form {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
}

.supplier-toolbar__actions {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-left: auto;
}

.cell-stack {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.tag-wrap {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.empty-state {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 32px 16px;
  border: 1px dashed var(--plm-color-border);
  border-radius: var(--plm-radius-base);
  background: #fafcff;
}

.supplier-detail-dialog {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.supplier-detail-dialog__head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}

.supplier-detail-dialog__head h3 {
  margin: 0;
}

.supplier-detail-dialog__actions {
  display: flex;
  align-items: center;
  gap: 10px;
}

.section-gap {
  margin-top: var(--plm-space-4);
}
.supplier-detail-basic { width: 100%; }
.supplier-detail-basic :deep(.el-descriptions__label) { width: 92px; color: #64748b; font-weight: 600; }
</style>
