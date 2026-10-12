<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { getOperationLogs, getSystemUsers, type OperationLogItem, type OperationLogQuery } from '@/api/modules/system'
import type { PilotUser } from '@/types/pilot'
import { useUserStore } from '@/stores/user'
import { useCachedRequest } from '@/composables/useCachedRequest'
import PageContainer from '@/components/PageContainer/index.vue'
import FixedTableViewport from '@/components/FixedTableViewport/index.vue'

const user = useUserStore(), accounts = ref<PilotUser[]>([]), operatorUserId = ref<number>(), action = ref('')
const timeRange = ref<[string,string] | null>(null), page = ref(1), size = ref(50), error = ref(''), selected = ref<OperationLogItem>(), detailVisible = ref(false)
const request = useCachedRequest(getOperationLogs)
const rows = computed(() => request.hasCurrentData.value ? request.data.value?.content || [] : [])
const total = computed(() => request.data.value?.totalElements || 0)
let timer: ReturnType<typeof setTimeout> | undefined, generation = 0
function query(): OperationLogQuery { return { page:page.value,size:size.value,operatorUserId:operatorUserId.value,action:action.value.trim() || undefined,createdFrom:timeRange.value?.[0],createdTo:timeRange.value?.[1] } }
function load(force = false) {
  clearTimeout(timer); error.value = ''
  if (!user.token) return Promise.resolve()
  if (timeRange.value && timeRange.value[0] > timeRange.value[1]) { error.value='结束时间不能早于开始时间';request.invalidate();request.hasCurrentData.value=false;return Promise.resolve() }
  return request.execute(query(),force)
}
function reset(debounce = false) { clearTimeout(timer);page.value=1;request.invalidate();if(debounce)timer=setTimeout(()=>void load(),300);else void load() }
watch(action,()=>reset(true))
watch([operatorUserId,timeRange,size],()=>reset())
watch(()=>user.token,()=>{generation++;clearTimeout(timer);request.clear();request.data.value=undefined;request.hasCurrentData.value=false;accounts.value=[];selected.value=undefined;detailVisible.value=false})
function clearFilters() { operatorUserId.value=undefined;action.value='';timeRange.value=null }
function open(row:OperationLogItem) { selected.value=row;detailVisible.value=true }
const display=(value:unknown)=>value==null || value===''?'未记录':String(value)
const timestamp=(value:string)=>value.replace('T',' ')
const loginName=(id:number | null)=>accounts.value.find(account=>account.userId===id)?.username
const detail = computed(()=>{
  if(!selected.value?.detailJson)return '该历史记录未保存详情。'
  try { const parsed:unknown=JSON.parse(selected.value.detailJson);return parsed && typeof parsed==='object'?JSON.stringify(parsed,null,2):'详情不是结构化对象，未直接展示原文。' }
  catch { return '详情格式无法安全显示；未直接展示原文。' }
})
onMounted(async()=>{
  const ticket=++generation,token=user.token
  void load()
  try { const result=await getSystemUsers();if(ticket===generation && token===user.token)accounts.value=result }
  catch { if(ticket===generation)error.value='真实账号列表加载失败，可重试或继续查看已有日志。' }
})
onBeforeUnmount(()=>{generation++;clearTimeout(timer)})
</script>

