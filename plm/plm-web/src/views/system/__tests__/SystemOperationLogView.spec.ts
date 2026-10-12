import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createPinia, disposePinia, setActivePinia, type Pinia } from 'pinia'
import ElementPlus, { ElDatePicker, ElPagination, ElSelect } from 'element-plus'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useUserStore } from '@/stores/user'
import type { OperationLogItem } from '@/api/modules/system'
const api=vi.hoisted(()=>({getOperationLogs:vi.fn(),getSystemUsers:vi.fn()}))
vi.mock('@/api/modules/system',()=>api)
vi.mock('@/components/FixedTableViewport/index.vue',()=>({default:{props:{fill:Boolean},template:'<div><slot :table-height="480" /></div>'}}))
import FixedTableViewport from '@/components/FixedTableViewport/index.vue'
import SystemOperationLogView from '../SystemOperationLogView.vue'
const accounts=['newman','young','Tony','Tony Granillo','Tiffany'].map((displayName,index)=>({userId:101+index,displayName,username:displayName.toLowerCase().replace(' ','.'),status:'active',roleCode:'administrator'}))
const log=(id=1):OperationLogItem=>({logId:id,operatorUserId:103,operatorUserName:'Tony',action:'PILOT_USER_GRANTS_SAVE',businessType:'PILOT_USER',businessId:'105',businessCode:'tiffany',businessName:'Tiffany',result:'success',requestId:`real-request-${id}`,createdAt:'2026-10-12T12:30:45',detailJson:null})
let wrapper:VueWrapper|undefined,pinia:Pinia
beforeEach(()=>{vi.clearAllMocks();localStorage.clear();pinia=createPinia();setActivePinia(pinia);useUserStore().token='test';useUserStore().permissions=['*'];api.getSystemUsers.mockResolvedValue(accounts);api.getOperationLogs.mockResolvedValue({content:[log()],page:1,size:50,totalElements:101,totalPages:3})})
afterEach(()=>{wrapper?.unmount();wrapper=undefined;disposePinia(pinia);vi.useRealTimers();vi.restoreAllMocks()})
async function start(){wrapper=mount(SystemOperationLogView,{global:{plugins:[pinia,ElementPlus]}});await flushPromises();return wrapper}
describe('existing server operation log viewer',()=>{
  it('loads fifty server records with separate real accounts and displays stored actor and time without fake audit statistics',async()=>{
    api.getOperationLogs.mockResolvedValue({content:Array.from({length:50},(_,i)=>log(i+1)),page:1,size:50,totalElements:101,totalPages:3})
    const view=await start();expect(api.getOperationLogs).toHaveBeenCalledWith(expect.objectContaining({page:1,size:50}));expect(api.getSystemUsers).toHaveBeenCalledTimes(1)
    expect(view.findComponent(FixedTableViewport).props('fill')).toBe(true)
    expect(view.findAll('.el-table__body tbody tr')).toHaveLength(50);expect(view.findComponent(ElPagination).props('pageSizes')).toEqual([20,50,100])
    expect(view.text()).toContain('Tony');expect(view.text()).toContain('2026-10-12 12:30:45');expect(view.text()).toContain('不代表全部查询、下载或失败请求均已审计')
    const selector=view.findComponent(ElSelect);expect(selector.findAllComponents({name:'ElOption'}).map(option=>option.props('label'))).toEqual(expect.arrayContaining(['Tony · tony','Tony Granillo · tony.granillo']))
  })
  it('submits actor, exact action and ISO local time to server filtering and resets pagination',async()=>{
    const view=await start(),pagination=view.findComponent(ElPagination)
    pagination.vm.$emit('update:current-page',3);pagination.vm.$emit('current-change',3);await flushPromises()
    view.findComponent(ElSelect).vm.$emit('update:modelValue',104);view.findComponent(ElDatePicker).vm.$emit('update:modelValue',['2026-10-01T00:00:00','2026-10-12T23:59:59'])
    await view.get('input[placeholder="动作代码（精确匹配，如 AUTH_LOGIN）"]').setValue('AUTH_LOGIN');await flushPromises()
    await view.findAll('button').find(button=>button.text()==='刷新日志')!.trigger('click');await flushPromises()
    expect(api.getOperationLogs).toHaveBeenLastCalledWith({page:1,size:50,operatorUserId:104,action:'AUTH_LOGIN',createdFrom:'2026-10-01T00:00:00',createdTo:'2026-10-12T23:59:59'})
    pagination.vm.$emit('update:current-page',2);pagination.vm.$emit('current-change',2);await flushPromises()
    expect(api.getOperationLogs).toHaveBeenLastCalledWith(expect.objectContaining({page:2,operatorUserId:104,action:'AUTH_LOGIN'}))
  })
  it('displays server-redacted detail without another row query and preserves metadata with escaped text',async()=>{
    api.getOperationLogs.mockResolvedValue({content:[{...log(),detailJson:JSON.stringify({before:{password:'[REDACTED]',nested:{appSecret:'[REDACTED]'}},after:{token:'[REDACTED]',role:'administrator',notes:'<script>not executable</script>'},passwordChanged:true})}],page:1,size:50,totalElements:1,totalPages:1})
    const view=await start();await view.findAll('button').find(button=>button.text()==='查看详情')!.trigger('click');await flushPromises()
    const details=view.get('[data-test="operation-log-detail"]');expect(details.text()).toContain('[REDACTED]');expect(details.text()).toContain('"passwordChanged": true');expect(details.text()).toContain('administrator')
    expect(details.find('script').exists()).toBe(false);expect(api.getOperationLogs).toHaveBeenCalledTimes(1)
  })
  it('rejects late filter results and clears records and open details when the real session ends',async()=>{
    const view=await start();let finish!:(value:unknown)=>void
    api.getOperationLogs.mockImplementationOnce(()=>new Promise(resolve=>{finish=resolve}));vi.useFakeTimers()
    const input=view.get('input[placeholder="动作代码（精确匹配，如 AUTH_LOGIN）"]');await input.setValue('OLD');await vi.advanceTimersByTimeAsync(300)
    api.getOperationLogs.mockResolvedValue({content:[{...log(),action:'LATEST'}],page:1,size:50,totalElements:1,totalPages:1});await input.setValue('LATEST');await vi.advanceTimersByTimeAsync(300);await flushPromises()
    finish({content:[{...log(),action:'OLD'}],page:1,size:50,totalElements:1,totalPages:1});await flushPromises();expect(view.get('.operation-log-table').text()).toContain('LATEST');expect(view.get('.operation-log-table').text()).not.toContain('OLD')
    await view.findAll('button').find(button=>button.text()==='查看详情')!.trigger('click');useUserStore().token='';await flushPromises()
    expect(view.findAll('.el-table__body tbody tr')).toHaveLength(0);expect(view.find('[data-test="operation-log-detail"]').exists()).toBe(false)
  })
})
