<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { getCustomerDetail } from '@/api/modules/customer'
import OperateLog from '@/components/OperateLog/index.vue'
import PageContainer from '@/components/PageContainer/index.vue'
import type { CustomerDetail } from '@/types/customer'

import CustomerStatusBadge from './components/CustomerStatusBadge.vue'

const route = useRoute()
const router = useRouter()
const detail = ref<CustomerDetail | null>(null)
const loading = ref(false)

async function loadDetail() {
  loading.value = true
  try {
    detail.value = await getCustomerDetail(Number(route.params.id))
  } finally {
    loading.value = false
  }
}

onMounted(loadDetail)
</script>

<template>
  <PageContainer v-if="detail" :title="detail.customerName" description="查看客户基础资料、关联订单 / 需求与操作历史。">
    <template #actions>
      <el-button @click="router.back()">返回</el-button>
      <el-button type="primary" @click="router.push(`/customers/${detail.customerId}/edit`)">编辑</el-button>
    </template>

    <section class="page-panel" v-loading="loading">
      <div class="toolbar-row">
        <div>
          <h2 class="page-panel-title">{{ detail.customerCode }}</h2>
          <p class="page-panel-desc">责任人：{{ detail.ownerUserName }}</p>
        </div>
        <CustomerStatusBadge :status="detail.status" />
      </div>

      <div class="detail-grid" style="margin-top: 20px">
        <el-descriptions :column="1" border>
          <el-descriptions-item label="客户简称">{{ detail.customerShortName }}</el-descriptions-item>
          <el-descriptions-item label="国家 / 地区">{{ detail.countryCode }}</el-descriptions-item>
          <el-descriptions-item label="来源类型">{{ detail.sourceType }}</el-descriptions-item>
          <el-descriptions-item label="地址">{{ detail.address }}</el-descriptions-item>
        </el-descriptions>
        <el-descriptions :column="1" border>
          <el-descriptions-item label="联系人">{{ detail.contactName }}</el-descriptions-item>
          <el-descriptions-item label="联系电话">{{ detail.contactPhone }}</el-descriptions-item>
          <el-descriptions-item label="邮箱">{{ detail.contactEmail }}</el-descriptions-item>
          <el-descriptions-item label="最近更新时间">{{ detail.updatedAt }}</el-descriptions-item>
        </el-descriptions>
      </div>
    </section>

    <section class="split-grid">
      <article class="page-panel">
        <h3 class="section-title">关联订单 / 需求</h3>
        <el-empty v-if="!detail.relatedOrders.length" description="暂无关联订单" />
        <el-table v-else :data="detail.relatedOrders" border stripe>
          <el-table-column prop="orderCode" label="订单编码" min-width="180" />
          <el-table-column prop="orderTitle" label="需求标题" min-width="220" />
          <el-table-column prop="productName" label="关联产品" min-width="180" />
          <el-table-column prop="status" label="状态" width="120" />
        </el-table>
      </article>

      <article class="page-panel">
        <h3 class="section-title">操作日志</h3>
        <OperateLog :logs="detail.operationLogs" />
      </article>
    </section>
  </PageContainer>
</template>
