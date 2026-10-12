import { mount, flushPromises, type VueWrapper } from '@vue/test-utils'
import ElementPlus, { ElDatePicker, ElMessageBox } from 'element-plus'
import { createPinia, setActivePinia } from 'pinia'
import { createRouter, createMemoryHistory } from 'vue-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
const api=vi.hoisted(()=>({getPilotTasks:vi.fn(),savePilotTask:vi.fn(),getPilotTaskFiles:vi.fn(),downloadPilotFile:vi.fn()}))
vi.mock('@/api/modules/pilot',()=>api)
import PilotMobileTasksView from '../PilotMobileTasksView.vue'
import { useUserStore } from '@/stores/user'
let w:VueWrapper|undefined
let taskRouter:ReturnType<typeof createRouter>
const task={moldSetId:1,itemId:2,assetNumber:'MS-1',setName:'首套',styleName:'亮甲',compatibleModels:'Apple iPhone 18',plannedMoldDeliveryDate:null,actualShipDate:null,pcStatus:'making',tpuStatus:'making'}
beforeEach(()=>{vi.clearAllMocks();api.getPilotTasks.mockResolvedValue({content:[task],totalElements:1});api.savePilotTask.mockResolvedValue({status:'saved',conflicts:[]});api.getPilotTaskFiles.mockResolvedValue([])})
afterEach(()=>{w?.unmount();w=undefined;vi.restoreAllMocks()})
async function start(permissions=['pilot:tasks','task:ship','file:read']){const pinia=createPinia();setActivePinia(pinia);const user=useUserStore();user.permissions=permissions;user.profile={userId:7,userName:'真实供应商',roleName:'供应商',department:'制模厂'};const router=createRouter({history:createMemoryHistory(),routes:[{path:'/',component:PilotMobileTasksView},{path:'/other',component:{template:'<p>其他页面</p>'}}]});taskRouter=router;await router.push('/');await router.isReady();w=mount({template:'<router-view />'},{global:{plugins:[ElementPlus,pinia,router]}});await flushPromises();return w}
describe('real-account mobile tasks',()=>{
 it('shows only assigned tasks and account actions, not money or identity switching',async()=>{const w=await start();expect(w.text()).toContain('真实供应商');expect(w.text()).toContain('Apple iPhone 18');expect(w.text()).not.toContain('身份切换');expect(w.findAll('button').some(b=>b.text()==='确认发货')).toBe(true);expect(w.findAll('button').some(b=>b.text()==='验收 / 异常')).toBe(false)})
 it('saves only changed fields and original values through the shared engine',async()=>{const w=await start();await w.findAll('button').find(b=>b.text()==='确认发货')!.trigger('click');await flushPromises();w.findComponent(ElDatePicker).vm.$emit('update:modelValue','2026-10-12');await flushPromises();await w.findAll('button').find(b=>b.text().startsWith('保存 1'))!.trigger('click');await flushPromises();expect(api.savePilotTask).toHaveBeenCalledWith(1,'ship',{entityType:'mold_set',id:1,changes:[{field:'actualShipDate',before:null,after:'2026-10-12'}]});expect(api.getPilotTasks).toHaveBeenCalledTimes(2)})
 it('keeps conflicting drafts and shows current versus attempted values',async()=>{api.savePilotTask.mockResolvedValue({status:'conflict',message:'他人修改',conflicts:[{label:'发货日期',current:'2026-10-11',attempted:'2026-10-12'}]});const w=await start();await w.findAll('button').find(b=>b.text()==='确认发货')!.trigger('click');await flushPromises();w.findComponent(ElDatePicker).vm.$emit('update:modelValue','2026-10-12');await flushPromises();await w.findAll('button').find(b=>b.text().startsWith('保存 1'))!.trigger('click');await flushPromises();expect(w.text()).toContain('当前值 2026-10-11');expect(w.findComponent(ElDatePicker).props('modelValue')).toBe('2026-10-12')})
 it('queries individually authorized files without requesting the global file list',async()=>{const w=await start();await w.findAll('button').find(b=>b.text()==='已授权文件')!.trigger('click');await flushPromises();expect(api.getPilotTaskFiles).toHaveBeenCalledWith(1);expect(w.text()).toContain('没有单独授权的文件')})
 it('keeps unsaved entries when the user cancels navigation',async()=>{vi.spyOn(ElMessageBox,'confirm').mockRejectedValue('cancel');const w=await start();await w.findAll('button').find(b=>b.text()==='确认发货')!.trigger('click');await flushPromises();w.findComponent(ElDatePicker).vm.$emit('update:modelValue','2026-10-12');await flushPromises();await taskRouter.push('/other');await flushPromises();expect(taskRouter.currentRoute.value.path).toBe('/');expect(api.savePilotTask).not.toHaveBeenCalled();expect(w.findComponent(ElDatePicker).props('modelValue')).toBe('2026-10-12')})
})
