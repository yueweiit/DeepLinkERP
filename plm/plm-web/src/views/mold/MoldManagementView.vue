<script setup lang="ts">
import { computed, onActivated, onBeforeUnmount, onDeactivated, onMounted, reactive, ref, watch } from 'vue'
import { onBeforeRouteLeave, useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, Refresh, Download, Upload, FullScreen } from '@element-plus/icons-vue'
import * as api from '@/api/modules/molds'
import * as collaboration from '@/api/modules/collaboration'
import { useUserStore } from '@/stores/user'
import { useCollaborationWorkspace } from '@/stores/collaborationWorkspace'
import { useCachedRequest } from '@/composables/useCachedRequest'
import FixedTableViewport from '@/components/FixedTableViewport/index.vue'
import CollaborationCell from '@/views/collaboration/components/CollaborationCell.vue'
import CollaborationImportDialog from '@/views/collaboration/components/CollaborationImportDialog.vue'
import MoldSourceCodes from './components/MoldSourceCodes.vue'
import type { CellValue, CollaborationOptions, CollaborationRow, MoldCodeOption, PlanField, PlanHistory, PlanQuery, RowResult } from '@/types/collaboration'
import { acceptanceNames, equalCell, groupNames, isCollaborationEntry, locationNames, moldStatuses, parseCell, rowKey, statusNames, suggestedArrivalDate, validateMoldRow } from '@/utils/collaboration'
defineOptions({ name: 'MoldManagementView' })
const user = useUserStore(), workspace = useCollaborationWorkspace(), drafts = workspace.drafts
const route = useRoute(), router = useRouter()
const options = ref<CollaborationOptions>(), keyword = ref(''), productLineId = ref<number>(), status = ref(''), location = ref(''), mineOnly = ref(false)
const page = ref(1), size = ref(50), expanded = ref(false), error = ref(''), saving = ref(false)
const sourceVisible = ref(false), sourceVisited = ref(false)
function openSources() { sourceVisited.value = true; sourceVisible.value = true }
const itemFilter = ref<number>(), setFilter = ref<number>()
const request = useCachedRequest(api.getMolds)
const rows = computed(() => request.hasCurrentData.value ? request.data.value?.content || [] : [])
const total = computed(() => request.data.value?.totalElements || 0)
const moldDrafts = computed(() => [...drafts.rows].filter(([,d]) => !!d.source.moldSetId))
const dirtyCount = computed(() => moldDrafts.value.reduce((n,[,d]) => n + d.changes.size, 0))
const parts = ['pc','tpu'] as const
const value = (row: CollaborationRow, key: string) => drafts.value(row,key)
const dirty = (row: CollaborationRow, key: string) => !!drafts.rows.get(rowKey(row))?.changes.has(key)
const can = (f: PlanField) => !!options.value?.writableGroups.includes(f.group)
const engineer = computed(() => !!options.value?.writableGroups.includes('engineering'))
const field = (key: string) => options.value?.moldFields.find(f => f.key === key)
const setFields = computed(() => (options.value?.moldFields || []).filter(f => !f.key.startsWith('pc') && !f.key.startsWith('tpu')))
const partFields = (prefix: string) => (options.value?.moldFields || []).filter(f => f.key.startsWith(prefix) && !f.key.endsWith('MoldCodeId') && !f.key.endsWith('InventoryId'))
function display(v: unknown) { return v == null || v === '' ? '未填写' : typeof v === 'object' ? JSON.stringify(v) : String(v) }
function code(row: CollaborationRow, prefix: string) {
  const id = value(row,prefix+'MoldCodeId')
  return id ? codeOptions.value.find(c=>c.moldCodeId===id)?.moldCode || row[prefix+'CatalogMoldCode'] || value(row,prefix+'OriginalMoldCode') : value(row,prefix+'OriginalMoldCode')
}
function locationText(row: CollaborationRow, prefix: string) { return locationNames[String(value(row,prefix+'CurrentLocation') || 'unknown')] }
function query(): PlanQuery { return { view:'delivery',page:page.value,size:size.value,keyword:keyword.value.trim(),productLineId:productLineId.value,status:status.value,location:location.value || undefined,mineOnly:mineOnly.value,itemId:itemFilter.value,moldSetId:setFilter.value } }
let timer: ReturnType<typeof setTimeout> | undefined, mounted = false, active = true
function load(force=false) { return options.value ? request.execute(query(),force) : Promise.resolve() }
function reset(debounce=false) { clearTimeout(timer); request.invalidate();page.value=1;if(debounce) timer=setTimeout(()=>void load(),300);else void load() }
watch(keyword,()=>reset(true),{flush:'sync'})
watch([productLineId,status,location,mineOnly,size],()=>reset(),{flush:'sync'})
watch(()=>workspace.revision,()=>{request.clear();if(active && mounted) void load()},{flush:'sync'})
watch(()=>user.token,()=>{detailGeneration++;searchGeneration++;inventoryGeneration++;request.clear();request.data.value=undefined;request.hasCurrentData.value=false;options.value=undefined;detail.value=undefined;detailVisible.value=false;codeOptions.value=[];historyRows.value=[];reference.value=undefined;inventoryRows.value=[];inventoryVisible.value=false;createTargets.value=[];createVisible.value=false;editorVisible.value=false;reviewVisible.value=false;importVisible.value=false},{flush:'sync'})
async function refresh() {const token=user.token;try {const result=await api.getMoldOptions();if(token!==user.token) return;options.value=result;error.value='';await load(true);if(detail.value) await openDetail(detail.value.moldSetId!)} catch {if(token===user.token) error.value='刷新失败，请检查登录状态后重试'} }
function changePage(n:number) {page.value=n;void load()}
function edit(row:CollaborationRow,f:PlanField,text:string,quiet=false,confirm=false) {
  if(!can(f)) return
  try {drafts.set(row,f.key,parseCell(f,text),confirm)} catch(e) {if(!quiet) ElMessage.warning(e instanceof Error?e.message:'填写格式不正确')}
}
function confirmArrival(row:CollaborationRow,suggested=false) {
  const f=field('plannedFactoryArrivalDate'),date=suggested?suggestedArrivalDate(value(row,'plannedMoldDeliveryDate')):value(row,'plannedFactoryArrivalDate')
  if(f && date) edit(row,f,String(date),false,true)
}
function arrivalReview(row:CollaborationRow) {return !!value(row,'plannedFactoryArrivalDate') && !drafts.rows.get(rowKey(row))?.changes.get('plannedFactoryArrivalDate')?.confirm && !equalCell(row.arrivalConfirmedBasisDate ?? null,value(row,'plannedMoldDeliveryDate'))}
async function afterChange() {workspace.changed();await load()}
const reviewVisible = ref(false)
async function save() {
  const patches = drafts.patches().filter(p=>p.entityType==='mold_set');if(!patches.length) return
  saving.value=true;error.value='';let saved=0,failed=0
  try {
    for(let n=0;n<patches.length;n+=100) {
      const submitted=patches.slice(n,n+100)
      // Keep invalid rows staged while valid rows remain independently saveable.
      const valid=submitted.filter(p=>{
        const d=drafts.rows.get(`mold_set:${p.id}`)!;const message=validateMoldRow(d.source,key=>value(d.source,key))
        if(!message) return true
        d.result={entityType:'mold_set',id:p.id,status:'invalid',message,conflicts:[],row:null};failed++;return false
      })
      const results:RowResult[]=valid.length?await api.saveMolds(valid):[]
      results.forEach(r=>{drafts.apply(r,valid.find(p=>p.id===r.id));if(detail.value?.moldSetId===r.id && r.row) detail.value=r.row;if(r.status==='saved') saved++;else failed++})
    }
    if(saved) {await afterChange();ElMessage.success(`已保存 ${saved} 套模具`)} else if(failed) {request.clear();await load()}
    if(failed) {error.value=`${failed} 套未保存，草稿已保留，请核对错误或冲突。`;reviewVisible.value=true}
    else reviewVisible.value=false
  } catch {error.value='保存未完成，未确认成功的草稿已保留，请重试'} finally {saving.value=false}
}
async function discard() {
  if(!dirtyCount.value) return
  try {await ElMessageBox.confirm('撤销两页中尚未保存的模具修改？市场资料和累计产量草稿不受影响。','撤销模具草稿',{confirmButtonText:'撤销修改',cancelButtonText:'保留'});moldDrafts.value.forEach(([key])=>drafts.rows.delete(key));error.value=''} catch {}
}
async function explain(row:CollaborationRow) {
  const d=drafts.rows.get(rowKey(row));if(!d) return
  try {const result=await ElMessageBox.prompt('填写日期异常核对、历史资料确认或更正原因。','修改说明',{inputType:'textarea',inputValue:d.reason,confirmButtonText:'暂存说明',cancelButtonText:'取消'});d.reason=result.value.trim()} catch {}
}
const detailVisible=ref(false), detail=ref<CollaborationRow>(), detailLoading=ref(false), detailTab=ref('entry'), codeOptions=ref<MoldCodeOption[]>([])
let detailGeneration=0
async function openDetail(id:number) {
  const generation=++detailGeneration;detailVisible.value=true;detailLoading.value=true;detailTab.value='entry';detail.value=undefined;codeOptions.value=[];error.value=''
  try {const row=await api.getMold(id);if(generation!==detailGeneration) return;detail.value=row;const codes=await collaboration.getCollaborationMoldCodes(row.itemId);if(generation===detailGeneration) codeOptions.value=codes} catch {if(generation===detailGeneration) error.value='模具详情加载失败，请重试'} finally {if(generation===detailGeneration) detailLoading.value=false}
}
const historyRows=ref<PlanHistory[]>([]),historyPage=ref(1),historyTotal=ref(0),reference=ref<Awaited<ReturnType<typeof api.getMoldReferences>>>(),auxLoading=ref(false)
watch(detailTab,async tab=>{if(!detail.value) return;const id=detail.value.moldSetId!;auxLoading.value=true;try {if(tab==='history') {historyPage.value=1;historyRows.value=[];await loadHistory()}if(tab==='references') {reference.value=undefined;const r=await api.getMoldReferences(id);if(detail.value?.moldSetId===id) reference.value=r}} catch {error.value='关联资料或历史加载失败，请重试'} finally {auxLoading.value=false}})
async function loadHistory() {if(!detail.value) return;const id=detail.value.moldSetId!,r=await api.getMoldHistory(id,historyPage.value);if(detail.value?.moldSetId===id){historyRows.value=r.content;historyTotal.value=r.totalElements}}
function label(key:string) {return field(key)?.label || ({__created:'创建 / 复制模具套',arrivalConfirmedBasisDate:'到厂计划确认依据'} as Record<string,string>)[key] || key}
function projectRoute(id:number,section?:string) {return {path:'/projects',query:{productId:id,...(section?{section}:{})}}}
function collaborationRoute(row?:CollaborationRow) {return router.push({path:'/collaboration-plans',query:{view:'delivery',...(row?.moldSetId?{moldSetId:row.moldSetId}:{})}})}
const createVisible=ref(false),createBusy=ref(false),createTargets=ref<CollaborationRow[]>([]),createItemId=ref<number>(),createName=ref(''),copySource=ref<CollaborationRow>()
let searchGeneration=0
async function searchItems(text='') {const gen=++searchGeneration;const r=await collaboration.getCollaborationPage({view:'market',page:1,size:50,keyword:text});if(gen===searchGeneration) createTargets.value=r.content}
function openCreate() {copySource.value=undefined;createItemId.value=itemFilter.value;createName.value='';createVisible.value=true;void searchItems()}
function openCopy(row:CollaborationRow) {if(drafts.rows.has(rowKey(row))) {ElMessage.warning('请先保存或撤销来源套的草稿，再复制已保存资料');return}copySource.value=row;createName.value='';createVisible.value=true}
async function create() {
  if(!copySource.value && !createItemId.value) {ElMessage.warning('请选择已有款式与兼容型号档案');return}
  createBusy.value=true
  try {const row=copySource.value?await api.copyMold(copySource.value.moldSetId!,createName.value):await api.createMold(createItemId.value!,createName.value);createVisible.value=false;setFilter.value=undefined;page.value=1;await afterChange();await openDetail(row.moldSetId!);ElMessage.success(`已建立 ${row.assetNumber}，日期、位置和验收待填写`)} finally {createBusy.value=false}
}
const inventoryVisible=ref(false),inventoryPart=ref<'pc'|'tpu'>('pc'),inventoryRows=ref<api.MoldInventoryOption[]>([]),inventorySearch=ref(''),inventoryId=ref<number>(),inventoryConfirmed=ref(false),inventoryReason=ref(''),inventoryLoading=ref(false)
let inventoryGeneration=0
function openInventory(part:'pc'|'tpu') {inventoryPart.value=part;inventoryRows.value=[];inventoryId.value=undefined;inventorySearch.value='';inventoryConfirmed.value=false;inventoryReason.value='';inventoryVisible.value=true}
async function searchInventory() {const key=inventorySearch.value.trim();if(key.length<2) {ElMessage.warning('请输入至少两个字符搜索来源资料');return}const generation=++inventoryGeneration;inventoryLoading.value=true;try {const r=await api.getMoldInventoryOptions(key);if(generation===inventoryGeneration) inventoryRows.value=r} finally {if(generation===inventoryGeneration) inventoryLoading.value=false}}
function stageInventory() {
  const row=detail.value,selected=inventoryRows.value.find(i=>i.inventoryId===inventoryId.value),prefix=inventoryPart.value
  if(!row||!selected||!inventoryConfirmed.value||!inventoryReason.value.trim()) {ElMessage.warning('请选择来源，并确认这是模具资料及填写确认说明');return}
  const master=code(row,prefix)
  if(value(row,prefix+'MoldCodeId') && master!==selected.inventoryCode) {ElMessage.warning('来源原码与已关联编码不一致。请先核对编码，不转移或改写历史编码。');return}
  drafts.set(row,prefix+'OriginalMoldCode',selected.inventoryCode);drafts.set(row,prefix+'InventoryId',selected.inventoryId)
  const d=drafts.rows.get(rowKey(row));if(d) d.reason=inventoryReason.value.trim()
  inventoryVisible.value=false;ElMessage.success('来源关联已暂存，未按库存数量新增模具')
}
async function removeInventory(part:string) {if(!detail.value) return;try {const r=await ElMessageBox.prompt('解除只读来源关联不会删除库存或原模具编码。请填写原因。','解除资料关联',{inputType:'textarea',inputValidator:v=>!!v?.trim() || '请填写原因'});drafts.set(detail.value,part+'InventoryId',null);const d=drafts.rows.get(rowKey(detail.value));if(d) d.reason=r.value.trim()} catch {}}
const editorVisible=ref(false),editorRow=ref<CollaborationRow>(),editorField=ref<PlanField>(),editorText=ref('')
function openEditor(row:CollaborationRow,f:PlanField) {editorRow.value=row;editorField.value=f;editorText.value=String(value(row,f.key)??'');editorVisible.value=true}
function stageEditor() {if(editorRow.value && editorField.value){try {drafts.set(editorRow.value,editorField.value.key,parseCell(editorField.value,editorText.value));editorVisible.value=false} catch(e) {ElMessage.warning(e instanceof Error?e.message:'格式不正确')}}}
const importVisible=ref(false)
function openImport() {if(dirtyCount.value){ElMessage.warning('请先保存或撤销模具草稿，再导入');return}importVisible.value=true}
function beforeUnload(event:BeforeUnloadEvent) {if(drafts.rows.size){event.preventDefault();event.returnValue=''}}
onBeforeRouteLeave(async to=>{
  if(!dirtyCount.value) return true
  const shared=isCollaborationEntry(to.path)
  try {await ElMessageBox.confirm(shared?'还有模具草稿，前往协作计划后会保留，可继续填写和保存。':'还有模具草稿，离开前请确认撤销；已保存记录不受影响。','未保存修改',{confirmButtonText:shared?'保留草稿并前往':'离开并丢弃',cancelButtonText:'继续填写',type:'warning'});if(!shared) moldDrafts.value.forEach(([key])=>drafts.rows.delete(key));return true} catch {return false}
})
function applyRoute() {if(route.path!=='/molds') return;itemFilter.value=Number(route.query.itemId)||undefined;setFilter.value=Number(route.query.moldSetId)||undefined;reset();if(setFilter.value && mounted) void openDetail(setFilter.value)}
watch(()=>route.fullPath,()=>applyRoute())
onMounted(async()=>{window.addEventListener('beforeunload',beforeUnload);const token=user.token;try {const result=await api.getMoldOptions();if(token!==user.token) return;options.value=result;applyRoute();await load();mounted=true;if(setFilter.value) await openDetail(setFilter.value)} catch {if(token===user.token) error.value='初始化失败，请刷新重试'}})
onActivated(()=>{active=true;if(mounted) void load()})
onDeactivated(()=>{active=false;clearTimeout(timer);request.invalidate()})
onBeforeUnmount(()=>{clearTimeout(timer);detailGeneration++;inventoryGeneration++;searchGeneration++;window.removeEventListener('beforeunload',beforeUnload)})
</script>

