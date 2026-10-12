<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Expand, Fold } from '@element-plus/icons-vue'

import { useAppStore } from '@/stores/app'
import { useUserStore } from '@/stores/user'

const route = useRoute()
const router = useRouter()
const appStore = useAppStore()
const userStore = useUserStore()

const breadcrumbItems = computed(() => {
  const configured = route.meta?.breadcrumb as string[] | undefined
  if (configured?.length) {
    return configured.map((title, index) => ({
      key: `${index}-${title}`,
      title
    }))
  }

  return route.matched
    .filter((item) => item.meta?.title)
    .map((item, index) => ({
      key: `${index}-${String(item.meta.title)}`,
      title: String(item.meta.title)
    }))
})

const routeSubtitle = computed(() => String(route.meta?.subtitle || ''))

async function handleLogout() {
  await userStore.logout()
  router.push('/login')
}
</script>

<template>
  <header class="navbar">
    <div class="navbar__left">
      <el-button circle :icon="appStore.sidebarCollapsed ? Expand : Fold" @click="appStore.toggleSidebar()" />
      <div class="navbar__route">
        <el-breadcrumb separator="/">
          <el-breadcrumb-item v-for="item in breadcrumbItems" :key="item.key">
            {{ item.title }}
          </el-breadcrumb-item>
        </el-breadcrumb>
        <span v-if="routeSubtitle" class="navbar__route-subtitle">{{ routeSubtitle }}</span>
      </div>
    </div>
    <div class="navbar__right">
      <div class="navbar__user">
        <strong>{{ userStore.profile?.userName || '--' }}</strong>
        <span>{{ userStore.profile?.roleName || '--' }}</span>
      </div>
      <el-button text @click="handleLogout">退出</el-button>
    </div>
  </header>
</template>

<style scoped>
.navbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 14px 20px;
  border-bottom: 1px solid var(--plm-color-border-light);
  background: var(--plm-color-navbar);
  backdrop-filter: blur(10px);
}

.navbar__left,
.navbar__right {
  display: flex;
  align-items: center;
  gap: 14px;
  min-width: 0;
}

.navbar__route {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
  flex-wrap: wrap;
}

.navbar__route-subtitle {
  color: var(--plm-color-text-secondary);
  font-size: 13px;
  white-space: nowrap;
}

.navbar__user {
  display: flex;
  flex-direction: column;
  gap: 2px;
  text-align: right;
}

.navbar__user span {
  color: var(--plm-color-text-secondary);
  font-size: 12px;
}

@media (max-width: 960px) {
  .navbar {
    flex-wrap: wrap;
  }

  .navbar__right {
    width: 100%;
    justify-content: flex-end;
  }
}
</style>
