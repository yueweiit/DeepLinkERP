import { createRouter, createWebHashHistory } from 'vue-router'
import type { RouteRecordRaw } from 'vue-router'

import Layout from '@/layout/index.vue'
import { useUserStore } from '@/stores/user'
import { normalizeLegacyProductTarget, toArchivedProductRoute, toArchivedSkuRoute, toInProgressProjectRoute } from '@/utils/projectRoute'

type RouteMetaConfig = {
  title: string
  permission?: string
  moduleKey?: string
  breadcrumb?: string[]
  subtitle?: string
  available?: boolean
}

function redirectLegacyProductList(to: { fullPath: string }) {
  return normalizeLegacyProductTarget(to.fullPath)
}

const routes: RouteRecordRaw[] = [
  {
    path: '/login',
    name: 'Login',
    component: () => import('@/views/login/LoginView.vue'),
    meta: {
      title: '登录',
      breadcrumb: ['登录']
    } satisfies RouteMetaConfig
  },
  {
    path: '/',
    component: Layout,
    redirect: '/dashboard',
    children: [
      { path:'my-tasks',name:'MyTasks',component:()=>import('@/views/pilotdelivery/MyTasksView.vue'),meta:{title:'我的待办',permission:'pilot:tasks',breadcrumb:['工作台','我的待办']} satisfies RouteMetaConfig },
      { path:'pilot/tasks',name:'PilotMobileTasks',component:()=>import('@/views/pilot/PilotMobileTasksView.vue'),meta:{title:'手机协作任务',permission:'pilot:tasks',breadcrumb:['工作台','我的待办']} satisfies RouteMetaConfig },
      { path:'mold-schedules',name:'MoldSchedules',component:()=>import('@/views/schedule/MoldScheduleView.vue'),meta:{title:'开模时间管控',permission:'schedule:read',breadcrumb:['项目管理','开模时间管控']} satisfies RouteMetaConfig },
      { path:'development-budgets',name:'DevelopmentBudgets',component:()=>import('@/views/development/DevelopmentBudgetView.vue'),meta:{title:'模具成本预算',permission:'finance:read',breadcrumb:['费用管理','模具成本预算']} satisfies RouteMetaConfig },
      { path:'development-expenses',name:'DevelopmentExpenses',component:()=>import('@/views/development/DevelopmentExpenseView.vue'),meta:{title:'开发费用归集',permission:'finance:read',breadcrumb:['费用管理','开发费用归集']} satisfies RouteMetaConfig },
      { path:'system/assignments',name:'CollaborationAssignments',component:()=>import('@/views/collaboration/components/CollaborationAssignments.vue'),props:{pageMode:true},meta:{title:'协作职责',permission:'pilot:admin',breadcrumb:['系统管理','协作职责']} satisfies RouteMetaConfig },
      { path:'system/integrations',name:'PilotIntegrations',component:()=>import('@/views/pilotdelivery/PilotIntegrationView.vue'),meta:{title:'系统对接',permission:'pilot:admin',breadcrumb:['系统管理','系统对接']} satisfies RouteMetaConfig },
      { path:'system/trials',name:'PilotTrials',component:()=>import('@/views/pilotdelivery/PilotTrialView.vue'),meta:{title:'试点范围配置',permission:'pilot:admin',breadcrumb:['系统管理','试点范围配置']} satisfies RouteMetaConfig },
      {
        path: 'molds', name: 'Molds', component: () => import('@/views/mold/MoldManagementView.vue'),
        meta: { title: '模具管理', permission: 'collaboration:view', breadcrumb: ['基础资料', '模具管理'] } satisfies RouteMetaConfig
      },
      {
        path: 'collaboration-plans',
        name: 'CollaborationPlans',
        component: () => import('@/views/collaboration/CollaborationPlanView.vue'),
        meta: { title: '协作计划', permission: 'collaboration:view', breadcrumb: ['项目管理', '协作计划'] } satisfies RouteMetaConfig
      },
      {
        path: 'market-watch',
        name: 'MarketWatch',
        component: () => import('@/views/market-watch/MarketWatchView.vue'),
        meta: { title: '手机新品监控', permission: 'collaboration:view', breadcrumb: ['项目管理', '手机新品监控'] } satisfies RouteMetaConfig
      },
      {
        path: 'dashboard',
        name: 'Dashboard',
        component: () => import('@/views/dashboard/DashboardView.vue'),
        meta: {
          title: '首页总览',
          permission: 'dashboard:view',
          breadcrumb: ['工作台', '首页总览'],
          subtitle: '聚焦当前推进中的产品、待办、风险和高频入口'
        } satisfies RouteMetaConfig
      },
      {
        path: 'products/create',
        name: 'ProductCreate',
        component: () => import('@/views/product/ProductEdit.vue'),
        meta: {
          title: '新项目',
          permission: 'project:view',
          breadcrumb: ['项目管理', '进行中']
        } satisfies RouteMetaConfig
      },
      {
        path: 'products/:id/edit',
        name: 'ProductEdit',
        component: () => import('@/views/product/ProductEdit.vue'),
        meta: {
          title: '归档产品',
          permission: 'project:view',
          breadcrumb: ['项目管理', '已归档', '产品管理']
        } satisfies RouteMetaConfig
      },
      {
        path: 'products/:id',
        name: 'ProductDetail',
        redirect: (to) => toArchivedProductRoute(String(to.params.id)),
        meta: {
          title: '归档产品',
          permission: 'project:view',
          breadcrumb: ['项目管理', '已归档', '产品管理']
        } satisfies RouteMetaConfig
      },
      {
        path: 'products',
        name: 'ProductList',
        redirect: redirectLegacyProductList,
        meta: {
          title: '归档产品',
          permission: 'project:view',
          breadcrumb: ['项目管理', '已归档', '产品管理']
        } satisfies RouteMetaConfig
      },
      {
        path: 'sku-view',
        name: 'SkuView',
        redirect: () => toArchivedSkuRoute(),
        meta: {
          title: '归档 SKU',
          permission: 'project:view',
          breadcrumb: ['项目管理', '已归档', 'SKU 管理']
        } satisfies RouteMetaConfig
      },
      {
        path: 'bom',
        name: 'BomCenter',
        component: () => import('@/views/bom/BomCenterView.vue'),
        meta: {
          title: 'BOM 管理',
          permission: 'product:view',
          breadcrumb: ['工程资料', 'BOM 管理']
        } satisfies RouteMetaConfig
      },
      {
        path: 'code-center',
        name: 'CodeCenter',
        component: () => import('@/views/code/CodeCenterView.vue'),
        meta: {
          title: '颜色编码',
          permission: 'product:view',
          breadcrumb: ['基础资料', '颜色编码']
        } satisfies RouteMetaConfig
      },
      {
        path: 'phone-model-codes',
        name: 'PhoneModelCodes',
        component: () => import('@/views/code/PhoneModelCodeView.vue'),
        meta: {
          title: '手机型号编码',
          permission: 'product:view',
          breadcrumb: ['基础资料', '手机型号编码']
        } satisfies RouteMetaConfig
      },
      {
        path: 'customers',
        name: 'CustomerList',
        component: () => import('@/views/customer/CustomerList.vue'),
        meta: {
          title: '客户管理',
          permission: 'customer:view',
          breadcrumb: ['客户管理', '客户列表']
        } satisfies RouteMetaConfig
      },
      {
        path: 'customers/create',
        name: 'CustomerCreate',
        component: () => import('@/views/customer/CustomerEdit.vue'),
        meta: {
          title: '新建客户',
          permission: 'customer:create',
          breadcrumb: ['客户管理', '新建客户']
        } satisfies RouteMetaConfig
      },
      {
        path: 'customers/:id',
        name: 'CustomerDetail',
        component: () => import('@/views/customer/CustomerDetail.vue'),
        meta: {
          title: '客户详情',
          permission: 'customer:view',
          breadcrumb: ['客户管理', '客户详情']
        } satisfies RouteMetaConfig
      },
      {
        path: 'customers/:id/edit',
        name: 'CustomerEdit',
        component: () => import('@/views/customer/CustomerEdit.vue'),
        meta: {
          title: '编辑客户',
          permission: 'customer:edit',
          breadcrumb: ['客户管理', '编辑客户']
        } satisfies RouteMetaConfig
      },
      {
        path: 'orders',
        name: 'OrderList',
        component: () => import('@/views/order/OrderCenterView.vue'),
        meta: {
          title: '需求订单',
          permission: 'order:view',
          breadcrumb: ['项目管理', '需求订单']
        } satisfies RouteMetaConfig
      },
      {
        path: 'projects',
        name: 'ProjectCenter',
        component: () => import('@/views/project/ProjectCenterView.vue'),
        meta: {
          title: '项目管理',
          permission: 'project:view',
          breadcrumb: ['项目管理', '项目中心']
        } satisfies RouteMetaConfig
      },
      {
        path: 'production-orders',
        name: 'TestCenter',
        component: () => import('@/views/test/TestCenterView.vue'),
        meta: {
          title: '测试管理',
          permission: 'production-order:view',
          breadcrumb: ['项目管理', '测试管理']
        } satisfies RouteMetaConfig
      },
      {
        path: 'processes',
        name: 'ProcessManagement',
        component: () => import('@/views/process/ProcessCenterView.vue'),
        meta: {
          title: '工艺管理',
          permission: 'process:view',
          breadcrumb: ['工程资料', '工艺管理']
        } satisfies RouteMetaConfig
      },
      {
        path: 'inventories',
        name: 'InventoryCenter',
        component: () => import('@/views/inventory/InventoryCenterView.vue'),
        meta: {
          title: '物料库存',
          permission: 'inventory:view',
          breadcrumb: ['基础资料', '物料库存']
        } satisfies RouteMetaConfig
      },
      {
        path: 'files',
        name: 'FileCenter',
        component: () => import('@/views/file/FileCenterView.vue'),
        meta: {
          title: '图纸与 3D 文件',
          permission: 'file:read',
          breadcrumb: ['工程资料', '图纸与 3D 文件']
        } satisfies RouteMetaConfig
      },
      {
        path: 'suppliers',
        name: 'SupplierCenter',
        component: () => import('@/views/supplier/SupplierCenterView.vue'),
        meta: {
          title: '供应商管理',
          permission: 'supplier:view',
          breadcrumb: ['基础资料', '供应商管理']
        } satisfies RouteMetaConfig
      },
      {
        path: 'workstations',
        name: 'WorkstationList',
        component: () => import('@/views/module/ModulePlaceholderView.vue'),
        meta: {
          title: '机台工位',
          permission: 'workstation:view',
          moduleKey: 'workstation',
          breadcrumb: ['基础资料', '机台工位']
        } satisfies RouteMetaConfig
      },
      {
        path: 'quality',
        name: 'QualityList',
        component: () => import('@/views/module/ModulePlaceholderView.vue'),
        meta: {
          title: '质量管理',
          permission: 'quality:view',
          moduleKey: 'quality',
          breadcrumb: ['基础资料', '质量管理']
        } satisfies RouteMetaConfig
      },
      {
        path: 'costs',
        name: 'CostCenter',
        redirect: '/development-budgets',
        meta: {
          title: '成本报价',
          permission: 'cost:view',
          moduleKey: 'cost',
          breadcrumb: ['基础资料', '成本报价']
        } satisfies RouteMetaConfig
      },
      {
        path: 'reports',
        name: 'ReportCenter',
        component: () => import('@/views/report/ReportCenterView.vue'),
        meta: {
          title: '报表中心',
          permission: 'report:view',
          breadcrumb: ['报表中心']
        } satisfies RouteMetaConfig
      },
      {
        path: 'approval-tasks',
        name: 'ApprovalTaskList',
        component: () => import('@/views/approval/ApprovalTaskList.vue'),
        meta: {
          title: '流程配置',
          permission: 'approval:view',
          breadcrumb: ['系统管理', '流程配置']
        } satisfies RouteMetaConfig
      },
      {
        path: 'system/users',
        name: 'SystemUsers',
        component: () => import('@/views/system/SystemUserManagementView.vue'),
        meta: {
          title: '账号与权限',
          permission: 'pilot:admin',
          moduleKey: 'system-user',
          breadcrumb: ['系统管理', '账号与权限']
        } satisfies RouteMetaConfig
      },
      {
        path: 'system/roles',
        name: 'SystemRoles',
        component: () => import('@/views/system/SystemRoleManagementView.vue'),
        meta: {
          title: '角色管理',
          permission: 'pilot:admin',
          moduleKey: 'system-role',
          breadcrumb: ['系统管理', '角色管理']
        } satisfies RouteMetaConfig
      },
      {
        path: 'system/fields',
        name: 'SystemFields',
        component: () => import('@/views/system/SystemFieldManagementView.vue'),
        meta: {
          title: '字段管理',
          permission: 'admin:field',
          moduleKey: 'system-field',
          available: false,
          breadcrumb: ['系统管理', '字段管理']
        } satisfies RouteMetaConfig
      },
      {
        path: 'system/dicts',
        redirect: '/system/fields'
      },
      {
        path: 'system/operation-log',
        name: 'SystemOperationLog',
        component: () => import('@/views/system/SystemOperationLogView.vue'),
        meta: {
          title: '操作日志',
          permission: 'admin:log',
          breadcrumb: ['系统管理', '操作日志']
        } satisfies RouteMetaConfig
      },
      {
        path: 'system/import',
        name: 'SystemImport',
        component: () => import('@/views/system/SystemImportExportView.vue'),
        meta: {
          title: '数据导入',
          permission: 'admin:import',
          moduleKey: 'system-import',
          breadcrumb: ['系统管理', '数据导入']
        } satisfies RouteMetaConfig
      }
    ]
  },
  {
    path: '/403',
    name: 'Forbidden',
    component: () => import('@/views/error/ForbiddenView.vue'),
    meta: {
      title: '无权限',
      breadcrumb: ['异常页面', '无权限']
    } satisfies RouteMetaConfig
  },
  {
    path: '/:pathMatch(.*)*',
    name: 'NotFound',
    component: () => import('@/views/error/NotFoundView.vue'),
    meta: {
      title: '页面不存在',
      breadcrumb: ['异常页面', '页面不存在']
    } satisfies RouteMetaConfig
  }
]

