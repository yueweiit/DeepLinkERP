import { mount, flushPromises } from '@vue/test-utils'
import ElementPlus, { ElPagination } from 'element-plus'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const api = vi.hoisted(() => ({
  getBomProductPage: vi.fn(), getProductBomPage: vi.fn(), getBomWorkbench: vi.fn(), getBomSkus: vi.fn(),
  previewHistoricalBomImport: vi.fn(), commitHistoricalBomImport: vi.fn(),
  downloadHistoricalBomTemplate: vi.fn(), downloadBomImportErrors: vi.fn()
}))
vi.mock('@/api/modules/bom', () => api)

import BomCenterView from '../BomCenterView.vue'
import HistoricalBomImportDialog from '../components/HistoricalBomImportDialog.vue'

describe('BomCenterView', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    api.getBomProductPage.mockResolvedValue({ content: [{ productId: 7, productCode: 'NBA4030', productName: '亮甲 2.0', bomCount: 1 }], page: 1, size: 50, totalElements: 1, totalPages: 1 })
    api.getProductBomPage.mockResolvedValue({ content: [{
      productBomId: 31, productId: 7, bomCode: 'BOM-NBA-001', productCode: 'NBA4030',
      productName: '亮甲 2.0', model: null, versionNo: 'V1', routeCount: 2, skuCount: 70,
      status: 'released', sourceType: 'manual', updatedAt: '2026-07-18T10:00:00'
    }], page: 1, size: 50, totalElements: 1, totalPages: 1 })
    api.getBomWorkbench.mockResolvedValue({
      productBomId: 31, productId: 7, bomCode: 'BOM-NBA-001', bomName: '亮甲正式 BOM',
      bomScope: 'formal', versionNo: 'V1', status: 'released', testItems: [],
      routes: [{ productBomRouteId: 81, processId: 9, routeCode: 'DYE', routeName: '染色路线', colors: ['黑色', '蓝色'], items: [], costSnapshot: null }]
    })
    api.getBomSkus.mockResolvedValue([{ productId: 9, skuCode: 'NBA4030112231', productName: '亮甲 2.0', phoneModel: 'Samsung A56', color: '蓝色', status: 'released', routeCode: 'DYE' }])
  })

  it('keeps list basic and opens detail drawer and related SKU dialog', async () => {
    const wrapper = mount(BomCenterView, { global: { plugins: [ElementPlus] }, attachTo: document.body })
    await vi.waitFor(() => expect(wrapper.text()).toContain('NBA4030'))
    expect(api.getProductBomPage).not.toHaveBeenCalled()
    expect(api.getBomWorkbench).not.toHaveBeenCalled()
    expect(api.getBomSkus).not.toHaveBeenCalled()
    await wrapper.get('[data-test="bom-product"]').trigger('click')
    await vi.waitFor(() => expect(wrapper.text()).toContain('BOM-NBA-001'))
    expect(api.getProductBomPage).toHaveBeenCalledWith({ productId: 7, page: 1, size: 50, keyword: '' })
    expect(wrapper.text()).toContain('BOM-NBA-001')
    expect(wrapper.text()).toContain('亮甲 2.0')
    expect(wrapper.text()).toContain('关联 SKU')

    await wrapper.get('[data-test="bom-detail"]').trigger('click')
    await vi.waitFor(() => expect(api.getBomWorkbench).toHaveBeenCalledWith(31))
    expect(document.body.textContent).toContain('染色路线')

    await wrapper.get('[data-test="bom-skus"]').trigger('click')
    await vi.waitFor(() => expect(api.getBomSkus).toHaveBeenCalledWith(31))
    expect(document.body.textContent).toContain('Samsung A56')
    await wrapper.get('[data-test="bom-back"]').trigger('click')
    expect(api.getBomProductPage).toHaveBeenCalledTimes(1)
    expect(wrapper.text()).toContain('条产品线')
    wrapper.unmount()
  })

  it('provides historical BOM batch import from the ledger', async () => {
    const wrapper = mount(BomCenterView, { global: { plugins: [ElementPlus] } })
    await vi.waitFor(() => expect(api.getBomProductPage).toHaveBeenCalled())
    expect(wrapper.find('[data-test="historical-bom-import"]').exists()).toBe(true)
    wrapper.unmount()
  })

  it('preserves product paging when the BOM page size changes and refreshes the current level after importing', async () => {
    api.getBomProductPage.mockResolvedValue({ content: [{ productId: 7, productCode: 'NBA4030', productName: '亮甲 2.0', bomCount: 1 }], page: 2, size: 50, totalElements: 100, totalPages: 2 })
    const wrapper = mount(BomCenterView, { global: { plugins: [ElementPlus] } })
    await vi.waitFor(() => expect(wrapper.find('[data-test="bom-product"]').exists()).toBe(true))
    wrapper.getComponent(ElPagination).vm.$emit('current-change', 2)
    await flushPromises()
    await vi.waitFor(() => expect(api.getBomProductPage).toHaveBeenCalledTimes(2))
    await wrapper.get('[data-test="bom-product"]').trigger('click')
    await flushPromises()
    await vi.waitFor(() => expect(api.getProductBomPage).toHaveBeenCalledTimes(1))
    wrapper.getComponent(ElPagination).vm.$emit('update:page-size', 100)
    await flushPromises()
    await vi.waitFor(() => expect(api.getProductBomPage).toHaveBeenLastCalledWith(expect.objectContaining({ size: 100 })))
    wrapper.getComponent(HistoricalBomImportDialog).vm.$emit('committed')
    await flushPromises()
    await vi.waitFor(() => expect(api.getProductBomPage).toHaveBeenCalledTimes(3))
    expect(api.getBomProductPage).toHaveBeenCalledTimes(2)
    await wrapper.get('[data-test="bom-back"]').trigger('click')
    await flushPromises()
    await vi.waitFor(() => expect(api.getBomProductPage).toHaveBeenCalledTimes(3))
    expect(api.getBomProductPage).toHaveBeenLastCalledWith({ page: 2, size: 50, keyword: '' })
    wrapper.unmount()
  })
})
