<script setup lang="ts">
import { Plus, Refresh } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { createCodeItem, disableCodeItem, enableCodeItem, getCodeItems, getPhoneModelReview, updateCodeItem,
  type CodeItem, type CodeItemPayload, type PhoneModelReviewKind } from '@/api/modules/code'
import { useCachedRequest } from '@/composables/useCachedRequest'
import FixedTableViewport from '@/components/FixedTableViewport/index.vue'
import CodeItemDialog from './components/CodeItemDialog.vue'

const keyword = ref('')
const status = ref('')
const page = ref(1)
const size = ref(50)
const listRequest = useCachedRequest(getCodeItems)
const rows = computed(() => listRequest.hasCurrentData.value ? listRequest.data.value?.content || [] : [])
const total = computed(() => listRequest.data.value?.totalElements || 0)
const editorVisible = ref(false)
const editing = ref<CodeItem | null>(null)
const saving = ref(false)
const changingId = ref<number | null>(null)
const operationError = ref('')
const reviewVisible = ref(false)
const reviewKind = ref<PhoneModelReviewKind>('code_many_names')
const reviewPage = ref(1)
const reviewRequest = useCachedRequest(getPhoneModelReview)
const reviewRows = computed(() => reviewRequest.hasCurrentData.value ? reviewRequest.data.value?.content || [] : [])
let searchTimer: ReturnType<typeof setTimeout> | undefined

function load(force = false) {
  return listRequest.execute({ codeType: 'phone_model', keyword: keyword.value.trim(), status: status.value,
    page: page.value, size: size.value }, force)
}
function reset(debounce = false) {
  clearTimeout(searchTimer); listRequest.invalidate(); page.value = 1
  if (debounce) searchTimer = setTimeout(() => { searchTimer = undefined; void load() }, 300)
  else void load()
}
watch(keyword, () => reset(true), { flush: 'sync' })
watch([status, size], () => reset(), { flush: 'sync' })
function changePage(value: number) { page.value = value; void load() }
function openCreate() { editing.value = null; editorVisible.value = true }
function openEdit(item: CodeItem) { editing.value = item; editorVisible.value = true }
async function save(payload: CodeItemPayload) {
  saving.value = true; operationError.value = ''
  try {
    if (editing.value) await updateCodeItem(editing.value.codeItemId, payload)
    else await createCodeItem(payload)
    ElMessage.success('手机型号编码已保存'); editorVisible.value = false
    listRequest.clear(); await load(true)
  } catch { operationError.value = '保存失败，请检查名称及编码是否重复' }
  finally { saving.value = false }
}
async function toggle(item: CodeItem) {
  changingId.value = item.codeItemId; operationError.value = ''
  try {
    if (item.status === 'enabled') await disableCodeItem(item.codeItemId)
    else await enableCodeItem(item.codeItemId)
    ElMessage.success(item.status === 'enabled' ? '手机型号编码已停用，历史记录不变' : '手机型号编码已启用')
    listRequest.clear(); await load(true)
  } catch { operationError.value = '状态更新失败，请重试' }
  finally { changingId.value = null }
}
function loadReview() {
  return reviewRequest.execute({ kind: reviewKind.value, page: reviewPage.value, size: 50 })
}
watch(reviewVisible, (visible) => { if (visible) void loadReview() })
watch(reviewKind, () => { reviewRequest.invalidate(); reviewPage.value = 1; if (reviewVisible.value) void loadReview() })
function changeReviewPage(value: number) { reviewPage.value = value; void loadReview() }
onMounted(() => void load())
onUnmounted(() => clearTimeout(searchTimer))
</script>

