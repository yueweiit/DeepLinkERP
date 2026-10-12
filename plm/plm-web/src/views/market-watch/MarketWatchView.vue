<script setup lang="ts">
import { Download, Refresh, Search } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { getCodeItems, type CodeItem } from '@/api/modules/code'
import { getCollaborationOptions } from '@/api/modules/collaboration'
import * as api from '@/api/modules/marketWatch'
import type { ProductLineOption } from '@/types/collaboration'
import type { MarketWatchConfig, MarketWatchItem, MarketWatchKind, MarketWatchQuery, MarketWatchSummary, PromotionOptions } from '@/types/marketWatch'

const router = useRouter()
const config = ref<MarketWatchConfig>({ enabled: false, writable: false, administrator: false })
const summary = ref<MarketWatchSummary | null>(null)
const kind = ref<MarketWatchKind>('phone')
const rows = ref<MarketWatchItem[]>([])
const loading = ref(false)
const error = ref('')
const page = ref(1)
const size = ref(20)
const total = ref(0)
const selected = ref<MarketWatchItem[]>([])
const dateRange = ref<[string, string] | []>([])
const filters = reactive({ keyword: '', country: '', brand: '', source: '', status: '' })
const detailVisible = ref(false)
const detailLoading = ref(false)
const detail = ref<MarketWatchItem | null>(null)
const edit = reactive({ status: '', badge: '', saleStatus: '' })
const saving = ref(false)
const bulkStatus = ref('')
const bulkBadge = ref('')
const promotionVisible = ref(false)
const promotionLoading = ref(false)
const promotionOptions = ref<PromotionOptions | null>(null)
const productLines = ref<ProductLineOption[]>([])
const phoneCodes = ref<CodeItem[]>([])
const promoteForm = reactive({ mode: 'create' as 'create' | 'link', itemId: null as number | null, productLineId: null as number | null,
  styleName: '', compatibleModels: '', phoneModelCode: '', notes: '' })

const statusOptions = ['未开模', '部分开模', '已开模', '忽略']
const badgeOptions = ['', '新品', '新品预告', '官网当前机型', 'Walmart MX 在售']
const canWrite = computed(() => config.value.writable)
const currentQuery = computed<MarketWatchQuery>(() => ({
  kind: kind.value, page: page.value, size: size.value,
  keyword: filters.keyword.trim() || undefined, country: filters.country || undefined,
  brand: filters.brand.trim() || undefined, source: filters.source.trim() || undefined,
  status: filters.status || undefined, dateFrom: dateRange.value[0] || undefined, dateTo: dateRange.value[1] || undefined
}))

async function loadConfig() { config.value = await api.getMarketWatchConfig() }
async function loadSummary() { summary.value = await api.getMarketWatchSummary() }
async function load() {
  if (!config.value.enabled) return
  loading.value = true; error.value = ''
  try {
    const result = await api.getMarketWatchItems(currentQuery.value)
    rows.value = result.content; total.value = result.totalElements
  } catch { error.value = '监控数据加载失败，请检查内部服务后重试' }
  finally { loading.value = false }
}
async function refreshAll() { await Promise.all([loadSummary(), load()]) }
function applyFilters() { page.value = 1; void load() }
function resetFilters() {
  Object.assign(filters, { keyword: '', country: '', brand: '', source: '', status: '' }); dateRange.value = []; applyFilters()
}
function changeKind(value: string | number) { kind.value = String(value) as MarketWatchKind; selected.value = []; page.value = 1; void load() }
function changePage(value: number) { page.value = value; void load() }
function changeSize(value: number) { size.value = value; page.value = 1; void load() }

async function openDetail(row: MarketWatchItem) {
  detailVisible.value = true; detailLoading.value = true; detail.value = null
  try {
    detail.value = await api.getMarketWatchItem(row.kind, row.id)
    Object.assign(edit, { status: detail.value.sampling_status || '', badge: detail.value.badge || '', saleStatus: detail.value.sale_status || '' })
  } catch { ElMessage.error('详情加载失败') }
  finally { detailLoading.value = false }
}
async function saveDetail() {
  if (!detail.value) return
  saving.value = true
  try {
    detail.value = await api.updateMarketWatchItem(detail.value.kind, detail.value.id, { status: edit.status, badge: edit.badge, saleStatus: edit.saleStatus })
    ElMessage.success('状态与标签已保存'); await Promise.all([load(), loadSummary()])
  } finally { saving.value = false }
}
async function runBulk(field: 'status' | 'badge') {
  const value = field === 'status' ? bulkStatus.value : bulkBadge.value
  if (!selected.value.length) return ElMessage.warning('请先选择记录')
  if (!value && field === 'status') return ElMessage.warning('请选择状态')
  saving.value = true
  try {
    await api.bulkUpdateMarketWatch({ kind: kind.value, ids: selected.value.map(item => item.id), [field]: value })
    ElMessage.success(`已更新 ${selected.value.length} 条记录`); selected.value = []; await refreshAll()
  } finally { saving.value = false }
}

