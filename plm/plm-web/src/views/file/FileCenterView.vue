<script setup lang="ts">
import { Delete, Download, FolderOpened, Refresh, Search, View } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'

import {
  deleteAttachment,
  getAttachmentVersions,
  getAttachmentDetail,
  getFileCenterAttachments,
  getProductAttachments,
  uploadAttachmentVersion,
  publishAttachmentVersion,
  type AttachmentVO,
  type FileCenterQuery
} from '@/api/modules/attachment'
import { getCollaborationPage } from '@/api/modules/collaboration'
import { getMolds } from '@/api/modules/molds'
import type { CollaborationRow } from '@/types/collaboration'
import { useUserStore } from '@/stores/user'
import FixedTableViewport from '@/components/FixedTableViewport/index.vue'
import PageContainer from '@/components/PageContainer/index.vue'
import { useAttachmentViewer } from '@/composables/useAttachmentViewer'
import type { PageResponse } from '@/api/request'
import { formatDate } from '@/utils/format'
import { FILE_CATEGORY_OPTIONS, fileCategoryLabel, formatFileSize } from '@/utils/file'
import { toInProgressProjectRoute } from '@/utils/projectRoute'

const router = useRouter()
const user = useUserStore()
const { viewAttachment, downloadFile } = useAttachmentViewer()
const loading = ref(false)
const loadError = ref('')
const pageData = ref<PageResponse<AttachmentVO>>({
  content: [],
  page: 1,
  size: 20,
  totalElements: 0,
  totalPages: 0
})

const filters = reactive({
  keyword: '',
  projectId: undefined as number | undefined,
  nodeKey: '',
  fileCategory: '',
  page: 1,
  size: 20
})

const categoryOptions = FILE_CATEGORY_OPTIONS
let listGeneration = 0

function errorMessage(error: unknown) {
  return error instanceof Error ? error.message : '文件中心查询失败，请稍后重试'
}

function buildQuery(): FileCenterQuery {
  return {
    ...(filters.keyword.trim() ? { keyword: filters.keyword.trim() } : {}),
    ...(filters.projectId ? { projectId: filters.projectId } : {}),
    ...(filters.nodeKey.trim() ? { nodeKey: filters.nodeKey.trim() } : {}),
    ...(filters.fileCategory ? { fileCategory: filters.fileCategory } : {}),
    page: filters.page,
    size: filters.size
  }
}

async function loadData() {
  const ticket = ++listGeneration, token = user.token
  loading.value = true
  loadError.value = ''
  try {
    const result = await getFileCenterAttachments(buildQuery())
    if (ticket === listGeneration && token === user.token) pageData.value = result
  } catch (error) {
    if (ticket === listGeneration && token === user.token) loadError.value = errorMessage(error)
  } finally {
    if (ticket === listGeneration && token === user.token) loading.value = false
  }
}

function searchFiles() {
  filters.page = 1
  loadData()
}

function resetFilters() {
  filters.keyword = ''
  filters.projectId = undefined
  filters.nodeKey = ''
  filters.fileCategory = ''
  filters.page = 1
  filters.size = 20
  loadData()
}

function changePage(page: number) {
  filters.page = page
  loadData()
}

function changePageSize(size: number) {
  filters.size = size
  filters.page = 1
  loadData()
}

function openProject(projectId: number | null | undefined) {
  if (!projectId) return
  router.push(toInProgressProjectRoute({ productId: String(projectId) }))
}

async function removeFile(attachment: AttachmentVO) {
  if (!user.hasPermission('documents:write') || attachment.releasedAt || attachment.status === 'released') return
  await ElMessageBox.confirm(`确认删除“${attachment.originalFileName}”吗？`, '删除附件', {
    confirmButtonText: '删除',
    cancelButtonText: '取消',
    type: 'warning'
  })
  await deleteAttachment(attachment.attachmentId)
  if (pageData.value.content.length === 1 && filters.page > 1) filters.page -= 1
  await loadData()
  ElMessage.success('附件已删除')
}

