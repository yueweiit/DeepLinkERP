<script setup lang="ts">
import { Download, Refresh, UploadFilled } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { computed, onMounted, reactive, ref } from 'vue'

import {
  commitImport,
  downloadImportTemplate,
  exportMasterData,
  getImportBatches,
  previewImport,
  type ImportBatchVO,
  type ImportExportObjectType,
  type ImportPreviewVO
} from '@/api/modules/importExport'
import FixedTableViewport from '@/components/FixedTableViewport/index.vue'
import PageContainer from '@/components/PageContainer/index.vue'
import { formatDate } from '@/utils/format'
import { saveBlob } from '@/utils/file'

const objectOptions: Array<{ label: string; value: ImportExportObjectType; desc: string }> = [
  { label: 'Product 产品/型号/SKU', value: 'product', desc: '历史产品线、型号线、SKU，可直接导入 released / archived' },
  { label: 'Inventory 物料/模具', value: 'inventory', desc: '物料、包材、模具治具等库存基础资料' },
  { label: 'Process 工艺记录', value: 'process', desc: '工艺路线、工序、历史工艺记录' },
  { label: 'Attachment 资料清单', value: 'attachment', desc: '只导入/导出资料清单口径，实体文件仍在对象详情页上传' }
]

const activeObjectType = ref<ImportExportObjectType>('product')
const selectedFile = ref<File | null>(null)
const preview = ref<ImportPreviewVO | null>(null)
const batches = ref<ImportBatchVO[]>([])
const loading = ref(false)
const previewLoading = ref(false)
const commitLoading = ref(false)
const templateLoading = ref(false)
const exportLoading = ref(false)

const exportFilters = reactive({
  keyword: '',
  status: '',
  full: false
})

const activeObject = computed(() => objectOptions.find((item) => item.value === activeObjectType.value) || objectOptions[0])
const canCommit = computed(() => Boolean(preview.value?.importToken && preview.value.successCount > 0))

function handleFileChange(event: Event) {
  selectedFile.value = (event.target as HTMLInputElement).files?.[0] || null
  preview.value = null
}

async function loadBatches() {
  loading.value = true
  try {
    batches.value = await getImportBatches(activeObjectType.value)
  } finally {
    loading.value = false
  }
}

async function downloadTemplate() {
  templateLoading.value = true
  try {
    const blob = await downloadImportTemplate(activeObjectType.value)
    saveBlob(blob, `${activeObjectType.value}_import_template.xlsx`)
  } finally {
    templateLoading.value = false
  }
}

async function runPreview() {
  if (!selectedFile.value) {
    ElMessage.warning('请选择要导入的 .xlsx 文件')
    return
  }
  previewLoading.value = true
  try {
    preview.value = await previewImport(activeObjectType.value, selectedFile.value)
    ElMessage.success('预览校验完成')
  } finally {
    previewLoading.value = false
  }
}

async function runCommit() {
  if (!preview.value?.importToken) return
  await ElMessageBox.confirm('确认提交校验通过的数据吗？提交后会写入业务表并记录导入批次。', '提交导入', {
    confirmButtonText: '提交导入',
    cancelButtonText: '取消',
    type: 'warning'
  })
  commitLoading.value = true
  try {
    preview.value = await commitImport(preview.value.importToken)
    selectedFile.value = null
    await loadBatches()
    ElMessage.success('导入提交完成')
  } finally {
    commitLoading.value = false
  }
}

async function runExport(full: boolean) {
  exportLoading.value = true
  try {
    const blob = await exportMasterData(activeObjectType.value, {
      keyword: full ? undefined : exportFilters.keyword.trim() || undefined,
      status: full ? undefined : exportFilters.status || undefined,
      full
    })
    saveBlob(blob, `${activeObjectType.value}_${full ? 'full' : 'filtered'}_export.xlsx`)
  } finally {
    exportLoading.value = false
  }
}

function switchObjectType(value: ImportExportObjectType) {
  activeObjectType.value = value
  selectedFile.value = null
  preview.value = null
  exportFilters.keyword = ''
  exportFilters.status = ''
  loadBatches()
}

onMounted(loadBatches)
</script>