async function openPromotion(row: MarketWatchItem) {
  promotionVisible.value = true; promotionLoading.value = true; promotionOptions.value = null
  try {
    const [options, collaboration, codes] = await Promise.all([
      api.getPromotionOptions(row.kind, row.id), getCollaborationOptions(), getCodeItems({ codeType: 'phone_model', status: 'enabled', page: 1, size: 200 })
    ])
    promotionOptions.value = options; productLines.value = collaboration.productLines; phoneCodes.value = codes.content
    Object.assign(promoteForm, { mode: options.matches.length ? 'link' : 'create', itemId: options.matches[0]?.itemId || null,
      productLineId: null, styleName: '', compatibleModels: options.source.model, phoneModelCode: '', notes: '' })
  } catch { ElMessage.error('转入信息加载失败') }
  finally { promotionLoading.value = false }
}
async function submitPromotion() {
  const options = promotionOptions.value
  if (!options) return
  if (promoteForm.mode === 'create' && (!promoteForm.styleName.trim() || !promoteForm.productLineId)) {
    return ElMessage.warning('请人工确认产品款式和产品线')
  }
  if (promoteForm.mode === 'link' && !promoteForm.itemId) return ElMessage.warning('请选择已有协作档案')
  promotionLoading.value = true
  try {
    const result = await api.promoteMarketWatch({ sourceKind: options.source.kind, sourceId: options.source.id, ...promoteForm,
      phoneModelCode: promoteForm.phoneModelCode || null })
    ElMessage.success(result.alreadyPromoted ? '该记录此前已转入，已定位原档案' : '已转入协作计划')
    promotionVisible.value = false; await load(); await router.push({ path: '/collaboration-plans', query: { itemId: result.itemId } })
  } finally { promotionLoading.value = false }
}
function openCollaboration(itemId: number) { return router.push({ path: '/collaboration-plans', query: { itemId } }) }

watch(size, () => { /* pagination callback is authoritative */ })
onMounted(async () => {
  try { await loadConfig(); if (config.value.enabled) await refreshAll() }
  catch { error.value = '手机新品监控功能配置加载失败' }
})
</script>

