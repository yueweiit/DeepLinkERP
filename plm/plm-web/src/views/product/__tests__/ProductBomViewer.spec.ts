import { mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { describe, expect, it, vi } from 'vitest'

const api = vi.hoisted(() => ({ getProductBomSummary: vi.fn() }))
vi.mock('@/api/modules/bom', () => api)

import ProductBomViewer from '../components/ProductBomViewer.vue'

describe('ProductBomViewer', () => {
  it('separates test total from formal route BOM and cost', async () => {
    api.getProductBomSummary.mockResolvedValue({
      testTotalCost: 12.5,
      testCalculatedAt: '2026-07-18T10:00:00',
      testVersionNo: 'T1',
      formalVersions: [{
        productBomId: 31, productId: 7, bomCode: 'BOM-31', bomName: '正式 BOM', bomScope: 'formal',
        versionNo: 'V1', status: 'released', testItems: [], routes: [{
          productBomRouteId: 81, processId: 9, routeCode: 'DYE', routeName: '染色路线', colors: ['蓝色'],
          items: [{ lineNo: 1, itemCode: 'MAT-1', itemName: 'TPU', quantity: 2, unit: 'kg' }],
          costSnapshot: { materialCost: 10, lossCost: 1, processCost: 2, packageCost: 0, laborCost: 0, toolingCost: 0, otherCost: 0, totalCost: 13, currencyCode: 'CNY', calculatedAt: '2026-07-18T11:00:00' }
        }]
      }]
    })
    const wrapper = mount(ProductBomViewer, { props: { productId: 7 }, global: { plugins: [ElementPlus] } })
    await vi.waitFor(() => expect(wrapper.text()).toContain('12.5'))
    expect(wrapper.text()).toContain('测试 BOM 成本')
    expect(wrapper.text()).toContain('正式 BOM')
    await wrapper.get('[data-test="formal-mode"]').trigger('click')
    expect(wrapper.text()).toContain('染色路线')
    expect(wrapper.text()).toContain('CNY 13')
    expect(wrapper.text()).toContain('TPU')
  })
})
