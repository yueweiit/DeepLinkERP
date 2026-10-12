<script setup lang="ts">
import { computed, onActivated, onDeactivated, onMounted, onUnmounted, ref, watch } from 'vue'

import { getInventoryPage, getInventoryGroups } from '@/api/modules/foundation'
import { useCachedRequest } from '@/composables/useCachedRequest'
import FixedTableViewport from '@/components/FixedTableViewport/index.vue'
import PageContainer from '@/components/PageContainer/index.vue'
import type { InventoryListRow, InventoryTreeNode } from '@/types/foundation'
import { getStatusLabel } from '@/utils/status'

type ItemGroupValue = string
type TimeRangeValue = 'all' | '7d' | '30d' | '90d' | 'this_year'
type InventoryActionMode = 'select' | 'delete'

interface InventoryItemCreateForm {
  nodeId: string
  item_code: string
  item_name: string
  item_group: string
  stock_uom: string
  is_stock_item: 0 | 1
  is_sales_item: 0 | 1
  is_purchase_item: 0 | 1
}

type ItemGroupOption = {
  label: string
  value: ItemGroupValue
  children?: ItemGroupOption[]
}

defineOptions({ name: 'InventoryCenterView' })
const page = ref(1)
const size = ref(50)
const total = ref(0)
const pageRequest = useCachedRequest(getInventoryPage)
const groupRequest = useCachedRequest(() => getInventoryGroups())
const { loading, error } = pageRequest
let searchTimer: ReturnType<typeof setTimeout> | undefined
let active = true
let initialized = false
const items = ref<InventoryListRow[]>([])
const keyword = ref('')
const itemGroup = ref<ItemGroupValue>('all')
const timeRange = ref<TimeRangeValue>('all')
const actionMode = ref<InventoryActionMode>('select')
const selectedItemIds = ref<string[]>([])
const deleteConfirmVisible = ref(false)
const deleteLoading = ref(false)

const itemGroupCascaderProps = {
  checkStrictly: true,
  emitPath: false
} as const

const serverItemGroupOptions = ref<ItemGroupOption[]>([{ label: '全部物料', value: 'all' }])

function toItemGroupOptions(nodes: InventoryTreeNode[]): ItemGroupOption[] {
  return nodes.map((node) => ({
    label: node.label,
    value: node.nodeId,
    children: node.children?.length ? toItemGroupOptions(node.children) : undefined
  }))
}

function collectNodeIds(nodes: ItemGroupOption[], target: ItemGroupValue): string[] {
  for (const node of nodes) {
    if (node.value === target) return collectSelfAndChildren(node)
    const matched = node.children ? collectNodeIds(node.children, target) : []
    if (matched.length) return matched
  }
  return []
}

function collectSelfAndChildren(node: ItemGroupOption): string[] {
  return [node.value, ...(node.children || []).flatMap(collectSelfAndChildren)]
}

function findGroupLabel(nodes: ItemGroupOption[], target: ItemGroupValue): string | undefined {
  for (const node of nodes) {
    if (node.value === target) return node.label
    const childLabel = node.children ? findGroupLabel(node.children, target) : undefined
    if (childLabel) return childLabel
  }
  return undefined
}

const currentViewTitle = computed(() => findGroupLabel(serverItemGroupOptions.value, itemGroup.value) || '全部物料')

// Only the current server page is rendered. These filters preserve temporary local edits.
const currentRows = computed(() => {
  if (!pageRequest.hasCurrentData.value) return []
  const search = keyword.value.trim().toLowerCase()
  const nodes = collectNodeIds(serverItemGroupOptions.value, itemGroup.value)
  return items.value.filter((item) =>
    (itemGroup.value === 'all' || nodes.includes(item.nodeId)) &&
    (!search || [item.code, item.name, item.spec, item.supplierName, item.productName || '']
      .some((text) => text.toLowerCase().includes(search)))
  ).slice(0, size.value)
})

// ---- create item dialog ----
const createItemVisible = ref(false)
const createItemForm = ref<InventoryItemCreateForm>({
  nodeId: '',
  item_code: '',
  item_name: '',
  item_group: '',
  stock_uom: '',
  is_stock_item: 1,
  is_sales_item: 1,
  is_purchase_item: 1
})

function openCreateItemDialog() {
  createItemForm.value = {
    nodeId: itemGroup.value,
    item_code: '',
    item_name: '',
    item_group: currentViewTitle.value,
    stock_uom: '',
    is_stock_item: 1,
    is_sales_item: 1,
    is_purchase_item: 1
  }
  createItemVisible.value = true
}

function submitCreateItem() {
  if (!createItemForm.value.item_code || !createItemForm.value.item_name || !createItemForm.value.stock_uom) return

  const newItem: InventoryListRow = {
    itemId: `inv-${Date.now()}`,
    nodeId: createItemForm.value.nodeId || 'all',
    code: createItemForm.value.item_code,
    name: createItemForm.value.item_name,
    spec: '--',
    stock: '0',
    inventoryType: createItemForm.value.item_group,
    productName: undefined,
    phoneModel: undefined,
    status: 'available',
    supplierName: '--',
    updatedAt: new Date().toISOString().split('T')[0]
  }

  items.value.unshift(newItem)
  total.value++
  createItemVisible.value = false
}