const router = createRouter({
  history: createWebHashHistory(),
  routes
})

let restored = false

export function defaultHome(userStore: ReturnType<typeof useUserStore>) {
  return userStore.hasPermission('dashboard:view') ? '/dashboard' : userStore.hasPermission('pilot:tasks') ? '/pilot/tasks' : userStore.hasPermission('collaboration:view') ? '/collaboration-plans' : '/403'
}

router.beforeEach(async (to) => {
  const userStore = useUserStore()

  if (!restored && userStore.token) {
    restored = true
    try {
      await userStore.restore()
    } catch {
      return { path: '/login', query: { redirect: to.fullPath } }
    }
  }

  if (to.path !== '/login' && !userStore.isLoggedIn) {
    return { path: '/login', query: { redirect: to.fullPath } }
  }

  if (to.path === '/login' && userStore.isLoggedIn) {
    return { path: defaultHome(userStore) }
  }

  if (to.path === '/dashboard' && !userStore.hasPermission('dashboard:view')) return defaultHome(userStore)
  if (to.path === '/my-tasks' && ['supplier','mexico'].includes(userStore.profile?.roleCode || '')) return '/pilot/tasks'
  if (to.path === '/my-tasks' && !userStore.hasPermission('schedule:read')) return '/403'
  if (to.meta.available === false) return '/403'
  if (to.path === '/reports' && !to.query.view && to.query.report) return {path:'/reports',query:{view:to.query.report==='cost'?'finance':'schedule'}}
  if (['supplier','mexico'].includes(userStore.profile?.roleCode || '') && to.path === '/mold-schedules') return '/pilot/tasks'

  const permission = to.path === '/reports' && to.query.view === 'finance' ? 'finance:read'
    : to.path === '/projects' && ['product','sku'].includes(String(to.query.archiveView || '')) ? 'product:view'
    : to.meta.permission as string | undefined
  if (permission && !userStore.hasPermission(permission)) {
    return '/403'
  }

  if (to.path === '/projects' && ['product','sku'].includes(String(to.query.archiveView || ''))) {
    to.meta.title = '产品平台与型号'
    to.meta.breadcrumb = ['基础资料', '产品平台与型号', ...(to.query.archiveView === 'sku' ? ['SKU资料'] : [])]
  }
  if (to.path === '/reports') {
    const title = ({schedule:'项目周期',finance:'预算与实际',pilot:'试点评估'} as Record<string,string>)[String(to.query.view || 'schedule')] || '项目周期'
    to.meta.title = title
    to.meta.breadcrumb = ['报表中心', title]
  }

  return true
})

router.afterEach((to) => {
  document.title = `${to.meta.title || 'Yuewei PLM'} - Yuewei PLM`
})

export default router