<template>
  <main class="mold-management" :class="{'is-expanded':expanded}">
    <header class="mold-head"><div><h2>模具管理 <span>台账与交付追踪</span></h2><p>一行一套 PC＋TPU · 原编码不变 · 与协作计划共用记录</p></div><div class="actions"><el-button @click="openSources">ERP / 钉钉编码资料</el-button><el-button :icon="FullScreen" @click="expanded=!expanded">{{ expanded?'退出宽屏':'宽屏台账' }}</el-button><el-button @click="collaborationRoute()">协作计划</el-button><el-button :icon="Refresh" @click="refresh">刷新</el-button><el-button v-if="engineer" :icon="Plus" type="primary" @click="openCreate">新增模具套</el-button></div></header>
    <el-drawer v-model="sourceVisible" title="模具编码来源核对" size="96%" class="mold-source-drawer"><MoldSourceCodes v-if="sourceVisited" :visible="sourceVisible" @close="sourceVisible=false" /></el-drawer>
    <section class="ledger-panel">
      <div class="filters"><el-input v-model="keyword" class="search" clearable placeholder="搜索实物编号 / 款式 / 型号 / 原编码 / 厂家" /><el-select v-model="productLineId" clearable placeholder="全部产品线"><el-option v-for="l in options?.productLines" :key="l.productLineId" :value="l.productLineId" :label="l.productName" /></el-select><el-select v-model="status" clearable placeholder="全部交付状态"><el-option v-for="s in moldStatuses" :key="s" :value="s" :label="statusNames[s]" /></el-select><el-select v-model="location" clearable placeholder="全部位置"><el-option v-for="(name,key) in locationNames" :key="key" :value="key" :label="name" /></el-select><el-checkbox v-model="mineOnly">待我填写</el-checkbox></div>
      <div class="ledger-toolbar"><span>共 {{ total }} 套模具 <el-tag v-if="itemFilter||setFilter" closable @close="itemFilter=undefined;setFilter=undefined;reset()">已定位关联模具</el-tag></span><div class="actions"><el-button :icon="Download" text @click="collaboration.downloadCollaborationTemplate('delivery',query())">下载本页模板（含 ID）</el-button><el-button :icon="Upload" text @click="openImport">Excel 导入预览</el-button></div></div>
      <p class="note">PC、TPU 分别到厂并验收通过才算交付完成。“实际抵达墨西哥”不等于“实际到厂”；未知位置保留为未知。</p>
      <el-alert v-if="error || request.error.value" :title="error || request.error.value" type="error" :closable="false" />
      <FixedTableViewport v-slot="{tableHeight}" fill :refresh-key="rows"><el-table :data="rows" :height="tableHeight" v-loading="request.loading.value" :row-key="rowKey" border class="mold-table">
        <el-table-column type="expand" width="42"><template #default="{row}"><div class="expanded-parts"><section v-for="part in parts" :key="part"><h4>{{ part.toUpperCase() }} <small>{{ row[part+'AssetNumber'] }}</small></h4><dl><dt>原模具编码</dt><dd>{{ display(row[part+'MoldCode']) }}</dd><dt>当前位置</dt><dd>{{ locationText(row,part) }} <span>{{ value(row,part+'LocationDetail') }}</span></dd><dt>实际到厂日期</dt><dd>{{ display(value(row,part+'FactoryArrivalDate')) }}</dd><dt>验收</dt><dd>{{ acceptanceNames[String(value(row,part+'AcceptanceStatus')||'pending')] }} · {{ display(value(row,part+'AcceptanceDate')) }}</dd><dt>问题说明</dt><dd>{{ display(value(row,part+'AcceptanceIssues')) }}</dd></dl><el-button link type="primary" @click="openDetail(row.moldSetId)">打开宽屏详情并填写</el-button></section></div></template></el-table-column>
        <el-table-column fixed="left" label="实物编号 / 套次" width="185"><template #default="{row}"><button class="asset-link" @click="openDetail(row.moldSetId)">{{ row.assetNumber }}</button><small>第 {{ row.setNo }} 套 · {{ row.setName }}</small><el-tag v-if="drafts.rows.has(rowKey(row))" size="small" type="warning">待保存</el-tag><button v-if="row.sourceMoldSetId" class="source-link" @click="openDetail(row.sourceMoldSetId)">来源套 #{{ row.sourceMoldSetId }}</button></template></el-table-column>
        <el-table-column label="款式 / 兼容手机型号" min-width="280"><template #default="{row}"><strong>{{ row.styleName }}</strong><div>{{ row.compatibleModels }}</div><small>{{ row.brand || '品牌未填写' }} · {{ row.projectCount }} 个关联项目（不按颜色重复）</small></template></el-table-column>
        <el-table-column label="原模具编码" width="175"><template #default="{row}"><div>PC：{{ display(row.pcMoldCode) }}</div><div>TPU：{{ display(row.tpuMoldCode) }}</div></template></el-table-column>
        <el-table-column label="制模厂家 / 负责人" min-width="190"><template #default="{row}"><div>{{ display(value(row,'manufacturerName')) }}</div><small>{{ options?.users?.find(u=>u.userId===value(row,'ownerUserId'))?.displayName || row.ownerName || '负责人未填写' }}</small></template></el-table-column>
        <el-table-column label="当前位置" width="200"><template #default="{row}"><div>PC · {{ locationText(row,'pc') }}</div><div>TPU · {{ locationText(row,'tpu') }}</div><small v-if="!equalCell(value(row,'pcCurrentLocation'),value(row,'tpuCurrentLocation'))" class="warning">两部分位置不同</small></template></el-table-column>
        <el-table-column label="交付状态" width="180"><template #default="{row}"><el-tag :type="row.status==='delivered'?'success':row.status==='acceptance_failed'?'danger':row.status.startsWith('partial')?'warning':'info'">{{ statusNames[row.status] }}</el-tag><small v-if="drafts.rows.has(rowKey(row))">状态按已保存记录计算</small></template></el-table-column>
        <el-table-column fixed="right" label="操作" width="90"><template #default="{row}"><el-button link type="primary" @click="openDetail(row.moldSetId)">查看 / 填写</el-button><el-button v-if="engineer" link @click="openCopy(row)">复制开模</el-button></template></el-table-column>
        <template #empty><div class="empty-ledger"><h3>暂无已确认的实物模具台账</h3><p>先选择已有款式与兼容型号档案建立一套，或预览交付表后人工确认导入。</p><p>历史库存的 tooling 分类还包含工具和零件，不会按库存数量自动生成模具。</p><el-button v-if="engineer" type="primary" @click="openCreate">新增第一套模具</el-button><el-button @click="openImport">预览历史交付表</el-button></div></template>
      </el-table></FixedTableViewport>
      <el-pagination :current-page="page" v-model:page-size="size" :page-sizes="[20,50,100]" :total="total" layout="total,sizes,prev,pager,next,jumper" @current-change="changePage" />
    </section>
    <footer v-if="dirtyCount" class="save-dock"><div><strong>{{ moldDrafts.length }} 套模具 · {{ dirtyCount }} 个字段待保存</strong><small>草稿与协作计划共用，刷新不会覆盖；保存后才写入台账。</small></div><div class="actions"><el-button @click="reviewVisible=true">查看待保存 / 冲突</el-button><el-button :disabled="saving" @click="discard">撤销未保存修改</el-button><el-button type="primary" :loading="saving" data-test="save-molds" @click="save">保存全部模具修改</el-button></div></footer>
    <el-drawer v-model="detailVisible" :title="detail ? `模具详情 · ${detail.assetNumber}` : '模具详情'" size="min(1400px,96vw)" :close-on-click-modal="false" class="mold-detail" @closed="detailGeneration++">
      <div v-loading="detailLoading"><template v-if="detail"><div class="detail-summary"><h3>{{ detail.styleName }} / {{ detail.compatibleModels }}</h3><p>第 {{ detail.setNo }} 套 · {{ detail.assetNumber }} <el-tag :type="detail.status==='delivered'?'success':'info'">{{ statusNames[detail.status] }}</el-tag><el-button v-if="detail.sourceMoldSetId" link @click="openDetail(detail.sourceMoldSetId)">来源套 #{{ detail.sourceMoldSetId }}</el-button></p><p class="note">实物编号与套次创建后固定。颜色项目共用档案，模具套数不改变累计产量。</p></div>
        <el-tabs v-model="detailTab"><el-tab-pane label="资料与交付录入" name="entry" /><el-tab-pane label="关联项目 / 附件 / 运模" name="references" /><el-tab-pane label="修改历史" name="history" /></el-tabs>
        <div v-if="detailTab==='entry'" class="entry-form"><section><h4>模具套资料与日期</h4><div class="set-fields"><label v-for="f in setFields" :key="f.key" :class="{'wide-field':f.key==='notes'}"><span>{{ f.label }} <small>{{ groupNames[f.group] }}</small></span><CollaborationCell :field="f" :users="options?.users" :value="value(detail,f.key)" :editable="can(f)" :dirty="dirty(detail,f.key)" expandable @preview="edit(detail!,f,$event,true)" @edit="edit(detail!,f,$event)" @expand="openEditor(detail!,f)" /><div v-if="f.key==='plannedFactoryArrivalDate'" class="suggestion"><template v-if="!value(detail,f.key) && suggestedArrivalDate(value(detail,'plannedMoldDeliveryDate'))">建议 {{ suggestedArrivalDate(value(detail,'plannedMoldDeliveryDate')) }}<el-button v-if="can(f)" link type="primary" @click="confirmArrival(detail,true)">采用并确认</el-button></template><template v-else-if="arrivalReview(detail)"><span class="warning">交付计划变化，请重新核对</span><el-button v-if="can(f)" link @click="confirmArrival(detail)">确认当前计划</el-button></template></div></label></div></section>
          <div class="part-grid"><section v-for="part in parts" :key="part" class="part-card"><h4>{{ part.toUpperCase() }} 部分 <small>{{ detail[part+'AssetNumber'] }}</small></h4><p class="note">原模具编码可复用；实物编号用于区分同编码的不同套。</p><label v-if="field(part+'MoldCodeId')"><span>关联现有模具编码 <small>中国工程</small></span><select :aria-label="`${part.toUpperCase()} 关联现有模具编码`" :disabled="!engineer" :value="value(detail,part+'MoldCodeId') ?? ''" @change="edit(detail!,field(part+'MoldCodeId')!,($event.target as HTMLSelectElement).value)"><option value="">未关联编码资料（可填写来源原码）</option><option v-if="value(detail,part+'MoldCodeId') && !codeOptions.some(c=>c.moldCodeId===value(detail!,part+'MoldCodeId'))" :value="String(value(detail,part+'MoldCodeId'))">当前关联 {{ detail[part+'CatalogMoldCode'] }}</option><option v-for="c in codeOptions" :key="c.moldCodeId" :value="c.moldCodeId">{{ c.moldCode }} / {{ c.moldName }}</option></select></label>
            <label v-for="f in partFields(part)" :key="f.key"><span>{{ f.label }} <small>{{ groupNames[f.group] }}</small></span><CollaborationCell :field="f" :value="value(detail,f.key)" :editable="can(f)" :dirty="dirty(detail,f.key)" expandable @preview="edit(detail!,f,$event,true)" @edit="edit(detail!,f,$event)" @expand="openEditor(detail!,f)" /></label>
            <div class="inventory-link"><span>历史来源资料：{{ value(detail,part+'InventoryId') ? detail[part+'InventoryName'] || '已选择 #'+value(detail,part+'InventoryId') : '未关联' }}</span><el-button v-if="engineer" link type="primary" @click="openInventory(part)">人工选择模具资料</el-button><el-button v-if="engineer && value(detail,part+'InventoryId')" link @click="removeInventory(part)">解除关联</el-button></div>
          </section></div><p class="note">验收通过必须填写本部分到厂与验收日期；验收日期不得早于到厂。不通过需说明问题，抵墨日期不会填入到厂日期。</p>
        </div>
        <div v-else-if="detailTab==='references'" v-loading="auxLoading"><h4>同档案的颜色项目（只读关联）</h4><div v-for="p in reference?.item.projects" :key="p.projectId" class="reference-row"><span>{{ p.productCode }} / {{ p.color || '未标颜色' }}</span><div><el-button link type="primary" @click="router.push(projectRoute(p.projectId))">项目工作台</el-button><el-button link @click="router.push(projectRoute(p.projectId,'materials'))">文件 / 附件</el-button></div></div><h4>历史运模记录</h4><p class="note">只读引用：不以快递状态或流程确认时间判断到厂、验收或自动改写日期。</p><div v-for="e in reference?.expressRecords" :key="e.projectId+':'+e.trackingNo" class="reference-row"><span>{{ e.trackingNo }} · {{ e.shippedAt || '未填写发模时间' }} · {{ e.latestStatusText }}</span><el-button link @click="router.push(projectRoute(e.projectId))">查看原记录</el-button></div><el-empty v-if="reference && !reference.expressRecords.length" description="暂无历史运模记录" /></div>
        <div v-else v-loading="auxLoading"><el-table :data="historyRows" border><el-table-column label="字段" width="190"><template #default="{row}">{{ label(row.fieldName) }}</template></el-table-column><el-table-column label="原值 → 新值" min-width="300"><template #default="{row}"><div class="history-value">{{ display(row.before) }} → {{ display(row.after) }}</div><small>{{ row.reason }}</small></template></el-table-column><el-table-column prop="actorName" label="真实保存账号" width="180" /><el-table-column prop="changedAt" label="保存时间" width="200" /></el-table><el-pagination v-model:current-page="historyPage" :page-size="20" :total="historyTotal" layout="prev,pager,next" @current-change="loadHistory" /></div>
      </template><el-empty v-else-if="!detailLoading" description="详情加载失败，请关闭后重试" /></div>
      <template #footer><div class="drawer-footer"><div><el-button v-if="detail" @click="collaborationRoute(detail)">打开协作计划</el-button><el-button v-if="detail && engineer" @click="openCopy(detail)">复制 / 重新开模</el-button><el-button v-if="detail && drafts.rows.has(rowKey(detail))" @click="explain(detail)">更正 / 核对说明</el-button></div><div><el-button @click="detailVisible=false">关闭（保留草稿）</el-button><el-button type="primary" :loading="saving" :disabled="!dirtyCount" @click="save">保存模具修改</el-button></div></div></template>
    </el-drawer>
    <el-dialog v-model="createVisible" :title="copySource?'复制 / 重新开模':'新增模具套'" width="min(900px,94vw)" :close-on-click-modal="false"><el-alert :title="copySource?'保留原模具编码及来源套关联，生成独立实物编号和套次；日期、位置、签收、验收、厂家及负责人均不复制。':'建立一套 PC＋TPU 实物模具。复用已有款式与兼容型号档案，不按颜色重复建档。'" type="info" :closable="false" /><el-form label-position="top"><el-form-item v-if="!copySource" label="已有协作档案（款式＋兼容型号组）" required><el-select v-model="createItemId" filterable remote :remote-method="searchItems" placeholder="搜索款式或手机型号"><el-option v-for="i in createTargets" :key="i.itemId" :value="i.itemId" :label="`${i.styleName} / ${i.compatibleModels} · ${i.moldSetCount} 套模具 / ${i.projectCount} 个项目`" /></el-select></el-form-item><p v-else>{{ copySource.assetNumber }} · {{ copySource.styleName }} / {{ copySource.compatibleModels }}</p><el-form-item label="新模具套名称（可留空，自动按套次命名）"><el-input v-model="createName" maxlength="255" placeholder="例如：首套、复制套、重新开模" /></el-form-item></el-form><p class="note">不修改历史项目、编码、BOM 或累计产量。新增后交付状态从待填写开始。</p><template #footer><el-button @click="createVisible=false">取消</el-button><el-button type="primary" :loading="createBusy" @click="create">确认建立新套</el-button></template></el-dialog>
    <el-dialog v-model="inventoryVisible" :title="`${inventoryPart.toUpperCase()} · 人工确认历史模具资料`" width="min(1000px,94vw)" :close-on-click-modal="false"><el-alert title="库存 tooling 分类还含工具与零件，不能整体转成模具。只关联你已人工确认的这条来源资料，不使用库存数量推断套数。" type="warning" :closable="false" /><div class="inventory-search"><el-input v-model="inventorySearch" placeholder="搜索原编码 / 名称 / 规格（至少两个字符）" @keyup.enter="searchInventory" /><el-button :loading="inventoryLoading" @click="searchInventory">搜索资料</el-button></div><el-table :data="inventoryRows" height="310" @row-click="(row: api.MoldInventoryOption)=>inventoryId=row.inventoryId"><el-table-column label="选择" width="65"><template #default="{row}"><el-radio v-model="inventoryId" :value="row.inventoryId" :aria-label="row.inventoryCode"><span /></el-radio></template></el-table-column><el-table-column prop="inventoryCode" label="来源原编码" width="220" /><el-table-column prop="inventoryName" label="名称" min-width="250" /><el-table-column prop="specification" label="规格" min-width="180" /><el-table-column prop="inventoryType" label="原分类" width="120" /></el-table><el-checkbox v-model="inventoryConfirmed">我已确认这是本部分的模具资料，而不是工具或零件</el-checkbox><el-input v-model="inventoryReason" type="textarea" :rows="3" placeholder="填写人工确认依据（会记录到修改历史）" /><template #footer><el-button @click="inventoryVisible=false">取消</el-button><el-button type="primary" @click="stageInventory">暂存关联与来源原码</el-button></template></el-dialog>
    <el-dialog v-model="editorVisible" :title="`展开编辑 · ${editorField?.label}`" width="min(1000px,94vw)"><el-input v-model="editorText" type="textarea" :autosize="{minRows:8,maxRows:18}" :maxlength="editorField?.maxLength" :readonly="!editorField || !can(editorField)" show-word-limit /><template #footer><el-button @click="editorVisible=false">关闭</el-button><el-button v-if="editorField && can(editorField)" type="primary" @click="stageEditor">暂存此格修改</el-button></template></el-dialog>
    <el-drawer v-model="reviewVisible" title="模具待保存与冲突核对" size="min(1000px,94vw)"><section v-for="[key,d] in moldDrafts" :key="key" class="draft-row"><strong>{{ d.source.assetNumber }} · {{ d.source.styleName }} / {{ d.source.compatibleModels }}</strong><p>{{ d.changes.size }} 个修改字段 <el-button link @click="explain(d.source)">{{ d.reason?'说明：'+d.reason:'填写更正 / 核对说明' }}</el-button></p><div v-for="[name,c] in d.changes" :key="name" class="draft-cell">{{ label(name) }}：{{ display(c.before) }} → {{ display(c.after) }}</div><p v-if="d.result" class="warning">{{ d.result.message }}</p><div v-for="c in d.result?.conflicts" :key="c.field" class="conflict-row"><strong>{{ c.label }}</strong><span>当前：{{ display(c.current) }}；我的修改：{{ display(c.attempted) }}</span><el-button size="small" @click="drafts.resolve(key,c.field,false)">采用当前值</el-button><el-button size="small" type="warning" @click="drafts.resolve(key,c.field,true)">确认保留我的修改</el-button></div></section><template #footer><el-button @click="reviewVisible=false">继续填写</el-button><el-button type="primary" :loading="saving" :disabled="!dirtyCount" @click="save">保存已核对修改</el-button></template></el-drawer>
    <CollaborationImportDialog v-if="options" v-model="importVisible" kind="delivery" :options="options" @imported="afterChange" />
  </main>
