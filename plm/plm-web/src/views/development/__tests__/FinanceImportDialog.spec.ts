import { mount,flushPromises,type VueWrapper } from '@vue/test-utils'
import { createPinia, disposePinia, getActivePinia, setActivePinia } from 'pinia'
import ElementPlus,{ElSelect} from 'element-plus'
import { afterEach,beforeEach,describe,expect,it,vi } from 'vitest'
const api=vi.hoisted(()=>({previewBudgetFile:vi.fn(),commitBudgetFile:vi.fn(),previewErpExpenses:vi.fn(),commitErpExpenses:vi.fn(),refreshErpExpenses:vi.fn()}))
vi.mock('@/api/modules/development',()=>api)
import FinanceImportDialog from '../FinanceImportDialog.vue'
import { useUserStore } from '@/stores/user'
const options={productLines:[{productId:1,productName:'亮甲2.0',productCode:'BA'}],items:[],molds:[],budgets:[],writable:true,confirmable:true,exportable:true}
let w:VueWrapper|undefined
beforeEach(()=>{vi.clearAllMocks();api.commitErpExpenses.mockResolvedValue({saved:1,skipped:0});api.commitBudgetFile.mockResolvedValue({saved:1,skipped:0})})
afterEach(()=>{w?.unmount();w=undefined;const pinia=getActivePinia();if(pinia)disposePinia(pinia);localStorage.clear()})
async function start(entity:'budget'|'expense'='expense'){const pinia=createPinia();setActivePinia(pinia);useUserStore().token='finance-preview-session';w=mount(FinanceImportDialog,{props:{entity,options,modelValue:true},global:{plugins:[ElementPlus,pinia],stubs:{ElDialog:{props:['modelValue'],template:'<div v-if="modelValue"><slot/><slot name="footer"/></div>'}}}});await flushPromises();return w}
const button=(wrapper:VueWrapper,text:string)=>wrapper.findAll('button').find(b=>b.text()===text)!
describe('shared finance preview and explicit commit',()=>{
  it('corrected Excel cells recalculate the preview immediately without committing or inventing scope',async()=>{api.previewBudgetFile.mockResolvedValue({token:'budget-preview',total:1,note:'预览',fileHash:'hash',rows:[{rowNo:2,sheetName:'Sheet1',name:'亮甲2.0',kind:'platform',currency:'CNY',productLineId:null,itemId:null,moldSetId:null,budgetId:null,values:{moldCost:14770,moldWeight:55,transportRate:74.68,fuelRate:33.18,customsCost:1000,salePrice:8,unitProductionCost:4.8},issues:[],formulas:{},before:{},calculatedTotal:21702.3,breakEvenQuantity:6782}]});const wrapper=await start('budget');const input=wrapper.get('input[type="file"]');Object.defineProperty(input.element,'files',{value:[new File(['source'],'budget.xlsx')],configurable:true});await input.trigger('change');await flushPromises();expect(wrapper.text()).toContain('21702.3');await wrapper.get('input[data-field="moldCost"]').setValue('10000');expect(wrapper.text()).toContain('16932.3');expect(api.commitBudgetFile).not.toHaveBeenCalled();expect(wrapper.text()).toContain('明确选择产品平台');expect(wrapper.text()).toContain('保存以服务器复算为准')})
  it('an unconfigured server pull never invents rows or writes expenses',async()=>{api.refreshErpExpenses.mockResolvedValue({status:'not_configured',message:'未配置，没有外部调用'});const w=await start();await button(w,'从服务器只读拉取ERP明细').trigger('click');await flushPromises();expect(api.refreshErpExpenses).toHaveBeenCalledOnce();expect(api.commitErpExpenses).not.toHaveBeenCalled();expect(w.findAll('.el-table__body tbody tr')).toHaveLength(0);expect(w.text()).toContain('未配置明确提示，不伪造实时数据')})
  it('server ERP rows still require an explicit scope and mapping reason before commit',async()=>{api.refreshErpExpenses.mockResolvedValue({status:'preview_ready',token:'server-preview',rows:[{rowNo:1,voucherId:'GL1',lineId:'ROW1',description:'冲销',currency:'CNY',postedAmount:-100,reversalOf:'GL0/ROW0',issues:['不按金额匹配']}],total:1,note:'只读核对',fileHash:'hash'});const w=await start();await button(w,'从服务器只读拉取ERP明细').trigger('click');await flushPromises();expect(w.text()).toContain('GL1');expect(w.text()).toContain('-100');await button(w,'确认映射并提交').trigger('click');expect(api.commitErpExpenses).not.toHaveBeenCalled();w.findAllComponents(ElSelect)[0].vm.$emit('update:modelValue',1);await w.get('textarea[placeholder="按单据/合同/模具ID确认的归属依据"]').setValue('合同明确属于所选平台');await button(w,'确认映射并提交').trigger('click');await flushPromises();expect(api.commitErpExpenses).toHaveBeenCalledWith('server-preview',[expect.objectContaining({voucherId:'GL1',lineId:'ROW1',productLineId:1,mappingReason:'合同明确属于所选平台'})]);expect(w.emitted('completed')).toHaveLength(1)})
  it('closes and clears a financial preview on account replacement and ignores the previous account response',async()=>{
    let finish!: (value:unknown)=>void
    api.refreshErpExpenses.mockImplementation(()=>new Promise(resolve=>{finish=resolve}))
    const wrapper=await start();await button(wrapper,'从服务器只读拉取ERP明细').trigger('click')
    useUserStore().token='another-session'
    finish({status:'preview_ready',token:'old-session-preview',total:1,note:'旧账号金额',rows:[{rowNo:1,voucherId:'OLD-GL',lineId:'1',currency:'CNY',postedAmount:12345,issues:[]}]});await flushPromises()
    expect(wrapper.emitted('update:modelValue')).toContainEqual([false])
    expect(wrapper.text()).not.toContain('OLD-GL');expect(wrapper.text()).not.toContain('12345')
    expect(api.commitErpExpenses).not.toHaveBeenCalled()
  })
})
