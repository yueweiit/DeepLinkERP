<script setup lang="ts">
import { Delete, Download, Refresh, Upload, View } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox, type UploadFile, type UploadUserFile } from 'element-plus'
import { computed, reactive, ref, watch } from 'vue'

import {
  deleteAttachment,
  getFileCenterAttachments,
  getTimelineAttachments,
  uploadTimelineAttachment,
  uploadProjectAttachment,
  type AttachmentVO
} from '@/api/modules/attachment'
import { useAttachmentViewer } from '@/composables/useAttachmentViewer'
import {
  ENGINEERING_UPLOAD_ACCEPT,
  FILE_CATEGORY_OPTIONS,
  MAX_UPLOAD_FILE_SIZE_BYTES,
  fileCategoryLabel,
  formatFileSize
} from '@/utils/file'

const props = withDefaults(defineProps<{
  projectId: number
  nodeKey?: string | null
  scope?: 'project' | 'node'
  title?: string
  description?: string
}>(), {
  nodeKey: null,
  scope: 'project',
  title: '',
  description: ''
})
const emit = defineEmits<{ (event: 'changed'): void }>()
const { viewAttachment, downloadFile } = useAttachmentViewer()

const loading = ref(false)
const uploading = ref(false)
const loadError = ref('')
const attachments = ref<AttachmentVO[]>([])
const selectedFile = ref<File | null>(null)
const fileList = ref<UploadUserFile[]>([])
const uploadForm = reactive({
  fileCategory: 'testing',
  versionNo: 'V1',
  remark: ''
})

const categoryOptions = FILE_CATEGORY_OPTIONS.filter((item) => item.value !== 'sample_image')

const isNodeScope = computed(() => props.scope === 'node')
const panelTitle = computed(() => props.title || (isNodeScope.value ? '当前节点资料' : '项目文件'))
const panelDescription = computed(() =>
  props.description || (isNodeScope.value
    ? '上传当前步骤需要的图纸、工程文件、生产资料或客户确认件。'
    : '汇总当前 Product 下的项目文件，可在文件中心按项目统一查询。')
)
const canUpload = computed(() => Boolean(selectedFile.value && !uploading.value && (!isNodeScope.value || props.nodeKey)))

function errorMessage(error: unknown) {
  return error instanceof Error ? error.message : '请求失败，请稍后重试'
}

async function loadAttachments() {
  loadError.value = ''
  if (isNodeScope.value && !props.nodeKey) {
    attachments.value = []
    return
  }
  loading.value = true
  try {
    if (isNodeScope.value && props.nodeKey) {
      attachments.value = await getTimelineAttachments(props.projectId, props.nodeKey)
    } else {
      const page = await getFileCenterAttachments({ projectId: props.projectId, page: 1, size: 100 })
      attachments.value = page.content
    }
  } catch (error) {
    loadError.value = errorMessage(error)
  } finally {
    loading.value = false
  }
}

function handleFileChange(uploadFile: UploadFile) {
  const file = uploadFile.raw || null
  if (!file) return
  if (file.size > MAX_UPLOAD_FILE_SIZE_BYTES) {
    ElMessage.warning(`单个文件不能超过 ${formatFileSize(MAX_UPLOAD_FILE_SIZE_BYTES)}`)
    selectedFile.value = null
    fileList.value = []
    return
  }
  selectedFile.value = file
  fileList.value = [uploadFile]
}

function handleFileRemove() {
  selectedFile.value = null
  fileList.value = []
}

async function uploadFile() {
  if (isNodeScope.value && !props.nodeKey) {
    ElMessage.warning('当前项目没有可用的时间轴节点')
    return
  }
  if (!selectedFile.value) {
    ElMessage.warning('请先选择文件')
    return
  }
  uploading.value = true
  try {
    const metadata = {
      fileCategory: uploadForm.fileCategory,
      versionNo: uploadForm.versionNo.trim() || undefined,
      remark: uploadForm.remark.trim() || undefined
    }
    if (isNodeScope.value && props.nodeKey) {
      await uploadTimelineAttachment(props.projectId, props.nodeKey, selectedFile.value, metadata)
    } else {
      await uploadProjectAttachment(props.projectId, selectedFile.value, metadata)
    }
    selectedFile.value = null
    fileList.value = []
    uploadForm.remark = ''
    await loadAttachments()
    emit('changed')
    ElMessage.success(isNodeScope.value ? '当前节点资料已上传' : '项目文件已上传')
  } finally {
    uploading.value = false
  }
}

