<script setup lang="ts">
import { ref } from 'vue'
import { ElMessage } from 'element-plus'

import { uploadTimelineAttachment } from '@/api/modules/attachment'

const props = withDefaults(defineProps<{
  projectId?: number
  nodeKey?: string
  fileCategory?: string
  versionNo?: string
  remark?: string
}>(), {
  fileCategory: 'document',
  versionNo: 'A'
})

const emit = defineEmits<{
  (event: 'uploaded', payload: { attachmentId: number; fileName: string }): void
}>()

const uploading = ref(false)

async function beforeUpload(file: File) {
  if (!props.projectId || !props.nodeKey) {
    ElMessage.error('请先选择项目和时间轴节点')
    return false
  }

  uploading.value = true
  try {
    const result = await uploadTimelineAttachment(props.projectId, props.nodeKey, file, {
      fileCategory: props.fileCategory,
      versionNo: props.versionNo,
      remark: props.remark
    })

    emit('uploaded', {
      attachmentId: result.attachmentId,
      fileName: result.originalFileName || result.fileName
    })
    ElMessage.success(`已上传 ${file.name}`)
  } finally {
    uploading.value = false
  }
  return false
}
</script>

<template>
  <el-upload drag :show-file-list="false" :before-upload="beforeUpload">
    <div class="upload-box">
      <el-icon class="upload-box__icon"><UploadFilled /></el-icon>
      <div class="upload-box__title">{{ uploading ? '上传中...' : '拖拽文件到此处，或点击上传' }}</div>
      <div class="upload-box__tip">文件会挂到当前项目的时间轴节点。</div>
    </div>
  </el-upload>
</template>

<style scoped>
.upload-box {
  padding: 16px;
  text-align: center;
  color: var(--plm-color-text-secondary);
}

.upload-box__icon {
  font-size: 24px;
  color: var(--plm-color-primary);
}

.upload-box__title {
  margin-top: 10px;
  color: var(--plm-color-text-primary);
}

.upload-box__tip {
  margin-top: 6px;
  font-size: 12px;
}
</style>
