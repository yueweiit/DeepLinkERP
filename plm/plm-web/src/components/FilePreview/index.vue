<script setup lang="ts">
import { computed } from 'vue'
import type { ProductionDocumentPreviewFile } from '@/types/foundation'

const props = defineProps<{
  modelValue: boolean
  /** 兼容旧接口：简单文件名模式 */
  fileName?: string
  /** 新接口：完整文件对象 */
  file?: ProductionDocumentPreviewFile | null
}>()

const emit = defineEmits<{
  (event: 'update:modelValue', value: boolean): void
  (event: 'download', file: ProductionDocumentPreviewFile): void
}>()

const displayName = computed(() => {
  if (props.file?.fileName) return props.file.fileName
  return props.fileName || '未知文件'
})

const dialogTitle = computed(() => {
  return `生产资料预览 - ${displayName.value}`
})

const fileMeta = computed(() => {
  if (!props.file) return []
  return [
    { label: '资料类型', value: props.file.category },
    { label: '版本', value: props.file.versionNo },
    { label: '状态', value: props.file.status || '--' },
    { label: '负责人', value: props.file.owner || '--' },
    { label: '更新时间', value: props.file.updatedAt || '--' }
  ]
})

const isPdf = computed(() => {
  const name = displayName.value.toLowerCase()
  return name.endsWith('.pdf')
})

const isImage = computed(() => {
  const name = displayName.value.toLowerCase()
  return ['.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp', '.svg'].some((ext) => name.endsWith(ext))
})

const isOffice = computed(() => {
  const name = displayName.value.toLowerCase()
  return ['.xlsx', '.xls', '.docx', '.doc', '.pptx', '.ppt'].some((ext) => name.endsWith(ext))
})

function handleDownload() {
  if (props.file) {
    emit('download', props.file)
  }
}
</script>

<template>
  <el-dialog
    :model-value="modelValue"
    width="820px"
    :title="dialogTitle"
    destroy-on-close
    @update:model-value="emit('update:modelValue', $event)"
  >
    <div class="preview-container">
      <!-- 文件摘要区 -->
      <div v-if="file" class="preview-meta">
        <div v-for="item in fileMeta" :key="item.label" class="preview-meta__item">
          <span class="preview-meta__label">{{ item.label }}</span>
          <strong>{{ item.value }}</strong>
        </div>
      </div>

      <!-- 预览主体区 -->
      <div class="preview-body">
        <!-- PDF 预览 -->
        <div v-if="file?.previewUrl && isPdf" class="preview-iframe-wrap">
          <iframe :src="file.previewUrl" class="preview-iframe" frameborder="0" />
        </div>

        <!-- 图片预览 -->
        <div v-else-if="file?.previewUrl && isImage" class="preview-image-wrap">
          <el-image :src="file.previewUrl" fit="contain" class="preview-image" />
        </div>

        <!-- Office 文件提示 -->
        <div v-else-if="isOffice" class="preview-placeholder">
          <el-empty description="Office 文件暂不支持在线预览，请下载后查看。">
            <template v-if="file?.downloadUrl">
              <el-button type="primary" @click="handleDownload">下载查看</el-button>
            </template>
          </el-empty>
        </div>

        <!-- 无预览地址 -->
        <div v-else class="preview-placeholder">
          <el-empty :description="file ? '当前演示环境仅保留预览入口，后续可对接 MinIO / S3 真实文件流。' : '请选择文件进行预览。'">
            <template v-if="file?.downloadUrl">
              <el-button type="primary" @click="handleDownload">下载资料</el-button>
            </template>
          </el-empty>
        </div>
      </div>
    </div>

    <template #footer>
      <div class="preview-footer">
        <el-button @click="emit('update:modelValue', false)">关闭</el-button>
        <el-button v-if="file?.downloadUrl" type="primary" @click="handleDownload">下载资料</el-button>
      </div>
    </template>
  </el-dialog>
</template>

<style scoped>
.preview-container {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.preview-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  padding: 12px 14px;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  background: #f8fafc;
}

.preview-meta__item {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 100px;
}

.preview-meta__label {
  color: #64748b;
  font-size: 12px;
}

.preview-body {
  min-height: 280px;
  display: flex;
  align-items: center;
  justify-content: center;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  background: #fff;
  overflow: hidden;
}

.preview-iframe-wrap {
  width: 100%;
  height: 520px;
}

.preview-iframe {
  width: 100%;
  height: 100%;
}

.preview-image-wrap {
  width: 100%;
  max-height: 520px;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 16px;
}

.preview-image {
  max-height: 488px;
}

.preview-placeholder {
  padding: 40px;
  text-align: center;
}

.preview-footer {
  display: flex;
  justify-content: flex-end;
  gap: 12px;
}
</style>
