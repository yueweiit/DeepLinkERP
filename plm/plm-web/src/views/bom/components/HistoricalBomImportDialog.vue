<script setup lang="ts">
import { Download, Upload } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { ref } from 'vue'

import { commitHistoricalBomImport, downloadBomImportErrors, downloadHistoricalBomTemplate, previewHistoricalBomImport } from '@/api/modules/bom'
import type { BomImportPreview } from '@/types/bom'

defineProps<{ modelValue: boolean }>()
const emit = defineEmits<{ (event: 'update:modelValue', value: boolean): void; (event: 'committed'): void }>()
const loading = ref(false)
const preview = ref<BomImportPreview | null>(null)

function saveBlob(blob: Blob, fileName: string) {
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = fileName
  link.click()
  URL.revokeObjectURL(url)
}

async function selectFile(file: { raw?: File }) {
  if (!file.raw) return false
  loading.value = true
  try { preview.value = await previewHistoricalBomImport(file.raw) }
  catch (error) { ElMessage.error(error instanceof Error ? error.message : '历史 BOM 预校验失败') }
  finally { loading.value = false }
  return false
}

async function commit() {
  if (preview.value?.status !== 'ready') return
  loading.value = true
  try {
    await commitHistoricalBomImport(preview.value.importToken)
    ElMessage.success('历史 BOM 已导入正式台账')
    emit('committed')
    emit('update:modelValue', false)
  } catch (error) { ElMessage.error(error instanceof Error ? error.message : '历史 BOM 导入失败') }
  finally { loading.value = false }
}
</script>

<template>
  <el-dialog :model-value="modelValue" title="批量导入历史 BOM" width="720px" destroy-on-close @close="emit('update:modelValue', false)">
    <el-alert title="仅用于以前已有产品。校验并确认后直接进入正式 BOM 台账，不创建项目。" type="info" show-icon :closable="false" />
    <div class="history-import__actions">
      <el-button :icon="Download" @click="downloadHistoricalBomTemplate().then(blob => saveBlob(blob, 'historical-BOM-template.xlsx'))">下载模板</el-button>
      <el-upload :auto-upload="false" :show-file-list="false" accept=".xlsx" :on-change="selectFile">
        <el-button type="primary" :icon="Upload" :loading="loading">选择 XLSX</el-button>
      </el-upload>
    </div>
    <el-result v-if="preview" :icon="preview.status === 'ready' ? 'success' : 'error'" :title="preview.status === 'ready' ? '预校验通过' : '预校验未通过'" :sub-title="`有效 ${preview.validRows} 行，错误 ${preview.errorRows} 行`">
      <template #extra><el-button v-if="preview.errors.length" @click="downloadBomImportErrors(preview.importToken).then(blob => saveBlob(blob, 'historical-BOM-errors.xlsx'))">下载错误报告</el-button></template>
    </el-result>
    <template #footer>
      <el-button @click="emit('update:modelValue', false)">取消</el-button>
      <el-button type="primary" :loading="loading" :disabled="preview?.status !== 'ready'" @click="commit">确认导入正式台账</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.history-import__actions { display: flex; gap: 8px; margin-top: 16px; }
</style>
