<script setup lang="ts">
import { computed, onMounted, ref, resolveDynamicComponent, watch } from 'vue'
import { ArrowDown, ArrowLeftBold, ArrowRightBold, ArrowUp } from '@element-plus/icons-vue'
import { useRoute, useRouter } from 'vue-router'

import { useAppStore } from '@/stores/app'
import { useUserStore } from '@/stores/user'
import type { MenuGroup, MenuItem } from '@/types/common'

const route = useRoute()
const router = useRouter()
const appStore = useAppStore()
const userStore = useUserStore()

const menuGroups: MenuGroup[] = [
  {
    title: '工作台',
    items: [
      { path: '/dashboard', title: '首页总览', icon: 'Odometer', permission: 'dashboard:view' },
      { path: '/my-tasks', title: '我的待办', icon: 'Checked', permission: 'pilot:tasks' }
    ]
  },
  {
    title: '项目管理',
    items: [
      { path: '/projects', title: '项目中心', icon: 'Management', permission: 'project:view' },
      { path: '/mold-schedules', title: '开模时间管控', icon: 'Timer', permission: 'schedule:read' },
      { path: '/collaboration-plans', title: '协作计划', icon: 'Calendar', permission: 'collaboration:view' },
      { path: '/production-orders', title: '测试管理', icon: 'Finished', permission: 'production-order:view' },
      { path: '/orders', title: '需求订单', icon: 'Document', permission: 'order:view' },
      { path: '/market-watch', title: '手机新品监控', icon: 'Monitor', permission: 'collaboration:view' }
    ]
  },
  { title: '工程资料', items: [
    { path: '/files', title: '图纸与 3D 文件', icon: 'FolderOpened', permission: 'file:read' },
    { path: '/bom', title: 'BOM 管理', icon: 'List', permission: 'product:view' },
    { path: '/processes', title: '工艺管理', icon: 'Connection', permission: 'process:view' }
  ] },
  { title: '费用管理', items: [
    { path: '/development-budgets', title: '模具成本预算', icon: 'Coin', permission: 'finance:read' },
    { path: '/development-expenses', title: '开发费用归集', icon: 'Wallet', permission: 'finance:read' }
  ] },
  { title: '基础资料', items: [
    { path: '/projects?tab=archived&archiveView=product', title: '产品平台与型号', icon: 'Grid', permission: 'product:view' },
    { path: '/molds', title: '模具管理', icon: 'Box', permission: 'collaboration:view' },
    { path: '/inventories', title: '物料库存', icon: 'Box', permission: 'inventory:view' },
    { path: '/suppliers', title: '供应商管理', icon: 'Van', permission: 'supplier:view' },
    { path: '/phone-model-codes', title: '手机型号编码', icon: 'Iphone', permission: 'product:view' },
    { path: '/code-center', title: '颜色编码', icon: 'CollectionTag', permission: 'product:view' }
  ] },
  {
    title: '报表中心',
    items: [
      { path: '/reports?view=schedule', title: '项目周期', icon: 'DataAnalysis', permission: 'report:view' },
      { path: '/reports?view=finance', title: '预算与实际', icon: 'Coin', permission: 'finance:read' },
      { path: '/reports?view=pilot', title: '试点评估', icon: 'TrendCharts', permission: 'report:view' }
    ]
  },
  {
    title: '系统管理',
    items: [
      { path: '/system/users', title: '账号与权限', icon: 'Avatar', permission: 'pilot:admin' },
      { path: '/system/operation-log', title: '操作日志', icon: 'Tickets', permission: 'admin:log' },
      { path: '/approval-tasks', title: '流程配置', icon: 'Checked', permission: 'approval:view' },
      { path: '/system/assignments', title: '协作职责', icon: 'User', permission: 'pilot:admin' },
      { path: '/system/integrations', title: '系统对接', icon: 'Connection', permission: 'pilot:admin' },
      { path: '/system/trials', title: '试点范围配置', icon: 'SetUp', permission: 'pilot:admin' },
      { path: '/system/import', title: '数据导入导出', icon: 'Upload', permission: 'admin:import' }
    ]
  }
]
const external = computed(() => ['supplier','mexico'].includes(userStore.profile?.roleCode || ''))

