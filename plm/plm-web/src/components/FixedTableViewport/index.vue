<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useResizeObserver } from '@vueuse/core'

import { useFixedTableHeight } from '@/composables/useFixedTableHeight'

const props = withDefaults(defineProps<{
  bottomOffset?: number
  compact?: boolean
  refreshKey?: unknown
  fill?: boolean
}>(), {
  bottomOffset: 24,
  compact: false,
  refreshKey: undefined,
  fill: false
})

const viewportRef = ref<HTMLElement | null>(null)
const { tableHeight, refreshAfterRender } = useFixedTableHeight(viewportRef, props.bottomOffset)
const measuredHeight=ref(400)
useResizeObserver(viewportRef,entries=>{if(entries[0]?.contentRect.height) measuredHeight.value=Math.round(entries[0].contentRect.height)})
const effectiveTableHeight = computed(() => props.fill ? measuredHeight.value : props.compact ? Math.min(tableHeight.value, 560) : tableHeight.value)

watch(() => props.refreshKey, refreshAfterRender)
</script>

<template>
  <section
    ref="viewportRef"
    class="plm-fixed-table-viewport"
    :class="{ 'plm-fixed-table-viewport--compact': compact, 'plm-fixed-table-viewport--fill': fill }"
    :style="{ '--plm-fixed-table-height': `${effectiveTableHeight}px` }"
  >
    <slot :table-height="effectiveTableHeight" />
  </section>
</template>

<style scoped>
.plm-fixed-table-viewport {
  min-width: 0;
  height: var(--plm-fixed-table-height);
  min-height: 320px;
  max-height: 760px;
}

.plm-fixed-table-viewport--compact {
  min-height: 260px;
  max-height: 560px;
}
.plm-fixed-table-viewport--fill {
  flex:1;
  height:0;
  min-height:0;
  max-height:none;
}

.plm-fixed-table-viewport :deep(.el-table) {
  height: 100%;
}

.plm-fixed-table-viewport :deep(.el-table__inner-wrapper::before) {
  z-index: 1;
}
</style>
