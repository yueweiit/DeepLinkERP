<script setup lang="ts">
import { computed, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'

import FixedTableViewport from '@/components/FixedTableViewport/index.vue'
import PageContainer from '@/components/PageContainer/index.vue'
import { systemFields } from '@/mock/systemFields'
import type {
  SystemFieldInputType,
  SystemFieldItem,
  SystemFieldOption,
  SystemFieldScope,
  SystemFieldStatus
} from '@/types/common'
import { formatDate } from '@/utils/format'

const systemFieldInputTypeLabels: Record<SystemFieldInputType, string> = {
  text: '文本',
  textarea: '多行文本',
  number: '数字',
  date: '日期',
  select: '单选',
  multi_select: '多选',
  switch: '开关'
}

const systemFieldScopeLabels: Record<SystemFieldScope, string> = {
  product: '产品',
  sku: 'SKU',
  order: '订单',
  project: '项目',
  bom: 'BOM',
  process: '工艺',
  inventory: '库存',
  approval: '审批',
  system: '系统'
}

/* ========== 筛选状态 ========== */

const query = reactive({
  keyword: '',
  scope: '' as SystemFieldScope | '',
  inputType: '' as SystemFieldInputType | '',
  status: '' as SystemFieldStatus | ''
})

const activeScope = ref<SystemFieldScope | 'all'>('all')

/* ========== 分类计数 ========== */

const scopeTabs = computed(() => {
  const counts: Record<string, number> = {}
  systemFields.forEach((f) => {
    counts[f.scope] = (counts[f.scope] || 0) + 1
  })
  const tabs: { label: string; value: SystemFieldScope | 'all'; count: number }[] = [
    { label: '全部字段', value: 'all', count: systemFields.length }
  ]
  const scopeOrder: SystemFieldScope[] = [
    'product', 'sku', 'order', 'project', 'bom', 'process', 'inventory', 'approval', 'system'
  ]
  scopeOrder.forEach((scope) => {
    if (counts[scope]) {
      tabs.push({ label: systemFieldScopeLabels[scope], value: scope, count: counts[scope] })
    }
  })
  return tabs
})

/* ========== 筛选后的字段列表 ========== */

const filteredFields = computed(() => {
  const keyword = query.keyword.trim().toLowerCase()
  return systemFields.filter((f) => {
    if (activeScope.value !== 'all' && f.scope !== activeScope.value) return false
    if (query.scope && f.scope !== query.scope) return false
    if (query.inputType && f.inputType !== query.inputType) return false
    if (query.status && f.status !== query.status) return false
    if (keyword) {
      return (
        f.fieldCode.toLowerCase().includes(keyword) ||
        f.fieldName.toLowerCase().includes(keyword) ||
        f.description.toLowerCase().includes(keyword)
      )
    }
    return true
  })
})

function handleReset() {
  query.keyword = ''
  query.scope = ''
  query.inputType = ''
  query.status = ''
  activeScope.value = 'all'
}

/* ========== 详情抽屉 ========== */

const detailVisible = ref(false)
const selectedField = ref<SystemFieldItem | null>(null)

function openDetailDrawer(row: SystemFieldItem) {
  selectedField.value = row
  detailVisible.value = true
}

/* ========== 编辑抽屉 ========== */

const editVisible = ref(false)
const fieldDraft = reactive<SystemFieldItem>(createEmptyFieldDraft())

function createEmptyFieldDraft(): SystemFieldItem {
  return {
    fieldId: 0,
    fieldCode: '',
    fieldName: '',
    scope: 'product',
    inputType: 'text',
    status: 'active',
    required: false,
    visibleInList: true,
    visibleInDetail: true,
    visibleInFilter: false,
    editable: true,
    sortNo: 999,
    description: '',
    usageScenes: [],
    options: [],
    isSystem: false,
    updatedAt: ''
  }
}

function openCreateDrawer() {
  Object.assign(fieldDraft, createEmptyFieldDraft())
  editVisible.value = true
}

function openEditDrawer(row: SystemFieldItem) {
  Object.assign(fieldDraft, JSON.parse(JSON.stringify(row)))
  editVisible.value = true
}

function addFieldOption() {
  const maxSort = fieldDraft.options.reduce((max, o) => Math.max(max, o.sortNo), 0)
  fieldDraft.options.push({
    optionId: Date.now(),
    label: '',
    value: '',
    sortNo: maxSort + 10,
    status: 'active',
    isSystem: false
  })
}

function removeFieldOption(index: number) {
  fieldDraft.options.splice(index, 1)
}

function submitFieldDraft() {
  if (!fieldDraft.fieldName.trim()) {
    ElMessage.warning('请填写字段名称')
    return
  }
  ElMessage.success('字段配置已保存（前端演示）')
  editVisible.value = false
}

function getScopeLabel(scope: SystemFieldScope) {
  return systemFieldScopeLabels[scope] || scope
}

function getInputTypeLabel(type: SystemFieldInputType) {
  return systemFieldInputTypeLabels[type] || type
}
</script>

<template>
  <PageContainer
    title="字段管理"
    description="维护前端字段展示、枚举选项、显示规则与使用范围。本页面不修改数据库字段和后端接口。"
  >
    <!-- 筛选区 -->
    <section class="page-panel field-toolbar">
      <div class="field-toolbar__filters">
        <el-input v-model="query.keyword" placeholder="搜索字段编码、名称或说明" clearable style="width: 240px" />
        <el-select v-model="query.scope" placeholder="所属模块" clearable style="width: 140px">
          <el-option
            v-for="(label, value) in systemFieldScopeLabels"
            :key="value"
            :label="label"
            :value="value"
          />
        </el-select>
        <el-select v-model="query.inputType" placeholder="字段类型" clearable style="width: 130px">
          <el-option
            v-for="(label, value) in systemFieldInputTypeLabels"
            :key="value"
            :label="label"
            :value="value"
          />
        </el-select>
        <el-select v-model="query.status" placeholder="状态" clearable style="width: 110px">
          <el-option label="启用" value="active" />
          <el-option label="停用" value="inactive" />
        </el-select>
        <el-button type="primary" @click="() => {}">查询</el-button>
        <el-button @click="handleReset">重置</el-button>
      </div>
      <el-button type="primary" @click="openCreateDrawer">新增字段配置</el-button>
    </section>

    <!-- 主体：左侧分类 + 右侧列表 -->
    <section class="field-layout">
      <aside class="field-layout__nav">
        <button
          v-for="tab in scopeTabs"
          :key="tab.value"
          type="button"
          class="field-scope-item"
          :class="{ 'is-active': activeScope === tab.value }"
          @click="activeScope = tab.value"
        >
          <span>{{ tab.label }}</span>
          <em>{{ tab.count }}</em>
        </button>
      </aside>

      <article class="page-panel field-layout__table">
        <div class="toolbar-row">
          <el-tag effect="light">{{ filteredFields.length }} 条</el-tag>
        </div>

        <FixedTableViewport v-slot="{ tableHeight }" compact :refresh-key="filteredFields">
        <el-table :data="filteredFields" :height="tableHeight" border stripe @row-click="openDetailDrawer">
          <el-table-column prop="fieldCode" label="字段编码" min-width="160" />
          <el-table-column prop="fieldName" label="字段名称" min-width="140" />
          <el-table-column label="所属模块" width="110">
            <template #default="{ row }">{{ getScopeLabel(row.scope) }}</template>
          </el-table-column>
          <el-table-column label="字段类型" width="100">
            <template #default="{ row }">{{ getInputTypeLabel(row.inputType) }}</template>
          </el-table-column>
          <el-table-column label="必填" width="70">
            <template #default="{ row }">
              <el-tag :type="row.required ? 'danger' : 'info'" effect="light" size="small">
                {{ row.required ? '是' : '否' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="列表显示" width="90">
            <template #default="{ row }">
              <el-tag :type="row.visibleInList ? 'success' : 'info'" effect="light" size="small">
                {{ row.visibleInList ? '是' : '否' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="可编辑" width="80">
            <template #default="{ row }">
              <el-tag :type="row.editable ? 'success' : 'info'" effect="light" size="small">
                {{ row.editable ? '是' : '否' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="状态" width="80">
            <template #default="{ row }">
              <el-tag :type="row.status === 'active' ? 'success' : 'danger'" effect="light" size="small">
                {{ row.status === 'active' ? '启用' : '停用' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="选项数" width="80">
            <template #default="{ row }">{{ row.options.length }}</template>
          </el-table-column>
          <el-table-column label="更新时间" width="120">
            <template #default="{ row }">{{ formatDate(row.updatedAt) }}</template>
          </el-table-column>
          <el-table-column label="操作" width="140" fixed="right">
            <template #default="{ row }">
              <el-button link type="primary" size="small" @click.stop="openDetailDrawer(row)">详情</el-button>
              <el-button link type="primary" size="small" @click.stop="openEditDrawer(row)">编辑</el-button>
            </template>
          </el-table-column>
        </el-table>
        </FixedTableViewport>
      </article>
    </section>

    <!-- 字段详情抽屉 -->
    <el-drawer v-model="detailVisible" title="字段详情" size="680px">
      <div v-if="selectedField" class="field-detail">
        <section class="field-detail__summary">
          <h3>{{ selectedField.fieldName }}</h3>
          <div class="field-detail__tags">
            <el-tag>{{ selectedField.fieldCode }}</el-tag>
            <el-tag type="warning" effect="light" v-if="selectedField.isSystem">系统内置</el-tag>
          </div>
          <p class="subtle-text">{{ selectedField.description }}</p>
        </section>

        <el-descriptions :column="2" border size="small">
          <el-descriptions-item label="所属模块">{{ getScopeLabel(selectedField.scope) }}</el-descriptions-item>
          <el-descriptions-item label="字段类型">{{ getInputTypeLabel(selectedField.inputType) }}</el-descriptions-item>
          <el-descriptions-item label="是否必填">{{ selectedField.required ? '是' : '否' }}</el-descriptions-item>
          <el-descriptions-item label="列表显示">{{ selectedField.visibleInList ? '是' : '否' }}</el-descriptions-item>
          <el-descriptions-item label="详情展示">{{ selectedField.visibleInDetail ? '是' : '否' }}</el-descriptions-item>
          <el-descriptions-item label="筛选展示">{{ selectedField.visibleInFilter ? '是' : '否' }}</el-descriptions-item>
          <el-descriptions-item label="是否可编辑">{{ selectedField.editable ? '是' : '否' }}</el-descriptions-item>
          <el-descriptions-item label="状态">{{ selectedField.status === 'active' ? '启用' : '停用' }}</el-descriptions-item>
          <el-descriptions-item label="排序">{{ selectedField.sortNo }}</el-descriptions-item>
          <el-descriptions-item label="更新时间">{{ formatDate(selectedField.updatedAt) }}</el-descriptions-item>
        </el-descriptions>

        <section v-if="selectedField.usageScenes.length">
          <h4>使用位置</h4>
          <div class="field-detail__scenes">
            <el-tag v-for="scene in selectedField.usageScenes" :key="scene" effect="light">{{ scene }}</el-tag>
          </div>
        </section>

        <section v-if="selectedField.options.length">
          <h4>选项列表</h4>
          <el-table :data="selectedField.options" border size="small">
            <el-table-column label="选项名称" min-width="220">
              <template #default="{ row }">
                <span class="field-option-text" :title="row.label">{{ row.label }}</span>
              </template>
            </el-table-column>
            <el-table-column prop="value" label="选项值" min-width="140" />
            <el-table-column prop="sortNo" label="排序" width="80" />
            <el-table-column label="状态" width="90">
              <template #default="{ row }">
                <el-tag :type="row.status === 'active' ? 'success' : 'danger'" effect="light" size="small">
                  {{ row.status === 'active' ? '启用' : '停用' }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="系统内置" width="100">
              <template #default="{ row }">
                <el-tag :type="row.isSystem ? 'warning' : 'info'" effect="light" size="small">
                  {{ row.isSystem ? '是' : '否' }}
                </el-tag>
              </template>
            </el-table-column>
          </el-table>
        </section>
      </div>
    </el-drawer>

    <!-- 字段编辑抽屉 -->
    <el-drawer v-model="editVisible" title="字段配置" size="760px">
      <el-form :model="fieldDraft" label-width="110px" class="field-edit-form">
        <el-alert
          type="info"
          show-icon
          :closable="false"
          title="本页面只维护前端字段展示与选项配置，不修改数据库字段和后端接口。"
          style="margin-bottom: 16px"
        />

        <el-divider content-position="left">基础配置</el-divider>

        <el-form-item label="字段编码" required>
          <el-input v-model="fieldDraft.fieldCode" :disabled="fieldDraft.isSystem" placeholder="字段编码" />
        </el-form-item>
        <el-form-item label="字段名称" required>
          <el-input v-model="fieldDraft.fieldName" placeholder="字段名称" />
        </el-form-item>
        <el-form-item label="字段说明">
          <el-input v-model="fieldDraft.description" type="textarea" :rows="2" placeholder="字段说明" />
        </el-form-item>
        <el-form-item label="所属模块" v-if="!fieldDraft.isSystem">
          <el-select v-model="fieldDraft.scope">
            <el-option
              v-for="(label, value) in systemFieldScopeLabels"
              :key="value"
              :label="label"
              :value="value"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="字段类型" v-if="!fieldDraft.isSystem">
          <el-select v-model="fieldDraft.inputType">
            <el-option
              v-for="(label, value) in systemFieldInputTypeLabels"
              :key="value"
              :label="label"
              :value="value"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="排序">
          <el-input-number v-model="fieldDraft.sortNo" :min="1" controls-position="right" />
        </el-form-item>
        <el-form-item label="状态">
          <el-switch v-model="fieldDraft.status" active-value="active" inactive-value="inactive" />
        </el-form-item>

        <el-divider content-position="left">显示规则</el-divider>

        <div class="field-edit-form__checks">
          <el-checkbox v-model="fieldDraft.required">必填</el-checkbox>
          <el-checkbox v-model="fieldDraft.visibleInList">列表显示</el-checkbox>
          <el-checkbox v-model="fieldDraft.visibleInDetail">详情页展示</el-checkbox>
          <el-checkbox v-model="fieldDraft.visibleInFilter">筛选区展示</el-checkbox>
          <el-checkbox v-model="fieldDraft.editable">可编辑</el-checkbox>
        </div>

        <template v-if="fieldDraft.inputType === 'select' || fieldDraft.inputType === 'multi_select'">
          <el-divider content-position="left">选项配置</el-divider>

          <div style="margin-bottom: 10px">
            <el-button size="small" @click="addFieldOption">新增选项</el-button>
          </div>

          <el-table :data="fieldDraft.options" border size="small">
            <el-table-column label="选项名称" min-width="140">
              <template #default="{ row }">
                <el-input v-model="row.label" size="small" placeholder="选项名称" :title="row.label" />
              </template>
            </el-table-column>
            <el-table-column label="选项值" min-width="140">
              <template #default="{ row }">
                <el-input v-model="row.value" size="small" :disabled="row.isSystem" placeholder="选项值" />
              </template>
            </el-table-column>
            <el-table-column label="排序" width="100">
              <template #default="{ row }">
                <el-input-number v-model="row.sortNo" size="small" :min="1" controls-position="right" />
              </template>
            </el-table-column>
            <el-table-column label="状态" width="100">
              <template #default="{ row }">
                <el-switch v-model="row.status" size="small" active-value="active" inactive-value="inactive" />
              </template>
            </el-table-column>
            <el-table-column label="操作" width="80">
              <template #default="{ $index, row }">
                <el-button v-if="!row.isSystem" link type="danger" size="small" @click="removeFieldOption($index)">删除</el-button>
              </template>
            </el-table-column>
          </el-table>
        </template>
      </el-form>

      <template #footer>
        <el-button @click="editVisible = false">取消</el-button>
        <el-button type="primary" @click="submitFieldDraft">保存配置</el-button>
      </template>
    </el-drawer>
  </PageContainer>
</template>

<style scoped>
.field-toolbar {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 14px;
  padding: 14px;
}

.field-toolbar__filters {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px;
}

.field-layout {
  display: grid;
  grid-template-columns: 180px minmax(0, 1fr);
  gap: 14px;
}

.field-layout__nav {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.field-scope-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: 100%;
  padding: 10px 12px;
  border: 0;
  border-radius: 6px;
  background: transparent;
  color: #334155;
  font-size: 13px;
  cursor: pointer;
  text-align: left;
  transition: background 0.16s, color 0.16s;
}

.field-scope-item:hover {
  background: #f1f5f9;
}

.field-scope-item.is-active {
  background: #eff6ff;
  color: #1d4ed8;
  font-weight: 600;
}

.field-scope-item em {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 22px;
  height: 20px;
  padding: 0 5px;
  border-radius: 999px;
  background: #e5e7eb;
  color: #64748b;
  font-size: 11px;
  font-style: normal;
  font-weight: 600;
}

.field-scope-item.is-active em {
  background: #dbeafe;
  color: #1d4ed8;
}

.field-layout__table {
  min-width: 0;
}

/* 详情抽屉 */
.field-detail {
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.field-detail__summary h3 {
  margin: 0 0 6px;
  font-size: 18px;
}

.field-detail__tags {
  display: flex;
  gap: 6px;
  margin-bottom: 8px;
}

.field-detail__scenes {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.field-option-text {
  display: inline-block;
  max-width: 100%;
  white-space: normal;
  overflow-wrap: anywhere;
  line-height: 1.45;
}

/* 编辑抽屉 */
.field-edit-form {
  padding-bottom: 40px;
}

.field-edit-form__checks {
  display: flex;
  flex-wrap: wrap;
  gap: 10px 18px;
  padding: 0 0 0 4px;
}

@media (max-width: 960px) {
  .field-layout {
    grid-template-columns: 1fr;
  }

  .field-layout__nav {
    flex-direction: row;
    flex-wrap: wrap;
    gap: 6px;
  }

  .field-scope-item {
    width: auto;
    flex: 0 0 auto;
  }
}
</style>