const versionVisible = ref(false), versionLoading = ref(false), versionError = ref(''), versions = ref<AttachmentVO[]>([]), fileContext = ref<AttachmentVO>(), versionId = ref<number>(), uploadFile = ref<File>(), versionSaving = ref(false), familyItems = ref<CollaborationRow[]>([]), familyMolds = ref<CollaborationRow[]>([]), relatedPdfs = ref<AttachmentVO[]>([])
const versionForm = reactive({ versionNo:'', reason:'', publicationReason:'', itemId:null as number|null, moldSetId:null as number|null, pdfAttachmentId:null as number|null })
const selectedVersion = computed(() => versions.value.find(a => a.attachmentId === versionId.value))
const pdfOptions = computed(() => relatedPdfs.value.filter(p => p.attachmentId !== versionId.value))
const recentFormal = computed(() => versions.value.filter(a => a.status === 'released').sort((a,b) => String(b.releasedAt || '').localeCompare(String(a.releasedAt || '')))[0])
const canWriteDocuments = computed(() => user.hasPermission('documents:write')), canPublishDocuments = computed(() => user.hasPermission('documents:publish'))
const isCad = computed(() => selectedVersion.value?.previewType === 'cad' || ['dwg','dxf','step','stp','igs','iges','stl','obj','3dm','prt','sldprt','sldasm'].includes(selectedVersion.value?.fileExt.toLowerCase() || ''))
let familyGeneration = 0, itemGeneration = 0, moldGeneration = 0
async function searchFamilyItems(keyword = '') {
  const ticket = ++itemGeneration, owner = fileContext.value?.ownerObjectId; if (!owner || !canPublishDocuments.value) return
  const result = await getCollaborationPage({view:'market',page:1,size:100,keyword})
  if (ticket !== itemGeneration || owner !== fileContext.value?.ownerObjectId) return
  familyItems.value = result.content.filter(i => i.productLineId === owner || i.projects.some(p => p.projectId === owner))
}
async function chooseItem(id: number | null) {
  versionForm.itemId = id; versionForm.moldSetId = null; familyMolds.value = []
  const ticket = ++moldGeneration; if (!id) return
  const result = await getMolds({view:'delivery',page:1,size:100,itemId:id})
  if (ticket === moldGeneration && versionForm.itemId === id) familyMolds.value = result.content
}
async function chooseVersion(id: number) {
  versionId.value = id; uploadFile.value = undefined; versionForm.versionNo = ''; versionForm.reason = ''; versionForm.publicationReason = ''
  const version = versions.value.find(a => a.attachmentId === id)
  versionForm.itemId = version?.collaborationItemId || null; versionForm.moldSetId = version?.moldSetId || null; versionForm.pdfAttachmentId = version?.derivedPdfAttachmentId || null
  if (versionForm.itemId && canPublishDocuments.value) {const existingMold = versionForm.moldSetId; await chooseItem(versionForm.itemId);versionForm.moldSetId = existingMold}
}
async function openVersions(file: AttachmentVO) {
  const ticket = ++familyGeneration; itemGeneration++; moldGeneration++; versionVisible.value = true; versionLoading.value = true; versionError.value = ''; fileContext.value = file; versions.value = []; familyItems.value = []; familyMolds.value = []; relatedPdfs.value = []
  try {const result = await getAttachmentVersions(file.attachmentId); if (ticket !== familyGeneration) return;versions.value = result; await chooseVersion(file.attachmentId)
    if (canPublishDocuments.value) {const [pdfs] = await Promise.all([getProductAttachments(file.ownerObjectId),searchFamilyItems()]);if (ticket === familyGeneration) relatedPdfs.value = pdfs.filter(a => a.fileExt.toLowerCase() === 'pdf')}
  } catch(e) {if (ticket === familyGeneration) versionError.value = errorMessage(e)} finally {if (ticket === familyGeneration) versionLoading.value = false}
}
function fileChosen(event: Event) { uploadFile.value = (event.target as HTMLInputElement).files?.[0] }
async function uploadVersion() {
  const selected = selectedVersion.value; if (!selected || !canWriteDocuments.value) return
  if (!uploadFile.value || !versionForm.versionNo.trim() || !versionForm.reason.trim()) {ElMessage.warning('请选择文件，并填写新版本编号与修改原因');return}
  if (versions.value.some(v => v.versionNo === versionForm.versionNo.trim())) {ElMessage.warning('同一版本族不能重复使用版本编号');return}
  const ticket = familyGeneration; versionSaving.value = true; versionError.value = ''
  try {const created = await uploadAttachmentVersion(selected.attachmentId,uploadFile.value,versionForm.versionNo.trim(),versionForm.reason.trim());if (ticket !== familyGeneration) return;versions.value = await getAttachmentVersions(created.attachmentId);await chooseVersion(created.attachmentId);await loadData();ElMessage.success('新版本已上传为草稿，尚未正式发布')}
  catch(e) {if (ticket === familyGeneration) versionError.value = errorMessage(e)} finally {if (ticket === familyGeneration) versionSaving.value = false}
}
async function releaseVersion() {
  const selected = selectedVersion.value;if (!selected || !canPublishDocuments.value || selected.releasedAt || selected.status === 'released') return
  if (!versionForm.publicationReason.trim()) {ElMessage.warning('请填写正式发布说明');return}
  if (isCad.value && !versionForm.pdfAttachmentId) {ElMessage.warning('CAD 正式发布须人工选择同项目的 PDF 衍生件');return}
  if (versionForm.moldSetId && !versionForm.itemId) {ElMessage.warning('请先选择模具所属的兼容型号档案');return}
  const confirmed = await ElMessageBox.confirm(`确认正式发布 ${selected.originalFileName}（${selected.versionNo}）？本次关联由你明确选择，正式版本以后通过新版本变更。`,'发布图纸版本',{confirmButtonText:'确认正式发布',cancelButtonText:'返回核对'}).catch(() => false)
  if (!confirmed) return
  const ticket = familyGeneration;versionSaving.value = true;versionError.value = ''
  try {await publishAttachmentVersion(selected.attachmentId,{reason:versionForm.publicationReason.trim(),itemId:versionForm.itemId,moldSetId:versionForm.moldSetId,pdfAttachmentId:versionForm.pdfAttachmentId});if (ticket !== familyGeneration) return;versions.value = await getAttachmentVersions(selected.attachmentId);await loadData();ElMessage.success('正式版本已发布；原文件及历史版本仍保留')}
  catch(e) {if (ticket === familyGeneration) versionError.value = errorMessage(e)} finally {if (ticket === familyGeneration) versionSaving.value = false}
}
async function previewDerivedPdf() {const id = selectedVersion.value?.derivedPdfAttachmentId;if (id) await viewAttachment(await getAttachmentDetail(id))}
watch(versionVisible, visible => {if (!visible) {familyGeneration++;itemGeneration++;moldGeneration++;versionSaving.value = false}})
watch(() => user.token, () => {listGeneration++;familyGeneration++;itemGeneration++;moldGeneration++;versionVisible.value = false;versions.value = [];fileContext.value = undefined;familyItems.value = [];familyMolds.value = [];relatedPdfs.value = [];pageData.value = {content:[],page:1,size:filters.size,totalElements:0,totalPages:0};loading.value=false},{flush:'sync'})
onBeforeUnmount(() => {listGeneration++;familyGeneration++;itemGeneration++;moldGeneration++})

