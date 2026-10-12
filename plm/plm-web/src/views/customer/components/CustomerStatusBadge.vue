<script setup lang="ts">
import StatusTag from '@/components/StatusTag/index.vue'
import type { CommonStatus } from '@/types/common'

defineProps<{
  status: CommonStatus
}>()
</script>

<template>
  <StatusTag :status="status" object-type="customer" />
</template>