const visibleMenus = computed(() =>
  menuGroups
    .map((group) => ({
      ...group,
      items: group.items.filter((item) => userStore.hasPermission(item.permission)
        && (item.path !== '/market-watch' || appStore.phoneWatchEnabled)
        && (item.path !== '/my-tasks' || external.value || userStore.hasPermission('schedule:read')))
        .map(item => item.path === '/my-tasks' && external.value ? { ...item, path: '/pilot/tasks' } : item)
    }))
    .filter((group) => group.items.length)
)

onMounted(() => { if (userStore.hasPermission('collaboration:view')) void appStore.loadFeatureConfig() })
watch(() => userStore.token, (token) => { if (token && userStore.hasPermission('collaboration:view')) void appStore.loadFeatureConfig(true) })

function normalizePath(path: string) {
  return path.replace(/\/+$/, '')
}

function isActive(path: string) {
  const target = router.resolve(path)
  if (normalizePath(target.path) !== normalizePath(route.path)) return false
  if (Object.keys(target.query).length) return Object.entries(target.query).every(([key, value]) => (route.path === '/reports' && key === 'view' ? route.query[key] || 'schedule' : route.query[key]) === value)
  if (target.path === '/projects') return !['product', 'sku'].includes(String(route.query.archiveView || ''))
  return true
}

function groupHasActiveItem(group: MenuGroup) {
  return group.items.some((item) => isActive(item.path))
}

const activeGroupTitle = ref('')

function syncActiveGroup() {
  const matched = visibleMenus.value.find((group) => groupHasActiveItem(group))
  activeGroupTitle.value = matched?.title || visibleMenus.value[0]?.title || ''

}

watch(
  () => [route.fullPath, visibleMenus.value.map((group) => group.title).join('|')],
  () => {
    syncActiveGroup()
  },
  { immediate: true }
)

function isGroupOpen(group: MenuGroup) {
  if (appStore.sidebarCollapsed) return false
  return activeGroupTitle.value === group.title
}

function toggleGroup(title: string) {
  if (appStore.sidebarCollapsed) {
    appStore.setSidebarCollapsed(false)
    activeGroupTitle.value = title
    return
  }

  activeGroupTitle.value = activeGroupTitle.value === title ? '' : title
}

function handleGroupClick(group: MenuGroup) {
  toggleGroup(group.title)
}

async function navigate(path: string, groupTitle: string) {
  activeGroupTitle.value = groupTitle
  const failed = await router.push(path)
  if (failed) syncActiveGroup()
}

function handleMenuItemClick(item: MenuItem, groupTitle: string) {
  navigate(item.path, groupTitle)
}
</script>

<template>
  <aside class="sidebar" :class="{ 'sidebar--collapsed': appStore.sidebarCollapsed }">
    <div class="sidebar__brand">
      <div class="sidebar__logo">YW</div>
      <div v-if="!appStore.sidebarCollapsed" class="sidebar__title">
        <strong>Yuewei PLM</strong>
        <span>产品研发协同</span>
      </div>
    </div>

    <div class="sidebar__menus">
      <section v-for="group in visibleMenus" :key="group.title" class="sidebar__group" :class="{ 'is-active-group': groupHasActiveItem(group) }">
        <button
          class="sidebar__group-trigger"
          :class="{ 'is-open': isGroupOpen(group), 'is-active': groupHasActiveItem(group) }"
          type="button"
          @click="handleGroupClick(group)"
        >
          <span v-if="!appStore.sidebarCollapsed" class="sidebar__group-label">{{ group.title }}</span>
          <el-icon v-else class="sidebar__group-icon">
            <component :is="resolveDynamicComponent(group.items[0].icon)" />
          </el-icon>
          <el-icon v-if="!appStore.sidebarCollapsed" class="sidebar__group-arrow">
            <component :is="isGroupOpen(group) ? ArrowUp : ArrowDown" />
          </el-icon>
        </button>

        <div v-if="isGroupOpen(group)" class="sidebar__group-items">
          <template v-for="item in group.items" :key="item.path">
            <button
              class="sidebar__item"
              :class="{ 'is-active': isActive(item.path) }"
              type="button"
              @click="handleMenuItemClick(item, group.title)"
            >
              <el-icon class="sidebar__item-icon"><component :is="resolveDynamicComponent(item.icon)" /></el-icon>
              <span v-if="!appStore.sidebarCollapsed">{{ item.title }}</span>
            </button>
          </template>
        </div>
      </section>
    </div>

    <div class="sidebar__footer">
      <button class="sidebar__collapse-trigger" type="button" @click="appStore.toggleSidebar()">
        <el-icon class="sidebar__collapse-icon">
          <component :is="appStore.sidebarCollapsed ? ArrowRightBold : ArrowLeftBold" />
        </el-icon>
        <span v-if="!appStore.sidebarCollapsed">收起侧栏</span>
      </button>
    </div>
  </aside>