<template>
  <main class="market-watch">
    <header class="page-head">
      <div><h2>手机新品监控</h2><p>在 PLM 内查看采集结果、维护市场状态，并将确认后的线索转入协作计划。</p></div>
      <div class="actions"><el-button :icon="Refresh" @click="refreshAll">刷新</el-button><el-button :icon="Download" @click="api.exportMarketWatch(currentQuery)">导出 CSV</el-button></div>
    </header>

    <el-alert v-if="!config.enabled" title="手机新品监控功能当前未启用" type="info" :closable="false" show-icon />
    <template v-else>
      <section v-if="summary" class="metrics">
        <div><strong>{{ summary.phones }}</strong><span>正式机型</span></div>
        <div><strong>{{ summary.candidates }}</strong><span>候选机型</span></div>
        <div><strong>{{ summary.unreviewed_candidates }}</strong><span>未处理候选</span></div>
        <div><strong>{{ summary.ignored_phones }}</strong><span>已忽略正式机型</span></div>
      </section>

      <section class="panel">
        <el-tabs :model-value="kind" @tab-change="changeKind"><el-tab-pane label="正式机型" name="phone" /><el-tab-pane label="候选机型" name="candidate" /></el-tabs>
        <div class="filters">
          <el-input v-model="filters.keyword" clearable placeholder="型号 / 品牌 / 来源关键词" @keyup.enter="applyFilters" />
          <el-select v-model="filters.country" clearable placeholder="国家/地区"><el-option v-for="value in ['MX','CN','KR','GLOBAL']" :key="value" :label="value" :value="value" /></el-select>
          <el-input v-model="filters.brand" clearable placeholder="品牌" />
          <el-input v-model="filters.source" clearable placeholder="来源" />
          <el-select v-model="filters.status" clearable placeholder="处理状态"><el-option v-for="value in statusOptions" :key="value" :label="value" :value="value" /></el-select>
          <el-date-picker v-model="dateRange" type="daterange" value-format="YYYY-MM-DD" start-placeholder="开始日期" end-placeholder="结束日期" />
          <el-button type="primary" :icon="Search" @click="applyFilters">筛选</el-button><el-button @click="resetFilters">重置</el-button>
        </div>
        <el-alert v-if="error" :title="error" type="error" :closable="false"><template #default><el-button link type="primary" @click="load">重试</el-button></template></el-alert>

        <div v-if="canWrite" class="bulk-bar">
          <span>已选 {{ selected.length }} 条</span>
          <el-select v-model="bulkStatus" placeholder="批量状态"><el-option v-for="value in statusOptions" :key="value" :label="value" :value="value" /></el-select><el-button :disabled="!selected.length" @click="runBulk('status')">应用状态</el-button>
          <el-select v-model="bulkBadge" placeholder="批量标签"><el-option v-for="value in badgeOptions" :key="value" :label="value || '无标签'" :value="value" /></el-select><el-button :disabled="!selected.length" @click="runBulk('badge')">应用标签</el-button>
        </div>

        <el-table v-loading="loading" :data="rows" border stripe height="calc(100vh - 430px)" @selection-change="selected = $event">
          <el-table-column type="selection" width="48" />
          <el-table-column label="品牌 / 型号" min-width="230"><template #default="{ row }"><div class="identity"><strong>{{ row.brand }} {{ row.model }}</strong><small>{{ row.kind === 'phone' ? row.country : `${row.source_country} → ${row.missing_country}` }}</small></div></template></el-table-column>
          <el-table-column prop="price" label="原始价格" min-width="135" />
          <el-table-column prop="source_name" label="来源" min-width="150" show-overflow-tooltip />
          <el-table-column label="状态" width="110"><template #default="{ row }"><el-tag>{{ row.sampling_status }}</el-tag></template></el-table-column>
          <el-table-column label="标签" min-width="135"><template #default="{ row }"><el-tag v-if="row.badge" type="success">{{ row.badge }}</el-tag><span v-else>—</span></template></el-table-column>
          <el-table-column prop="last_seen_at" label="最后发现" min-width="180" />
          <el-table-column label="协作计划" width="125"><template #default="{ row }"><el-button v-if="row.collaborationLink" link type="success" @click="openCollaboration(row.collaborationLink.itemId)">已转入 · 打开</el-button><span v-else>未转入</span></template></el-table-column>
          <el-table-column label="操作" width="190" fixed="right"><template #default="{ row }"><el-button link type="primary" @click="openDetail(row)">详情</el-button><el-button v-if="canWrite && !row.collaborationLink" link type="primary" @click="openPromotion(row)">转入协作计划</el-button></template></el-table-column>
        </el-table>
        <el-pagination :current-page="page" :page-size="size" :page-sizes="[20,50,100]" :total="total" layout="total, sizes, prev, pager, next, jumper" @current-change="changePage" @size-change="changeSize" />
      </section>
    </template>

    <el-drawer v-model="detailVisible" title="监控记录详情" size="520px">
      <div v-loading="detailLoading" v-if="detail" class="detail-grid">
        <label>品牌</label><span>{{ detail.brand }}</span><label>型号</label><span>{{ detail.model }}</span>
        <label>来源</label><span>{{ detail.source_name || '—' }}</span><label>原始价格</label><span>{{ detail.price || '—' }}</span>
        <label>首次发现</label><span>{{ detail.first_seen_at }}</span><label>最后发现</label><span>{{ detail.last_seen_at }}</span>
        <label>来源链接</label><a v-if="detail.source_url" :href="detail.source_url" target="_blank" rel="noopener">打开来源</a><span v-else>—</span>
      </div>
      <el-form v-if="detail && canWrite" label-position="top" class="detail-form"><el-form-item label="处理状态"><el-select v-model="edit.status"><el-option v-for="value in statusOptions" :key="value" :label="value" :value="value" /></el-select></el-form-item><el-form-item label="展示标签"><el-select v-model="edit.badge"><el-option v-for="value in badgeOptions" :key="value" :label="value || '无标签'" :value="value" /></el-select></el-form-item><el-form-item label="销售状态"><el-select v-model="edit.saleStatus"><el-option v-for="value in ['已售','未发售','未发布','未上市']" :key="value" :label="value" :value="value" /></el-select></el-form-item><el-button type="primary" :loading="saving" @click="saveDetail">保存维护信息</el-button></el-form>
      <template #footer><el-button @click="detailVisible = false">关闭</el-button></template>
    </el-drawer>

    <el-dialog v-model="promotionVisible" title="转入协作计划" width="680px" destroy-on-close>
      <div v-loading="promotionLoading">
        <el-alert v-if="promotionOptions?.matches.length" title="检测到相同兼容型号的协作档案，请优先关联已有档案；系统不会静默创建重复记录。" type="warning" :closable="false" show-icon />
        <el-form v-if="promotionOptions" label-position="top" class="promote-form">
          <el-form-item label="处理方式"><el-radio-group v-model="promoteForm.mode"><el-radio value="create">新建档案</el-radio><el-radio value="link">关联已有档案</el-radio></el-radio-group></el-form-item>
          <template v-if="promoteForm.mode === 'link'"><el-form-item label="已有协作档案" required><el-select v-model="promoteForm.itemId" filterable><el-option v-for="item in promotionOptions.matches" :key="item.itemId" :label="`${item.styleName} · ${item.compatibleModels}`" :value="item.itemId" /></el-select></el-form-item></template>
          <template v-else>
            <div class="form-grid"><el-form-item label="产品款式（人工确认）" required><el-input v-model="promoteForm.styleName" placeholder="不要直接使用采集型号代替产品款式" /></el-form-item><el-form-item label="产品线（人工确认）" required><el-select v-model="promoteForm.productLineId" filterable><el-option v-for="line in productLines" :key="line.productLineId" :label="`${line.productName} (${line.productCode})`" :value="line.productLineId" /></el-select></el-form-item><el-form-item label="兼容手机型号"><el-input v-model="promoteForm.compatibleModels" /></el-form-item><el-form-item label="手机型号编码（可留空）"><el-select v-model="promoteForm.phoneModelCode" clearable filterable placeholder="只能选择已有四位编码"><el-option v-for="code in phoneCodes" :key="code.codeItemId" :label="`${code.codeValue} · ${code.codeName}`" :value="code.codeValue" /></el-select></el-form-item></div>
            <el-descriptions :column="2" border><el-descriptions-item label="品牌">{{ promotionOptions.source.brand }}</el-descriptions-item><el-descriptions-item label="平台">{{ promotionOptions.source.source_name || '—' }}</el-descriptions-item><el-descriptions-item label="原始价格">{{ promotionOptions.source.price || '—' }}</el-descriptions-item><el-descriptions-item label="来源链接">{{ promotionOptions.source.source_url || '—' }}</el-descriptions-item></el-descriptions>
            <el-form-item label="市场备注"><el-input v-model="promoteForm.notes" type="textarea" :rows="3" placeholder="价格或币种不明确时，后端会自动把原始值保留在备注，不会猜测。" /></el-form-item>
          </template>
        </el-form>
      </div>
      <template #footer><el-button @click="promotionVisible = false">取消</el-button><el-button type="primary" :loading="promotionLoading" @click="submitPromotion">确认转入</el-button></template>
    </el-dialog>
  </main>
