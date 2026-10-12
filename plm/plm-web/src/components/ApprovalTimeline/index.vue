<script setup lang="ts">
import type { ApprovalStep } from '@/types/common'
import { formatDateTime } from '@/utils/format'
import { getStatusColor, getStatusLabel } from '@/utils/status'

defineProps<{
  steps: ApprovalStep[]
}>()
</script>

<template>
  <el-empty v-if="!steps.length" description="暂无审批记录" />
  <el-steps v-else :active="steps.findIndex((item) => item.status === 'pending') + 1 || steps.length" finish-status="success">
    <el-step v-for="step in steps" :key="step.stepName" :title="step.stepName">
      <template #description>
        <div class="approval-step">
          <div>{{ step.approver }}</div>
          <el-tag size="small" :type="getStatusColor(step.status)">{{ getStatusLabel(step.status, 'product') }}</el-tag>
          <div class="approval-step__time">{{ formatDateTime(step.time) }}</div>
          <div class="approval-step__comment">{{ step.comment }}</div>
        </div>
      </template>
    </el-step>
  </el-steps>
</template>

<style scoped>
.approval-step {
  display: flex;
  flex-direction: column;
  gap: 6px;
  min-width: 160px;
  padding-top: 8px;
}

.approval-step__time,
.approval-step__comment {
  color: var(--plm-color-text-secondary);
  line-height: 1.6;
}
</style>
