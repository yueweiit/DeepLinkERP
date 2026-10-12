<script setup lang="ts">
import { computed, onMounted, reactive, ref, toRaw } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Bottom, Check, CopyDocument, Delete, Plus, Top } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'

import {
  activateWorkflowTemplate,
  copyWorkflowTemplate,
  createWorkflowTemplate,
  getApprovalTasks,
  getApprovalTemplateOptions,
  getWorkflowTemplates,
  updateWorkflowTemplate,
  type ApprovalTemplateOptions,
  type WorkflowTemplateSavePayload
} from '@/api/modules/approval'
import FixedTableViewport from '@/components/FixedTableViewport/index.vue'
import PageContainer from '@/components/PageContainer/index.vue'
import SearchBar from '@/components/SearchBar/index.vue'
import StatusTag from '@/components/StatusTag/index.vue'
import { useTable } from '@/composables/useTable'
import type { ApprovalTask, SearchField, WorkflowTemplate, WorkflowTemplateNode } from '@/types/common'

type ApprovalView = 'tasks' | 'workflow'

const route = useRoute()
const router = useRouter()

const taskRows = ref<ApprovalTask[]>([])
const workflowRows = ref<WorkflowTemplate[]>([])
const loading = ref(false)
const saving = ref(false)
const activeView = ref<ApprovalView>('workflow')
const drawerVisible = ref(false)
const editingTemplateId = ref<number | null>(null)

const options = reactive<ApprovalTemplateOptions>({
  flowTypes: [],
  statuses: [],
  fileCategories: []
})

const workflowForm = reactive<WorkflowTemplate>({
  flowType: 'product_line',
  templateName: '',
  versionNo: 'V1',
  status: 'draft',
  activeFlag: false,
  description: '',
  nodes: []
})

const searchFields: SearchField[] = [
  { prop: 'keyword', label: '关键词', type: 'input', placeholder: '业务对象 / 审批节点 / 发起人 / 审批人' },
  {
    prop: 'status',
    label: '状态',
    type: 'select',
    options: [
      { label: '全部', value: '' },
      { label: '待处理', value: 'pending' },
      { label: '已通过', value: 'approved' },
      { label: '已驳回', value: 'rejected' }
    ]
  }
]

const table = useTable(taskRows, ['objectName', 'nodeName', 'initiator', 'approver'], (row, filters) => {
  const status = String(filters.status || '')
  return !status || row.status === status
})

const workflowSummary = computed(() => ({
  total: workflowRows.value.length,
  active: workflowRows.value.filter((item) => item.activeFlag).length,
  draft: workflowRows.value.filter((item) => item.status === 'draft').length
}))

function flowTypeName(flowType: WorkflowTemplate['flowType']) {
  return options.flowTypes.find((item) => item.value === flowType)?.label || flowType
}

function fileCategoryName(value?: string | null) {
  return options.fileCategories.find((item) => item.value === value)?.label || value || '未配置'
}

function cloneWorkflow(template: WorkflowTemplate): WorkflowTemplate {
  return JSON.parse(JSON.stringify(toRaw(template))) as WorkflowTemplate
}

function createEmptyNode(stepNo: number): WorkflowTemplateNode {
  return {
    stepNo,
    nodeCode: '',
    nodeName: '',
    stageCode: '',
    stageName: '',
    phaseName: '',
    requiredAttachment: false,
    requiredFileCategory: '',
    uploadPrompt: '',
    confirmPrompt: '',
    emptyFileMessage: '',
    gateFlag: false,
    enabledFlag: true,
    remark: ''
  }
}

function resetForm(flowType: WorkflowTemplate['flowType'] = 'product_line') {
  workflowForm.workflowTemplateId = undefined
  workflowForm.flowType = flowType
  workflowForm.templateName = ''
  workflowForm.versionNo = 'V1'
  workflowForm.status = 'draft'
  workflowForm.activeFlag = false
  workflowForm.description = ''
  workflowForm.nodes = [createEmptyNode(1)]
}

function openTask(task: ApprovalTask) {
  router.push(task.targetPath || '/approval-tasks')
}

function openCreateWorkflow(flowType?: WorkflowTemplate['flowType']) {
  editingTemplateId.value = null
  resetForm(flowType || options.flowTypes[0]?.value || 'product_line')
  drawerVisible.value = true
}

function openEditWorkflow(template: WorkflowTemplate) {
  editingTemplateId.value = template.workflowTemplateId || null
  Object.assign(workflowForm, cloneWorkflow(template))
  workflowForm.nodes = workflowForm.nodes.length ? workflowForm.nodes : [createEmptyNode(1)]
  drawerVisible.value = true
}

