<script setup lang="ts">
import { computed } from 'vue'

import type { CommonStatus, ObjectType } from '@/types/common'
import { getStatusColor, getStatusLabel } from '@/utils/status'

const props = withDefaults(
  defineProps<{
    status: CommonStatus
    objectType?: ObjectType
  }>(),
  {
    objectType: 'product'
  }
)

const label = computed(() => getStatusLabel(props.status, props.objectType))
const type = computed(() => getStatusColor(props.status))
</script>

<template>
  <el-tag :type="type" effect="light" round>{{ label }}</el-tag>
</template>
