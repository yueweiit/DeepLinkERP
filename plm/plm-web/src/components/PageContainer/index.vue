<script setup lang="ts">
defineProps<{
  title: string
  description?: string
}>()
</script>

<template>
  <section class="page-stack">
    <header class="page-panel">
      <div class="page-panel-header">
        <div>
          <h1 class="page-panel-title">{{ title }}</h1>
          <p v-if="description" class="page-panel-desc">{{ description }}</p>
        </div>
        <div class="toolbar-actions">
          <slot name="actions" />
        </div>
      </div>
      <slot name="header-extra" />
    </header>
    <slot />
  </section>
</template>
