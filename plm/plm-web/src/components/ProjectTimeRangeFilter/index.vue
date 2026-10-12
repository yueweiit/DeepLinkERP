<script setup lang="ts">
export type ProjectTimeRangeValue = 'all' | '3d' | '7d' | '30d' | '180d'

const model = defineModel<ProjectTimeRangeValue>({ default: 'all' })

const options = [
  { label: '全部', value: 'all' },
  { label: '最近三天', value: '3d' },
  { label: '最近一星期', value: '7d' },
  { label: '最近一个月', value: '30d' },
  { label: '半年', value: '180d' }
]
</script>

<template>
  <el-segmented v-model="model" :options="options" class="project-time-range-filter" />
</template>

<style scoped>
.project-time-range-filter {
  max-width: 100%;
}
</style>
