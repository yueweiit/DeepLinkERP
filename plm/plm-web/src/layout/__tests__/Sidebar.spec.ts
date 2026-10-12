import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory, createRouter, type Router } from 'vue-router'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { useUserStore } from '@/stores/user'
import Sidebar from '../Sidebar.vue'

vi.mock('@/api/modules/marketWatch', () => ({
  getMarketWatchConfig: vi.fn().mockResolvedValue({ enabled: false })
}))

let wrapper: VueWrapper | undefined

afterEach(() => wrapper?.unmount())

async function start(permissions = ['*'], path = '/molds', roleCode = '') {
  const pinia = createPinia()
  setActivePinia(pinia)
  useUserStore().permissions = permissions
  useUserStore().profile = {userId:1,userName:'测试',roleName:'测试',department:'测试',roleCode}
  const router: Router = createRouter({
    history: createMemoryHistory(),
    routes: ['/molds','/files','/projects','/collaboration-plans','/dashboard','/my-tasks','/pilot/tasks','/mold-schedules','/development-budgets','/development-expenses','/production-orders','/orders','/market-watch','/bom','/processes','/inventories','/suppliers','/phone-model-codes','/code-center','/reports','/system/users','/system/operation-log','/approval-tasks','/system/assignments','/system/fields','/system/integrations','/system/trials','/system/import'].map(path => ({
      path, component: { template: '<div />' }
    }))
  })
  await router.push(path)
  await router.isReady()
  wrapper = mount(Sidebar, {
    global: { plugins: [pinia, router], stubs: { ElIcon: { template: '<span><slot /></span>' } } }
  })
  await flushPromises()
  return { wrapper, router }
}

describe('mold ledger navigation', () => {
  it('opens the basic-data group for the mold URL and keeps one mold entry', async () => {
    const { wrapper, router } = await start()
    const active = wrapper.get('.sidebar__group.is-active-group')
    expect(active.get('.sidebar__group-label').text()).toBe('基础资料')
    expect(active.get('.sidebar__item.is-active').text()).toBe('模具管理')
    expect(wrapper.findAll('.sidebar__item').filter(item => item.text() === '模具管理')).toHaveLength(1)
    await wrapper.findAll('.sidebar__group-trigger').find(button=>button.text()==='系统管理')!.trigger('click')
    await wrapper.findAll('.sidebar__item').find(button=>button.text()==='操作日志')!.trigger('click');await flushPromises()
    expect(router.currentRoute.value.path).toBe('/system/operation-log');expect(wrapper.get('.sidebar__item.is-active').text()).toBe('操作日志')
  })

  it('keeps collaboration in project management without a duplicate mold entry', async () => {
    const { wrapper } = await start(['*'], '/collaboration-plans')
    const active = wrapper.get('.sidebar__group.is-active-group')
    expect(active.get('.sidebar__group-label').text()).toBe('项目管理')
    expect(active.text()).toContain('协作计划')
    expect(active.text()).not.toContain('模具管理')
  })

  it('retains the mold URL and existing collaboration permission', async () => {
    const { wrapper, router } = await start(['collaboration:view'], '/collaboration-plans')
    await wrapper.findAll('.sidebar__group-trigger').find(button => button.text() === '基础资料')!.trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.path).toBe('/collaboration-plans')
    await wrapper.findAll('.sidebar__item').find(button => button.text() === '模具管理')!.trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.path).toBe('/molds')
    expect(wrapper.get('.sidebar__item.is-active').text()).toBe('模具管理')
  })

  it('does not expose molds without the original collaboration permission', async () => {
    const { wrapper } = await start(['product:view'], '/files')
    expect(wrapper.text()).not.toContain('模具管理')
    expect(wrapper.text()).not.toContain('操作日志')
  })
  it('highlights exactly one query report and defaults direct report links to schedule',async()=>{
    const {wrapper,router}=await start(['*'],'/reports?view=finance')
    expect(wrapper.findAll('.sidebar__item.is-active').map(b=>b.text())).toEqual(['预算与实际'])
    await router.push('/reports');await flushPromises()
    expect(wrapper.findAll('.sidebar__item.is-active').map(b=>b.text())).toEqual(['项目周期'])
  })
  it('shows external accounts only their working phone-task entry',async()=>{
    const {wrapper}=await start(['pilot:tasks','task:ship'],'/pilot/tasks','supplier')
    expect(wrapper.findAll('.sidebar__group-label').map(b=>b.text())).toEqual(['工作台'])
    expect(wrapper.get('.sidebar__item.is-active').text()).toBe('我的待办')
    expect(wrapper.text()).not.toContain('费用管理')
  })
  it('keeps platform archives separate from the general project-center highlight',async()=>{
    const {wrapper}=await start(['*'],'/projects?tab=archived&archiveView=product')
    expect(wrapper.get('.sidebar__group.is-active-group .sidebar__group-label').text()).toBe('基础资料')
    expect(wrapper.get('.sidebar__item.is-active').text()).toBe('产品平台与型号')
  })
})
