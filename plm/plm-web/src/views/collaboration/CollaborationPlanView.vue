<script setup lang="ts">
import { computed, onActivated, onBeforeUnmount, onDeactivated, onMounted, reactive, ref, watch } from 'vue'
import { onBeforeRouteLeave, useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, Refresh, Upload, Download, Setting, FullScreen, MoreFilled, QuestionFilled } from '@element-plus/icons-vue'
import * as api from '@/api/modules/collaboration'
import { getCodeItems, type CodeItem } from '@/api/modules/code'
import { useCachedRequest } from '@/composables/useCachedRequest'
import { useUserStore } from '@/stores/user'
import { useCollaborationWorkspace } from '@/stores/collaborationWorkspace'
import FixedTableViewport from '@/components/FixedTableViewport/index.vue'
import type { CellValue, CollaborationOptions, CollaborationRow, FieldGroup, MoldCodeOption, PlanField, PlanHistory, PlanView, ProjectOption, RowResult } from '@/types/collaboration'
import { brandFromModel, equalCell, groupNames, isCollaborationEntry, moldStatuses, parseCell, parseClipboard, productionFields, rowKey, statusNames, suggestedArrivalDate } from '@/utils/collaboration'
import CollaborationCell from './components/CollaborationCell.vue'
import CollaborationImportDialog from './components/CollaborationImportDialog.vue'
import CollaborationAssignments from './components/CollaborationAssignments.vue'
defineOptions({ name: 'CollaborationPlanView' })
const router = useRouter(); const route = useRoute(); const user = useUserStore(); const workspace = useCollaborationWorkspace()
const options = ref<CollaborationOptions>(); const view = ref<PlanView>('market'); const mode = ref('table')
const keyword = ref(''); const productLineId = ref<number>(); const status = ref(''); const mineOnly = ref(false)
const page = ref(1); const size = ref(50); const focusGroup = ref<FieldGroup | ''>('')
const selectedKey = ref(''); const saving = ref(false); const error = ref('')
const expanded = ref(false); const draftReviewVisible = ref(false)
const drafts = workspace.drafts
const moldSetFilter = ref<number>()
const itemFilter = ref<number>()
const request = useCachedRequest(api.getCollaborationPage)
const rows = computed(() => request.hasCurrentData.value ? request.data.value?.content || [] : [])
const total = computed(() => request.data.value?.totalElements || 0)
const selected = computed(() => rows.value.find(r => rowKey(r) === selectedKey.value) || rows.value[0])
const dirtyCells = computed(() => [...drafts.rows.values()].reduce((sum, d) => sum + d.changes.size, 0))
const fields = computed(() => {
  let all = view.value === 'delivery' ? options.value?.moldFields || [] : options.value?.itemFields || []
  if (view.value === 'market') all = all.filter(f => f.group === 'market' && !['styleName', 'compatibleModels', 'productLineId'].includes(f.key))
  if (view.value === 'production') all = all.filter(f => productionFields.includes(f.key))
  return all.filter(f => !['pcMoldCodeId', 'tpuMoldCodeId', 'pcInventoryId', 'tpuInventoryId', 'setName'].includes(f.key) && (!focusGroup.value || f.group === focusGroup.value))
})
const identityFields = computed(() => view.value === 'market' ? (options.value?.itemFields || []).filter(f => ['styleName','compatibleModels'].includes(f.key)) : [])
const tableFields = computed(() => [...identityFields.value, ...fields.value])
const groupedFields = computed(() => Object.entries(groupNames).map(([group, name]) => ({ group, name, fields: fields.value.filter(f => f.group === group) })).filter(g => g.fields.length))
const statusOptions = computed(() => view.value === 'market' ? ['candidate','linked'] : view.value === 'delivery' ? moldStatuses : ['missing','recorded'])
const editable = (field?: PlanField) => !!field && !!options.value?.writableGroups.includes(field.group)
const dirty = (row: CollaborationRow, field: string) => !!drafts.rows.get(rowKey(row))?.changes.has(field)
const value = (row: CollaborationRow, field: string) => drafts.value(row, field)
const suggestion = (row: CollaborationRow) => suggestedArrivalDate(value(row,'plannedMoldDeliveryDate'))
const needsArrivalReview = (row: CollaborationRow) => !!value(row,'plannedFactoryArrivalDate') && !drafts.rows.get(rowKey(row))?.changes.get('plannedFactoryArrivalDate')?.confirm && !equalCell(row.arrivalConfirmedBasisDate ?? null, value(row,'plannedMoldDeliveryDate'))
let timer: ReturnType<typeof setTimeout> | undefined; let mounted = false; let active = true
function load(force = false) { if (!options.value) return Promise.resolve(); return request.execute({ view: view.value, page: page.value, size: size.value, keyword: keyword.value.trim(), productLineId: productLineId.value, status: status.value, mineOnly: mineOnly.value, ...(itemFilter.value ? {itemId:itemFilter.value} : {}), ...(moldSetFilter.value && view.value==='delivery' ? {moldSetId:moldSetFilter.value} : {}) }, force) }
function downloadPage() { return api.downloadCollaborationTemplate(view.value, { view: view.value, page: page.value, size: size.value, keyword: keyword.value.trim(), productLineId: productLineId.value, status: status.value, mineOnly: mineOnly.value }) }
function reset(debounce = false) { clearTimeout(timer); request.invalidate(); page.value = 1; if (debounce) timer = setTimeout(() => void load(), 300); else void load() }
watch(keyword, () => reset(true), { flush: 'sync' })
watch([productLineId, status, mineOnly, size], () => reset(), { flush: 'sync' })
watch(view, () => { status.value = ''; focusGroup.value = ''; selectedKey.value = ''; reset() })
watch(() => user.token, () => { drafts.clear(); request.clear(); request.data.value = undefined; request.hasCurrentData.value = false; options.value = undefined })
watch(() => workspace.revision, () => { request.clear(); if(active && mounted) void load() }, {flush:'sync'})
function changePage(p: number) { page.value = p; void load() }
async function refresh() {const token=user.token;try {if(!options.value) {const result=await api.getCollaborationOptions();if(token!==user.token)return;options.value=result} error.value = ''; await load(true) } catch {if(token===user.token) error.value = '刷新失败，请检查登录状态后重试' } }
function mapProductLine(row: CollaborationRow, id: number | null) {
  const f = options.value?.itemFields.find(f => f.key === 'productLineId')
  if (!f || !editable(f) || row.projectCount) return
  drafts.set(row, f.key, id)
  const line = options.value?.productLines.find(l => l.productLineId === id)
  if (line) drafts.set(row, 'styleName', line.productName)
}
function edit(row: CollaborationRow, field: PlanField, text: string, confirm = false) {
  if (!editable(field)) return
  try { drafts.set(row, field.key, parseCell(field, text), confirm); if(field.key==='compatibleModels') stageExplicitBrand(row) } catch (e) { ElMessage.warning(e instanceof Error ? e.message : '填写格式不正确') }
}
function stageExplicitBrand(row: CollaborationRow) {
  const brandField = options.value?.itemFields.find(f => f.key === 'brand')
  if (!editable(brandField) || value(row,'brand')) return
  const brand = brandFromModel(String(value(row,'compatibleModels') ?? ''))
  if (brand) drafts.set(row,'brand',brand)
}
function previewCell(row:CollaborationRow,field:PlanField,text:string) {
  if(!editable(field)) return
  try {drafts.set(row,field.key,parseCell(field,text))} catch { /* Validate incomplete typing on blur, not on each keystroke. */ }
}
function paste(row: CollaborationRow, field: PlanField, event: ClipboardEvent) {
  const text = event.clipboardData?.getData('text/plain') || ''
  if (!/[\t\n\r]/.test(text)) return
  event.preventDefault()
  try {
    const cells = parseClipboard(text); const startRow = rows.value.findIndex(r => rowKey(r) === rowKey(row)); const startCol = tableFields.value.findIndex(f => f.key === field.key)
    if (startRow + cells.length > rows.value.length) throw new Error('粘贴超出当前页，请分批粘贴或调整起始行')
    const changes: { row: CollaborationRow; field: PlanField; value: CellValue }[] = []
    cells.forEach((line, ri) => line.forEach((text, ci) => {
      const f = tableFields.value[startCol + ci]
      if (!f || !editable(f)) throw new Error('粘贴范围包含只读列或超出可填写列，请核对起始位置')
      changes.push({ row: rows.value[startRow + ri], field: f, value: parseCell(f, text) })
    }))
    changes.forEach(c => drafts.set(c.row, c.field.key, c.value))
    // Infer only after the whole rectangle is staged, so an explicitly pasted brand takes priority.
    changes.filter(c => c.field.key === 'compatibleModels').forEach(c => stageExplicitBrand(c.row))
    ElMessage.success(`已暂存 ${changes.length} 个单元格，请点击保存`)
  } catch (e) { ElMessage.warning(e instanceof Error ? e.message : '粘贴失败') }
}
async function save() {
  const patches = drafts.patches(); if (!patches.length) return
  if (patches.some(p => p.changes.some(c => ['pcTotal','tpuTotal','finishedTotal'].includes(c.field) && c.before != null && (c.after == null || Number(c.after) < Number(c.before)) && !c.reason))) { ElMessage.warning('下调或清空累计数量，请先在该行填写更正说明'); return }
  saving.value = true; error.value = ''; let saved = 0; let failed = 0
  try {
    for (let n = 0; n < patches.length; n += 100) {
      const submitted = patches.slice(n, n + 100)
      const results = await api.saveCollaborationRows(submitted)
      results.forEach(r => { drafts.apply(r, submitted.find(p => p.id === r.id && p.entityType === r.entityType)); if (r.status === 'saved') saved++; else failed++ })
    }
    if(saved) workspace.changed(); else request.clear(); await load()
    if (saved) ElMessage.success(`已保存 ${saved} 行`)
    if (failed) error.value = `${failed} 行未保存。草稿已保留，请查看待保存区中的错误或冲突。`
    if (failed) draftReviewVisible.value = true
    if (!dirtyCells.value) draftReviewVisible.value = false
  } catch { error.value = '保存未完成，未确认成功的草稿已保留，请重试' }
  finally { saving.value = false }
}
async function discard() { if (!dirtyCells.value) return; try { await ElMessageBox.confirm('撤销所有尚未保存的修改？已保存的数据不会改变。','撤销修改',{ confirmButtonText: '撤销修改', cancelButtonText: '保留' }); drafts.clear(); error.value = '' } catch {} }
const editorVisible = ref(false); const editorRow = ref<CollaborationRow>(); const editorField = ref<PlanField>(); const editorText = ref('')
function openEditor(row: CollaborationRow,field: PlanField) { if(!field.maxLength) return;editorRow.value=row;editorField.value=field;editorText.value=String(value(row,field.key) ?? '');editorVisible.value=true }
function stageEditor() {
  if(!editorRow.value||!editorField.value||!editable(editorField.value)) return
  try { drafts.set(editorRow.value,editorField.value.key,parseCell(editorField.value,editorText.value));if(editorField.value.key==='compatibleModels') stageExplicitBrand(editorRow.value);editorVisible.value=false } catch(e) { ElMessage.warning(e instanceof Error ? e.message : '格式不正确') }
}
function rowAction(command:string,row:CollaborationRow) {
  if(command==='history') void openHistory(row)
  else if(command==='references') void openReferences(row)
  else if(command==='links') void openLinks(row)
  else if(command==='project') void startProject(row)
  else if(command==='mold') void (view.value==='delivery'?openMolds(row):addMold(row))
  else if(command==='reason') void explain(row)
  else if(command==='ledger') void router.push({path:'/molds',query:row.moldSetId ? {moldSetId:row.moldSetId} : {itemId:row.itemId}})
}
async function explain(row: CollaborationRow) {
  const draft = drafts.rows.get(rowKey(row)); if (!draft) return
  try { const result = await ElMessageBox.prompt('填写累计产量更正原因或日期异常核对说明。','填写说明',{ inputType: 'textarea', inputValue: draft.reason, confirmButtonText: '暂存说明', cancelButtonText: '取消' }); draft.reason = result.value.trim() } catch {}
}
function confirmArrival(row: CollaborationRow, suggestion = false) {
  const field = options.value?.moldFields.find(f => f.key === 'plannedFactoryArrivalDate')
  const date = suggestion ? suggestedArrivalDate(value(row,'plannedMoldDeliveryDate')) : value(row, 'plannedFactoryArrivalDate')
  if (field && date) edit(row, field, String(date), true)
}
async function refreshAfterChange() { workspace.changed(); await load() }