</template>

<style scoped>
.sidebar {
  display: flex;
  flex-direction: column;
  width: 248px;
  min-width: 248px;
  height: 100%;
  padding: 14px 10px 12px;
  border-right: 1px solid rgba(148, 163, 184, 0.16);
  background: #f3f5f7;
  color: #1f2937;
  transition: width 0.2s ease, min-width 0.2s ease;
}

.sidebar--collapsed {
  width: 84px;
  min-width: 84px;
}

.sidebar__brand {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 8px 10px 18px;
}

.sidebar__logo {
  display: grid;
  place-items: center;
  width: 40px;
  height: 40px;
  border-radius: 10px;
  background: linear-gradient(135deg, rgba(37, 99, 235, 0.14), rgba(14, 165, 233, 0.12));
  color: #1d4ed8;
  font-weight: 700;
}

.sidebar__title {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.sidebar__title span {
  color: #6b7280;
  font-size: 12px;
}

.sidebar__menus {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-height: 0;
  overflow-y: auto;
  padding-right: 4px;
}

.sidebar__group {
  overflow: visible;
  border-radius: 0;
  background: transparent;
  transition: background 0.2s ease;
}

.sidebar__group.is-active-group {
  background: transparent;
}

.sidebar__group-trigger {
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: 100%;
  padding: 11px 12px;
  border: 0;
  background: transparent;
  border-radius: 10px;
  color: #475569;
  cursor: pointer;
  text-align: left;
  transition: background 0.2s ease, color 0.2s ease;
}

.sidebar__group-trigger.is-active,
.sidebar__group-trigger:hover {
  background: rgba(148, 163, 184, 0.1);
  color: #1f2937;
}

.sidebar__group-trigger.is-open {
  background: rgba(148, 163, 184, 0.12);
}

.sidebar__group-label {
  font-size: 14px;
  font-weight: 600;
}

.sidebar__group-arrow,
.sidebar__group-icon,
.sidebar__item-icon,
.sidebar__collapse-icon {
  color: #64748b;
}

.sidebar__group-items {
  margin-top: 4px;
  padding: 2px 0 6px;
}

.sidebar__item {
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
  margin-top: 4px;
  padding: 11px 14px 11px 16px;
  border: 0;
  border-radius: 10px;
  background: transparent;
  color: #475569;
  text-align: left;
  cursor: pointer;
  transition: background 0.2s ease, color 0.2s ease;
}

.sidebar__item:hover {
  background: rgba(148, 163, 184, 0.1);
  color: #1f2937;
}

.sidebar__item.is-active {
  position: relative;
  background: rgba(37, 99, 235, 0.08);
  color: #1d4ed8;
  font-weight: 600;
}

.sidebar__item.is-active::before {
  content: '';
  position: absolute;
  left: 6px;
  top: 8px;
  bottom: 8px;
  width: 3px;
  border-radius: 999px;
  background: #2563eb;
}

.sidebar__footer {
  padding-top: 10px;
}

.sidebar__collapse-trigger {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  width: 100%;
  padding: 11px 14px;
  border: 1px solid rgba(148, 163, 184, 0.18);
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.56);
  color: #334155;
  cursor: pointer;
  transition: background 0.2s ease, border-color 0.2s ease;
}

.sidebar__collapse-trigger:hover {
  background: rgba(255, 255, 255, 0.88);
  border-color: rgba(148, 163, 184, 0.3);
}

.sidebar--collapsed .sidebar__group {
  background: transparent;
}

.sidebar--collapsed .sidebar__group-trigger {
  justify-content: center;
  padding: 12px 0;
  border-radius: 10px;
}

.sidebar--collapsed .sidebar__group-items {
  display: none;
}

.sidebar--collapsed .sidebar__footer {
  padding-top: 8px;
}

.sidebar--collapsed .sidebar__collapse-trigger {
  padding: 12px 0;
}

.sidebar--collapsed .sidebar__item {
  justify-content: center;
  margin-top: 0;
  padding: 12px 0;
}
</style>