function addNode() {
  workflowForm.nodes.push(createEmptyNode(workflowForm.nodes.length + 1))
}

function removeNode(index: number) {
  if (workflowForm.nodes.length === 1) {
    ElMessage.warning('流程至少保留一个节点。')
    return
  }
  workflowForm.nodes.splice(index, 1)
  resequenceNodes()
}

function moveNode(index: number, direction: -1 | 1) {
  const target = index + direction
  if (target < 0 || target >= workflowForm.nodes.length) return
  const current = workflowForm.nodes[index]
  workflowForm.nodes[index] = workflowForm.nodes[target]
  workflowForm.nodes[target] = current
  resequenceNodes()
}

function resequenceNodes() {
  workflowForm.nodes.forEach((node, index) => {
    node.stepNo = index + 1
  })
}

function normalizeNode(node: WorkflowTemplateNode, index: number): WorkflowTemplateNode {
  return {
    workflowNodeId: node.workflowNodeId,
    stepNo: index + 1,
    nodeCode: node.nodeCode.trim().toUpperCase(),
    nodeName: node.nodeName.trim(),
    stageCode: node.stageCode?.trim() || null,
    stageName: node.stageName?.trim() || null,
    phaseName: node.phaseName?.trim() || null,
    requiredFileCategory: node.requiredAttachment ? node.requiredFileCategory || null : null,
    uploadPrompt: node.uploadPrompt?.trim() || null,
    confirmPrompt: node.confirmPrompt?.trim() || null,
    emptyFileMessage: node.emptyFileMessage?.trim() || null,
    requiredAttachment: node.requiredAttachment,
    gateFlag: node.gateFlag,
    enabledFlag: node.enabledFlag,
    remark: node.remark?.trim() || null
  }
}

function validateWorkflow() {
  if (!workflowForm.templateName.trim()) {
    ElMessage.warning('请填写流程模板名称。')
    return false
  }
  if (!workflowForm.versionNo.trim()) {
    ElMessage.warning('请填写版本号。')
    return false
  }
  const invalidNode = workflowForm.nodes.find((node) => !node.nodeCode.trim() || !node.nodeName.trim())
  if (invalidNode) {
    ElMessage.warning('请补全所有节点的编码和名称。')
    return false
  }
  const missingCategory = workflowForm.nodes.find((node) => node.requiredAttachment && !node.requiredFileCategory)
  if (missingCategory) {
    ElMessage.warning(`节点“${missingCategory.nodeName || missingCategory.nodeCode}”已设为必传资料，请配置资料类别。`)
    return false
  }
  return true
}

async function saveWorkflow() {
  if (!validateWorkflow()) return
  saving.value = true
  try {
    const payload: WorkflowTemplateSavePayload = {
      flowType: workflowForm.flowType,
      templateName: workflowForm.templateName.trim(),
      versionNo: workflowForm.versionNo.trim(),
      status: workflowForm.status,
      description: workflowForm.description?.trim() || null,
      nodes: workflowForm.nodes.map(normalizeNode)
    }
    if (editingTemplateId.value) {
      await updateWorkflowTemplate(editingTemplateId.value, payload)
      ElMessage.success('流程模板已更新。')
    } else {
      await createWorkflowTemplate(payload)
      ElMessage.success('流程模板已新增。')
    }
    drawerVisible.value = false
    await loadData()
  } finally {
    saving.value = false
  }
}

async function activateTemplate(template: WorkflowTemplate) {
  if (!template.workflowTemplateId) return
  await activateWorkflowTemplate(template.workflowTemplateId)
  ElMessage.success('流程模板已启用。')
  await loadData()
}

async function copyTemplate(template: WorkflowTemplate) {
  if (!template.workflowTemplateId) return
  await copyWorkflowTemplate(template.workflowTemplateId, template.flowType)
  ElMessage.success('已复制为草稿模板。')
  await loadData()
}

async function loadData() {
  loading.value = true
  try {
    const [tasks, templates, templateOptions] = await Promise.all([
      getApprovalTasks(),
      getWorkflowTemplates(),
      getApprovalTemplateOptions()
    ])
    taskRows.value = tasks
    workflowRows.value = templates
    options.flowTypes = templateOptions.flowTypes
    options.statuses = templateOptions.statuses
    options.fileCategories = templateOptions.fileCategories
    if (!workflowForm.nodes.length) resetForm(options.flowTypes[0]?.value || 'product_line')
  } finally {
    loading.value = false
  }
}