const createVisible = ref(false); const creating = ref(false); const phoneOptions = ref<CodeItem[]>([])
const candidate = reactive({ productLineId: null as number | null, styleName: '', brand: '', compatibleModels: '', phoneModelCode: null as string | null, notes: '' })
watch(() => candidate.compatibleModels,model => {if(!candidate.brand && brandFromModel(model)) candidate.brand=brandFromModel(model)!})
async function searchPhone(text = '') { phoneOptions.value = (await getCodeItems({ codeType: 'phone_model', status: 'enabled', keyword: text, page: 1, size: 100 })).content }
function openCreate() { Object.assign(candidate, { productLineId: null, styleName: '', brand: '', compatibleModels: '', phoneModelCode: null, notes: '' }); createVisible.value = true; void searchPhone() }
function chooseLine(id: number | null) { candidate.styleName = options.value?.productLines.find(l => l.productLineId === id)?.productName || candidate.styleName }
function choosePhone(code: string | null) { if (!candidate.compatibleModels.trim()) candidate.compatibleModels = phoneOptions.value.find(c => c.codeValue === code)?.codeName || '' }
async function create() {
  if (!candidate.styleName.trim() || !candidate.compatibleModels.trim()) { ElMessage.warning('请填写款式和兼容手机型号'); return }
  creating.value = true
  try { await api.createCollaborationItem({ ...candidate }); createVisible.value = false; ElMessage.success('市场候选已建档，累计产量仍为空'); await refreshAfterChange() } finally { creating.value = false }
}
async function addMold(row: CollaborationRow) {
  if(row.moldSetCount) {ElMessage.info('已有模具套，请在台账选择来源套复制 / 重新开模，以保留原编码和来源关系');await router.push({path:'/molds',query:{itemId:row.itemId}});return}
  try {
    const result = await ElMessageBox.prompt('建立一套 PC＋TPU 模具，日期由各负责人填写。','新增模具套',{ inputValue: '第 1 套', confirmButtonText: '新增模具套', cancelButtonText: '取消' })
    await api.createCollaborationMold(row.itemId, { setName: result.value }); view.value = 'delivery'; await refreshAfterChange(); ElMessage.success('已新增模具套')
  } catch (e) { if (e !== 'cancel' && e !== 'close') error.value = '新增模具套失败，请重试' }
}
async function startProject(row: CollaborationRow) {
  if (!row.productLineId) { ElMessage.warning('请先给档案指定现有产品线'); return }
  await router.push({ path: '/products/create', query: { collaborationItemId: row.itemId } })
}
const historyVisible = ref(false); const historyRows = ref<PlanHistory[]>([]); const historyPage = ref(1); const historyTotal = ref(0); const historyItem = ref<CollaborationRow>(); const historyLoading = ref(false)
async function openHistory(row: CollaborationRow) { historyItem.value = row; historyPage.value = 1; historyVisible.value = true; await loadHistory() }
async function loadHistory() { if (!historyItem.value) return; historyLoading.value = true; try { const r = await api.getCollaborationHistory(historyItem.value.itemId, historyPage.value); historyRows.value = r.content; historyTotal.value = r.totalElements } finally { historyLoading.value = false } }
function label(field: string) { return [...(options.value?.itemFields || []), ...(options.value?.moldFields || [])].find(f => f.key === field)?.label || ({ __created: '创建档案 / 模具套', projects: '项目关联', arrivalConfirmedBasisDate: '到厂计划确认依据' } as Record<string,string>)[field] || field }
function display(v: unknown) { return v == null ? '—' : typeof v === 'object' ? JSON.stringify(v) : String(v) }