<template>
  <PageContainer class="operation-log-page" title="操作日志" description="仅展示实际写入的操作记录，不代表全部查询、下载或失败请求均已审计。">
    <template #actions><el-button @click="load(true)">刷新日志</el-button></template>
    <section class="page-panel operation-log-panel">
      <div class="log-filters">
        <el-select v-model="operatorUserId" clearable filterable placeholder="全部真实账号" aria-label="操作账号"><el-option v-for="account in accounts" :key="account.userId" :value="account.userId" :label="`${account.displayName} · ${account.username}${account.status==='inactive'?'（已停用）':''}`" /></el-select>
        <el-input v-model="action" clearable placeholder="动作代码（精确匹配，如 AUTH_LOGIN）" aria-label="动作代码" />
        <el-date-picker v-model="timeRange" type="datetimerange" value-format="YYYY-MM-DDTHH:mm:ss" start-placeholder="开始时间（服务器本地）" end-placeholder="结束时间（服务器本地）" range-separator="至" aria-label="操作时间范围" />
        <el-button @click="clearFilters">清除筛选</el-button>
      </div>
      <p class="log-note">默认每页 50 条，筛选由服务器执行；时间沿用日志响应，不作时区转换。历史记录保留当时的操作人名称与账号 ID。</p>
      <el-alert v-if="error || request.error.value" :title="error || request.error.value" type="error" :closable="false" />
      <FixedTableViewport v-slot="{tableHeight}" fill :refresh-key="rows"><el-table :data="rows" :height="tableHeight" v-loading="request.loading.value" row-key="logId" border class="operation-log-table">
        <el-table-column label="记录时间" width="180"><template #default="{row}">{{ timestamp(row.createdAt) }}</template></el-table-column>
        <el-table-column label="真实操作者" min-width="180"><template #default="{row}"><strong>{{ display(row.operatorUserName) }}</strong><small v-if="row.operatorUserId!=null">账号 ID {{ row.operatorUserId }}<span v-if="loginName(row.operatorUserId)"> · {{ loginName(row.operatorUserId) }}</span></small></template></el-table-column>
        <el-table-column prop="action" label="动作代码" min-width="230" />
        <el-table-column label="业务对象" min-width="220"><template #default="{row}">{{ display(row.businessName) }}<small>{{ display(row.businessType) }} · ID {{ display(row.businessId) }}<span v-if="row.businessCode"> · {{ row.businessCode }}</span></small></template></el-table-column>
        <el-table-column label="结果" width="100"><template #default="{row}"><el-tag :type="row.result==='success'?'success':'info'">{{ row.result==='success'?'成功':display(row.result) }}</el-tag></template></el-table-column>
        <el-table-column prop="requestId" label="请求追踪 ID" min-width="220" />
        <el-table-column label="已有详情" fixed="right" width="110"><template #default="{row}"><el-button link type="primary" @click="open(row)">查看详情</el-button></template></el-table-column>
        <template #empty>暂无符合条件的实际操作记录。</template>
      </el-table></FixedTableViewport>
      <el-pagination v-model:current-page="page" v-model:page-size="size" :page-sizes="[20,50,100]" :total="total" layout="total,sizes,prev,pager,next,jumper" @current-change="load()" />
    </section>
    <el-drawer v-model="detailVisible" title="已有操作详情" size="min(1100px,95vw)"><section v-if="selected" class="log-detail">
      <dl><dt>真实操作者（历史名称）</dt><dd>{{ display(selected.operatorUserName) }} · 账号 ID {{ display(selected.operatorUserId) }}</dd><dt>记录时间</dt><dd>{{ timestamp(selected.createdAt) }}</dd><dt>动作代码</dt><dd>{{ selected.action }}</dd><dt>业务对象</dt><dd>{{ display(selected.businessType) }} · {{ display(selected.businessId) }} · {{ display(selected.businessName) }}</dd><dt>请求追踪 ID</dt><dd>{{ display(selected.requestId) }}</dd></dl>
      <el-alert title="下方为该记录已有的 detailJson；敏感凭据由服务器统一脱敏。没有详情不表示操作未发生，也不补造旧记录。" type="info" :closable="false" />
      <pre data-test="operation-log-detail">{{ detail }}</pre>
    </section></el-drawer>
  </PageContainer>
</template>
<style scoped>
.operation-log-page{height:100%;min-height:0;display:flex;flex-direction:column}.operation-log-page>:deep(header){flex:none}
.operation-log-panel{flex:1;min-height:0}.operation-log-panel>.log-filters,.operation-log-panel>.log-note,.operation-log-panel>.el-alert,.operation-log-panel>.el-pagination{flex:none}
.operation-log-panel{display:flex;flex-direction:column;gap:16px;min-width:0}.log-filters{display:flex;gap:12px;flex-wrap:wrap;align-items:center}.log-filters>.el-select{width:240px}.log-filters>.el-input{min-width:280px;flex:1}.log-filters :deep(.el-date-editor){min-width:400px;flex:1}.log-note{margin:0;font-size:12px;color:#718399;line-height:1.8}.operation-log-table small{display:block;color:#748399;font-size:12px;margin-top:6px}.operation-log-panel .el-pagination{justify-content:flex-end}.log-detail{display:flex;flex-direction:column;gap:20px}.log-detail dl{display:grid;grid-template-columns:190px minmax(0,1fr);gap:14px;margin:0}.log-detail dt{color:#718399}.log-detail dd{margin:0;overflow-wrap:anywhere}.log-detail pre{margin:0;padding:20px;background:#f4f7fb;border:1px solid #e1e8f2;border-radius:8px;white-space:pre-wrap;overflow-wrap:anywhere;line-height:1.7;font-size:13px}@media(max-width:680px){.log-filters :deep(.el-date-editor){min-width:0;width:100%;flex-basis:100%}.log-detail dl{grid-template-columns:1fr}}
</style>
