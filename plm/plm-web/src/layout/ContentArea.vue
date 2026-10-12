<script setup lang="ts">
import { nextTick, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { useUserStore } from '@/stores/user'

const userStore = useUserStore()
const route = useRoute()
const content = ref<HTMLElement>()
const positions = new Map<string, number>()
watch(() => route.path, async (path, previous) => {
  if (content.value) positions.set(previous, content.value.scrollTop)
  await nextTick()
  if (content.value) content.value.scrollTop = positions.get(path) || 0
})
watch(() => userStore.token, () => positions.clear())
</script>

<template>
  <main ref="content" class="content-area" :class="{ 'content-area--collaboration': ['/collaboration-plans','/molds','/market-watch','/mold-schedules','/development-budgets','/development-expenses'].includes(route.path) }">
    <router-view v-slot="{ Component }">
      <KeepAlive :key="userStore.token" :include="['InventoryCenterView', 'BomCenterView', 'CollaborationPlanView', 'MoldManagementView', 'MoldScheduleView', 'DevelopmentBudgetView', 'DevelopmentExpenseView']" :max="7">
        <component :is="Component" />
      </KeepAlive>
    </router-view>
  </main>
</template>

<style scoped>
.content-area {
  flex: 1;
  min-height: 0;
  padding: 20px;
  overflow-y: auto;
  overflow-x: hidden;
}
.content-area--collaboration { padding:12px; overflow:hidden; }
</style>
