import { defineStore } from 'pinia'
import { ref } from 'vue'
import { getMarketWatchConfig } from '@/api/modules/marketWatch'

export const useAppStore = defineStore('app', () => {
  const sidebarCollapsed = ref(false)
  const phoneWatchEnabled = ref(false)
  const phoneWatchConfigLoaded = ref(false)

  function toggleSidebar() {
    sidebarCollapsed.value = !sidebarCollapsed.value
  }

  function setSidebarCollapsed(value: boolean) {
    sidebarCollapsed.value = value
  }

  async function loadFeatureConfig(force = false) {
    if (phoneWatchConfigLoaded.value && !force) return
    try {
      const config = await getMarketWatchConfig()
      phoneWatchEnabled.value = config.enabled
    } catch {
      phoneWatchEnabled.value = false
    } finally {
      phoneWatchConfigLoaded.value = true
    }
  }

  return {
    sidebarCollapsed,
    phoneWatchEnabled,
    phoneWatchConfigLoaded,
    toggleSidebar,
    setSidebarCollapsed,
    loadFeatureConfig
  }
})
