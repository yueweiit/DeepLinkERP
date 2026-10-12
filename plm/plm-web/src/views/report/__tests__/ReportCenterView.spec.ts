import { mount, flushPromises, type VueWrapper } from '@vue/test-utils'
import ElementPlus, { ElPagination } from 'element-plus'
import { createPinia, setActivePinia } from 'pinia'
import { createRouter, createMemoryHistory } from 'vue-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
const api=vi.hoisted(()=>({getScheduleTasks:vi.fn(),getFinanceSummary:vi.fn(),exportBudgetFile:vi.fn(),getTrials:vi.fn(),getTrialMetrics:vi.fn(),exportTrial:vi.fn()}))
vi.mock('@/api/modules/schedule',()=>({getScheduleTasks:api.getScheduleTasks}))
vi.mock('@/api/modules/development',()=>({getFinanceSummary:api.getFinanceSummary,exportBudgetFile:api.exportBudgetFile}))
vi.mock('@/api/modules/pilotDelivery',()=>({getTrials:api.getTrials,getTrialMetrics:api.getTrialMetrics,exportTrial:api.exportTrial}))
vi.mock('@/components/FixedTableViewport/index.vue',()=>({default:{template:'<div><slot :table-height="400" /></div>'}}))
import ReportCenterView from '../ReportCenterView.vue'
import { useUserStore } from '@/stores/user'
let w:VueWrapper|undefined
beforeEach(()=>{vi.clearAllMocks();api.getScheduleTasks.mockResolvedValue({content:[{moldSetId:1,assetNumber:'MS-000001',styleName:'亮甲',compatibleModels:'Apple',title:'到厂验收',dueDate:'2026-10-12',overdue:false}],totalElements:51});api.getTrials.mockResolvedValue([]);api.getFinanceSummary.mockImplementation(async(entity:string)=>({currencyGroups:entity==='budget'?[{currencyCode:'CNY',budgetKind:'platform',budgetTotal:100,recordCount:1,unknownCount:0}]:[{currencyCode:'MXN',erpPostedNet:50,requestedTotal:null,approvedTotal:30,declaredTotal:null,recordCount:1,unmappedCount:0}],rule:entity+'真实原币分组'}))})
afterEach(()=>{w?.unmount();w=undefined})
async function start(view='schedule',permissions=['*']){const pinia=createPinia();setActivePinia(pinia);useUserStore().permissions=permissions;const router=createRouter({history:createMemoryHistory(),routes:[{path:'/reports',component:{template:'<p/>'}}]});await router.push('/reports?view='+view);await router.isReady();w=mount(ReportCenterView,{global:{plugins:[ElementPlus,pinia,router]}});await flushPromises();return w}
describe('report center uses authoritative services',()=>{
 it('paginates real plan tasks instead of loading a fake snapshot',async()=>{const w=await start();expect(w.text()).toContain('MS-000001');expect(api.getScheduleTasks).toHaveBeenCalledWith(expect.objectContaining({page:1,size:50}));w.findComponent(ElPagination).vm.$emit('update:current-page',2);w.findComponent(ElPagination).vm.$emit('current-change',2);await flushPromises();expect(api.getScheduleTasks).toHaveBeenLastCalledWith(expect.objectContaining({page:2,size:50}))})
 it('renders separate server currency/level totals and never turns unknown amounts into zero',async()=>{const w=await start('finance',['finance:read']);expect(api.getFinanceSummary).toHaveBeenCalledWith('budget',expect.anything());expect(api.getFinanceSummary).toHaveBeenCalledWith('expense',expect.anything());expect(w.text()).toContain('CNY');expect(w.text()).toContain('MXN');expect(w.text()).toContain('未知');expect(w.findAll('button').some(b=>b.text().includes('导出预算'))).toBe(false);expect(api.exportBudgetFile).not.toHaveBeenCalled()})
 it('does not query financial data without an independent money-view grant',async()=>{const w=await start('finance',['report:view']);expect(w.text()).toContain('没有当前报表查看权限');expect(api.getFinanceSummary).not.toHaveBeenCalled()})
 it('shows an honest empty state before a real trial is configured',async()=>{const w=await start('pilot',['report:view']);expect(api.getTrials).toHaveBeenCalled();expect(api.getTrialMetrics).not.toHaveBeenCalled();expect(w.text()).toContain('不生成演示评估指标')})
})
