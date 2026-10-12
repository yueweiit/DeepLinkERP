<script setup lang="ts">
import { Download, Upload } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { computed, ref, watch } from 'vue'

import { commitBomImport, downloadBomImportErrors, downloadBomImportTemplate, previewBomImport } from '@/api/modules/bom'
import type { BomImportPreview } from '@/types/bom'
import { useUserStore } from '@/stores/user'

const props = defineProps<{ modelValue: boolean; productId: number; bomId: number | null }>()
const emit = defineEmits<{ (event: 'update:modelValue', value: boolean): void; (event: 'committed'): void }>()
const loading = ref(false)
const user = useUserStore()
const canReadMoney = computed(() => user.hasPermission('finance:read'))
const canWriteMoney = computed(() => user.hasPermission('finance:write'))
const error = ref('')
const preview = ref<BomImportPreview | null>(null)
const previewStats = computed(() => {
  const rows = preview.value?.rows || []
  return {
    autoMatched: rows.filter(row => row.materialSource !== 'manual' && row.unmatchedFlag !== 1).length,
    manualRows: rows.filter(row => row.materialSource === 'manual' || row.unmatchedFlag === 1).length,
    supplierMissing: rows.filter(row => !row.supplierName).length,
    costMissing: rows.filter(row => row.unitCost == null || row.lineCost == null).length
  }
})

function saveBlob(blob: Blob, fileName: string) {
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = fileName
  link.click()
  URL.revokeObjectURL(url)
}

async function selectFile(file: { raw?: File }) {
  if (!props.bomId || !file.raw || !user.hasPermission('bom:write')) return false
  const token = user.token
  preview.value = null
  error.value = ''
  loading.value = true
  try { const result = await previewBomImport(props.productId, props.bomId, file.raw); if (token === user.token) preview.value = result }
  catch (e) { if (token === user.token) error.value = e instanceof Error ? e.message : '导入预览失败，请核对文件与填写权限' }
  finally { loading.value = false }
  return false
}

async function commit() {
  if (!preview.value || preview.value.status !== 'ready' || !user.hasPermission('bom:write') || loading.value) return
  loading.value = true
  error.value = ''
  try {
    await commitBomImport(preview.value.importToken)
    ElMessage.success('草稿明细已导入，尚未正式发布或推送 ERP')
    emit('committed')
    emit('update:modelValue', false)
  } catch (e) { error.value = e instanceof Error ? e.message : '导入未确认完成，请核对预览与权限' }
  finally { loading.value = false }
}
watch(() => user.token, () => { preview.value = null; error.value = '' })
</script>

<template>
  <el-dialog :model-value="modelValue" title="导入 XLSX" width="720px" @close="emit('update:modelValue', false)">
    <el-alert :title="canWriteMoney ? '导入只维护候选草稿，不自动正式发布；请核对单价、币种及变更范围。' : '可导入无价格的物料表；单价与单个成本须留空，已保存价格由服务端保留，未知价格不会记为零。'" type="info" :closable="false" />
    <el-alert v-if="error" :title="error" type="error" :closable="false" />
    <div class="import-actions">
      <el-button :icon="Download" @click="downloadBomImportTemplate().then(blob => saveBlob(blob, 'BOM-import-template.xlsx'))">下载模板</el-button>
      <el-upload :auto-upload="false" :show-file-list="false" accept=".xlsx" :on-change="selectFile">
        <el-button type="primary" :icon="Upload" :loading="loading">选择 XLSX</el-button>
      </el-upload>
    </div>
    <el-result v-if="preview" :icon="preview.status === 'ready' ? 'success' : 'error'" :title="preview.status === 'ready' ? '预校验通过' : '预校验未通过'" :sub-title="`有效 ${preview.validRows} 行，错误 ${preview.errorRows} 行`">
      <template #extra>
        <el-button v-if="preview.errors.length" @click="downloadBomImportErrors(preview.importToken).then(blob => saveBlob(blob, 'BOM-import-errors.xlsx'))">下载错误报告</el-button>
      </template>
    </el-result>
    <div v-if="preview" class="preview-quality">
      <el-tag type="success">自动匹配 {{ previewStats.autoMatched }}</el-tag>
      <el-tag type="warning">人工录入 {{ previewStats.manualRows }}</el-tag>
      <el-tag :type="previewStats.supplierMissing ? 'danger' : 'info'">供应商缺失 {{ previewStats.supplierMissing }}</el-tag>
      <el-tag v-if="canReadMoney" :type="previewStats.costMissing ? 'danger' : 'info'">成本缺失 {{ previewStats.costMissing }}</el-tag>
    </div>
    <el-table v-if="preview?.rows.length" :data="preview.rows" size="small" max-height="260" class="preview-table">
      <el-table-column prop="lineNo" label="NO" width="64" />
      <el-table-column prop="routeName" label="路线" min-width="120" />
      <el-table-column prop="itemCode" label="物料编码" min-width="120" />
      <el-table-column prop="itemName" label="物料名称" min-width="140" />
      <el-table-column prop="supplierName" label="供应商" min-width="130">
        <template #default="{ row }">{{ row.supplierName || '未选择' }}</template>
      </el-table-column>
      <el-table-column v-if="canReadMoney" prop="unitCost" label="单价" width="100" />
      <el-table-column v-if="canReadMoney" prop="lineCost" label="单个成本" width="110" />
      <el-table-column label="来源" width="90">
        <template #default="{ row }">
          <el-tag :type="row.materialSource === 'manual' || row.unmatchedFlag === 1 ? 'warning' : 'success'" size="small">
            {{ row.materialSource === 'manual' || row.unmatchedFlag === 1 ? '人工' : '库存' }}
          </el-tag>
        </template>
      </el-table-column>
    </el-table>
    <template #footer>
      <el-button @click="emit('update:modelValue', false)">取消</el-button>
      <el-button type="primary" :loading="loading" :disabled="preview?.status !== 'ready' || !user.hasPermission('bom:write')" @click="commit">确认导入草稿</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.import-actions, .preview-quality { display: flex; flex-wrap: wrap; gap: 8px; }
.preview-quality { margin: 10px 0; }
.preview-table { margin-top: 8px; }
</style>
