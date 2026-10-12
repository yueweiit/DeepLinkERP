import { mount, flushPromises } from '@vue/test-utils'
import ElementPlus, { ElCascader, ElPagination, ElSelect } from 'element-plus'
import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest'

const api = vi.hoisted(() => ({ getInventoryPage: vi.fn(), getInventoryGroups: vi.fn() }))
vi.mock('@/api/modules/foundation', () => api)
import InventoryCenterView from '../InventoryCenterView.vue'

const records = Array.from({ length: 50 }, (_, index) => ({ itemId: String(index), nodeId: 'material-group:1',
  code: `INV-${index}`, name: `物料 ${index}`, spec: '--', stock: '0', inventoryType: '原材料',
  supplierName: '--', status: 'available', updatedAt: '2026-10-08' }))
beforeEach(() => {
  vi.clearAllMocks()
  api.getInventoryGroups.mockResolvedValue([{ nodeId: 'all', label: '全部物料', nodeType: 'category', children: [
    { nodeId: 'material-group:1', label: '原料', nodeType: 'category', children: [] }
  ] }])
  api.getInventoryPage.mockResolvedValue({ content: records, page: 1, size: 50, totalElements: 7803, totalPages: 157 })
})
afterEach(() => vi.useRealTimers())

describe('InventoryCenterView', () => {
  it('loads only the first server page and paginates with combined filters', async () => {
    const wrapper = mount(InventoryCenterView, { global: { plugins: [ElementPlus] } })
    await flushPromises()
    expect(api.getInventoryPage).toHaveBeenCalledWith({ page: 1, size: 50, keyword: '', nodeId: 'all', timeRange: 'all' })
    expect(wrapper.findAll('.el-table__body tbody tr')).toHaveLength(50)
    expect(wrapper.text()).toContain('7803 条记录')
    wrapper.findComponent(ElPagination).vm.$emit('current-change', 157)
    await flushPromises()
    expect(api.getInventoryPage).toHaveBeenLastCalledWith(expect.objectContaining({ page: 157 }))
    wrapper.findComponent(ElCascader).vm.$emit('update:modelValue', 'material-group:1')
    wrapper.findComponent(ElSelect).vm.$emit('update:modelValue', '90d')
    await flushPromises()
    expect(api.getInventoryPage).toHaveBeenLastCalledWith(expect.objectContaining({ page: 1, nodeId: 'material-group:1', timeRange: '90d' }))
    wrapper.unmount()
  })

  it('debounces continuous input by 300ms and searches beyond the current page', async () => {
    const wrapper = mount(InventoryCenterView, { global: { plugins: [ElementPlus] } })
    await flushPromises()
    vi.useFakeTimers()
    const search = wrapper.get('input[placeholder="搜索编码 / 名称 / 规格 / 供应商 / 产品"]')
    await search.setValue('INV-7')
    await vi.advanceTimersByTimeAsync(200)
    await search.setValue('INV-7802')
    await vi.advanceTimersByTimeAsync(299)
    expect(api.getInventoryPage).toHaveBeenCalledTimes(1)
    api.getInventoryPage.mockResolvedValue({ content: [{ ...records[0], code: 'INV-7802' }], totalElements: 1, page: 1, size: 50, totalPages: 1 })
    await vi.advanceTimersByTimeAsync(1)
    await flushPromises()
    expect(api.getInventoryPage).toHaveBeenLastCalledWith(expect.objectContaining({ keyword: 'INV-7802', page: 1 }))
    expect(wrapper.text()).toContain('INV-7802')
    wrapper.unmount()
  })
})