</template>

<style scoped>
.mold-management{display:flex;flex-direction:column;gap:12px;height:100%;min-height:0;min-width:0;color:#293e58;overflow:hidden}.is-expanded{position:fixed;inset:0;z-index:100;background:#f0f4f8;padding:14px;box-sizing:border-box;height:100dvh}.mold-head,.actions,.ledger-toolbar,.drawer-footer,.reference-row{display:flex;align-items:center;gap:10px}.mold-head,.ledger-toolbar,.drawer-footer,.reference-row{justify-content:space-between}.mold-head{flex:none;flex-wrap:wrap}h2{font-size:22px;margin:0 0 5px}h2 span{font-size:12px;color:#8190a4;font-weight:400;margin-left:10px}.mold-head p{font-size:12px;color:#8190a4;margin:0}.actions{flex-wrap:wrap}.ledger-panel{display:flex;flex-direction:column;flex:1;min-height:0;padding:14px;background:#fff;border:1px solid #e0e7f0;border-radius:10px}.filters{display:flex;flex-wrap:wrap;gap:12px;margin-bottom:10px;flex:none}.filters .search{flex:1;min-width:260px}.filters .el-select{width:165px}.ledger-toolbar{flex:none;font-size:13px;color:#71839b;margin-bottom:4px}.note{color:#8190a4;font-size:12px;line-height:1.6;margin:6px 0 12px}.mold-table small,.save-dock small{display:block;color:#8190a4;margin-top:5px;font-size:11px}.mold-table strong{display:block;margin-bottom:4px}.asset-link,.source-link{border:0;background:transparent;padding:0;color:#3674c1;cursor:pointer;text-align:left;font:inherit}.asset-link{font-weight:600}.source-link{display:block;font-size:11px;margin-top:5px}.warning{color:#b37518!important}.empty-ledger{padding:38px 20px;line-height:1.6}.empty-ledger h3{font-size:17px;color:#486384;margin:0 0 12px}.empty-ledger p{font-size:13px;margin:6px 0 12px}.expanded-parts{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:22px;padding:18px 26px;background:#f6f9fe}.expanded-parts section{border:1px solid #dfe8f3;background:#fff;border-radius:8px;padding:16px}.expanded-parts h4{margin:0 0 10px}.expanded-parts h4 small{display:inline;margin-left:12px}dl{display:grid;grid-template-columns:110px minmax(0,1fr);font-size:13px;gap:10px;margin:0 0 12px}dt{color:#7a8ba0}dd{margin:0;white-space:pre-wrap;overflow-wrap:anywhere}.el-pagination{flex:none;margin-top:12px}.mold-table :deep(th.el-table__cell){background:#f1f5fa;color:#5f7795}.mold-table :deep(.cell){padding:9px 12px}.save-dock{flex:none;display:flex;align-items:center;justify-content:space-between;padding:13px 17px;background:#edf4ff;border:1px solid #ccdffd;border-radius:9px}.save-dock small{font-size:12px}.detail-summary h3{margin:0 0 10px;font-size:20px}.detail-summary p{margin:8px 0}.entry-form h4{margin:10px 0 14px}.set-fields{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:18px 24px}.entry-form label{display:block;margin:0 0 16px}.entry-form label>span{display:flex;justify-content:space-between;font-size:13px;color:#516b88;margin-bottom:8px}.entry-form label small{font-size:11px;color:#93a2b5}.wide-field{grid-column:1/-1}.part-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:24px;margin:18px 0}.part-card{min-width:0;background:#f8fafd;padding:20px;border:1px solid #e1e9f3;border-radius:10px}.part-card h4{font-size:18px;margin:0 0 8px;color:#385f91}.part-card h4 small{font-size:12px;color:#93a2b5;margin-left:10px}.part-card select{padding:10px 8px;box-sizing:border-box;width:100%;font:inherit;font-size:13px;color:#355777;background:#eff5ff;border:1px solid #dce7f8;border-radius:5px}.entry-form :deep(.plan-cell){min-height:44px}.entry-form :deep(input),.entry-form :deep(select),.entry-form :deep(textarea){padding:11px 4px}.entry-form :deep(textarea){min-height:82px;resize:vertical}.suggestion{font-size:12px;color:#8190a4;line-height:1.5}.inventory-link{font-size:12px;border-top:1px solid #dfe8f3;padding-top:12px;line-height:1.8}.reference-row{padding:14px 0;border-bottom:1px solid #edf0f6}.history-value{white-space:pre-wrap;overflow-wrap:anywhere;max-height:150px;overflow:auto}.inventory-search{display:flex;gap:12px;margin:16px 0}.el-form{margin-top:18px}.el-form .el-select{width:100%}.draft-row{padding:18px 0;border-bottom:1px solid #e4ebf4}.draft-cell{padding:5px 0;font-size:13px;white-space:pre-wrap;overflow-wrap:anywhere}.conflict-row{display:flex;flex-wrap:wrap;gap:10px;padding:12px;background:#fff5dc;margin-top:10px;border-radius:6px}.drawer-footer>div{display:flex;gap:8px;flex-wrap:wrap}
@media(max-width:1000px){.set-fields{grid-template-columns:repeat(2,minmax(0,1fr))}.filters .el-select{width:145px}.drawer-footer,.save-dock{flex-wrap:wrap;gap:12px}}
@media(max-width:700px){.part-grid,.expanded-parts,.set-fields{grid-template-columns:1fr}.filters .search{min-width:180px}.part-card{padding:14px}.mold-head h2{font-size:19px}}
</style>
