import { mount, flushPromises, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import ElementPlus, { ElPagination, ElSelect } from 'element-plus'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
const api = vi.hoisted(() => ({ getMoldSourceCodes: vi.fn(), getMoldSourceSummary: vi.fn() }))
vi.mock('@/api/modules/moldSources', () => api)
vi.mock('@/components/FixedTableViewport/index.vue', () => ({ default: { template: '<div><slot :table-height="400" /></div>' } }))
import MoldSourceCodes from '../components/MoldSourceCodes.vue'
import { useUserStore } from '@/stores/user'
const row = (n = 1) => ({ sourceCodeId: n, sourceSystem: 'erp', moldCode: `MBA20${String(n).padStart(4, '0')}`, moldName: 'IP 11\t', itemGroup: 'MBA20PC', specifications: 'PC\t', originalAlias: null, disabled: false, styleCode: 'BA', phoneModelCode: String(n).padStart(4, '0'), partType: 'PC', archiveCount: 1, itemId: n, styleName: '亮甲2.0', compatibleModels: 'Apple iPhone 11', pcCount: 1, tpuCount: 1, nameCount: 1, approvalInstanceId: null })
let w: VueWrapper | undefined
beforeEach(() => { vi.clearAllMocks(); localStorage.clear(); api.getMoldSourceCodes.mockImplementation(async q => ({ content: Array.from({ length: q.size }, (_, i) => row(i + 1)), totalElements: 3770, page: q.page, size: q.size })); api.getMoldSourceSummary.mockResolvedValue({ erp: 3770, dingtalk: 0, paired: 1240, nonstandard: 1013, name_conflicts: 13 }) })
afterEach(() => { w?.unmount(); w = undefined; vi.useRealTimers() })
async function start(visible = true) {
  const pinia = createPinia(); setActivePinia(pinia); useUserStore().token = 'source-test'
  const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/', component: { template: '<p />' } }, { path: '/collaboration-plans', component: { template: '<p>archive</p>' } }] }); await router.push('/'); await router.isReady()
  w = mount(MoldSourceCodes, { props: { visible }, global: { plugins: [ElementPlus, pinia, router] } }); await flushPromises(); return { w, router }
}
describe('read-only ERP / DingTalk code review', () => {
  it('loads only on opening, renders a page of fifty codes and does not infer physical sets', async () => {
    const { w } = await start(false); expect(api.getMoldSourceCodes).not.toHaveBeenCalled()
    await w.setProps({ visible: true }); await flushPromises()
    expect(w.findAll('.el-table__body tbody tr')).toHaveLength(50)
    expect(w.text()).toContain('MBA200001'); expect(w.text()).toContain('0001'); expect(w.text()).toContain('未自动建立任何实物模具套')
    expect(w.text()).toContain('PC＋TPU 编码对'); expect(w.text()).not.toContain('1240 套')
  })
  it('paginates and filters independently without overwriting the ledger or its drafts', async () => {
    const { w } = await start()
    w.findComponent(ElPagination).vm.$emit('update:current-page', 2); w.findComponent(ElPagination).vm.$emit('current-change', 2); await flushPromises()
    expect(api.getMoldSourceCodes).toHaveBeenLastCalledWith(expect.objectContaining({ page: 2, size: 50 }))
    w.findAllComponents(ElSelect)[2].vm.$emit('update:modelValue', 'name_conflict'); await flushPromises()
    expect(api.getMoldSourceCodes).toHaveBeenLastCalledWith(expect.objectContaining({ page: 1, review: 'name_conflict' }))
    expect(w.findComponent(ElPagination).props('pageSizes')).toEqual([20, 50, 100])
  })
  it('shows source mismatches, missing parts and unknown approval trace explicitly', async () => {
    api.getMoldSourceCodes.mockResolvedValue({ content: [{ ...row(), sourceSystem: 'dingtalk', nameCount: 2, tpuCount: 0, archiveCount: 0, itemId: null }], totalElements: 1 })
    const { w } = await start(); expect(w.text()).toContain('名称不一致'); expect(w.text()).toContain('PC / TPU 不完整'); expect(w.text()).toContain('不虚构审批记录')
    expect(w.findAll('button').some(b => b.text().startsWith('查看关联档案'))).toBe(false)
  })
  it('debounces continuous search and preserves original codes in a cross-page hit', async () => {
    const { w } = await start(); vi.useFakeTimers()
    const input = w.get('input[placeholder="搜索 ERP 原编码 / 名称 / 规格 / 型号 / 别名"]')
    await input.setValue('MBA'); await vi.advanceTimersByTimeAsync(250); await input.setValue('MBA200052'); await vi.advanceTimersByTimeAsync(299)
    expect(api.getMoldSourceCodes).toHaveBeenCalledTimes(1)
    api.getMoldSourceCodes.mockResolvedValue({ content: [row(52)], totalElements: 1 }); await vi.advanceTimersByTimeAsync(1); await flushPromises()
    expect(api.getMoldSourceCodes).toHaveBeenLastCalledWith(expect.objectContaining({ keyword: 'MBA200052', page: 1 }))
    expect(w.text()).toContain('0052')
  })
  it('returns from the sixty-second cache and clears source results on logout', async () => {
    const { w } = await start(); await w.setProps({ visible: false }); await w.setProps({ visible: true }); await flushPromises()
    expect(api.getMoldSourceCodes).toHaveBeenCalledTimes(1)
    useUserStore().token = ''; await flushPromises(); expect(w.findAll('.el-table__body tbody tr')).toHaveLength(0)
    expect(w.text()).not.toContain('MBA200001')
  })
  it('opens only the exact archive without creating molds or changing historical projects', async () => {
    const { w, router } = await start(); await w.findAll('button').find(b => b.text() === '查看关联档案（不创建实物）')!.trigger('click'); await flushPromises()
    expect(router.currentRoute.value.fullPath).toBe('/collaboration-plans?view=market&itemId=1')
    expect(w.emitted('close')).toHaveLength(1)
  })
})
