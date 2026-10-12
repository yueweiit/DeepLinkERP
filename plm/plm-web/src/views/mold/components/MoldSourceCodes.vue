<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { isNavigationFailure, useRouter } from 'vue-router'
import { useUserStore } from '@/stores/user'
import { useCachedRequest } from '@/composables/useCachedRequest'
import FixedTableViewport from '@/components/FixedTableViewport/index.vue'
import { getMoldSourceCodes, getMoldSourceSummary, type MoldSourceCode, type MoldSourceSummary } from '@/api/modules/moldSources'
const props = defineProps<{ visible: boolean }>()
const emit = defineEmits<{ close: [] }>()
const user = useUserStore(), router = useRouter(), request = useCachedRequest(getMoldSourceCodes)
const keyword = ref(''), source = ref('erp'), part = ref(''), review = ref(''), page = ref(1), size = ref(50)
const summary = ref<MoldSourceSummary>(), error = ref('')
const rows = computed(() => request.hasCurrentData.value ? request.data.value?.content || [] : [])
const total = computed(() => request.data.value?.totalElements || 0)
let timer: ReturnType<typeof setTimeout> | undefined, generation = 0
function load(force = false) {
  return user.token && props.visible ? request.execute({ page: page.value, size: size.value, keyword: keyword.value.trim(), source: source.value || undefined, part: part.value || undefined, review: review.value || undefined }, force) : Promise.resolve()
}
async function loadSummary() {
  const ticket = ++generation, token = user.token
  try { const value = await getMoldSourceSummary(); if (ticket === generation && token === user.token) summary.value = value }
  catch { if (ticket === generation && token === user.token) error.value = '来源统计加载失败，请刷新重试' }
}
function reset(debounce = false) { clearTimeout(timer); request.invalidate(); page.value = 1; if (debounce) timer = setTimeout(() => void load(), 300); else void load() }
watch(keyword, () => reset(true), { flush: 'sync' })
watch([source, part, review, size], () => reset(), { flush: 'sync' })
watch(() => props.visible, visible => { if (visible) { void load(); void loadSummary() } else { clearTimeout(timer); request.invalidate() } }, { immediate: true })
watch(() => user.token, () => { generation++; clearTimeout(timer); request.clear(); request.data.value = undefined; request.hasCurrentData.value = false; summary.value = undefined; keyword.value = ''; error.value = '' }, { flush: 'sync' })
onBeforeUnmount(() => { clearTimeout(timer); generation++; request.invalidate() })
async function refresh() { error.value = ''; await Promise.all([load(true), loadSummary()]) }
function flags(row: MoldSourceCode) {
  const result: string[] = []
  if (row.disabled) result.push(row.sourceSystem === 'erp' ? 'ERP 已停用' : '钉钉来源已停用')
  if (row.sourceNameCount > 1) result.push('同编码跨来源名称不一致，未相互覆盖')
  if (!row.partType) result.push('非标准编码，人工分类')
  else { if (row.pcCount !== 1 || row.tpuCount !== 1) result.push('PC / TPU 不完整'); if (row.nameCount > 1) result.push('PC / TPU 名称不一致') }
  if (row.archiveCount !== 1) result.push(row.archiveCount ? '档案匹配有歧义' : '尚未匹配档案')
  return result.length ? result : ['编码对应可核对（不是实物确认）']
}
async function openArchive(row: MoldSourceCode) {
  if (!row.itemId || row.archiveCount !== 1) return
  const result = await router.push({ path: '/collaboration-plans', query: { view: 'market', itemId: row.itemId } })
  if (!isNavigationFailure(result)) emit('close')
}
</script>