const linksVisible = ref(false); const linkItem = ref<CollaborationRow>(); const projectOptions = ref<ProjectOption[]>([]); const projectIds = ref<number[]>([]); const projectKeyword = ref(''); const confirmCompatibility = ref(false); const linkLoading = ref(false)
async function openLinks(row: CollaborationRow) { linkItem.value = row; projectIds.value = row.projects.map(p => p.projectId); projectKeyword.value = row.compatibleModels.slice(0,128); confirmCompatibility.value = false; linksVisible.value = true; await searchProjects() }
async function searchProjects() { projectOptions.value = await api.getCollaborationProjects(linkItem.value?.productLineId || undefined, projectKeyword.value) }
async function saveLinks() { if (!linkItem.value) return; linkLoading.value = true; try { await api.linkCollaborationProjects(linkItem.value.itemId, projectIds.value, confirmCompatibility.value, linkItem.value.projects.map(p => p.projectId)); linksVisible.value = false; await refreshAfterChange() } finally { linkLoading.value = false } }
function projectRoute(id: number, section?: string) { return { path: '/projects', query: { productId: id, ...(section ? { section } : {}) } } }
const referencesVisible = ref(false); const references = ref<Awaited<ReturnType<typeof api.getCollaborationReferences>>>()
async function openReferences(row: CollaborationRow) { references.value = undefined; referencesVisible.value = true; references.value = await api.getCollaborationReferences(row.itemId) }
const moldVisible = ref(false); const moldItem = ref<CollaborationRow>(); const moldOptions = ref<MoldCodeOption[]>([]); const moldForm = reactive({ pcMoldCodeId: null as number | null, tpuMoldCodeId: null as number | null })
async function openMolds(row: CollaborationRow) { moldItem.value = row; Object.assign(moldForm, { pcMoldCodeId: row.pcMoldCodeId ?? null, tpuMoldCodeId: row.tpuMoldCodeId ?? null }); moldVisible.value = true; moldOptions.value = await api.getCollaborationMoldCodes(row.itemId) }
function stageMolds() { if (!moldItem.value) return; for (const key of ['pcMoldCodeId','tpuMoldCodeId'] as const) drafts.set(moldItem.value, key, moldForm[key]); moldVisible.value = false }
const assignmentsVisible = ref(false)
function openAssignments() { assignmentsVisible.value = true }
async function assignmentsSaved() { options.value = await api.getCollaborationOptions() }
const importVisible = ref(false)
function openImport() { if (dirtyCells.value) { ElMessage.warning('请先保存或撤销当前草稿，再进行导入'); return } importVisible.value = true }
function beforeUnload(event: BeforeUnloadEvent) { if (dirtyCells.value) { event.preventDefault(); event.returnValue = '' } }
onBeforeRouteLeave(async to => { if (!dirtyCells.value) return true; const shared=isCollaborationEntry(to.path);try { await ElMessageBox.confirm(shared?'还有未保存的修改，前往共用模具入口后会保留草稿。':'还有未保存的修改，离开会丢弃这些草稿。','未保存修改',{ confirmButtonText: shared?'保留草稿并前往':'离开并丢弃', cancelButtonText: '继续填写', type: 'warning' }); if(!shared) drafts.clear(); return true } catch { return false } })
function applyRoute() {if(route.path!=='/collaboration-plans') return; if(['market','delivery','production'].includes(String(route.query.view))) view.value=route.query.view as PlanView;itemFilter.value=Number(route.query.itemId)||undefined;moldSetFilter.value=Number(route.query.moldSetId)||undefined;if(mounted) reset()}
watch(()=>route.fullPath,()=>applyRoute())
onMounted(async () => { window.addEventListener('beforeunload', beforeUnload);const token=user.token;try {const result=await api.getCollaborationOptions();if(token!==user.token)return;options.value=result;applyRoute();await load();mounted=true} catch {if(token===user.token) error.value = '页面初始化失败，请刷新重试' } })
onActivated(() => { active=true;if (mounted) void load() })
onDeactivated(() => { active=false;expanded.value=false;clearTimeout(timer); request.invalidate() })
onBeforeUnmount(() => { clearTimeout(timer); window.removeEventListener('beforeunload', beforeUnload) })
</script>

