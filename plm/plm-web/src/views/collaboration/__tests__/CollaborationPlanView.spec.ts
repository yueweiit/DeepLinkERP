import { mount, flushPromises, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory, createRouter, type Router } from 'vue-router'
import ElementPlus, { ElCheckbox, ElMessageBox, ElPagination, ElRadioGroup } from 'element-plus'
import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest'
import type { CollaborationOptions, CollaborationRow } from '@/types/collaboration'

const api=vi.hoisted(()=>({ getCollaborationOptions:vi.fn(),getCollaborationPage:vi.fn(),saveCollaborationRows:vi.fn(),getCollaborationHistory:vi.fn(),getCollaborationReferences:vi.fn(),getCollaborationItem:vi.fn(),createCollaborationItem:vi.fn(),createCollaborationMold:vi.fn(),getCollaborationProjects:vi.fn(),linkCollaborationProjects:vi.fn(),getCollaborationMoldCodes:vi.fn(),getCollaborationAssignments:vi.fn(),saveCollaborationAssignments:vi.fn(),downloadCollaborationTemplate:vi.fn(),previewCollaborationImport:vi.fn(),commitCollaborationImport:vi.fn() }))
vi.mock('@/api/modules/collaboration',()=>api)
vi.mock('@/api/modules/code',()=>({getCodeItems:vi.fn().mockResolvedValue({content:[]})}))
// happy-dom has no real viewport; exercise resize behaviour in browser QA, not its observer loop.
vi.mock('@/components/FixedTableViewport/index.vue',()=>({default:{template:'<div><slot :table-height="400" /></div>'}}))
import CollaborationPlanView from '../CollaborationPlanView.vue'
import { useUserStore } from '@/stores/user'

const options:CollaborationOptions={administrator:true,userId:1,productLines:[{productLineId:9,productName:'薇武士',productCode:'W',status:'released'}],writableGroups:['market','engineering','logistics','mexico','production'],itemFields:[
  {key:'styleName',label:'产品款式',group:'market',kind:'required',maxLength:255},{key:'brand',label:'品牌',group:'market',kind:'text',maxLength:128},{key:'compatibleModels',label:'兼容手机型号',group:'market',kind:'required',maxLength:512},{key:'productLineId',label:'关联产品线',group:'market',kind:'id',maxLength:0},
  {key:'phoneModelCode',label:'手机型号编码',group:'market',kind:'code',maxLength:4},{key:'pcTotal',label:'PC 半成品累计',group:'production',kind:'count',maxLength:0},{key:'tpuTotal',label:'TPU 半成品累计',group:'production',kind:'count',maxLength:0},{key:'finishedTotal',label:'成品累计',group:'production',kind:'count',maxLength:0},{key:'productionNotes',label:'产量备注',group:'production',kind:'text',maxLength:4000}],moldFields:[
  {key:'openedDate',label:'开模日期',group:'engineering',kind:'date',maxLength:0},{key:'plannedMoldDeliveryDate',label:'计划模具交付日期',group:'engineering',kind:'date',maxLength:0},{key:'plannedFactoryArrivalDate',label:'计划到墨西哥工厂',group:'logistics',kind:'date',maxLength:0},{key:'actualMexicoArrivalDate',label:'实际抵达墨西哥',group:'mexico',kind:'date',maxLength:0}]}