<template>
  <PageContainer title="数据导入导出" description="按核心对象导入历史基础资料，预览通过后再提交落库。">
    <section class="page-panel import-export-layout">
      <aside class="import-object-list">
        <button
          v-for="item in objectOptions"
          :key="item.value"
          type="button"
          class="import-object-card"
          :class="{ 'is-active': activeObjectType === item.value }"
          @click="switchObjectType(item.value)"
        >
          <strong>{{ item.label }}</strong>
          <span class="subtle-text">{{ item.desc }}</span>
        </button>
      </aside>

      <main class="import-workspace">
        <div class="toolbar-row import-workspace__head">
          <div>
            <h3 class="section-title">{{ activeObject.label }}</h3>
            <p class="page-panel-desc">{{ activeObject.desc }}</p>
          </div>
          <el-button :icon="Download" :loading="templateLoading" @click="downloadTemplate">下载模板</el-button>
        </div>

        <section class="import-step-panel">
          <h4>导入预览</h4>
          <div class="import-upload-row">
            <input data-test="import-export-file" type="file" accept=".xlsx" @change="handleFileChange" />
            <el-button type="primary" :icon="UploadFilled" :loading="previewLoading" @click="runPreview">上传预览</el-button>
            <el-button type="success" :disabled="!canCommit" :loading="commitLoading" @click="runCommit">提交导入</el-button>
          </div>

          <div v-if="preview" class="import-preview-summary">
            <div><span class="subtle-text">总行数</span><strong>{{ preview.totalCount }}</strong></div>
            <div><span class="subtle-text">可导入</span><strong>{{ preview.successCount }}</strong></div>
            <div><span class="subtle-text">失败</span><strong>{{ preview.failCount }}</strong></div>
            <div><span class="subtle-text">文件</span><strong>{{ preview.fileName }}</strong></div>
          </div>

          <el-table v-if="preview" :data="preview.rows" border stripe size="small" max-height="300">
            <el-table-column prop="rowNo" label="行号" width="80" />
            <el-table-column prop="businessKey" label="业务键" min-width="160" />
            <el-table-column label="状态" width="110">
              <template #default="{ row }">
                <el-tag :type="row.status === 'ready' ? 'success' : 'danger'" effect="light">{{ row.status === 'ready' ? '可导入' : '错误' }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="message" label="提示" min-width="220" />
          </el-table>
        </section>

        <section class="import-step-panel">
          <div class="toolbar-row">
            <div>
              <h4>导出</h4>
              <p class="page-panel-desc">支持当前筛选导出，也支持全量导出。</p>
            </div>
            <el-button :icon="Refresh" :loading="loading" @click="loadBatches">刷新批次</el-button>
          </div>
          <div class="export-filter-row">
            <el-input v-model="exportFilters.keyword" clearable placeholder="编码 / 名称 / 文件名" />
            <el-input v-model="exportFilters.status" clearable placeholder="状态" />
            <el-button :loading="exportLoading" @click="runExport(false)">按筛选导出</el-button>
            <el-button type="primary" :loading="exportLoading" @click="runExport(true)">全量导出</el-button>
          </div>
        </section>
      </main>
    </section>

    <section class="page-panel" v-loading="loading">
      <div class="toolbar-row import-batch-head">
        <div>
          <h3 class="section-title">导入批次</h3>
          <p class="page-panel-desc">展示最近 50 条导入批次，便于追溯历史资料入库结果。</p>
        </div>
        <strong>{{ batches.length }} 批</strong>
      </div>
      <FixedTableViewport v-slot="{ tableHeight }" compact :refresh-key="batches">
      <el-table :data="batches" :height="tableHeight" border stripe>
        <el-table-column prop="importBatchId" label="批次ID" width="90" />
        <el-table-column prop="objectType" label="对象" width="120" />
        <el-table-column prop="fileName" label="文件名" min-width="220" />
        <el-table-column prop="totalCount" label="总数" width="80" />
        <el-table-column prop="successCount" label="成功" width="80" />
        <el-table-column prop="failCount" label="失败" width="80" />
        <el-table-column label="状态" width="110">
          <template #default="{ row }"><el-tag effect="light">{{ row.status }}</el-tag></template>
        </el-table-column>
        <el-table-column label="导入时间" width="160">
          <template #default="{ row }">{{ formatDate(row.createdAt) }}</template>
        </el-table-column>
        <el-table-column prop="createdBy" label="操作人" width="120" />
      </el-table>
      </FixedTableViewport>
    </section>
  </PageContainer>
</template>

<style scoped>
.import-export-layout {
  display: grid;
  grid-template-columns: 280px minmax(0, 1fr);
  gap: 16px;
}

.import-object-list,
.import-workspace,
.import-step-panel {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.import-object-card {
  display: flex;
  min-height: 78px;
  flex-direction: column;
  gap: 6px;
  padding: 12px;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  background: #fff;
  color: #0f172a;
  text-align: left;
  cursor: pointer;
}

.import-object-card.is-active {
  border-color: #2563eb;
  background: #eff6ff;
}

.import-workspace__head,
.import-batch-head {
  align-items: flex-start;
}

.import-step-panel {
  padding: 12px;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  background: #fff;
}

.import-step-panel h4 {
  margin: 0;
}

.import-upload-row,
.export-filter-row {
  display: grid;
  grid-template-columns: minmax(220px, 1fr) auto auto;
  gap: 10px;
  align-items: center;
}

.export-filter-row {
  grid-template-columns: minmax(200px, 1fr) 160px auto auto;
}

.import-preview-summary {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;
}

.import-preview-summary > div {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 4px;
  padding: 10px;
  border-radius: 8px;
  background: #f8fafc;
}

@media (max-width: 1000px) {
  .import-export-layout,
  .import-preview-summary {
    grid-template-columns: 1fr;
  }

  .import-upload-row,
  .export-filter-row {
    grid-template-columns: 1fr;
  }
}
</style>