<template>
  <main class="collaboration-plan" :class="{ 'is-expanded': expanded }">
    <header class="plan-head"><div class="title-row"><h2>协作计划</h2><el-popover placement="bottom-start" trigger="click" :width="360"><template #reference><el-button :icon="QuestionFilled" text aria-label="填写说明">填写说明</el-button></template><p>按款式与兼容型号组维护，不按颜色重复累计。蓝色区域可填写，黄色表示待保存；长内容可点 ↗ 展开。</p><p>管理员试用：工作视图仅聚焦字段，不改变登录账号权限。</p></el-popover></div>
      <div class="actions"><el-button :icon="FullScreen" @click="expanded=!expanded">{{ expanded ? '退出宽屏' : '宽屏录入' }}</el-button><el-button :icon="Setting" v-if="options?.administrator" @click="openAssignments">职责配置</el-button><el-button :icon="Refresh" @click="refresh">刷新</el-button><el-button :icon="Plus" type="primary" v-if="options?.writableGroups.includes('market')" @click="openCreate">新增市场候选</el-button></div></header>
    <section class="plan-panel">
      <div class="tab-bar"><el-radio-group v-model="view" size="large"><el-radio-button value="market">市场资料</el-radio-button><el-radio-button value="delivery">模具交付</el-radio-button><el-radio-button value="production">累计产量</el-radio-button></el-radio-group><el-radio-group v-model="mode"><el-radio-button value="table">协作表格</el-radio-button><el-radio-button value="task">待办式录入</el-radio-button></el-radio-group></div>
      <div class="filter-bar"><el-input v-model="keyword" clearable placeholder="搜索款式 / 品牌 / 型号 / 编码" class="search" /><el-select v-model="productLineId" clearable placeholder="全部产品线"><el-option v-for="line in options?.productLines" :key="line.productLineId" :label="line.productName" :value="line.productLineId" /></el-select><el-select v-model="status" clearable placeholder="全部状态"><el-option v-for="s in statusOptions" :key="s" :label="statusNames[s]" :value="s" /></el-select><el-checkbox v-model="mineOnly">待我填写</el-checkbox><span class="record-count">共 {{ total }} {{ view === 'delivery' ? '套模具' : '条档案' }}</span></div>
      <div class="work-bar"><div><el-select v-model="focusGroup" clearable placeholder="工作视图：全部字段"><el-option v-for="g in (view === 'delivery' ? ['engineering','logistics','mexico'] : [view])" :key="g" :label="groupNames[g as FieldGroup]" :value="g" /></el-select><span class="legend"><i class="editable-swatch" />可填写<i class="dirty-swatch" />待保存</span></div><div><el-button :icon="Download" text @click="downloadPage">下载本页模板（含 ID）</el-button><el-button :icon="Upload" text @click="openImport">Excel 导入预览</el-button></div></div>
      <p v-if="view === 'production'" class="view-note">数量为累计产量，不是当前库存。PC 与 TPU 不要求相等，成品仅统计一次；空白表示未知，0 表示已确认零产量。</p>
      <p v-if="view === 'delivery'" class="view-note">一行一套 PC＋TPU 模具。“抵达墨西哥”不等于“到达工厂”；＋7天只是待确认的建议。<el-button link type="primary" @click="router.push('/molds')">打开模具台账</el-button><el-button v-if="moldSetFilter" link @click="moldSetFilter=undefined;reset()">清除模具定位</el-button></p>
      <el-alert v-if="error || request.error.value" :title="error || request.error.value" type="error" :closable="false" />
      <FixedTableViewport v-if="mode === 'table'" v-slot="{ tableHeight }" fill :refresh-key="rows">
        <el-table :data="rows" :height="tableHeight" v-loading="request.loading.value" border :row-key="rowKey" class="plan-table">
          <el-table-column fixed="left" label="款式 / 兼容手机型号" :width="view === 'market' ? 310 : 290"><template #default="{ row }"><div class="identity-cell" :data-row="row.itemId">
            <template v-if="view === 'market'"><label v-for="f in identityFields" :key="f.key" class="identity-field"><small>{{ f.key === 'styleName' ? '款式' : '兼容手机型号' }}</small><CollaborationCell :field="f" :value="value(row, f.key)" :editable="editable(f)" :dirty="dirty(row,f.key)" compact expandable @preview="previewCell(row,f,$event)" @edit="edit(row,f,$event)" @paste="paste(row,f,$event)" @expand="openEditor(row,f)" /></label><select v-if="!row.projectCount && options?.writableGroups.includes('market')" class="line-mapping" aria-label="关联产品线" :value="value(row,'productLineId') ?? ''" @change="mapProductLine(row, ($event.target as HTMLSelectElement).value ? Number(($event.target as HTMLSelectElement).value) : null)"><option value="">产品线待映射</option><option v-for="l in options.productLines" :key="l.productLineId" :value="l.productLineId">{{ l.productName }}</option></select></template>
            <template v-else><strong>{{ row.styleName }}</strong><span>{{ row.compatibleModels }}</span><small>{{ row.brand || '品牌未填写' }}<template v-if="row.setName"> · {{ row.setName }}</template></small></template>
            <div class="identity-meta"><el-tag :type="['linked','mexico_arrived','recorded'].includes(row.status) ? 'success' : 'info'" size="small">{{ statusNames[row.status] }}</el-tag><small>{{ row.projectCount }} 个项目<template v-if="view === 'market' && row.productLineName"> · {{ row.productLineName }}</template></small></div>
          </div></template></el-table-column>
          <el-table-column v-for="g in groupedFields" :key="g.group" :label="g.name" align="center" :class-name="`owner-${g.group}`">
            <el-table-column v-for="f in g.fields" :key="f.key" :label="f.label" :min-width="['notes','productionNotes','salesPlatform','referenceUrl'].includes(f.key) ? 280 : f.kind === 'date' ? 194 : 160"><template #default="{ row }"><CollaborationCell :field="f" :users="options?.users" :value="value(row,f.key)" :editable="editable(f)" :dirty="dirty(row,f.key)" compact expandable @preview="previewCell(row,f,$event)" @edit="edit(row,f,$event)" @paste="paste(row,f,$event)" @expand="openEditor(row,f)" />
              <div v-if="f.key === 'plannedFactoryArrivalDate'" class="arrival-hint"><template v-if="!value(row,f.key) && suggestion(row)"><span>建议 {{ suggestion(row) }}</span><button v-if="editable(f)" @click="confirmArrival(row,true)">采用并确认</button></template><template v-else-if="needsArrivalReview(row)"><span class="warning-text">交付计划变化，需重新核对</span><button v-if="editable(f)" @click="confirmArrival(row)">确认当前日期</button></template></div>
            </template></el-table-column>
          </el-table-column>
          <el-table-column fixed="right" label="操作" width="76" align="center"><template #default="{ row }"><el-dropdown trigger="click" @command="rowAction($event,row)"><el-button text :icon="MoreFilled" :aria-label="`操作 ${row.compatibleModels}`" /><template #dropdown><el-dropdown-menu><el-dropdown-item command="ledger">打开模具台账</el-dropdown-item><el-dropdown-item command="history">修改历史</el-dropdown-item><el-dropdown-item command="references">项目 / 物流 / 文件</el-dropdown-item><el-dropdown-item v-if="view === 'market' && options?.writableGroups.includes('market')" command="links">关联项目</el-dropdown-item><el-dropdown-item v-if="view === 'market' && !row.projectCount && options?.writableGroups.includes('market')" command="project">沿用现有立项</el-dropdown-item><el-dropdown-item v-if="options?.writableGroups.includes('engineering')" command="mold">{{ view === 'delivery' ? '关联模具编码' : '新增模具套' }}</el-dropdown-item><el-dropdown-item v-if="drafts.rows.has(rowKey(row))" command="reason">更正 / 核对说明</el-dropdown-item></el-dropdown-menu></template></el-dropdown></template></el-table-column>
          <template #empty><div class="empty-plan">{{ view === 'delivery' ? '暂无模具套。可在市场资料中为档案新增一套，或导入交付表并确认映射。' : '暂无匹配档案。可新增市场候选，或调整筛选。' }}</div></template>
        </el-table>
      </FixedTableViewport>
      <div v-else class="task-layout">
        <aside><button v-for="row in rows" :key="rowKey(row)" :class="{ active: rowKey(selected || row) === rowKey(row) }" @click="selectedKey = rowKey(row)"><strong>{{ row.compatibleModels }}</strong><span>{{ row.styleName }} · {{ row.setName || statusNames[row.status] }}</span></button><el-empty v-if="!rows.length" description="暂无匹配记录" /></aside>
        <article v-if="selected" class="task-form">
          <h3>{{ selected.compatibleModels }}</h3><p>{{ selected.styleName }}<template v-if="selected.setName"> · {{ selected.setName }}</template></p>
          <label v-if="view === 'market' && !selected.projectCount && options?.writableGroups.includes('market')" class="task-line"><span>关联产品线（可暂不关联）</span><select aria-label="关联产品线" :value="value(selected,'productLineId') ?? ''" @change="mapProductLine(selected, ($event.target as HTMLSelectElement).value ? Number(($event.target as HTMLSelectElement).value) : null)"><option value="">产品线待映射</option><option v-for="l in options.productLines" :key="l.productLineId" :value="l.productLineId">{{ l.productName }}</option></select></label>
          <section v-for="g in groupedFields" :key="g.group"><h4>{{ g.name }}</h4><div class="task-fields"><label v-for="f in [...(g.group === 'market' ? identityFields : []),...g.fields]" :key="f.key" :class="{ 'wide-field': ['notes','productionNotes','referenceUrl','compatibleModels'].includes(f.key) }"><span>{{ f.label }}</span><CollaborationCell :field="f" :users="options?.users" :value="value(selected,f.key)" :editable="editable(f)" :dirty="dirty(selected,f.key)" expandable @preview="previewCell(selected,f,$event)" @edit="edit(selected,f,$event)" @expand="openEditor(selected,f)" />
            <div v-if="f.key === 'plannedFactoryArrivalDate'" class="arrival-hint"><template v-if="!value(selected,f.key) && suggestion(selected)"><span>建议 {{ suggestion(selected) }}</span><button v-if="editable(f)" @click.prevent="confirmArrival(selected,true)">采用并确认</button></template><template v-else-if="needsArrivalReview(selected)"><span class="warning-text">交付计划变化，需重新核对</span><button v-if="editable(f)" @click.prevent="confirmArrival(selected)">确认当前日期</button></template></div>
          </label></div></section>
          <div class="actions"><el-button @click="openHistory(selected)">修改历史</el-button><el-button @click="openReferences(selected)">项目 / 物流 / 文件</el-button><el-button v-if="drafts.rows.has(rowKey(selected))" @click="explain(selected)">填写更正 / 核对说明</el-button><el-button @click="selectedKey = rowKey(rows[(rows.findIndex(r => rowKey(r) === rowKey(selected!)) + 1) % rows.length])">下一条</el-button></div>
        </article>
      </div>
      <el-pagination :current-page="page" v-model:page-size="size" :page-sizes="[20,50,100]" :total="total" layout="total, sizes, prev, pager, next, jumper" @current-change="changePage" />
    </section>
    <section v-if="dirtyCells" class="save-dock"><div><strong>{{ dirtyCells }} 个单元格待保存</strong><span>{{ drafts.rows.size }} 行 · 修改尚未写入数据库</span></div><div class="actions"><el-button @click="draftReviewVisible=true">查看草稿 / 填写说明</el-button><el-button @click="discard">撤销未保存修改</el-button><el-button data-test="save-plans" type="primary" :loading="saving" @click="save">保存全部修改</el-button></div></section>
    <el-drawer v-model="draftReviewVisible" title="待保存修改与冲突核对" size="min(760px,95vw)"><section class="draft-review"><div v-for="[key,d] in drafts.rows" :key="key"><strong>{{ d.source.styleName }} / {{ d.source.compatibleModels }} {{ d.source.setName || '' }}</strong><button @click="explain(d.source)">{{ d.reason ? '说明：' + d.reason : '填写更正 / 核对说明' }}</button><p v-if="!d.result" class="view-note">{{ d.changes.size }} 个修改字段待保存</p><p v-if="d.result" class="warning-text">{{ d.result.message }}</p><div v-for="c in d.result?.conflicts" :key="c.field" class="conflict-row"><strong>{{ c.label }}</strong><span>原值 {{ display(c.before) }} → 当前 {{ display(c.current) }}；我的修改 {{ display(c.attempted) }}</span><el-button size="small" @click="drafts.resolve(key,c.field,false)">采用当前值</el-button><el-button size="small" type="warning" @click="drafts.resolve(key,c.field,true)">确认保留我的修改</el-button></div></div></section><template #footer><el-button @click="draftReviewVisible=false">返回继续录入</el-button><el-button type="primary" :loading="saving" :disabled="!dirtyCells" @click="save">保存已核对修改</el-button></template></el-drawer>

    <el-dialog v-model="editorVisible" :title="`${editable(editorField!) ? '展开编辑' : '查看'} · ${editorField?.label || ''}`" width="min(1000px,94vw)" :close-on-click-modal="false"><p class="view-note">{{ editorRow?.styleName }} / {{ editorRow?.compatibleModels }} · 此处确认后仍是草稿，需点击“保存全部修改”才写入数据库。</p><el-input v-model="editorText" type="textarea" :autosize="{minRows:8,maxRows:18}" :maxlength="editorField?.maxLength || undefined" show-word-limit :readonly="!editorField || !editable(editorField)" :aria-label="editorField?.label" /><template #footer><el-button @click="editorVisible=false">{{ editorField && editable(editorField) ? '取消' : '关闭' }}</el-button><el-button v-if="editorField && editable(editorField)" type="primary" @click="stageEditor">暂存此格修改</el-button></template></el-dialog>

    <el-dialog v-model="createVisible" title="新增市场候选" width="640px" destroy-on-close><el-form label-position="top" class="form-grid"><el-form-item label="关联现有产品线（可暂不关联）"><el-select v-model="candidate.productLineId" clearable @change="chooseLine"><el-option v-for="l in options?.productLines" :key="l.productLineId" :label="l.productName" :value="l.productLineId" /></el-select></el-form-item><el-form-item label="产品款式" required><el-input v-model="candidate.styleName" maxlength="255" /></el-form-item><el-form-item label="品牌"><el-input v-model="candidate.brand" maxlength="128" /></el-form-item><el-form-item label="手机型号编码（可待确认）"><el-select v-model="candidate.phoneModelCode" clearable filterable remote :remote-method="searchPhone" @change="choosePhone"><el-option v-for="p in phoneOptions" :key="p.codeItemId" :label="`${p.codeValue} / ${p.codeName}`" :value="p.codeValue" /></el-select></el-form-item><el-form-item label="兼容手机型号" required><el-input v-model="candidate.compatibleModels" maxlength="512" /></el-form-item><el-form-item label="备注"><el-input v-model="candidate.notes" type="textarea" /></el-form-item></el-form><template #footer><el-button @click="createVisible=false">取消</el-button><el-button type="primary" :loading="creating" @click="create">建立档案</el-button></template></el-dialog>
    <el-drawer v-model="historyVisible" title="修改历史" size="700px"><p>{{ historyItem?.styleName }} / {{ historyItem?.compatibleModels }}</p><el-table :data="historyRows" v-loading="historyLoading"><el-table-column label="字段" width="140"><template #default="{row}">{{ label(row.fieldName) }}<small class="linked-count">{{ row.entityType === 'mold_set' ? '模具套 ' + row.entityId : '档案' }}</small></template></el-table-column><el-table-column label="原值 → 新值" min-width="220"><template #default="{row}"><span class="history-value">{{ display(row.before) }} → {{ display(row.after) }}</span><small class="linked-count">{{ row.reason }}</small></template></el-table-column><el-table-column prop="actorName" label="填写人" width="110" /><el-table-column prop="changedAt" label="时间" width="180" /></el-table><el-pagination v-model:current-page="historyPage" :page-size="20" :total="historyTotal" layout="prev,pager,next" @current-change="loadHistory" /></el-drawer>
    <el-dialog v-model="linksVisible" title="关联已有型号项目" width="850px"><p>可以关联同款同型号的多个颜色项目。累计产量只维护在这一条档案上，不修改历史项目。</p><div class="actions"><el-input v-model="projectKeyword" placeholder="搜索项目 / 型号" @keyup.enter="searchProjects" /><el-button @click="searchProjects">搜索</el-button></div><p>已选择 {{ projectIds.length }} 个项目</p><el-table :data="projectOptions" height="330"><el-table-column label="选择" width="65"><template #default="{row}"><el-checkbox v-model="projectIds" :value="row.projectId" :disabled="!!row.linkedItemId && row.linkedItemId !== linkItem?.itemId" /></template></el-table-column><el-table-column prop="productCode" label="项目编码" width="150" /><el-table-column prop="model" label="型号" /><el-table-column prop="color" label="颜色" width="100" /><el-table-column label="已关联" width="100"><template #default="{row}">{{ row.linkedItemId ? '档案 ' + row.linkedItemId : '未关联' }}</template></el-table-column></el-table><el-checkbox v-model="confirmCompatibility">已人工确认所选项目属于这个兼容型号组（名称不同也适配）</el-checkbox><template #footer><el-button @click="linksVisible=false">取消</el-button><el-button type="primary" :loading="linkLoading" @click="saveLinks">保存项目关联</el-button></template></el-dialog>
    <el-drawer v-model="referencesVisible" title="关联项目、文件与物流" size="600px"><p>{{ references?.item.styleName }} / {{ references?.item.compatibleModels }}</p><h4>已有项目</h4><div v-for="p in references?.item.projects" :key="p.projectId" class="reference-row"><span>{{ p.productCode }} / {{ p.color || '未标颜色' }}</span><el-button link type="primary" @click="router.push(projectRoute(p.projectId))">打开工作台</el-button><el-button link @click="router.push(projectRoute(p.projectId,'materials'))">文件 / 附件</el-button></div><h4>历史物流（只读引用）</h4><p class="view-note">不会把流程确认时间填成实际发模日期，也不自动同步新表日期。</p><div v-for="e in references?.expressRecords" :key="e.projectId + e.trackingNo" class="reference-row"><span>{{ e.trackingNo }} · {{ e.shippedAt || '未填发模时间' }} · {{ e.latestStatusText }}</span><el-button link type="primary" @click="router.push(projectRoute(e.projectId))">查看原记录</el-button></div><el-empty v-if="references && !references.expressRecords.length" description="暂无历史物流记录" /></el-drawer>
    <el-dialog v-model="moldVisible" title="关联 PC / TPU 模具编码" width="600px"><p>仅引用已有项目或产品线的模具编码，不转移原编码的归属。</p><el-form label-position="top"><el-form-item v-for="part in ['pcMoldCodeId','tpuMoldCodeId'] as const" :key="part" :label="part.startsWith('pc') ? 'PC 模具编码' : 'TPU 模具编码'"><el-select v-model="moldForm[part]" clearable filterable><el-option v-for="m in moldOptions" :key="m.moldCodeId" :label="m.moldCode + ' / ' + (m.moldName || '')" :value="m.moldCodeId" /></el-select></el-form-item></el-form><template #footer><el-button @click="moldVisible=false">取消</el-button><el-button type="primary" @click="stageMolds">暂存到当前模具套</el-button></template></el-dialog>
    <CollaborationAssignments v-model="assignmentsVisible" @saved="assignmentsSaved" />
    <CollaborationImportDialog v-if="options" v-model="importVisible" :kind="view" :options="options" @imported="refreshAfterChange" />
  </main>