function displayOptionalText(value?: string | null) {
  const text = value?.trim()
  return text || '--'
}

// ---- create group dialog ----
const createGroupVisible = ref(false)
const createGroupForm = ref({ parentGroup: '', groupCode: '', groupName: '' })

function openCreateGroupDialog() {
  createGroupForm.value = {
    parentGroup: currentViewTitle.value,
    groupCode: '',
    groupName: ''
  }
  createGroupVisible.value = true
}

// ---- delete logic ----
const selectedRows = computed(() =>
  currentRows.value.filter((row) => selectedItemIds.value.includes(row.itemId))
)

function handleSelectionChange(rows: InventoryListRow[]) {
  selectedItemIds.value = rows.map((row) => row.itemId)
}

function submitDeleteItems() {
  deleteLoading.value = true
  try {
    const removed = items.value.filter((row) => selectedItemIds.value.includes(row.itemId)).length
    items.value = items.value.filter((row) => !selectedItemIds.value.includes(row.itemId))
    total.value = Math.max(0, total.value - removed)
    selectedItemIds.value = []
    actionMode.value = 'select'
    deleteConfirmVisible.value = false
  } finally {
    deleteLoading.value = false
  }
}

watch(pageRequest.data, (result) => {
  if (!result) return
  items.value = result.content
  total.value = result.totalElements
  selectedItemIds.value = []
})
watch(groupRequest.data, (tree) => {
  serverItemGroupOptions.value = tree?.length ? toItemGroupOptions(tree) : [{ label: '全部物料', value: 'all' }]
})

function loadData(force = false) {
  return pageRequest.execute({
    page: page.value, size: size.value, keyword: keyword.value.trim(),
    nodeId: itemGroup.value || 'all', timeRange: timeRange.value
  }, force)
}

function resetAndLoad(debounce = false) {
  clearTimeout(searchTimer)
  pageRequest.invalidate()
  selectedItemIds.value = []
  page.value = 1
  if (!active) return
  if (debounce) searchTimer = setTimeout(() => { searchTimer = undefined; void loadData() }, 300)
  else void loadData()
}

watch(keyword, () => resetAndLoad(true), { flush: 'sync' })
watch([itemGroup, timeRange, size], () => resetAndLoad(), { flush: 'sync' })
function changePage(value: number) {
  clearTimeout(searchTimer)
  searchTimer = undefined
  page.value = value
  void loadData()
}
function refresh() {
  clearTimeout(searchTimer)
  searchTimer = undefined
  void groupRequest.execute(undefined, true)
  void loadData(true)
}
onMounted(() => {
  initialized = true
  void groupRequest.execute(undefined)
  void loadData()
})
onActivated(() => {
  active = true
  if (initialized) {
    void groupRequest.execute(undefined)
    void loadData()
  }
})
onDeactivated(() => {
  active = false
  clearTimeout(searchTimer)
  searchTimer = undefined
  pageRequest.invalidate()
})
onUnmounted(() => clearTimeout(searchTimer))
</script>