const records:CollaborationRow[]=Array.from({length:50},(_,i)=>({itemId:i+1,productLineId:9,styleName:'薇武士',brand:'HONOR',compatibleModels:`Honor Model ${i}`,phoneModelCode:'0001',phonePrice:null,priceCurrency:null,salesPlatform:null,referenceUrl:null,notes:null,pcTotal:null,tpuTotal:null,finishedTotal:null,productionNotes:null,projectCount:3,projects:[],moldSetCount:1,status:'linked',updatedAt:'2026-10-09'}))
let wrapper:VueWrapper|undefined
let testRouter:Router
beforeEach(()=>{
  vi.clearAllMocks();localStorage.clear();api.getCollaborationOptions.mockResolvedValue(options)
  api.getCollaborationPage.mockImplementation(async(q)=>({content:records.map(r=>q.view==='delivery'?{...r,moldSetId:r.itemId,setName:'第 1 套',plannedMoldDeliveryDate:'2026-08-01',plannedFactoryArrivalDate:null,arrivalConfirmedBasisDate:null}:r),page:q.page,size:q.size,totalElements:657,totalPages:14}))
  api.saveCollaborationRows.mockImplementation(async(rows)=>rows.map((p:{id:number,entityType:string})=>({id:p.id,entityType:p.entityType,status:'saved',message:'已保存',conflicts:[],row:records.find(r=>r.itemId===p.id)})))
})
afterEach(()=>{wrapper?.unmount();wrapper=undefined;vi.useRealTimers();vi.restoreAllMocks()})
async function start() {
  const pinia=createPinia();setActivePinia(pinia);useUserStore().token='test-session'
  const router=createRouter({history:createMemoryHistory(),routes:[{path:'/',component:CollaborationPlanView},{path:'/other',component:{template:'<p>other</p>'}}]});testRouter=router;await router.push('/');await router.isReady()
  wrapper=mount({template:'<router-view v-slot="{ Component }"><keep-alive include="CollaborationPlanView"><component :is="Component" /></keep-alive></router-view>'},{global:{plugins:[ElementPlus,pinia,router],stubs:{ElDropdown:{template:'<div><slot /></div>'},ElPopover:{template:'<div><slot name="reference" /></div>'}}}});await flushPromises();return wrapper
}
async function tab(view:string) {wrapper!.findAllComponents(ElRadioGroup)[0].vm.$emit('update:modelValue',view);await flushPromises()}