<template>
  <main class="phone-model-codes">
    <header class="page-head">
      <div><h2>手机型号编码</h2><p>独立维护四位型号编码，保留前导零。名称与编码分别唯一，编码创建后固定；停用记录保留。</p></div>
      <div class="page-actions">
        <el-button data-test="phone-review-toggle" @click="reviewVisible = !reviewVisible">{{ reviewVisible ? '收起历史核对' : '查看历史关系核对' }}</el-button>
        <el-button :icon="Refresh" @click="load(true)">刷新</el-button>
        <el-button data-test="create-phone-code" type="primary" :icon="Plus" @click="openCreate">新增手机型号编码</el-button>
      </div>
    </header>
    <el-alert title="本页不改写产品、钉钉或编码生成流程中的历史字段；核对区只读，歧义关系待确认。" type="info" :closable="false" show-icon />
    <div class="filter-bar">
      <el-input v-model="keyword" clearable placeholder="搜索型号名称 / 四位编码" />
      <el-select v-model="status" clearable placeholder="全部状态"><el-option label="启用" value="enabled" /><el-option label="停用" value="disabled" /></el-select>
      <span>共 {{ total }} 条手机型号编码</span>
    </div>
    <el-alert v-if="listRequest.error.value || operationError" :title="listRequest.error.value || operationError" type="error" :closable="false" />
    <FixedTableViewport v-slot="{ tableHeight }" compact :bottom-offset="80" :refresh-key="rows">
    <el-table :data="rows" :height="tableHeight" v-loading="listRequest.loading.value" border stripe>
      <el-table-column label="手机型号编码" width="150"><template #default="{ row }"><code>{{ row.codeValue }}</code></template></el-table-column>
      <el-table-column prop="codeName" label="手机型号名称" min-width="260" />
      <el-table-column label="状态" width="100"><template #default="{ row }"><el-tag :type="row.status === 'enabled' ? 'success' : 'info'">{{ row.status === 'enabled' ? '启用' : '停用' }}</el-tag></template></el-table-column>
      <el-table-column prop="updatedAt" label="更新时间" min-width="180" />
      <el-table-column label="操作" width="200"><template #default="{ row }">
        <el-button data-test="edit-phone-code" link type="primary" @click="openEdit(row)">编辑名称</el-button>
        <el-button :data-test="`toggle-phone-${row.codeItemId}`" link :loading="changingId === row.codeItemId" :type="row.status === 'enabled' ? 'danger' : 'success'" @click="toggle(row)">{{ row.status === 'enabled' ? '停用' : '启用' }}</el-button>
      </template></el-table-column>
    </el-table>
    </FixedTableViewport>
    <el-pagination v-model:page-size="size" :current-page="page" :page-sizes="[20, 50, 100]" :total="total" layout="total, sizes, prev, pager, next, jumper" @current-change="changePage" />

    <section v-if="reviewVisible" class="review-section">
      <h3>历史手机型号关系核对（只读）</h3>
      <p>来自当前产品记录，可能包含别名或共用适配型号；不会自动合并或改写历史记录。</p>
      <el-radio-group v-model="reviewKind"><el-radio-button value="code_many_names">同码多名称</el-radio-button><el-radio-button value="name_many_codes">同名称多编码</el-radio-button></el-radio-group>
      <el-button class="review-refresh" @click="reviewRequest.clear(); loadReview()">重新核对</el-button>
      <el-alert v-if="reviewRequest.error.value" :title="reviewRequest.error.value" type="error" :closable="false" />
      <el-table :data="reviewRows" :height="400" v-loading="reviewRequest.loading.value" border stripe class="review-table">
        <el-table-column label="涉及编码" min-width="160"><template #default="{ row }"><div class="review-tags"><el-tag v-for="code in row.codeValues" :key="code" type="info">{{ code }}</el-tag></div></template></el-table-column>
        <el-table-column label="涉及手机型号名称" min-width="460"><template #default="{ row }"><div v-for="name in row.modelNames" :key="name">{{ name }}</div></template></el-table-column>
        <el-table-column prop="sourceCount" label="历史记录数" width="120" />
      </el-table>
      <el-pagination :current-page="reviewPage" :page-size="50" :total="reviewRequest.data.value?.totalElements || 0" layout="total, prev, pager, next" @current-change="changeReviewPage" />
    </section>
    <CodeItemDialog v-model="editorVisible" code-type="phone_model" :item="editing" :loading="saving" @save="save" />
  </main>
</template>

<style scoped>
.phone-model-codes { min-width: 0; }
.page-head, .page-actions, .filter-bar { display: flex; align-items: center; gap: 12px; }
.page-head { justify-content: space-between; align-items: flex-start; margin-bottom: 16px; }
h2, .page-head p { margin: 0 0 6px; }
p, .filter-bar span { color: var(--plm-color-text-secondary); font-size: 13px; }
.filter-bar { margin: 16px 0; }
.filter-bar .el-input { max-width: 340px; }.filter-bar .el-select { width: 160px; }
.el-pagination { margin-top: 14px; }
code { font-weight: 600; color: #1d4ed8; letter-spacing: .08em; }
.review-section { margin-top: 28px; padding-top: 14px; border-top: 1px solid var(--el-border-color); }
.review-refresh { margin-left: 12px; }.review-table { margin-top: 12px; }
.review-tags { display: flex; flex-wrap: wrap; gap: 6px; }
@media (max-width: 760px) { .page-head, .filter-bar { flex-direction: column; align-items: stretch; }.page-actions { flex-wrap: wrap; } }
</style>