<template>
  <section class="source-catalog">
    <div class="source-heading"><div><h2>ERP / 钉钉编码资料</h2><p>编码来源核对区 · 不代表实物套数 · 不写入库存或交付状态</p></div><el-button @click="refresh">刷新来源资料</el-button></div>
    <div v-if="summary" class="source-summary"><span>ERP 原记录 <b>{{ summary.erp }}</b></span><span>钉钉同步 <b>{{ summary.dingtalk }}</b></span><span>PC＋TPU 编码对 <b>{{ summary.paired }}</b></span><span>非标准编码 <b>{{ summary.nonstandard }}</b></span><span>名称不一致 <b>{{ summary.name_conflicts }}</b></span><span v-if="summary.source_conflicts">跨来源同码冲突 <b>{{ summary.source_conflicts }}</b></span></div>
    <el-alert title="历史资料仅供核对，未自动建立任何实物模具套。名称不一致、缺少部件或非标准编码需人工确认；相同编码可有多套实物。" type="warning" :closable="false" />
    <div class="source-filters"><el-input v-model="keyword" clearable placeholder="搜索 ERP 原编码 / 名称 / 规格 / 型号 / 别名" /><el-select v-model="source" aria-label="编码来源"><el-option label="全部来源" value="" /><el-option label="DeepLinkERP" value="erp" /><el-option label="钉钉双写" value="dingtalk" /></el-select><el-select v-model="part" clearable placeholder="全部部件"><el-option label="PC" value="PC" /><el-option label="TPU" value="TPU" /><el-option label="非标准编码" value="nonstandard" /></el-select><el-select v-model="review" clearable placeholder="全部核对情况"><el-option label="唯一匹配档案" value="matched" /><el-option label="尚未唯一匹配" value="unmatched" /><el-option label="部件不完整" value="incomplete" /><el-option label="名称不一致" value="name_conflict" /><el-option label="跨来源同码冲突" value="source_conflict" /><el-option label="ERP 已停用" value="disabled" /><el-option label="非标准编码" value="nonstandard" /></el-select></div>
    <el-alert v-if="error || request.error.value" :title="error || request.error.value" type="error" :closable="false" />
    <div class="source-total">共 {{ total }} 条来源编码 · 原编码及前导零保留 · 档案只按款式编码＋手机型号编码精确核对</div>
    <FixedTableViewport v-slot="{ tableHeight }" fill :refresh-key="rows"><el-table :data="rows" :height="tableHeight" v-loading="request.loading.value" row-key="sourceCodeId" border>
      <el-table-column fixed="left" label="原模具编码 / 部件" width="190"><template #default="{ row }"><strong>{{ row.moldCode }}</strong><div class="source-sub">{{ row.partType || '待分类' }} · {{ row.sourceSystem === 'erp' ? 'DeepLinkERP' : '钉钉' }}</div></template></el-table-column>
      <el-table-column label="来源名称 / 规格" min-width="310"><template #default="{ row }"><div class="source-name">{{ row.moldName }}</div><div class="source-sub">{{ row.specifications || '无规格' }}</div><div v-if="row.originalAlias" class="source-sub">原别名：{{ row.originalAlias }}</div></template></el-table-column>
      <el-table-column label="来源分类" width="200" prop="itemGroup" />
      <el-table-column label="款式编码 / 手机型号编码" width="200"><template #default="{ row }"><div>{{ row.styleCode || '待核对' }}</div><div>{{ row.phoneModelCode || '待核对' }}</div></template></el-table-column>
      <el-table-column label="PLM 协作档案" min-width="300"><template #default="{ row }"><template v-if="row.itemId"><div>{{ row.styleName }}</div><div class="source-sub">{{ row.compatibleModels }}</div><el-button link type="primary" @click="openArchive(row)">查看关联档案（不创建实物）</el-button></template><span v-else>{{ row.archiveCount ? '存在多个候选，待确认' : '尚未唯一匹配' }}</span></template></el-table-column>
      <el-table-column label="核对情况" min-width="270"><template #default="{ row }"><div v-for="flag in flags(row)" :key="flag" class="source-flag">{{ flag }}</div><div v-if="row.sourceSystem === 'dingtalk'" class="source-sub">{{ row.approvalInstanceId ? '审批实例：' + row.approvalInstanceId : '来源未提供审批实例 ID，不虚构审批记录' }}</div></template></el-table-column>
    </el-table></FixedTableViewport>
    <el-pagination v-model:current-page="page" v-model:page-size="size" :page-sizes="[20, 50, 100]" :total="total" layout="total, sizes, prev, pager, next, jumper" @current-change="load()" />
  </section>
</template>

<style scoped>
.source-catalog{height:100%;min-height:0;display:flex;flex-direction:column;gap:16px}.source-heading{display:flex;justify-content:space-between;gap:20px;align-items:center;flex:none}.source-heading h2{margin:0;font-size:23px}.source-heading p{color:#7890a5;margin:8px 0 0}.source-summary{display:flex;flex-wrap:wrap;gap:16px 32px;background:#eef5ff;padding:16px 20px;border-radius:8px;font-size:14px}.source-summary b{margin-left:8px;color:#2f6196;font-size:20px}.source-filters{display:flex;gap:14px;flex-wrap:wrap}.source-filters .el-input{flex:1;min-width:300px}.source-filters .el-select{width:185px}.source-total,.source-sub{font-size:12px;color:#7d8fa2;line-height:1.8}.source-name{white-space:pre-wrap;overflow-wrap:anywhere}.source-flag{line-height:1.8;font-size:13px}.source-catalog :deep(.cell){padding:12px}.source-catalog .el-pagination{flex:none;justify-content:flex-end;padding-top:8px}
</style>