onMounted(loadData)
</script>

<template>
  <PageContainer
    title="文件中心"
    description="沿用项目附件维护版本族、正式图纸及变更原因；CAD 原文件与人工关联的 PDF 分别保留。"
  >
    <section class="page-panel file-center-toolbar">
      <div class="file-center-toolbar__filters">
        <el-input
          v-model="filters.keyword"
          clearable
          placeholder="搜索文件名或备注"
          @keyup.enter="searchFiles"
        />
        <el-input-number
          v-model="filters.projectId"
          :min="1"
          :controls="false"
          placeholder="项目 ID"
          aria-label="项目 ID"
        />
        <el-input v-model="filters.nodeKey" clearable placeholder="时间轴节点编码" />
        <el-select v-model="filters.fileCategory" clearable placeholder="文件分类">
          <el-option v-for="item in categoryOptions" :key="item.value" :label="item.label" :value="item.value" />
        </el-select>
      </div>
      <div class="file-center-toolbar__actions">
        <el-button type="primary" :icon="Search" @click="searchFiles">查询</el-button>
        <el-button :icon="Refresh" @click="resetFilters">重置</el-button>
      </div>
    </section>

    <el-alert
      title="上传入口在项目详情的当前时间轴节点"
      description="首份资料仍从项目详情上传；已有文件可在版本抽屉上传新版本和显式发布，不另建脱离项目的文件库。"
      type="info"
      show-icon
      :closable="false"
      class="file-center-note"
    />

    <section class="page-panel" v-loading="loading">
      <div class="file-center-summary">
        <div>
          <h3 class="section-title">归档文件</h3>
          <p class="page-panel-desc">查询成功后显示后端分页结果；接口失败不会伪装成空列表。</p>
        </div>
        <strong>{{ pageData.totalElements }} 个文件</strong>
      </div>

      <el-alert v-if="loadError" :title="loadError" type="error" show-icon :closable="false" />

      <template v-else>
        <FixedTableViewport v-slot="{ tableHeight }" :refresh-key="pageData.content">
        <el-table :data="pageData.content" :height="tableHeight" border stripe class="file-center-table">
          <el-table-column prop="originalFileName" label="文件名称" min-width="230" />
          <el-table-column label="项目编码" min-width="170">
            <template #default="{ row }">{{ row.projectCode || '--' }}</template>
          </el-table-column>
          <el-table-column label="项目名称" min-width="200">
            <template #default="{ row }">{{ row.projectName || '--' }}</template>
          </el-table-column>
          <el-table-column prop="timelineNodeKey" label="时间轴节点" min-width="150"><template #default="{ row }">{{ row.timelineNodeKey || '--' }}</template></el-table-column>
          <el-table-column label="分类" width="110"><template #default="{ row }">{{ fileCategoryLabel(row.fileCategory) }}</template></el-table-column>
          <el-table-column label="版本 / 正式状态" width="155"><template #default="{row}">{{ row.versionNo }} <el-tag v-if="row.status === 'released'" size="small" type="success">正式</el-tag><el-tag v-else-if="row.releasedAt" size="small" type="info">历史正式</el-tag></template></el-table-column>
          <el-table-column label="大小" width="100"><template #default="{ row }">{{ formatFileSize(row.fileSize) }}</template></el-table-column>
          <el-table-column prop="createdBy" label="上传人" width="120" />
          <el-table-column label="上传时间" width="150"><template #default="{ row }">{{ formatDate(row.createdAt) }}</template></el-table-column>
          <el-table-column prop="remark" label="备注" min-width="150"><template #default="{ row }">{{ row.remark || '--' }}</template></el-table-column>
          <el-table-column label="操作" width="245" fixed="right">
            <template #default="{ row }">
              <el-button link type="primary" :icon="FolderOpened" title="进入项目" @click="openProject(row.projectId || row.ownerObjectId)" />
              <el-button link type="primary" :icon="View" title="查看" @click="viewAttachment(row)" />
              <el-button link type="primary" :icon="Download" title="下载" @click="downloadFile(row)" />
              <el-button link type="primary" title="版本与发布" @click="openVersions(row)">版本 / 发布</el-button>
              <el-button v-if="canWriteDocuments && !row.releasedAt && row.status !== 'released'" link type="danger" :icon="Delete" title="删除" @click="removeFile(row)" />
            </template>
          </el-table-column>
        </el-table>
        </FixedTableViewport>

        <el-empty v-if="!pageData.content.length" description="当前筛选条件下没有文件" />

        <el-pagination
          v-if="pageData.totalElements > 0"
          class="file-center-pagination"
          background
          layout="total, sizes, prev, pager, next"
          :current-page="filters.page"
          :page-size="filters.size"
          :page-sizes="[10, 20, 50, 100]"
          :total="pageData.totalElements"
          @current-change="changePage"
          @size-change="changePageSize"
        />
      </template>
    </section>
    <el-drawer v-model="versionVisible" title="图纸与文档 · 版本族" size="96%" class="file-version-drawer">
      <section v-loading="versionLoading" class="file-version-content">
        <header><h2>{{ fileContext?.originalFileName }}</h2><p>所属平台 / 机型项目：{{ fileContext?.projectName || fileContext?.projectCode || `#${fileContext?.ownerObjectId}` }} · 版本族 #{{ fileContext?.familyId || fileContext?.attachmentId }}</p><p>最近正式发布：{{ recentFormal?.versionNo || '尚未正式发布' }} · 历史版本和原文件保留</p></header>
        <el-alert v-if="versionError" :title="versionError" type="error" :closable="false" />