async function removeFile(attachment: AttachmentVO) {
  await ElMessageBox.confirm(`确认删除“${attachment.originalFileName}”吗？`, '删除附件', {
    confirmButtonText: '删除',
    cancelButtonText: '取消',
    type: 'warning'
  })
  await deleteAttachment(attachment.attachmentId)
  await loadAttachments()
  emit('changed')
  ElMessage.success('附件已删除')
}

watch([() => props.projectId, () => props.nodeKey, () => props.scope], loadAttachments, { immediate: true })
</script>

<template>
  <div class="attachment-panel" v-loading="loading">
    <div class="attachment-panel__toolbar">
      <div>
        <h4 class="section-title">{{ panelTitle }}</h4>
        <p class="page-panel-desc">{{ panelDescription }}</p>
      </div>
      <el-button :icon="Refresh" circle title="刷新附件" @click="loadAttachments" />
    </div>

    <el-alert v-if="loadError" :title="loadError" type="error" show-icon :closable="false" />

    <div class="attachment-upload-bar">
      <el-select v-model="uploadForm.fileCategory" aria-label="文件分类" placeholder="文件分类">
        <el-option v-for="item in categoryOptions" :key="item.value" :label="item.label" :value="item.value" />
      </el-select>
      <el-input v-model="uploadForm.versionNo" aria-label="文件版本" placeholder="版本，例如 V1" maxlength="50" />
      <el-input v-model="uploadForm.remark" aria-label="附件备注" placeholder="备注" maxlength="500" />
      <el-upload
        v-model:file-list="fileList"
        action="#"
        :auto-upload="false"
        :limit="1"
        :accept="ENGINEERING_UPLOAD_ACCEPT"
        :on-change="handleFileChange"
        :on-remove="handleFileRemove"
      >
        <el-button :icon="Upload">选择文件</el-button>
      </el-upload>
      <el-button
        data-test="attachment-upload"
        type="primary"
        :icon="Upload"
        :disabled="!canUpload"
        :loading="uploading"
        @click="uploadFile"
      >
        上传
      </el-button>
    </div>

    <template v-if="!loadError">
      <el-table :data="attachments" border stripe size="small" class="attachment-panel__table">
        <el-table-column prop="originalFileName" label="文件名称" min-width="220" />
        <el-table-column label="归属节点" min-width="150">
          <template #default="{ row }">{{ row.timelineStepName || row.timelineStageName || row.timelineNodeKey || '--' }}</template>
        </el-table-column>
        <el-table-column label="分类" width="110"><template #default="{ row }">{{ fileCategoryLabel(row.fileCategory) }}</template></el-table-column>
        <el-table-column prop="versionNo" label="版本" width="90" />
        <el-table-column label="大小" width="100"><template #default="{ row }">{{ formatFileSize(row.fileSize) }}</template></el-table-column>
        <el-table-column prop="createdBy" label="上传人" width="120" />
        <el-table-column prop="createdAt" label="上传时间" min-width="170" />
        <el-table-column prop="remark" label="备注" min-width="150"><template #default="{ row }">{{ row.remark || '--' }}</template></el-table-column>
        <el-table-column label="操作" width="150" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" :icon="View" title="查看" @click="viewAttachment(row)" />
            <el-button link type="primary" :icon="Download" title="下载" @click="downloadFile(row)" />
            <el-button link type="danger" :icon="Delete" title="删除" @click="removeFile(row)" />
          </template>
        </el-table-column>
      </el-table>
      <el-empty v-if="!attachments.length" :description="isNodeScope ? '当前节点还没有附件' : '当前项目还没有附件'" />
    </template>
  </div>
</template>

<style scoped>
.attachment-panel { min-width: 0; }
.attachment-panel__toolbar { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 14px; }
.attachment-panel__toolbar h4,
.attachment-panel__toolbar p { margin-top: 0; }
.attachment-upload-bar { display: grid; grid-template-columns: 150px 130px minmax(180px, 1fr) auto auto; gap: 10px; align-items: start; margin: 14px 0; }
.attachment-panel__table { width: 100%; }
@media (max-width: 900px) {
  .attachment-upload-bar { grid-template-columns: 1fr 1fr; }
}
@media (max-width: 620px) {
  .attachment-panel__toolbar { align-items: flex-start; }
  .attachment-upload-bar { grid-template-columns: 1fr; }
}
</style>
