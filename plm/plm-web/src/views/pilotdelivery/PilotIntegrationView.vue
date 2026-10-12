<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { useRouter } from 'vue-router'
import { getIntegrationConfiguration, getDeliveryTasks, retryDeliveryTask, type DeliveryTask, type IntegrationConfiguration } from '@/api/modules/pilotDelivery'
const router = useRouter(), loading = ref(false), error = ref(''), page = ref(1), total = ref(0), status = ref(''), rows = ref<DeliveryTask[]>([])
const config = ref<IntegrationConfiguration | null>(null)
const statuses: Record<string, string> = { pending: '待发送', sending: '发送中', succeeded: '已取得业务回执', failed: '失败待重试', not_configured: '接入未配置' }
async function load() { loading.value = true; error.value = ''; try { const [a, b] = await Promise.all([getIntegrationConfiguration(), getDeliveryTasks(page.value, status.value || undefined)]); config.value = a; rows.value = b.content; total.value = b.totalElements } catch (e) { error.value = e instanceof Error ? e.message : '查询失败' } finally { loading.value = false } }
async function retry(row: DeliveryTask) { await retryDeliveryTask(row.task_id); ElMessage.success('已恢复待发送；实际成功以业务回执为准'); await load() }
onMounted(load)
</script>
<template>
 <section class="integration-page" v-loading="loading">
  <header><div><h2>系统对接</h2><p>正式 BOM 发布与 ERP 同步分开；失败任务持久保留，重试不生成新版本。</p></div><el-button @click="load">刷新</el-button><el-button @click="router.push('/system/trials')">试点范围与启动条件</el-button></header>
  <el-alert v-if="error" :title="error" type="error" :closable="false" />
  <div class="connection-state"><span>外发开关：{{ config?.enabled ? '已启用' : '未启用' }}</span><span>ERP BOM发送：{{ config?.erpConfigured ? '配置已提供，仍需联调' : '尚未配置' }}</span><span>ERP费用只读：{{ config?.erpExpensesConfigured ? '配置已提供，仍需联调' : '尚未配置' }}</span><span>钉钉通知：{{ config?.dingtalkConfigured ? '配置已提供，仍需联调' : '尚未配置' }}</span></div>
  <el-alert :title="config?.message || '凭据由运行环境提供，不在页面和代码中保存。'" type="info" :closable="false" />
  <el-select v-model="status" clearable placeholder="全部发送状态" @change="page=1;load()"><el-option v-for="(label,key) in statuses" :key="key" :label="label" :value="key" /></el-select>
  <el-table :data="rows" border height="calc(100vh - 365px)" empty-text="暂无同步任务。草稿不会进入队列；正式版本审核发布后生成持久任务。">
   <el-table-column prop="event_id" label="稳定业务事件" min-width="240" fixed="left"/><el-table-column prop="kind" label="对接类型" width="160"/><el-table-column label="状态" min-width="180"><template #default="{row}">{{ statuses[row.status] || row.status }}</template></el-table-column><el-table-column prop="attempts" label="尝试次数" width="105"/><el-table-column prop="last_error" label="最近错误" min-width="230"/><el-table-column prop="updated_at" label="更新时间" min-width="200"/><el-table-column label="操作" width="100" fixed="right"><template #default="{row}"><el-button v-if="['failed','not_configured'].includes(row.status)" link @click="retry(row)">重试</el-button></template></el-table-column>
  </el-table><el-pagination v-model:current-page="page" :total="total" :page-size="50" layout="total,prev,pager,next" @current-change="load"/>
 </section>
</template>
<style scoped>.integration-page{display:flex;flex-direction:column;gap:16px;width:100%;min-width:0}header,.connection-state{display:flex;align-items:center;gap:20px;flex-wrap:wrap}header>div{flex:1}h2{margin:0}p{color:#64748b;margin:8px 0}.connection-state{padding:18px;background:#f1f5f9;border-radius:8px}.el-select{width:230px}</style>