describe('collaboration table and task entry',()=>{
  it('starts in the normal layout and enters wide-screen editing only on request',async()=>{
    const w=await start();expect(w.get('.collaboration-plan').classes()).not.toContain('is-expanded')
    const wideButton=w.findAll('button').find(button=>button.text()==='宽屏录入')!;await wideButton.trigger('click')
    expect(w.get('.collaboration-plan').classes()).toContain('is-expanded')
    expect(w.findAll('.identity-cell input[data-field="brand"]')).toHaveLength(0)
    expect(w.findAll('th').some(h=>h.text()==='品牌')).toBe(true)
    await w.get('button[aria-label="展开兼容手机型号"]').trigger('click');await flushPromises()
    expect(w.text()).toContain('展开编辑 · 兼容手机型号');expect(w.find('textarea[aria-label="兼容手机型号"]').exists()).toBe(true)
    expect(api.saveCollaborationRows).not.toHaveBeenCalled()
  })
  it('recognises explicit Apple and Samsung prefixes without replacing an existing brand',async()=>{
    api.getCollaborationPage.mockResolvedValue({content:[{...records[0],brand:null},{...records[1],brand:null},records[2]],page:1,size:50,totalElements:3,totalPages:1})
    const w=await start();const modelInputs=w.findAll('input[data-field="compatibleModels"]')
    await modelInputs[0].setValue('Apple iPhone 18 Pro Max');await modelInputs[1].setValue('Samsung Galaxy A37 5G');await modelInputs[2].setValue('Samsung Galaxy A37 5G')
    const brands=w.findAll('input[data-field="brand"]').map(i=>(i.element as HTMLInputElement).value)
    expect(brands).toEqual(['Apple','Samsung','HONOR']);expect(api.saveCollaborationRows).not.toHaveBeenCalled()
    await w.get('[data-test="save-plans"]').trigger('click');await flushPromises()
    expect(api.saveCollaborationRows.mock.calls[0][0][0].changes).toContainEqual({field:'brand',before:null,after:'Apple',reason:undefined})
    expect(api.saveCollaborationRows.mock.calls[0][0][2].changes).not.toEqual(expect.arrayContaining([expect.objectContaining({field:'brand'})]))
  })
  it('keeps input-only typing in the local draft before blur or refresh',async()=>{
    const w=await start();await tab('production');const input=w.get('input[data-field="pcTotal"]')
    ;(input.element as HTMLInputElement).value='0';await input.trigger('input')
    expect(w.text()).toContain('1 个单元格待保存')
    await w.findAll('button').find(b=>b.text()==='刷新')!.trigger('click');await flushPromises()
    expect((w.get('input[data-field="pcTotal"]').element as HTMLInputElement).value).toBe('0');expect(api.saveCollaborationRows).not.toHaveBeenCalled()
  })
  it('renders one server page only, filters/paginates and defers other views until clicked',async()=>{
    const w=await start();expect(api.getCollaborationPage).toHaveBeenCalledTimes(1)
    expect(api.getCollaborationPage).toHaveBeenCalledWith(expect.objectContaining({view:'market',page:1,size:50}))
    expect(w.findAll('.el-table__body tbody tr')).toHaveLength(50);expect(w.text()).toContain('657 条档案')
    w.findComponent(ElPagination).vm.$emit('current-change',14);await flushPromises();expect(api.getCollaborationPage).toHaveBeenLastCalledWith(expect.objectContaining({page:14}))
    w.findComponent(ElCheckbox).vm.$emit('update:modelValue',true);await flushPromises();expect(api.getCollaborationPage).toHaveBeenLastCalledWith(expect.objectContaining({page:1,mineOnly:true}))
    await tab('production');expect(api.getCollaborationPage).toHaveBeenLastCalledWith(expect.objectContaining({view:'production',page:1}));expect(w.text()).toContain('不是当前库存')
  })
  it('edits stay local, refresh does not replace drafts, and only changed fields are saved',async()=>{
    const w=await start();await tab('production');await w.get('input[data-field="pcTotal"]').setValue('0')
    expect(api.saveCollaborationRows).not.toHaveBeenCalled();expect(w.text()).toContain('1 个单元格待保存')
    await w.findAll('button').find(b=>b.text()==='刷新')!.trigger('click');await flushPromises()
    expect((w.get('input[data-field="pcTotal"]').element as HTMLInputElement).value).toBe('0')
    await w.get('[data-test="save-plans"]').trigger('click');await flushPromises()
    expect(api.saveCollaborationRows).toHaveBeenCalledWith([{entityType:'item',id:1,changes:[{field:'pcTotal',before:null,after:0,reason:undefined}]}])
    expect(w.text()).not.toContain('个单元格待保存')
  })
  it('pastes a two-row rectangle including unknown and zero without immediate writes',async()=>{
    const w=await start();await tab('production')
    const target=w.get('input[data-field="pcTotal"]');await target.trigger('paste',{clipboardData:{getData:()=> '0\t12\t\n10\t20\t5\n'}})
    expect(api.saveCollaborationRows).not.toHaveBeenCalled();expect(w.text()).toContain('5 个单元格待保存')
    await w.get('[data-test="save-plans"]').trigger('click');await flushPromises()
    expect(api.saveCollaborationRows.mock.calls[0][0]).toHaveLength(2)
    expect(api.saveCollaborationRows.mock.calls[0][0][0].changes).toEqual(expect.arrayContaining([{field:'pcTotal',before:null,after:0,reason:undefined},{field:'tpuTotal',before:null,after:12,reason:undefined}]))
  })
  it('retains conflict drafts, exposes current and attempted values, and offers explicit resolution',async()=>{
    const w=await start();await tab('production');await w.get('input[data-field="pcTotal"]').setValue('10')
    api.saveCollaborationRows.mockResolvedValue([{entityType:'item',id:1,status:'conflict',message:'同字段已被他人修改',row:{...records[0],pcTotal:15},conflicts:[{field:'pcTotal',label:'PC',before:null,current:15,attempted:10}]}])
    await w.get('[data-test="save-plans"]').trigger('click');await flushPromises();expect(w.text()).toContain('当前 15；我的修改 10')
    await w.findAll('button').find(b=>b.text()==='确认保留我的修改')!.trigger('click')
    await w.get('[data-test="save-plans"]').trigger('click');await flushPromises()
    expect(api.saveCollaborationRows).toHaveBeenCalledTimes(1)
    vi.spyOn(ElMessageBox,'prompt').mockImplementation(()=>Promise.resolve({value:'已核对更正原因',action:'confirm'}) as ReturnType<typeof ElMessageBox.prompt>)
    await w.findAll('button').find(b=>b.text()==='填写更正 / 核对说明')!.trigger('click');await flushPromises()
    await w.get('[data-test="save-plans"]').trigger('click');await flushPromises()
    expect(api.saveCollaborationRows).toHaveBeenLastCalledWith([{entityType:'item',id:1,changes:[{field:'pcTotal',before:15,after:10,reason:'已核对更正原因'}]}])
  })
  it('ordinary accounts see only their writable field groups even after work-view changes',async()=>{
    api.getCollaborationOptions.mockResolvedValue({...options,administrator:false,writableGroups:['engineering']})
    const w=await start();expect(w.text()).not.toContain('职责配置');expect(w.find('input[data-field="brand"]').exists()).toBe(false)
    await tab('delivery');expect(w.find('input[data-field="openedDate"]').exists()).toBe(true);expect(w.find('input[data-field="plannedFactoryArrivalDate"]').exists()).toBe(false)
    await tab('production');expect(w.find('input[data-field="pcTotal"]').exists()).toBe(false)
  })
  it('task mode uses the same date suggestion and explicit confirmation draft',async()=>{
    const w=await start();await tab('delivery');w.findAllComponents(ElRadioGroup)[1].vm.$emit('update:modelValue','task');await flushPromises()
    expect(w.text()).toContain('建议 2026-08-08');await w.findAll('button').find(b=>b.text()==='采用并确认')!.trigger('click')
    expect(api.saveCollaborationRows).not.toHaveBeenCalled();expect(w.text()).toContain('1 个单元格待保存')
    await w.get('[data-test="save-plans"]').trigger('click');await flushPromises()
    expect(api.saveCollaborationRows).toHaveBeenCalledWith([{entityType:'mold_set',id:1,changes:[{field:'plannedFactoryArrivalDate',before:null,after:'2026-08-08',reason:undefined}]}])
  })
  it('debounces search for 300ms and can retrieve a result outside the first page',async()=>{
    const w=await start();vi.useFakeTimers();const search=w.get('input[placeholder="搜索款式 / 品牌 / 型号 / 编码"]')
    await search.setValue('Honor');await vi.advanceTimersByTimeAsync(200);await search.setValue('Honor 999');await vi.advanceTimersByTimeAsync(299)
    expect(api.getCollaborationPage).toHaveBeenCalledTimes(1)
    api.getCollaborationPage.mockResolvedValue({content:[{...records[0],compatibleModels:'Honor 999'}],page:1,size:50,totalElements:1,totalPages:1})
    await vi.advanceTimersByTimeAsync(1);await flushPromises();expect(api.getCollaborationPage).toHaveBeenLastCalledWith(expect.objectContaining({keyword:'Honor 999',page:1}));expect(w.text()).not.toContain('Honor Model 1')
  })
  it('warns about unsaved changes, supports discard and clears results/drafts on logout',async()=>{
    const w=await start();await tab('production');await w.get('input[data-field="pcTotal"]').setValue('0')
    const event=new Event('beforeunload',{cancelable:true});window.dispatchEvent(event);expect(event.defaultPrevented).toBe(true)
    vi.spyOn(ElMessageBox,'confirm').mockImplementation(()=>Promise.resolve('confirm') as ReturnType<typeof ElMessageBox.confirm>)
    await w.findAll('button').find(b=>b.text()==='撤销未保存修改')!.trigger('click');await flushPromises();expect(w.text()).not.toContain('个单元格待保存')
    await w.get('input[data-field="pcTotal"]').setValue('10');useUserStore().token='';await flushPromises()
    expect(w.findAll('.el-table__body tbody tr')).toHaveLength(0);expect(w.text()).not.toContain('个单元格待保存')
  })
  it('cancels navigation with unsaved edits and reuses page/view results on a fresh cached return',async()=>{
    const w=await start();await tab('production');w.findComponent(ElPagination).vm.$emit('current-change',2);await flushPromises()
    await w.get('input[data-field="pcTotal"]').setValue('10')
    const prompt=vi.spyOn(ElMessageBox,'confirm').mockRejectedValue('cancel')
    await testRouter.push('/other');expect(testRouter.currentRoute.value.path).toBe('/');expect(w.text()).toContain('1 个单元格待保存')
    prompt.mockImplementation(()=>Promise.resolve('confirm') as ReturnType<typeof ElMessageBox.confirm>);await testRouter.push('/other');await flushPromises();const calls=api.getCollaborationPage.mock.calls.length
    await testRouter.push('/');await flushPromises();expect(w.findComponent(ElPagination).props('currentPage')).toBe(2)
    expect(w.find('input[data-field="pcTotal"]').exists()).toBe(true);expect(api.getCollaborationPage).toHaveBeenCalledTimes(calls)
  })
})
