<script setup lang="ts">
import { Upload } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { ref } from 'vue'
import { commitCodeImport, previewCodeImport, type CodeImportPreview } from '@/api/modules/code'

defineProps<{ modelValue: boolean }>()
const emit = defineEmits<{ (event: 'update:modelValue', value: boolean): void; (event: 'committed'): void }>()
const loading = ref(false)
const preview = ref<CodeImportPreview | null>(null)

async function selectFile(file: { raw?: File }) {
  if (!file.raw) return false
  loading.value = true
  try { preview.value = await previewCodeImport(file.raw) }
  catch (error) { ElMessage.error(error instanceof Error ? error.message : '颜色编码预校验失败') }
  finally { loading.value = false }
  return false
}

async function commit() {
  if (!preview.value || preview.value.errorCount) return
  loading.value = true
  try {
    const result = await commitCodeImport(preview.value.importToken)
    ElMessage.success(`已导入 ${result.committedCount} 条颜色编码`)
    emit('committed'); emit('update:modelValue', false)
  } finally { loading.value = false }
}
</script>

<template>
  <el-dialog :model-value="modelValue" title="批量导入颜色编码" width="760px" destroy-on-close @close="emit('update:modelValue', false)">
    <el-alert title="支持 Códigos de color 或 颜色编码工作表，第 6 行表头、第 7 行起为颜色数据。西语模板更新原名称，中文模板更新中文名称。" type="info" show-icon :closable="false" />
    <el-upload class="import-drop" drag :auto-upload="false" :show-file-list="false" accept=".xlsx" :on-change="selectFile">
      <el-icon class="import-drop__icon"><Upload /></el-icon><div>拖入 XLSX，或点击选择文件</div>
    </el-upload>
    <div v-if="preview" class="preview-stats">
      <span class="is-create">新增 {{ preview.createCount }}</span><span>更新 {{ preview.updateCount }}</span><span>无变化 {{ preview.unchangedCount }}</span><span class="is-error">错误 {{ preview.errorCount }}</span>
    </div>
    <el-table v-if="preview?.rows.length" :data="preview.rows" max-height="300" border>
      <el-table-column prop="rowNo" label="行" width="64" /><el-table-column prop="codeValue" label="编码" width="100" />
      <el-table-column prop="codeName" label="原名称" /><el-table-column prop="codeNameZh" label="中文名称" /><el-table-column prop="status" label="状态" width="100" /><el-table-column prop="action" label="处理" width="100" />
    </el-table>
    <el-alert v-for="error in preview?.errors || []" :key="`${error.rowNo}-${error.field}`" type="error" :title="`第 ${error.rowNo} 行 ${error.field}：${error.reason}`" :closable="false" />
    <template #footer><el-button @click="emit('update:modelValue', false)">取消</el-button><el-button type="primary" :loading="loading" :disabled="!preview || preview.errorCount > 0 || preview.createCount + preview.updateCount === 0" @click="commit">确认导入</el-button></template>
  </el-dialog>
</template>

<style scoped>.import-drop { display: block; margin: 16px 0; }.import-drop__icon { margin-bottom: 8px; font-size: 30px; color: var(--el-color-primary); }.preview-stats { display: flex; gap: 18px; margin-bottom: 12px; font-weight: 600; }.is-create { color: var(--el-color-success); }.is-error { color: var(--el-color-danger); }</style>
