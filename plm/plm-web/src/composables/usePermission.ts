import { computed } from 'vue'
import { useUserStore } from '@/stores/user'

const COST_VIEW_ROLES = ['采购', '财务', '管理层', '项目经理', '超级管理员']
const PROFIT_VIEW_ROLES = ['财务', '管理层', '超级管理员']
const PRODUCT_EDIT_ROLES = ['工程', '项目经理', '超级管理员']
const PRODUCT_CREATE_ROLES = ['工程', '项目经理', '超级管理员']
const PRODUCT_PUBLISH_ROLES = ['工程', '管理层', '超级管理员']
const ORDER_CREATE_ROLES = ['销售', '项目经理', '超级管理员']
const INVENTORY_EDIT_ROLES = ['采购', '工程', '超级管理员']
const PROCESS_EDIT_ROLES = ['工程', '超级管理员']
const WORKSTATION_EDIT_ROLES = ['生产', '工程', '超级管理员']
const QUALITY_EDIT_ROLES = ['品质', '工程', '超级管理员']

export function usePermission() {
  const userStore = useUserStore()
  const roleName = computed(() => userStore.profile?.roleName || '')

  const canViewCost = computed(() => COST_VIEW_ROLES.includes(roleName.value))
  const canViewProfit = computed(() => PROFIT_VIEW_ROLES.includes(roleName.value))
  const isEngineer = computed(() => roleName.value === '工程')
  const isPM = computed(() => roleName.value === '项目经理')
  const isManager = computed(() => roleName.value === '管理层')
  const isSuperAdmin = computed(() => roleName.value === '超级管理员')
  const isSales = computed(() => roleName.value === '销售')
  const isPurchasing = computed(() => roleName.value === '采购')
  const isQuality = computed(() => roleName.value === '品质')
  const isProduction = computed(() => roleName.value === '生产')
  const isFinance = computed(() => roleName.value === '财务')

  function canCreateProduct() {
    return PRODUCT_CREATE_ROLES.includes(roleName.value)
  }

  function canEditProduct(status: string) {
    return PRODUCT_EDIT_ROLES.includes(roleName.value) && !['released', 'archived'].includes(status)
  }

  function getEditProductDisabledReason(status: string) {
    if (!PRODUCT_EDIT_ROLES.includes(roleName.value)) return '当前角色无编辑权限'
    if (status === 'released') return '已发布版本不可直接修改，请发起变更流程'
    if (status === 'archived') return '已归档版本不可编辑'
    return ''
  }

  function canPublishProduct(status: string, createdBy?: string) {
    if (['released', 'archived'].includes(status)) return false
    if (isSuperAdmin.value) return true
    if (!PRODUCT_PUBLISH_ROLES.includes(roleName.value)) return false
    return !(isManager.value && createdBy && userStore.profile?.userName === createdBy)
  }

  function canFreezeProduct(status: string, createdBy?: string) {
    if (status !== 'developing') return false
    if (isSuperAdmin.value) return true
    if (!PRODUCT_PUBLISH_ROLES.includes(roleName.value)) return false
    return !(isManager.value && createdBy && userStore.profile?.userName === createdBy)
  }

  function canInitChange(status: string) {
    if (isSuperAdmin.value) return true
    if (!['工程', '项目经理', '品质'].includes(roleName.value)) return false
    return status === 'released'
  }

  return {
    permissions: computed(() => userStore.permissions),
    profile: computed(() => userStore.profile),
    hasPermission: userStore.hasPermission,
    roleName,
    isEngineer,
    isPM,
    isManager,
    isSuperAdmin,
    isSales,
    isPurchasing,
    isQuality,
    isProduction,
    isFinance,
    canViewCost,
    canViewProfit,
    canCreateProduct,
    canEditProduct,
    getEditProductDisabledReason,
    canPublishProduct,
    canFreezeProduct,
    canInitChange,
    canCreateOrder: () => ORDER_CREATE_ROLES.includes(roleName.value),
    canEditInventory: () => INVENTORY_EDIT_ROLES.includes(roleName.value),
    canEditProcess: () => PROCESS_EDIT_ROLES.includes(roleName.value),
    canEditWorkstation: () => WORKSTATION_EDIT_ROLES.includes(roleName.value),
    canEditQuality: () => QUALITY_EDIT_ROLES.includes(roleName.value),
    isInitiatorEqualsConfirmer: (initiatorName: string, confirmerName: string) => initiatorName === confirmerName
  }
}