</template>

<style scoped>
.collaboration-plan { min-width:0; color:#25364a; }.plan-head,.actions,.tab-bar,.filter-bar,.work-bar,.save-dock,.reference-row { display:flex; align-items:center; gap:12px; }.plan-head { justify-content:space-between; align-items:flex-start; margin-bottom:18px; }.eyebrow { color:#718097; font-size:12px; margin-bottom:6px; }h2 { font-size:24px; margin:0 0 7px; letter-spacing:-.4px; }.plan-head p { margin:0; color:#718097; font-size:13px; }.actions { flex-wrap:wrap; }.pilot-note { display:flex; gap:10px; align-items:center; margin-bottom:16px; padding:10px 14px; background:#eff4fc; color:#62738b; border-radius:8px; font-size:12px; }.pilot-tag { background:#dce7fb; color:#3963a0; border-radius:4px; padding:3px 7px; flex:none; }.plan-panel { background:#fff; border:1px solid #e2e8f0; border-radius:10px; padding:18px; }.tab-bar,.work-bar { justify-content:space-between; }.tab-bar { padding-bottom:16px; border-bottom:1px solid #e9eef5; }.filter-bar { flex-wrap:wrap; margin:17px 0 12px; }.filter-bar .search { width:290px; }.filter-bar .el-select { width:170px; }.record-count { margin-left:auto; color:#728095; font-size:13px; }.work-bar { margin-bottom:10px; }.work-bar > div { display:flex; gap:12px; align-items:center; }.work-bar .el-select { width:210px; }.legend { color:#7c889a; font-size:12px; display:flex; gap:7px; align-items:center; }.legend i { width:10px; height:10px; border-radius:2px; display:inline-block; }.editable-swatch { background:#dce8ff; }.dirty-swatch { background:#f5da87; }.view-note { color:#7c889a; font-size:12px; margin:8px 0 14px; }.identity-cell { display:flex; flex-direction:column; gap:5px; padding:4px 0; }.identity-cell strong { color:#28476c; }.identity-cell small,.linked-count { color:#8995a6; font-size:11px; }.linked-count { display:block; margin-top:5px; }.row-actions { display:flex; flex-wrap:wrap; gap:5px 10px; }.row-actions button,.arrival-hint button,.draft-review button { border:0; padding:0; background:none; color:#4478c7; font:inherit; font-size:12px; cursor:pointer; text-align:left; }.arrival-hint { display:flex; flex-direction:column; gap:4px; font-size:11px; color:#7789a0; margin-top:5px; }.warning-text { color:#b27914; }.empty-plan { padding:36px; line-height:1.7; }.el-pagination { margin-top:17px; }.save-dock { position:sticky; bottom:0; z-index:10; justify-content:space-between; background:#edf4ff; border:1px solid #cfdffd; padding:14px 18px; border-radius:9px; margin-top:12px; box-shadow:0 -4px 16px #263f6410; }.save-dock span { display:block; color:#718198; font-size:12px; margin-top:4px; }.draft-review { font-size:12px; background:#fff; padding:14px; border-radius:8px; margin-top:10px; }.draft-review > div { padding:8px 0; border-bottom:1px solid #eef1f6; }.draft-review button { margin-left:12px; }.conflict-row { display:flex; flex-wrap:wrap; align-items:center; gap:8px; margin-top:8px; padding:9px; background:#fff6df; }.task-layout { display:grid; grid-template-columns:260px minmax(0,1fr); gap:18px; min-height:380px; margin-top:14px; }.task-layout aside { max-height:540px; overflow:auto; border:1px solid #e3e9f2; border-radius:8px; }.task-layout aside button { display:flex; flex-direction:column; gap:8px; border:0; border-bottom:1px solid #e9eef5; background:#fff; width:100%; padding:17px; text-align:left; cursor:pointer; color:#384d68; }.task-layout aside span { color:#8795a6; font-size:12px; }.task-layout aside button.active { background:#edf4ff; box-shadow:inset 3px 0 #4a7fe4; }.task-form { padding:8px 16px; }.task-form h3 { margin:0 0 5px; }.task-form > p { color:#8090a5; font-size:13px; }.task-form section { border-top:1px solid #e9eef4; padding:12px 0; }.task-form h4 { margin:0 0 12px; color:#416592; }.task-fields,.form-grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:12px 20px; }.task-fields label > span { display:block; font-size:12px; color:#76879c; margin-bottom:6px; }.reference-row { justify-content:space-between; flex-wrap:wrap; padding:10px 0; border-bottom:1px solid #edf0f4; }.history-value { display:block; max-height:90px; overflow:auto; white-space:pre-wrap; overflow-wrap:anywhere; font-size:12px; }.plan-table :deep(th.el-table__cell) { background:#f1f5fa; color:#5e7491; }.plan-table :deep(.owner-engineering) { background:#f6f9ff; }.plan-table :deep(.owner-logistics) { background:#f3fafb; }.plan-table :deep(.owner-mexico) { background:#f6f8ff; }.plan-table :deep(.cell) { padding:7px 10px; }.el-form .el-select { width:100%; }
.line-mapping,.task-line select { width:100%; color:#385270; border:1px solid #dce6f5; background:#f0f6ff; border-radius:5px; padding:7px; font:inherit; }.task-line { display:block; margin:12px 0; font-size:12px; }.task-line span { display:block; margin-bottom:6px; color:#76879c; }
.collaboration-plan { display:flex; flex-direction:column; gap:10px; height:100%; min-height:0; overflow:hidden; }
.collaboration-plan.is-expanded { position:fixed; inset:0; z-index:100; height:100dvh; background:#f0f4f8; padding:14px; box-sizing:border-box; }
.plan-head { flex:none; margin:0; min-height:34px; align-items:center; gap:12px; }
.title-row { display:flex; align-items:center; flex-shrink:0; gap:8px; }.title-row h2 { font-size:20px; margin:0; white-space:nowrap; }
.plan-panel { flex:1; min-height:0; display:flex; flex-direction:column; padding:12px 14px; }
.tab-bar { flex:none; padding-bottom:10px; }.filter-bar { flex:none; gap:10px; margin:10px 0; }.filter-bar .search { flex:1; min-width:190px; max-width:400px; }.filter-bar .el-select { width:148px; }
.work-bar { flex:none; margin-bottom:8px; }.view-note { flex:none; margin:3px 0 8px; }.plan-panel > .el-pagination { flex:none; margin-top:10px; }
.identity-cell { gap:5px; padding:2px 0; }.identity-field { display:block; }.identity-field > small { display:none; }.identity-meta { display:flex; align-items:center; gap:8px; flex-wrap:wrap; }
.identity-cell :deep(.plan-cell) { min-height:34px; }.identity-cell :deep(input) { padding:5px 0; line-height:22px; }
.plan-table :deep(td.el-table__cell) { padding:3px 0; }
.plan-table :deep(th.el-table__cell) { padding:5px 0; }.plan-table :deep(.cell) { padding:6px 9px; }
.task-layout { flex:1; min-height:0; grid-template-columns:230px minmax(0,1fr); margin-top:4px; }.task-layout aside { max-height:none; min-height:0; }.task-form { min-height:0; overflow:auto; padding:10px 18px; }.task-fields { gap:18px 24px; }.wide-field { grid-column:1/-1; }
.save-dock { flex:none; position:static; margin:0; padding:10px 14px; }.draft-review { margin:0; padding:0; }.draft-review > div { padding:15px 0; }
@media(max-width:900px) { .plan-head { flex-wrap:wrap; gap:8px; }.work-bar { flex-wrap:wrap; gap:6px; }.work-bar .el-select { width:160px; }.tab-bar { gap:10px; flex-wrap:wrap; }.task-layout { grid-template-columns:190px minmax(0,1fr); }.task-fields { grid-template-columns:1fr; } }
@media(max-width:700px) { .collaboration-plan.is-expanded { padding:8px; }.plan-panel { padding:8px; }.record-count { margin-left:0; }.task-layout,.task-fields,.form-grid { grid-template-columns:1fr; }.task-layout aside { max-height:120px; }.save-dock { flex-direction:column; align-items:stretch; gap:8px; }.title-row h2 { font-size:18px; } }
</style>
