<script setup lang="ts">
import { computed } from 'vue'
import type { ProductTimelineNode, ProjectFlowNode } from '@/types/foundation'
import { formatDate } from '@/utils/format'

const props = withDefaults(
  defineProps<{
    /** 项目流程节点数据，支持 ProductTimelineNode 或 ProjectFlowNode */
    nodes: (ProductTimelineNode | ProjectFlowNode)[]
    /** 紧凑模式：SKU 详情弹窗等场景 */
    compact?: boolean
    /** 最多展示节点数，0 表示不限制 */
    maxNodes?: number
  }>(),
  {
    compact: false,
    maxNodes: 0
  }
)

/** 将 ProductTimelineNode 映射为统一展示格式 */
interface FlowRow {
  stepNo: number
  nodeKey: string
  nodeName: string
  phaseName: string
  experienceSummary: string
  receiverName: string
  receivedAt: string
  promoterName: string
  promotedAt: string
  status: string
  nextAction: string
  gateLabel?: string
  riskNote?: string
}

const flowRows = computed<FlowRow[]>(() => {
  let rows = props.nodes.map((node, index) => {
    if ('stepNo' in node) {
      // ProjectFlowNode
      return {
        stepNo: node.stepNo,
        nodeKey: node.nodeKey,
        nodeName: node.nodeName,
        phaseName: node.phaseName,
        experienceSummary: node.experienceSummary,
        receiverName: node.receiverUserName || node.receiverRole || '--',
        receivedAt: node.receivedAt || '--',
        promoterName: node.promoterUserName || node.promoterRole || '--',
        promotedAt: node.promotedAt || '--',
        status: node.status,
        nextAction: node.nextAction || '--',
        gateLabel: node.gateLabel,
        riskNote: node.riskNote
      }
    }
    // ProductTimelineNode — map to FlowRow
    const n = node as ProductTimelineNode
    return {
      stepNo: index + 1,
      nodeKey: n.nodeKey,
      nodeName: n.nodeName,
      phaseName: n.phaseName || '--',
      experienceSummary: n.experienceSummary || n.summary,
      receiverName: n.receiverUserName || n.receiverRole || '--',
      receivedAt: n.receivedAt || n.actualDate || '--',
      promoterName: n.promoterUserName || n.promoterRole || n.ownerRole || '--',
      promotedAt: n.promotedAt || n.actualDate || '--',
      status: n.status,
      nextAction: n.nextAction || '--',
      gateLabel: n.gateLabel,
      riskNote: n.riskNote
    }
  })

  if (props.maxNodes > 0 && rows.length > props.maxNodes) {
    rows = rows.slice(0, props.maxNodes)
  }

  return rows
})

function getFlowStatusLabel(status: string) {
  const map: Record<string, string> = {
    completed: '已完成',
    current: '进行中',
    pending: '待开始',
    rejected: '已驳回'
  }
  return map[status] || status
}

function getFlowStatusType(status: string) {
  const map: Record<string, string> = {
    completed: 'success',
    current: 'warning',
    pending: 'info',
    rejected: 'danger'
  }
  return map[status] || 'info'
}

const columns = computed(() => {
  if (props.compact) {
    return [
      { prop: 'stepNo', label: '顺序', width: '60' },
      { prop: 'nodeName', label: '环节', minWidth: '120' },
      { prop: 'experienceSummary', label: '经历内容', minWidth: '200' },
      { prop: 'receiverName', label: '接收人', width: '100' },
      { prop: 'receivedAt', label: '接收时间', width: '110' },
      { prop: 'promoterName', label: '推动人', width: '100' },
      { prop: 'promotedAt', label: '推动时间', width: '110' },
      { prop: 'status', label: '状态', width: '90' },
      { prop: 'nextAction', label: '下一步', minWidth: '140' }
    ]
  }
  return [
    { prop: 'stepNo', label: '顺序', width: '70' },
    { prop: 'nodeName', label: '环节', minWidth: '140' },
    { prop: 'phaseName', label: '阶段', minWidth: '130' },
    { prop: 'experienceSummary', label: '经历内容', minWidth: '240' },
    { prop: 'receiverName', label: '接收人', width: '130' },
    { prop: 'receivedAt', label: '接收时间', width: '150' },
    { prop: 'promoterName', label: '推动人', width: '130' },
    { prop: 'promotedAt', label: '推动时间', width: '150' },
    { prop: 'status', label: '状态', width: '110' },
    { prop: 'nextAction', label: '下一步', minWidth: '180' }
  ]
})
</script>

<template>
  <div class="project-flow-panel">
    <el-table :data="flowRows" border stripe>
      <el-table-column
        v-for="col in columns"
        :key="col.prop"
        :prop="col.prop"
        :label="col.label"
        :width="col.width"
        :min-width="col.minWidth"
      >
        <template v-if="col.prop === 'status'" #default="{ row }">
          <el-tag :type="getFlowStatusType(row.status)" effect="light">
            {{ getFlowStatusLabel(row.status) }}
          </el-tag>
          <el-tag v-if="row.gateLabel" type="danger" effect="light" size="small" style="margin-left: 4px">
            {{ row.gateLabel }}
          </el-tag>
        </template>

        <template v-else-if="col.prop === 'receiverName' || col.prop === 'receiverAt' || col.prop === 'promoterName' || col.prop === 'promotedAt'" #default="{ row }">
          <span :class="{ 'subtle-text': row[col.prop] === '--' }">{{ row[col.prop] }}</span>
        </template>

        <template v-else-if="col.prop === 'nextAction'" #default="{ row }">
          <span class="cell-next-action">{{ row.nextAction }}</span>
          <el-tooltip v-if="row.riskNote" :content="row.riskNote" placement="top">
            <el-tag type="danger" size="small" effect="plain" style="margin-left: 6px">风险</el-tag>
          </el-tooltip>
        </template>
      </el-table-column>
    </el-table>
  </div>
</template>

<style scoped>
.project-flow-panel {
  width: 100%;
  overflow-x: auto;
}

.cell-next-action {
  display: inline;
  vertical-align: middle;
}

.subtle-text {
  color: #94a3b8;
}
</style>