</template>

<style scoped>
.market-watch{display:flex;flex-direction:column;gap:14px;height:100%;min-height:0}.page-head,.actions,.filters,.bulk-bar{display:flex;align-items:center;gap:10px}.page-head{justify-content:space-between}.page-head h2,.page-head p{margin:0 0 5px}.page-head p{color:#718096;font-size:13px}.metrics{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px}.metrics div{background:#fff;border:1px solid #e2e8f0;border-radius:10px;padding:16px}.metrics strong{display:block;font-size:26px;color:#254f83}.metrics span{color:#718096;font-size:13px}.panel{min-height:0;flex:1;background:#fff;border:1px solid #e2e8f0;border-radius:10px;padding:14px}.filters{flex-wrap:wrap;margin-bottom:12px}.filters .el-input{width:190px}.filters .el-select{width:145px}.bulk-bar{padding:10px;background:#f4f7fb;border-radius:8px;margin-bottom:10px}.bulk-bar .el-select{width:160px}.identity{display:flex;flex-direction:column;gap:4px}.identity small{color:#8492a6}.el-pagination{margin-top:13px}.detail-grid{display:grid;grid-template-columns:110px 1fr;gap:12px;border-bottom:1px solid #e5e7eb;padding-bottom:18px}.detail-grid label{color:#718096}.detail-form{margin-top:18px}.detail-form .el-select,.promote-form .el-select{width:100%}.form-grid{display:grid;grid-template-columns:1fr 1fr;gap:0 16px}.promote-form{margin-top:14px}@media(max-width:900px){.metrics{grid-template-columns:1fr 1fr}.page-head{align-items:flex-start;flex-direction:column}.form-grid{grid-template-columns:1fr}}
</style>
