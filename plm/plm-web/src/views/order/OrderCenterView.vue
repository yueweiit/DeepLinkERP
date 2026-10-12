<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { getOrders, type OrderStatus, type OrderVO } from '@/api/modules/order'
import FixedTableViewport from '@/components/FixedTableViewport/index.vue'
import PageContainer from '@/components/PageContainer/index.vue'

const filters = reactive({ progress: 'all', source: '', keyword: '' })
const rows = ref<OrderVO[]>([])
const loading = ref(false)
const filteredRows = computed(() => rows.value.filter(row => filters.progress === 'all' || (filters.progress === 'in_progress' ? ['draft', 'confirmed', 'in_production'].includes(row.status) : ['completed', 'closed'].includes(row.status))))
const statusNames: Record<OrderStatus, string> = { draft: '草稿', confirmed: '已确认', in_production: '进行中', completed: '已完成', closed: '已关闭' }
const typeNames = { customer_requirement: '客户订单', market_requirement: '市场需求' }
async function load() { loading.value = true; try { rows.value = (await getOrders({ page: 1, size: 100, keyword: filters.keyword || undefined, source: filters.source || undefined })).content } finally { loading.value = false } }
watch(() => [filters.source, filters.keyword], load)
onMounted(load)
</script>

<template>
  <PageContainer title="需求订单">
    <section class="page-panel order-toolbar">
      <el-select v-model="filters.progress" class="order-toolbar__select"><el-option label="全部" value="all" /><el-option label="进行中订单" value="in_progress" /><el-option label="历史订单" value="history" /></el-select>
      <el-select v-model="filters.source" clearable class="order-toolbar__select" placeholder="订单类型"><el-option label="客户订单" value="customer" /><el-option label="市场需求" value="market" /></el-select>
      <el-input v-model="filters.keyword" clearable class="order-toolbar__search" placeholder="搜索钉钉审批编号 / 订单号 / 手机型号 / 产品 / 类型" />
    </section>
    <section class="page-panel">
      <div class="toolbar-row"><div><h3 class="section-title">订单列表</h3><p class="page-panel-desc">项目状态与需求订单状态同步更新。</p></div><el-tag>{{ filteredRows.length }} 条</el-tag></div>
      <FixedTableViewport v-slot="{ tableHeight }" :refresh-key="filteredRows">
      <el-table v-loading="loading" :data="filteredRows" :height="tableHeight" border stripe size="small" empty-text="当前筛选条件下没有需求订单">
        <el-table-column prop="dingTalkApprovalNo" label="钉钉审批编号" min-width="170" />
        <el-table-column prop="orderCode" label="订单号" min-width="170" />
        <el-table-column label="手机型号" min-width="140"><template #default="{ row }">{{ row.projectType === 'product_line' ? '--' : (row.phoneModel || '--') }}</template></el-table-column>
        <el-table-column label="类型" width="120"><template #default="{ row }">{{ typeNames[row.orderType as keyof typeof typeNames] || row.orderType }}</template></el-table-column>
        <el-table-column prop="productName" label="关联产品" min-width="180" />
        <el-table-column label="状态" width="110"><template #default="{ row }"><el-tag>{{ statusNames[row.status as OrderStatus] }}</el-tag></template></el-table-column>
        <el-table-column prop="createdAt" label="时间" min-width="150" />
        <el-table-column label="操作" width="90" fixed="right"><template #default><el-button link type="primary">更多</el-button></template></el-table-column>
      </el-table>
      </FixedTableViewport>
    </section>
  </PageContainer>
</template>

<style scoped>.order-toolbar{display:flex;gap:12px;flex-wrap:wrap}.order-toolbar__select{width:180px}.order-toolbar__search{max-width:420px;margin-left:auto}</style>