<template>
  <PageContainer
    title="物料库存"
    description="按物料组和查看范围筛选库存物料记录，支持关键字搜索与就地新建物料。"
  >
    <section class="page-panel inventory-filter-bar">
      <el-cascader
        v-model="itemGroup"
        class="inventory-filter-bar__group"
        :options="serverItemGroupOptions"
        :props="itemGroupCascaderProps"
        placeholder="选择物料组"
      />

      <el-select v-model="timeRange" class="inventory-filter-bar__time" placeholder="选择时间范围">
        <el-option label="全部时间" value="all" />
        <el-option label="最近 7 天" value="7d" />
        <el-option label="最近 1 个月" value="30d" />
        <el-option label="最近 3 个月" value="90d" />
      </el-select>

      <el-input
        v-model="keyword"
        clearable
        class="inventory-filter-bar__search"
        placeholder="搜索编码 / 名称 / 规格 / 供应商 / 产品"
      />

      <div class="inventory-filter-bar__actions">
        <el-button
          v-if="actionMode === 'select'"
          @click="actionMode = 'delete'"
        >
          选择
        </el-button>
        <el-button
          v-if="actionMode === 'delete' && selectedItemIds.length"
          type="danger"
          @click="deleteConfirmVisible = true"
        >
          删除
        </el-button>
        <el-button
          v-if="actionMode === 'delete'"
          @click="actionMode = 'select'; selectedItemIds = []"
        >
          取消
        </el-button>
        <el-button type="primary" @click="openCreateItemDialog">新增物料</el-button>
        <el-button @click="openCreateGroupDialog">新增物料组</el-button>
        <el-button @click="refresh">刷新</el-button>
      </div>
    </section>

    <section class="page-panel inventory-list-panel" v-loading="loading">
      <div class="toolbar-row inventory-list-panel__header">
        <div>
          <h3 class="section-title">{{ currentViewTitle }}</h3>
          <p class="page-panel-desc">按当前物料组和查看范围筛选库存物料记录。</p>
        </div>
        <el-tag effect="light">{{ total }} 条记录</el-tag>
      </div>

      <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon />
      <FixedTableViewport v-slot="{ tableHeight }" :bottom-offset="80" :refresh-key="currentRows">
      <el-table :data="currentRows" :height="tableHeight" border stripe @selection-change="handleSelectionChange">
        <el-table-column v-if="actionMode === 'delete'" type="selection" width="48" />
        <el-table-column prop="code" label="物料编码" min-width="160" />
        <el-table-column prop="name" label="物料名称" min-width="200" />
        <el-table-column prop="inventoryType" label="类型" width="110" />
        <el-table-column label="所属产品" min-width="180">
          <template #default="{ row }">
            {{ displayOptionalText(row.productName) }}
          </template>
        </el-table-column>
        <el-table-column label="手机型号" min-width="130">
          <template #default="{ row }">
            {{ displayOptionalText(row.phoneModel) }}
          </template>
        </el-table-column>
        <el-table-column prop="spec" label="规格 / 型号" min-width="160" />
        <el-table-column prop="stock" label="库存" width="120" />
        <el-table-column label="状态" width="110">
          <template #default="{ row }">
            {{ getStatusLabel(row.status, 'inventory') }}
          </template>
        </el-table-column>
        <el-table-column prop="supplierName" label="供应商" min-width="160" />
        <el-table-column prop="updatedAt" label="更新时间" width="140" />
      </el-table>
      </FixedTableViewport>
      <el-pagination
        v-model:page-size="size" :current-page="page" :page-sizes="[20, 50, 100]"
        :total="total" layout="total, sizes, prev, pager, next, jumper"
        @current-change="changePage"
      />
    </section>

    <!-- create item dialog -->
    <el-dialog v-model="createItemVisible" title="新建物料" width="680px">
      <el-form :model="createItemForm" label-width="110px">
        <el-row :gutter="16">
          <el-col :span="12">
            <el-form-item label="物料编码" required>
              <el-input v-model="createItemForm.item_code" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="物料名称" required>
              <el-input v-model="createItemForm.item_name" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="所属分类">
              <el-input :model-value="createItemForm.item_group" disabled />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="库存单位" required>
              <el-input v-model="createItemForm.stock_uom" placeholder="pcs / kg / set" />
            </el-form-item>
          </el-col>
        </el-row>
      </el-form>
      <template #footer>
        <el-button @click="createItemVisible = false">取消</el-button>
        <el-button type="primary" @click="submitCreateItem">确认新建</el-button>
      </template>
    </el-dialog>

    <!-- create group dialog -->
    <el-dialog v-model="createGroupVisible" title="新增物料组" width="480px">
      <el-form :model="createGroupForm" label-width="100px">
        <el-form-item label="父级物料组">
          <el-input :model-value="createGroupForm.parentGroup" disabled />
        </el-form-item>
        <el-form-item label="分组编码">
          <el-input v-model="createGroupForm.groupCode" placeholder="如 MHC06 / NHC02" />
        </el-form-item>
        <el-form-item label="分组名称" required>
          <el-input v-model="createGroupForm.groupName" placeholder="如 超队 3.0 新工艺组" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createGroupVisible = false">取消</el-button>
        <el-button type="primary" @click="createGroupVisible = false">确认新增</el-button>
      </template>
    </el-dialog>

    <!-- delete confirm dialog -->
    <el-dialog v-model="deleteConfirmVisible" title="删除物料确认" width="520px">
      <p>确认删除已选中的 {{ selectedItemIds.length }} 条物料记录吗？</p>
      <ul>
        <li v-for="row in selectedRows.slice(0, 5)" :key="row.itemId">
          {{ row.code }} / {{ row.name }}
        </li>
      </ul>
      <p v-if="selectedRows.length > 5" class="subtle-text">...及其他 {{ selectedRows.length - 5 }} 条</p>
      <template #footer>
        <el-button @click="deleteConfirmVisible = false">取消</el-button>
        <el-button type="danger" :loading="deleteLoading" @click="submitDeleteItems">确认删除</el-button>
      </template>
    </el-dialog>
  </PageContainer>
</template>

<style scoped>
.inventory-filter-bar {
  display: flex;
  align-items: center;
  gap: 16px;
  flex-wrap: wrap;
}

.inventory-filter-bar__group {
  width: 240px;
}

.inventory-filter-bar__time {
  width: 180px;
}

.inventory-filter-bar__search {
  width: 320px;
}

.inventory-filter-bar__actions {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-left: auto;
}

.inventory-list-panel__header {
  margin-bottom: 12px;
}
.inventory-list-panel > .el-pagination { margin-top: 12px; }
</style>