<div class="file-version-workspace"><section><h3>版本历史</h3><el-table :data="versions" row-key="attachmentId" border highlight-current-row @row-click="(row:AttachmentVO)=>chooseVersion(row.attachmentId)"><el-table-column prop="versionNo" label="版本" width="100" /><el-table-column prop="originalFileName" label="原始文件" min-width="190" /><el-table-column label="状态" width="120"><template #default="{row}">{{ row.status==='released'?'正式发布':row.releasedAt?'历史正式':'草稿' }}</template></el-table-column><el-table-column label="变更原因" min-width="220"><template #default="{row}">{{ row.changeReason || row.remark || '未填写' }}</template></el-table-column><el-table-column prop="createdBy" label="上传账号" width="120" /><el-table-column label="发布账号" width="140"><template #default="{row}">{{ row.releasedBy || (row.releasedByUserId ? `#${row.releasedByUserId}` : '尚未发布') }}</template></el-table-column><el-table-column label="发布日期" width="160"><template #default="{row}">{{ row.releasedAt?formatDate(row.releasedAt):'尚未发布' }}</template></el-table-column></el-table><div v-if="selectedVersion" class="version-actions"><strong>选中 {{ selectedVersion.versionNo }}</strong><el-button @click="downloadFile(selectedVersion)">下载原文件</el-button><el-button @click="viewAttachment(selectedVersion)">{{ isCad?'原格式预览说明':'预览文件' }}</el-button><el-button v-if="selectedVersion.derivedPdfAttachmentId" type="primary" @click="previewDerivedPdf">查看已关联 PDF</el-button></div><el-alert v-if="isCad" title="CAD / 3D 本期下载原文件或查看手工关联的 PDF，不宣称已有原格式在线转换。" type="info" :closable="false" /></section>
          <aside v-if="selectedVersion" class="version-editors"><section v-if="canWriteDocuments"><h3>基于选中版本上传新版本</h3><p>已有版本不可替换；新版本先保存为草稿。</p><input :key="versionId" type="file" aria-label="选择新版本文件" @change="fileChosen" /><el-form label-position="top"><el-form-item label="新版本编号" required><el-input v-model="versionForm.versionNo" maxlength="32" placeholder="人工填写，例如 V2" /></el-form-item><el-form-item label="修改原因" required><el-input v-model="versionForm.reason" type="textarea" :rows="3" placeholder="明确说明本次变更" /></el-form-item></el-form><el-button data-test="upload-file-version" type="primary" :loading="versionSaving" @click="uploadVersion">上传新版本草稿</el-button></section>
            <section v-if="canPublishDocuments && !selectedVersion.releasedAt && selectedVersion.status !== 'released'"><h3>显式正式发布</h3><el-form label-position="top"><el-form-item label="适用兼容型号档案（平台共用资料可不选）"><el-select v-model="versionForm.itemId" clearable filterable remote :remote-method="searchFamilyItems" placeholder="人工选择同项目关联档案" @change="chooseItem"><el-option v-for="i in familyItems" :key="i.itemId" :value="i.itemId" :label="`${i.styleName} / ${i.compatibleModels} (#${i.itemId})`" /></el-select></el-form-item><el-form-item label="关联实物模具套"><el-select v-model="versionForm.moldSetId" clearable :disabled="!versionForm.itemId" placeholder="人工选择，不按编码推断套数"><el-option v-for="m in familyMolds" :key="m.moldSetId" :value="m.moldSetId!" :label="`${m.assetNumber} / ${m.setName}`" /></el-select></el-form-item><el-form-item label="同项目 PDF 衍生件" :required="isCad"><el-select v-model="versionForm.pdfAttachmentId" clearable placeholder="人工关联，不自动转换 CAD"><el-option v-for="p in pdfOptions" :key="p.attachmentId" :value="p.attachmentId" :label="`${p.originalFileName} / ${p.versionNo}`" /></el-select></el-form-item><el-form-item label="正式发布说明" required><el-input v-model="versionForm.publicationReason" type="textarea" :rows="3" placeholder="确认本版本及适用范围" /></el-form-item></el-form><el-button data-test="release-file-version" type="primary" :loading="versionSaving" @click="releaseVersion">确认正式发布</el-button></section><el-alert v-else-if="selectedVersion.releasedAt" title="此版本已有正式发布记录。变更请上传新版本，不能原地修改历史正式版本。" type="success" :closable="false" /><el-alert v-if="!canWriteDocuments && !canPublishDocuments" title="当前账号仅可查看获授权的版本及文件，不能上传或正式发布。" type="info" :closable="false" /></aside></div>
      </section>
    </el-drawer>
  </PageContainer>