onMounted(async () => {
  table.setQuery({
    keyword: String(route.query.keyword || ''),
    status: String(route.query.status || '')
  })
  await loadData()
})
</script>

<template>
  <PageContainer title="审批中心" description="维护新产品线和新型号线的流程节点、必传资料与节点提示。">
    <template #actions>
      <el-segmented
        v-model="activeView"
        :options="[
          { label: '流程编辑', value: 'workflow' },
          { label: '审批任务', value: 'tasks' }
        ]"
      />
      <el-button v-if="activeView === 'workflow'" type="primary" :icon="Plus" @click="openCreateWorkflow()">
        新增流程
      </el-button>
    </template>

    <template v-if="activeView === 'workflow'">
      <section class="workflow-toolbar">
        <div class="metric">
          <strong>{{ workflowSummary.total }}</strong>
          <span>流程模板</span>
        </div>
        <div class="metric">
          <strong>{{ workflowSummary.active }}</strong>
          <span>已启用</span>
        </div>
        <div class="metric">
          <strong>{{ workflowSummary.draft }}</strong>
          <span>草稿</span>
        </div>
      </section>

      <section class="page-panel" v-loading="loading">
        <FixedTableViewport v-slot="{ tableHeight }" compact :refresh-key="workflowRows">
        <el-table :data="workflowRows" :height="tableHeight" border stripe>
          <el-table-column prop="templateName" label="流程模板" min-width="220" />
          <el-table-column label="流程线" width="140">
            <template #default="{ row }">{{ flowTypeName(row.flowType) }}</template>
          </el-table-column>
          <el-table-column prop="versionNo" label="版本" width="110" />
          <el-table-column label="状态" width="110">
            <template #default="{ row }">
              <el-tag :type="row.activeFlag ? 'success' : row.status === 'draft' ? 'warning' : 'info'" effect="light">
                {{ row.activeFlag ? '启用' : row.status === 'draft' ? '草稿' : '停用' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="节点" width="90">
            <template #default="{ row }">{{ row.nodes?.length || 0 }}</template>
          </el-table-column>
          <el-table-column prop="description" label="说明" min-width="220" show-overflow-tooltip />
          <el-table-column label="操作" width="260" fixed="right">
            <template #default="{ row }">
              <el-button link type="primary" @click.stop="openEditWorkflow(row)">编辑</el-button>
              <el-button link :icon="CopyDocument" @click="copyTemplate(row)">复制</el-button>
              <el-button v-if="!row.activeFlag" link type="success" :icon="Check" @click="activateTemplate(row)">
                启用
              </el-button>
            </template>
          </el-table-column>
        </el-table>
        </FixedTableViewport>
      </section>
    </template>

    <template v-else>
      <SearchBar
        :fields="searchFields"
        :model-value="table.query"
        @search="table.setQuery"
        @reset="table.resetQuery({ keyword: '', status: '' })"
      />

      <section class="page-panel" v-loading="loading">
        <FixedTableViewport v-slot="{ tableHeight }" compact :refresh-key="table.pagedRows.value">
        <el-table :data="table.pagedRows.value" :height="tableHeight" border stripe @row-click="openTask">
          <el-table-column prop="objectName" label="业务对象" min-width="260" />
          <el-table-column prop="nodeName" label="审批节点" min-width="180" />
          <el-table-column prop="initiator" label="发起人" width="120" />
          <el-table-column prop="approver" label="审批人" width="120" />
          <el-table-column prop="dueDate" label="截止日期" width="140" />
          <el-table-column label="状态" width="120">
            <template #default="{ row }">
              <StatusTag :status="row.status" object-type="product" />
            </template>
          </el-table-column>
          <el-table-column label="操作" width="100" fixed="right">
            <template #default="{ row }">
              <el-button link type="primary" @click.stop="openTask(row)">查看</el-button>
            </template>
          </el-table-column>
        </el-table>
        </FixedTableViewport>

        <div class="toolbar-row pager-row">
          <span class="subtle-text">共 {{ table.filteredRows.value.length }} 条</span>
          <el-pagination
            v-model:current-page="table.currentPage.value"
            v-model:page-size="table.pageSize.value"
            layout="prev, pager, next"
            :total="table.filteredRows.value.length"
          />
        </div>
      </section>
    </template>

    <el-drawer v-model="drawerVisible" title="流程模板配置" size="86%">
      <div class="drawer-stack">
        <section class="template-form-grid">
          <el-input v-model="workflowForm.templateName" placeholder="模板名称，例如：新产品线标准流程" />
          <el-select v-model="workflowForm.flowType" placeholder="流程线" :disabled="Boolean(editingTemplateId)">
            <el-option v-for="item in options.flowTypes" :key="item.value" :label="item.label" :value="item.value" />
          </el-select>
          <el-input v-model="workflowForm.versionNo" placeholder="版本号，例如：V2" />
          <el-select v-model="workflowForm.status" placeholder="状态" :disabled="Boolean(workflowForm.activeFlag)">
            <el-option v-for="item in options.statuses" :key="item.value" :label="item.label" :value="item.value" />
          </el-select>
        </section>

        <el-input v-model="workflowForm.description" type="textarea" :rows="2" placeholder="流程说明" />

        <div class="toolbar-row">
          <h3 class="section-title">节点配置</h3>
          <el-button type="primary" plain :icon="Plus" @click="addNode">新增节点</el-button>
        </div>

        <section class="node-list">
          <article v-for="(node, index) in workflowForm.nodes" :key="node.workflowNodeId || index" class="node-row">
            <div class="node-order">
              <strong>{{ node.stepNo }}</strong>
              <div>
                <el-button text :icon="Top" :disabled="index === 0" @click="moveNode(index, -1)" />
                <el-button text :icon="Bottom" :disabled="index === workflowForm.nodes.length - 1" @click="moveNode(index, 1)" />
                <el-button text type="danger" :icon="Delete" @click="removeNode(index)" />
              </div>
            </div>

            <div class="node-fields">
              <el-input v-model="node.nodeCode" placeholder="节点编码，例如 PRODUCT_LINE_INIT_CREATE" />
              <el-input v-model="node.nodeName" placeholder="节点名称" />
              <el-input v-model="node.stageCode" placeholder="阶段编码" />
              <el-input v-model="node.stageName" placeholder="阶段名称" />
              <el-input v-model="node.phaseName" placeholder="阶段展示名" />
              <el-select v-model="node.requiredFileCategory" placeholder="必传资料类别" :disabled="!node.requiredAttachment">
                <el-option v-for="item in options.fileCategories" :key="item.value" :label="item.label" :value="item.value" />
              </el-select>
              <el-input v-model="node.uploadPrompt" placeholder="上传资料提示" />
              <el-input v-model="node.confirmPrompt" placeholder="确认节点提示" />
              <el-input v-model="node.emptyFileMessage" placeholder="缺少资料提示" />
              <el-input v-model="node.remark" placeholder="备注" />
            </div>

            <div class="node-switches">
              <el-checkbox v-model="node.requiredAttachment">必传资料</el-checkbox>
              <el-checkbox v-model="node.gateFlag">门禁节点</el-checkbox>
              <el-checkbox v-model="node.enabledFlag">启用</el-checkbox>
              <span v-if="node.requiredAttachment" class="subtle-text">{{ fileCategoryName(node.requiredFileCategory) }}</span>
            </div>
          </article>
        </section>

        <div class="drawer-actions">
          <el-button @click="drawerVisible = false">取消</el-button>
          <el-button type="primary" :loading="saving" @click="saveWorkflow">保存流程</el-button>
        </div>
      </div>
    </el-drawer>
  </PageContainer>
</template>

<style scoped>
.workflow-toolbar {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 160px));
  gap: 12px;
  margin-bottom: 14px;
}

