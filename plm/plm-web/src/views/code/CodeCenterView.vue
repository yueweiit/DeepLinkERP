<script setup lang="ts">
import { Plus, Upload } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { onMounted, reactive, ref } from 'vue'
import { createCodeItem, disableCodeItem, enableCodeItem, getCodeItems, updateCodeItem, type CodeItem, type CodeItemPayload } from '@/api/modules/code'
import FixedTableViewport from '@/components/FixedTableViewport/index.vue'
import CodeImportDialog from './components/CodeImportDialog.vue'
import CodeItemDialog from './components/CodeItemDialog.vue'

const loading = ref(false); const saving = ref(false); const rows = ref<CodeItem[]>([]); const total = ref(0)
const editorVisible = ref(false); const importVisible = ref(false); const editing = ref<CodeItem | null>(null)
const query = reactive({ codeType: 'color', keyword: '', status: '', page: 1, size: 200 })

async function load() { loading.value = true; try { const result = await getCodeItems(query); rows.value = result.content; total.value = result.totalElements } finally { loading.value = false } }
function openCreate() { editing.value = null; editorVisible.value = true }
function openEdit(item: CodeItem) { editing.value = item; editorVisible.value = true }
async function save(payload: CodeItemPayload) { saving.value = true; try { if (editing.value) await updateCodeItem(editing.value.codeItemId, payload); else await createCodeItem(payload); ElMessage.success('颜色编码已保存'); editorVisible.value = false; await load() } finally { saving.value = false } }
async function toggle(item: CodeItem) { if (item.status === 'enabled') await disableCodeItem(item.codeItemId); else await enableCodeItem(item.codeItemId); ElMessage.success(item.status === 'enabled' ? '颜色编码已停用' : '颜色编码已启用'); await load() }
onMounted(load)
</script>

<template>
  <main class="code-center" v-loading="loading">
    <header class="page-head"><div><p class="eyebrow">COLOR CODE REGISTRY</p><h2>颜色编码</h2><p>维护颜色编码、原名称及中文名称，停用后保留历史引用。</p></div><div class="page-actions"><el-button data-test="import-code-items" :icon="Upload" @click="importVisible = true">导入颜色编码 XLSX</el-button><el-button data-test="create-code-item" type="primary" :icon="Plus" @click="openCreate">新增颜色编码</el-button></div></header>
    <section class="registry-strip"><div><span>当前编码类型</span><strong>颜色编码</strong></div><div><span>记录数</span><strong>{{ total }}</strong></div><code>code_type = color</code></section>
    <section class="filter-bar"><el-input v-model="query.keyword" clearable placeholder="搜索编码、原名称或中文名称" @keyup.enter="load" /><el-select v-model="query.status" clearable placeholder="全部状态" @change="load"><el-option label="启用" value="enabled" /><el-option label="停用" value="disabled" /></el-select><el-button @click="load">查询</el-button></section>
    <FixedTableViewport v-slot="{ tableHeight }" compact :refresh-key="rows"><el-table :data="rows" :height="tableHeight" border stripe><el-table-column label="编码" width="120"><template #default="{ row }"><code class="code-chip">{{ row.codeValue }}</code></template></el-table-column><el-table-column prop="codeName" label="原名称" min-width="200" /><el-table-column prop="codeNameZh" label="中文名称" min-width="200" /><el-table-column label="状态" width="100"><template #default="{ row }"><el-tag :type="row.status === 'enabled' ? 'success' : 'info'">{{ row.status === 'enabled' ? '启用' : '停用' }}</el-tag></template></el-table-column><el-table-column prop="sortOrder" label="排序" width="90" /><el-table-column prop="updatedAt" label="更新时间" min-width="170" /><el-table-column label="操作" width="180"><template #default="{ row }"><el-button link type="primary" @click="openEdit(row)">编辑</el-button><el-button :data-test="`${row.status === 'enabled' ? 'disable' : 'enable'}-code-${row.codeItemId}`" link :type="row.status === 'enabled' ? 'danger' : 'success'" @click="toggle(row)">{{ row.status === 'enabled' ? '停用' : '启用' }}</el-button></template></el-table-column></el-table></FixedTableViewport>
    <el-empty v-if="!rows.length && !loading" description="暂无颜色编码，可新增或从 XLSX 导入" />
    <CodeItemDialog v-model="editorVisible" :item="editing" :loading="saving" @save="save" />
    <CodeImportDialog v-model="importVisible" @committed="load" />
  </main>
</template>

<style scoped>.code-center { min-width: 0; }.page-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 20px; margin-bottom: 16px; }.page-head h2,.page-head p { margin: 0; }.page-head h2 { margin: 3px 0 5px; }.eyebrow { color: #2563eb; font: 700 11px/1.2 ui-monospace, SFMono-Regular, Consolas, monospace; letter-spacing: .13em; }.page-actions,.filter-bar,.registry-strip { display: flex; align-items: center; gap: 10px; }.registry-strip { margin-bottom: 14px; padding: 12px 16px; border: 1px solid #dbe4f0; border-radius: 10px; background: linear-gradient(100deg,#f8fbff,#f3f6fa); }.registry-strip div { display: grid; gap: 2px; min-width: 120px; }.registry-strip span { color: #64748b; font-size: 12px; }.registry-strip code { margin-left: auto; color: #1d4ed8; }.filter-bar { margin-bottom: 14px; }.filter-bar :deep(.el-input) { max-width: 320px; }.filter-bar :deep(.el-select) { width: 150px; }.code-chip { display: inline-flex; min-width: 38px; justify-content: center; padding: 4px 8px; border: 1px solid #bfdbfe; border-radius: 6px; background: #eff6ff; color: #1d4ed8; font-weight: 700; letter-spacing: .06em; }@media(max-width:760px){.page-head{flex-direction:column}.registry-strip{align-items:flex-start;flex-wrap:wrap}.registry-strip code{width:100%;margin-left:0}.filter-bar{align-items:stretch;flex-direction:column}.filter-bar :deep(.el-input),.filter-bar :deep(.el-select){width:100%;max-width:none}}</style>
