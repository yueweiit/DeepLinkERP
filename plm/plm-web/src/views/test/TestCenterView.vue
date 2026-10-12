<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import { getTestCenterSnapshot } from '@/api/modules/foundation'
import FixedTableViewport from '@/components/FixedTableViewport/index.vue'
import PageContainer from '@/components/PageContainer/index.vue'
import SearchBar from '@/components/SearchBar/index.vue'
import type { SearchField } from '@/types/common'
import type { TestCategoryItem, TestRecordItem } from '@/types/foundation'
import { formatDate } from '@/utils/format'
import { toArchivedProductRoute } from '@/utils/projectRoute'

const router = useRouter()
const loading = ref(false)
const categories = ref<TestCategoryItem[]>([])
const records = ref<TestRecordItem[]>([])
const keyword = ref('')
const selectedResult = ref('')

const searchFields: SearchField[] = [
  { prop: 'keyword', label: '记录搜索', type: 'input', placeholder: '产品名 / 测试项 / 备注' },
  {
    prop: 'result',
    label: '结果',
    type: 'select',
    options: [
      { label: '全部', value: '' },
      { label: '通过', value: '通过' },
      { label: '不通过', value: '不通过' },
      { label: '复测中', value: '复测中' }
    ]
  }
]

const filteredRecords = computed(() => {
  const search = keyword.value.trim().toLowerCase()
  return records.value.filter((item) => {
    const resultMatched = !selectedResult.value || item.result === selectedResult.value
    const keywordMatched =
      !search ||
      item.productName.toLowerCase().includes(search) ||
      item.testCategory.toLowerCase().includes(search) ||
      item.note.toLowerCase().includes(search)
    return resultMatched && keywordMatched
  })
})

const metrics = computed(() => [
  { label: '测试种类', value: categories.value.length, hint: '只保留业务真正需要的测试类型' },
  { label: '测试记录', value: records.value.length, hint: '按日期倒序查看执行结果' },
  { label: '复测中', value: records.value.filter((item) => item.result === '复测中').length, hint: '优先回到对应产品节点处理' },
  { label: '已通过', value: records.value.filter((item) => item.result === '通过').length, hint: '可继续推进下一业务环节' }
])

function openProduct(productId: number) {
  router.push(toArchivedProductRoute(productId))
}

async function loadData() {
  loading.value = true
  try {
    const snapshot = await getTestCenterSnapshot()
    categories.value = snapshot.categories
    records.value = snapshot.records
  } catch {
    categories.value = []
    records.value = []
  } finally {
    loading.value = false
  }
}

onMounted(loadData)
</script>

<template>
  <PageContainer title="测试管理" description="页面只保留两块：测试种类和测试记录。先知道测什么，再知道谁测过、结果如何。">
    <section class="metric-grid">
      <div v-for="metric in metrics" :key="metric.label" class="metric-card">
        <p class="metric-card__label">{{ metric.label }}</p>
        <p class="metric-card__value">{{ metric.value }}</p>
        <span class="metric-card__trend">{{ metric.hint }}</span>
      </div>
    </section>

    <SearchBar
      :fields="searchFields"
      :model-value="{ keyword, result: selectedResult }"
      @search="
        (value) => {
          keyword = String(value.keyword || '')
          selectedResult = String(value.result || '')
        }
      "
      @reset="
        () => {
          keyword = ''
          selectedResult = ''
        }
      "
    />

    <section class="split-grid test-layout" v-loading="loading">
      <article class="page-panel">
        <div class="toolbar-row">
          <div>
            <h3 class="section-title">测试种类</h3>
            <p class="page-panel-desc">按常用测试种类维护，不堆 KPI，也不做趋势图。</p>
          </div>
          <el-button type="primary" plain>新增测试种类</el-button>
        </div>

        <div class="category-grid">
          <section v-for="item in categories" :key="item.categoryId" class="category-card">
            <strong>{{ item.categoryName }}</strong>
            <p class="page-panel-desc">{{ item.method }}</p>
            <div class="toolbar-row">
              <span class="subtle-text">默认阶段：{{ item.defaultFrequency }}</span>
              <span class="subtle-text">{{ item.owner }}</span>
            </div>
          </section>
        </div>
      </article>

      <article class="page-panel">
        <div class="toolbar-row">
          <div>
            <h3 class="section-title">测试记录</h3>
            <p class="page-panel-desc">记录只关心产品、测试项、结果、执行人和备注。</p>
          </div>
          <el-button type="primary">新增测试记录</el-button>
        </div>

        <FixedTableViewport v-slot="{ tableHeight }" :refresh-key="filteredRecords">
        <el-table :data="filteredRecords" :height="tableHeight" border stripe>
          <el-table-column prop="productName" label="关联产品" min-width="220" />
          <el-table-column prop="testCategory" label="测试项" min-width="140" />
          <el-table-column label="结果" width="120">
            <template #default="{ row }">
              <el-tag :type="row.result === '通过' ? 'success' : row.result === '不通过' ? 'danger' : 'warning'" effect="light">
                {{ row.result }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="owner" label="测试人" width="120" />
          <el-table-column label="日期" width="120">
            <template #default="{ row }">{{ formatDate(row.testedAt) }}</template>
          </el-table-column>
          <el-table-column prop="note" label="备注" min-width="260" />
          <el-table-column label="操作" width="120">
            <template #default="{ row }">
              <el-button link type="primary" @click="openProduct(row.productId)">查看节点</el-button>
            </template>
          </el-table-column>
        </el-table>
        </FixedTableViewport>
      </article>
    </section>
  </PageContainer>
</template>

<style scoped>
.test-layout {
  grid-template-columns: 360px minmax(0, 1fr);
}

.category-grid {
  display: grid;
  grid-template-columns: 1fr;
  gap: 12px;
}

.category-card {
  padding: 14px;
  border: 1px solid var(--plm-color-border-light);
  border-radius: var(--plm-radius-base);
  background: #fff;
}

@media (max-width: 1200px) {
  .test-layout {
    grid-template-columns: 1fr;
  }
}
</style>