.metric {
  padding: 12px 14px;
  border: 1px solid var(--plm-color-border-light);
  border-radius: var(--plm-radius-base);
  background: #fff;
}

.metric strong {
  display: block;
  font-size: 22px;
  line-height: 1.2;
}

.metric span {
  color: var(--plm-color-text-secondary);
  font-size: var(--plm-font-size-sm);
}

.pager-row {
  margin-top: 16px;
}

.drawer-stack {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.template-form-grid,
.node-fields {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

.node-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.node-row {
  display: grid;
  grid-template-columns: 96px minmax(0, 1fr) 220px;
  gap: 12px;
  padding: 12px;
  border: 1px solid var(--plm-color-border-light);
  border-radius: var(--plm-radius-base);
  background: #fff;
}

.node-order,
.node-switches,
.drawer-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.node-order,
.node-switches {
  flex-direction: column;
  align-items: flex-start;
}

.node-order strong {
  font-size: 20px;
}

.drawer-actions {
  justify-content: flex-end;
  padding-top: 6px;
}

@media (max-width: 1200px) {
  .workflow-toolbar,
  .template-form-grid,
  .node-fields,
  .node-row {
    grid-template-columns: 1fr;
  }

  .node-switches {
    flex-direction: row;
    flex-wrap: wrap;
  }
}
</style>
