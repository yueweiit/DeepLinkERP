<script setup lang="ts">
import { computed } from 'vue'

import type { TimelineItem } from '@/types/common'
import { formatDateTime } from '@/utils/format'

const props = defineProps<{
  history: TimelineItem[]
}>()

const decoratedHistory = computed(() =>
  props.history.map((item, index) => {
    const status = item.status || 'pending'
    const isCurrent = status === 'developing'
    const isDone = ['approved', 'released', 'confirmed', 'archived', 'completed'].includes(status)
    const isRisk = status === 'blocked'
    const isSkipped = status === 'skipped' || item.branchStatus === 'skipped'
    const isDecision = item.nodeType === 'decision'

    const variantMeta =
      item.variantTag === 'inherited'
        ? { type: 'info', label: '继承' }
        : item.variantTag === 'difference'
          ? { type: 'warning', label: '差异' }
          : item.variantTag === 'optional'
            ? { type: 'success', label: '可选' }
            : null

    const branchMeta =
      item.branchLabel && item.branchStatus === 'selected'
        ? { type: 'success', label: item.branchLabel }
        : item.branchLabel && item.branchStatus === 'optional'
          ? { type: 'info', label: item.branchLabel }
          : item.branchLabel && item.branchStatus === 'skipped'
            ? { type: 'info', label: `${item.branchLabel} / 已跳过` }
            : null

    return {
      ...item,
      index,
      isCurrent,
      isDone,
      isRisk,
      isSkipped,
      isDecision,
      variantMeta,
      branchMeta,
      tagType: isRisk ? 'danger' : isCurrent ? 'primary' : isDone ? 'success' : 'info',
      tagLabel: isRisk ? '风险' : isCurrent ? '当前' : isDone ? '完成' : isSkipped ? '已跳过' : '待推进'
    }
  })
)
</script>

<template>
  <el-empty v-if="!history.length" description="暂无流程记录" />
  <div v-else class="timeline-list">
    <article
      v-for="item in decoratedHistory"
      :key="`${item.title}-${item.index}`"
      class="timeline-item"
      :class="{
        'is-current': item.isCurrent,
        'is-done': item.isDone,
        'is-risk': item.isRisk,
        'is-gate': item.gate,
        'is-skipped': item.isSkipped,
        'is-decision': item.isDecision
      }"
    >
      <div class="timeline-item__axis">
        <span class="timeline-item__dot" />
        <span v-if="item.index !== decoratedHistory.length - 1" class="timeline-item__line" />
      </div>
      <div class="timeline-item__card">
        <div class="timeline-item__header">
          <div class="timeline-item__title">
            <span v-if="item.stepNo" class="timeline-step-no">{{ String(item.stepNo).padStart(2, '0') }}</span>
            <strong>{{ item.title }}</strong>
            <el-tag v-if="item.gate" type="warning" effect="light">{{ item.gateLabel || '门禁点' }}</el-tag>
            <el-tag v-if="item.variantMeta" :type="item.variantMeta.type" effect="light">{{ item.variantMeta.label }}</el-tag>
            <el-tag v-if="item.branchMeta" :type="item.branchMeta.type" effect="light">{{ item.branchMeta.label }}</el-tag>
            <el-tag v-if="item.isDecision" type="primary" effect="light">决策点</el-tag>
          </div>
          <el-tag :type="item.tagType" effect="light">{{ item.tagLabel }}</el-tag>
        </div>
        <div class="timeline-item__meta">
          <span>{{ item.phase || item.owner || '--' }}</span>
          <span>{{ formatDateTime(item.time) }}</span>
        </div>
        <p v-if="item.description" class="timeline-item__desc">{{ item.description }}</p>
        <ul v-if="item.detailLines?.length" class="timeline-item__details">
          <li v-for="line in item.detailLines" :key="line">{{ line }}</li>
        </ul>
      </div>
    </article>
  </div>
</template>

<style scoped>
.timeline-list {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.timeline-item {
  display: grid;
  grid-template-columns: 28px minmax(0, 1fr);
  gap: 12px;
}

.timeline-item__axis {
  display: flex;
  flex-direction: column;
  align-items: center;
}

.timeline-item__dot {
  width: 12px;
  height: 12px;
  border: 2px solid #cbd5e1;
  border-radius: 999px;
  background: #fff;
}

.timeline-item__line {
  flex: 1;
  width: 2px;
  margin-top: 6px;
  background: #e2e8f0;
}

.timeline-item__card {
  padding: 14px;
  border: 1px solid var(--plm-color-border-light);
  border-radius: var(--plm-radius-base);
  background: #fff;
}

.timeline-item__header,
.timeline-item__meta {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.timeline-item__title {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.timeline-step-no {
  display: inline-flex;
  min-width: 28px;
  height: 28px;
  align-items: center;
  justify-content: center;
  border-radius: 999px;
  background: rgba(37, 99, 235, 0.08);
  color: var(--plm-color-primary);
  font-size: 12px;
  font-weight: 700;
}

.timeline-item__meta {
  margin-top: 8px;
  color: var(--plm-color-text-secondary);
  font-size: var(--plm-font-size-sm);
}

.timeline-item__desc {
  margin: 10px 0 0;
  color: var(--plm-color-text-secondary);
  line-height: 1.6;
}

.timeline-item__details {
  margin: 10px 0 0;
  padding-left: 18px;
  color: var(--plm-color-text-secondary);
  font-size: var(--plm-font-size-sm);
  line-height: 1.6;
}

.timeline-item__details li + li {
  margin-top: 4px;
}

.timeline-item.is-current .timeline-item__dot {
  border-color: #2563eb;
  background: #2563eb;
}

.timeline-item.is-current .timeline-item__card {
  border-color: rgba(37, 99, 235, 0.38);
  box-shadow: var(--plm-shadow-sm);
}

.timeline-item.is-done .timeline-item__dot {
  border-color: #22c55e;
  background: #22c55e;
}

.timeline-item.is-risk .timeline-item__dot {
  border-color: #ef4444;
  background: #ef4444;
}

.timeline-item.is-gate .timeline-item__card {
  background: rgba(255, 251, 235, 0.75);
}

.timeline-item.is-risk .timeline-item__card {
  border-color: rgba(239, 68, 68, 0.3);
  background: rgba(254, 242, 242, 0.8);
}

.timeline-item.is-skipped .timeline-item__card {
  background: rgba(248, 250, 252, 0.92);
  opacity: 0.82;
}

.timeline-item.is-skipped .timeline-item__dot {
  border-color: #94a3b8;
  background: #e2e8f0;
}

.timeline-item.is-decision .timeline-item__card {
  border-style: dashed;
}
</style>
