<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { getScheduleTasks, type ScheduleTask } from '@/api/modules/schedule'
import { getFinanceSummary, exportBudgetFile, type FinanceValue } from '@/api/modules/development'
import { getTrials, getTrialMetrics, exportTrial, type Trial } from '@/api/modules/pilotDelivery'
import { useUserStore } from '@/stores/user'
import FixedTableViewport from '@/components/FixedTableViewport/index.vue'
import PageContainer from '@/components/PageContainer/index.vue'
const user=useUserStore(),route=useRoute(),router=useRouter(),loading=ref(false),error=ref(''),keyword=ref(''),page=ref(1),total=ref(0),overdue=ref(false),currency=ref(''),trialId=ref<number|null>(null)
const tasks=ref<ScheduleTask[]>([]),budgets=ref<Record<string,FinanceValue>[]>([]),expenses=ref<Record<string,FinanceValue>[]>([]),rules=ref<string[]>([]),trials=ref<Trial[]>([]),metrics=ref<Record<string,unknown>|null>(null)
const view=computed(()=>['schedule','finance','pilot'].includes(String(route.query.view||''))?String(route.query.view):'schedule')
const views=computed(()=>[{key:'schedule',label:'项目周期',permission:'report:view'},{key:'finance',label:'预算与实际',permission:'finance:read'},{key:'pilot',label:'试点评估',permission:'report:view'}].filter(v=>user.hasPermission(v.permission)))
const allowed=computed(()=>user.hasPermission(view.value==='finance'?'finance:read':'report:view'))
const projects=computed(()=>Array.isArray(metrics.value?.projects)?metrics.value.projects as Record<string,unknown>[]:[])
const baseline=computed(()=>metrics.value?.baseline && typeof metrics.value.baseline==='object'?metrics.value.baseline as Record<string,unknown>:{})
const baselineNames:Record<string,string>={moldLeadDays:'手工模式开模至验收周期（天）',bomPushMinutes:'手工BOM推送工时（分钟）',fileLookupMinutes:'手工资料查找工时（分钟）',communicationMinutes:'手工跨地域沟通工时（分钟）'}
const currencies=computed(()=>[...new Set([...budgets.value,...expenses.value].map(r=>String(r.currencyCode||'')).filter(Boolean))])
let generation=0
async function load(){const id=++generation;loading.value=true;error.value='';if(!allowed.value){error.value='没有当前报表查看权限';loading.value=false;return}
 try{if(view.value==='schedule'){const result=await getScheduleTasks({page:page.value,size:50,keyword:keyword.value,overdueOnly:overdue.value});if(id===generation){tasks.value=result.content;total.value=result.totalElements}}
 else if(view.value==='finance'){const query={page:1,size:50,keyword:keyword.value,currency:currency.value||undefined};const [a,b]=await Promise.all([getFinanceSummary('budget',query),getFinanceSummary('expense',query)]);if(id===generation){budgets.value=a.currencyGroups;expenses.value=b.currencyGroups;rules.value=[a.rule,b.rule]}}
 else{const available=await getTrials();if(id!==generation)return;trials.value=available;if(!trialId.value||!available.some(t=>t.trial_id===trialId.value))trialId.value=available[0]?.trial_id||null;const result=trialId.value?await getTrialMetrics(trialId.value):null;if(id===generation)metrics.value=result}
 }catch{if(id===generation)error.value='真实报表加载失败，请重试；不会显示演示数据'}finally{if(id===generation)loading.value=false}}
