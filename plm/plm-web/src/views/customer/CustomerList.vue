<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import { getCustomerList } from '@/api/modules/customer'
import FixedTableViewport from '@/components/FixedTableViewport/index.vue'
import PageContainer from '@/components/PageContainer/index.vue'
import SearchBar from '@/components/SearchBar/index.vue'
import { usePermission } from '@/composables/usePermission'
import { useTable } from '@/composables/useTable'
import type { SearchField } from '@/types/common'
import type { CustomerSummary } from '@/types/customer'

import CustomerStatusBadge from './components/CustomerStatusBadge.vue'

const router = useRouter()
const { hasPermission } = usePermission()
const rows = ref<CustomerSummary[]>([])
const loading = ref(false)

const searchFields: SearchField[] = [
  { prop: 'keyword', label: '关键词', type: 'input', placeholder: '编码 / 客户名 / 联系人' },
  {
    prop: 'status',
    label: '状态',
    type: 'select',
    options: [
      { label: '全部', value: '' },
      { label: '草稿', value: 'draft' },
      { label: '启用', value: 'active' },
      { label: '停用', value: 'inactive' }
    ]
  }
]

const table = useTable(rows, ['customerCode', 'customerName', 'contactName', 'countryCode'], (row, filters) => {
  const status = String(filters.status || '')
  return !status || row.status === status
})

async function loadCustomers() {
  loading.value = true
  try {
    rows.value = await getCustomerList()
  } catch {
    rows.value = []
  } finally {
    loading.value = false
  }
}

function handleSearch(form: Record<string, unknown>) {
  table.setQuery(form)
}

function handleReset() {
  table.resetQuery({ keyword: '', status: '' })
}

onMounted(loadCustomers)
</script>

<template>
  <PageContainer title="客户管理" description="统一维护客户来源、联系人、关联需求与操作日志。">
    <template #actions>
      <el-button v-if="hasPermission('customer:create')" type="primary" @click="router.push('/customers/create')">
        新建客户
      </el-button>
    </template>

    <SearchBar :fields="searchFields" @search="handleSearch" @reset="handleReset" />

    <section class="page-panel" v-loading="loading">
      <FixedTableViewport v-slot="{ tableHeight }" :refresh-key="table.pagedRows.value">
      <el-table :data="table.pagedRows.value" :height="tableHeight" border stripe>
        <el-table-column prop="customerCode" label="客户编码" min-width="170" />
        <el-table-column prop="customerName" label="客户名称" min-width="220" />
        <el-table-column prop="customerShortName" label="简称" width="120" />
        <el-table-column prop="countryCode" label="国家 / 地区" width="120" />
        <el-table-column prop="contactName" label="联系人" width="120" />
        <el-table-column prop="contactPhone" label="联系电话" min-width="150" />
        <el-table-column label="状态" width="120">
          <template #default="{ row }">
            <CustomerStatusBadge :status="row.status" />
          </template>
        </el-table-column>
        <el-table-column label="操作" width="160">
          <template #default="{ row }">
            <el-button link type="primary" @click="router.push(`/customers/${row.customerId}`)">详情</el-button>
            <el-button link @click="router.push(`/customers/${row.customerId}/edit`)">编辑</el-button>
          </template>
        </el-table-column>
      </el-table>
      </FixedTableViewport>

      <div class="toolbar-row" style="margin-top: 16px">
        <span class="subtle-text">共 {{ table.filteredRows.value.length }} 条</span>
        <el-pagination
          v-model:current-page="table.currentPage.value"
          v-model:page-size="table.pageSize.value"
          layout="prev, pager, next"
          :total="table.filteredRows.value.length"
        />
      </div>
    </section>
  </PageContainer>
</template>
