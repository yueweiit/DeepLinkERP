<script setup lang="ts">
import FinanceLedger from '@/views/development/FinanceLedger.vue'
defineProps<{ projectId: number }>()
const emit = defineEmits<{ changed: [] }>()
</script>
<template>
  <FinanceLedger entity="expense" :project-id="projectId" @changed="emit('changed')" />
</template>
