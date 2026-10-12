<script setup lang="ts">
defineProps<{
  message: string
}>()
</script>

<template>
  <div class="audit-highlight">
    <el-icon><WarningFilled /></el-icon>
    <span>{{ message }}</span>
  </div>
</template>

<style scoped>
.audit-highlight {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px 14px;
  border: 1px solid rgba(255, 77, 79, 0.18);
  border-radius: var(--plm-radius-base);
  background: rgba(255, 77, 79, 0.08);
  color: var(--plm-color-audit);
}
</style>