function switchView(key:string){router.push({path:'/reports',query:{view:key}})}
function search(){page.value=1;void load()}
function cell(value:unknown){return value===null||value===undefined?'未知':String(value)}
function exportSchedule(){const csv=[['实物编号','款式','兼容型号','待完成事项','计划日期','逾期'],...tasks.value.map(t=>[t.assetNumber,t.styleName,t.compatibleModels,t.title,t.dueDate||'',t.overdue?'是':'否'])].map(row=>row.map(value=>'"'+String(value).replace(/^[=+\-@\t\r]/,"'$&").replace(/"/g,'""')+'"').join(',')).join('\r\n');download(new Blob(['\uFEFF'+csv],{type:'text/csv;charset=utf-8'}),'项目周期-当前页.csv')}
function download(blob:Blob,name:string){const url=URL.createObjectURL(blob),link=document.createElement('a');link.href=url;link.download=name;link.click();URL.revokeObjectURL(url)}
async function exportBudget(){try{download(await exportBudgetFile({page:1,size:50,keyword:keyword.value,currency:currency.value||undefined}),'模具成本预算.xlsx')}catch{error.value='预算导出失败或无金额导出权限'}}
async function exportPilot(){if(trialId.value)try{await exportTrial(trialId.value)}catch{error.value='试点归档导出失败，请核对对象及金额导出权限'}}
watch(view,()=>{page.value=1;tasks.value=[];budgets.value=[];expenses.value=[];metrics.value=null;void load()})
onMounted(load)
</script>
<template>
 <PageContainer title="报表中心" description="从唯一业务记录读取计划、预算、实际与试点基准；不混币相加，不从零散备注猜测数据。">
  <div class="report-toolbar"><el-button v-for="option in views" :key="option.key" :type="view===option.key?'primary':'default'" @click="switchView(option.key)">{{option.label}}</el-button><el-button @click="load">刷新</el-button></div>
  <el-alert v-if="error" :title="error" type="error" :closable="false"/>
  <section v-if="allowed" v-loading="loading" class="report-body">
   <template v-if="view==='schedule'">
    <div class="report-toolbar"><el-input v-model="keyword" placeholder="搜索款式 / 型号 / 模具" @keyup.enter="search"/><el-checkbox v-model="overdue" @change="search">只看逾期</el-checkbox><el-button @click="search">查询</el-button><el-button :disabled="!tasks.length" @click="exportSchedule">导出当前页 CSV</el-button></div>
    <p>按计划任务查看推进与逾期；未完成任务是事实清单，不将流程确认时间当作实际交付。</p>
    <FixedTableViewport v-slot="{tableHeight}" :refresh-key="tasks"><el-table :data="tasks" :height="tableHeight" border empty-text="当前条件没有待完成计划任务"><el-table-column prop="assetNumber" label="实物编号" width="170" fixed="left"/><el-table-column prop="styleName" label="款式" min-width="180"/><el-table-column prop="compatibleModels" label="兼容手机型号" min-width="280"/><el-table-column prop="title" label="计划任务" min-width="200"/><el-table-column prop="dueDate" label="计划日期" width="140"/><el-table-column label="推进状态" width="130"><template #default="{row}">{{row.overdue?'已逾期':'待完成'}}</template></el-table-column><el-table-column label="操作" width="110" fixed="right"><template #default="{row}"><el-button link @click="router.push({path:'/mold-schedules',query:{moldSetId:row.moldSetId}})">查看源记录</el-button></template></el-table-column></el-table></FixedTableViewport>
    <el-pagination v-model:current-page="page" :page-size="50" :total="total" layout="total,prev,pager,next" @current-change="load"/>
   </template>
   <template v-else-if="view==='finance'">
    <div class="report-toolbar"><el-input v-model="keyword" placeholder="预算 / 款式 / 型号关键词" @keyup.enter="search"/><el-select v-model="currency" clearable placeholder="全部原币"><el-option v-for="c in currencies" :key="c" :value="c" :label="c"/></el-select><el-button @click="search">查询</el-button><el-button v-if="user.hasPermission('finance:export')" @click="exportBudget">导出预算明细 Excel</el-button></div>
    <el-alert v-for="rule in rules" :key="rule" :title="rule" type="info" :closable="false"/>
    <h3>预算结构（按层级与原币分组，不汇总混加）</h3><el-table :data="budgets" border empty-text="尚无符合条件的真实预算"><el-table-column prop="currencyCode" label="原币" width="120"/><el-table-column label="预算层级" width="170"><template #default="{row}">{{row.budgetKind==='platform'?'产品平台研发预算':'模具预算'}}</template></el-table-column><el-table-column prop="recordCount" label="预算记录数" width="150"/><el-table-column label="已知预算金额" min-width="170"><template #default="{row}">{{cell(row.budgetTotal)}}</template></el-table-column><el-table-column prop="unknownCount" label="金额仍未知的记录" min-width="180"/></el-table>
    <h3>开发费用事实（审批、申报、入账分开）</h3><el-table :data="expenses" border empty-text="尚无符合条件的真实费用"><el-table-column prop="currencyCode" label="原币" width="110"/><el-table-column prop="recordCount" label="记录数" width="100"/><el-table-column label="申请金额" min-width="140"><template #default="{row}">{{cell(row.requestedTotal)}}</template></el-table-column><el-table-column label="批准金额" min-width="140"><template #default="{row}">{{cell(row.approvedTotal)}}</template></el-table-column><el-table-column label="手工申报（已确认）" min-width="180"><template #default="{row}">{{cell(row.declaredTotal)}}</template></el-table-column><el-table-column label="ERP入账净额" min-width="160"><template #default="{row}">{{cell(row.erpPostedNet)}}</template></el-table-column><el-table-column prop="unmappedCount" label="待归属" width="120"/></el-table>
    <p>本页不把两个独立层级预算相加，也不把批准金额或手工申报当作ERP已入账。</p>
   </template>
   <template v-else>
    <div class="report-toolbar"><el-select v-model="trialId" placeholder="选择已配置的真实试点" @change="load"><el-option v-for="trial in trials" :key="trial.trial_id" :value="trial.trial_id" :label="trial.name"/></el-select><el-button v-if="user.hasPermission('finance:export')" :disabled="!trialId" @click="exportPilot">导出完整试点归档</el-button><el-button v-if="user.hasPermission('pilot:admin')" @click="router.push('/system/trials')">配置范围与手工基准</el-button></div>
    <el-empty v-if="!trialId" description="尚未配置真实试点范围，不生成演示评估指标"/>
    <template v-else-if="metrics"><el-alert :title="cell(metrics.message)" type="info" :closable="false"/><h3>已授权项目与资料</h3><p>当前试点授权文件数：{{cell(metrics.fileCount)}}</p><el-table :data="projects" border><el-table-column prop="product_code" label="项目编码" width="180"/><el-table-column prop="product_name" label="项目名称" min-width="220"/><el-table-column prop="model" label="手机型号" min-width="220"/><el-table-column prop="status" label="状态" width="120"/><el-table-column prop="created_at" label="建档时间" min-width="190"/><el-table-column prop="updated_at" label="最近更新时间" min-width="190"/></el-table><h3>手工模式基准（由负责人录入）</h3><dl class="baseline"><template v-for="(name,key) in baselineNames" :key="key"><dt>{{name}}</dt><dd>{{cell(baseline[key])}}</dd></template></dl><p>计划 / 实际日期、各原币费用和真实集成结果分别见源业务页面；不据本页自动宣称试点通过或缩短物理周期。</p></template>
   </template>
  </section>
 </PageContainer>
</template>
<style scoped>.report-toolbar{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin-bottom:16px}.report-toolbar .el-input{max-width:400px}.report-toolbar .el-select{min-width:200px}.report-body{width:100%;display:flex;flex-direction:column;gap:16px;min-width:0}p{color:#64748b;line-height:1.7}h3{margin:12px 0 0}.baseline{display:grid;grid-template-columns:minmax(220px,1fr) minmax(180px,1fr);gap:14px;border:1px solid #e2e8f0;padding:20px}.baseline dd{margin:0}.el-alert{margin-bottom:10px}</style>