</template>

<style scoped>
.file-center-toolbar { display: flex; align-items: center; justify-content: space-between; gap: 14px; }
.file-center-toolbar__filters { display: grid; grid-template-columns: minmax(220px, 1.5fr) 130px minmax(180px, 1fr) 150px; gap: 10px; flex: 1; min-width: 0; }
.file-center-toolbar__actions { display: flex; gap: 8px; flex: 0 0 auto; }
.file-center-note { margin-bottom: 16px; }
.file-center-summary { display: flex; align-items: center; justify-content: space-between; gap: 16px; margin-bottom: 14px; }
.file-center-summary h3,
.file-center-summary p { margin-top: 0; }
.file-center-table { width: 100%; }
.file-center-pagination { justify-content: flex-end; margin-top: 16px; }
.file-version-content{display:flex;flex-direction:column;gap:18px;min-height:0}.file-version-content h2,.file-version-content h3{margin:0 0 12px}.file-version-content p{color:#73859d;font-size:13px;line-height:1.8}.file-version-workspace{display:grid;grid-template-columns:minmax(550px,1.7fr) minmax(380px,1fr);gap:24px;min-height:0}.version-editors{display:flex;flex-direction:column;gap:24px}.version-editors section{border:1px solid #dfe8f3;background:#f8fbff;border-radius:8px;padding:20px}.version-editors .el-select{width:100%}.version-actions{display:flex;align-items:center;gap:12px;flex-wrap:wrap;margin:16px 0}.version-editors input[type=file]{max-width:100%;margin:12px 0}.file-version-drawer :deep(.el-drawer__body){padding:24px}
@media(max-width:1100px){.file-version-workspace{grid-template-columns:1fr}.version-editors{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:20px}}@media(max-width:720px){.version-editors{grid-template-columns:1fr}}
@media (max-width: 1080px) {
  .file-center-toolbar { align-items: stretch; flex-direction: column; }
  .file-center-toolbar__filters { grid-template-columns: 1fr 1fr; }
}
@media (max-width: 620px) {
  .file-center-toolbar__filters { grid-template-columns: 1fr; }
  .file-center-toolbar__actions > * { flex: 1; }
  .file-center-summary { align-items: flex-start; flex-direction: column; }
  .file-center-pagination { justify-content: flex-start; overflow-x: auto; }
}
</style>

