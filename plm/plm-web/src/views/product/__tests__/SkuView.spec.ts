import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { describe, expect, it, vi } from 'vitest'

import SkuView from '../SkuView.vue'

const productApi = vi.hoisted(() => ({
  getProductList: vi.fn()
}))

vi.mock('@/api/modules/product', () => productApi)
vi.mock('@/api/modules/foundation', () => ({
  getProductPresentation: vi.fn()
}))
vi.mock('@/api/modules/attachment', () => ({
  deleteAttachment: vi.fn(),
  downloadAttachment: vi.fn(),
  getProductAttachments: vi.fn().mockResolvedValue([]),
  uploadProductAttachment: vi.fn()
}))
vi.mock('vue-router', () => ({
  useRouter: () => ({ push: vi.fn() })
}))
vi.mock('@/utils/projectRoute', () => ({
  toInProgressProjectRoute: () => '/projects/in-progress'
}))

function product(overrides: Record<string, unknown>) {
  return {
    productId: 1,
    parentProductId: null,
    productCode: 'PRD-SUPER-0001',
    productSpecificCode: 'HA',
    phoneModelCode: null,
    colorCode: null,
    finishedProductCode: null,
    productName: '超队 4.0',
    productType: 'product_line',
    seriesName: '超队',
    model: '',
    color: '',
    material: '',
    ownerUserName: 'tester',
    versionNo: 'A',
    status: 'released',
    currentStage: 'released',
    customerName: '',
    frozenFlag: false,
    releasedAt: null,
    completionRate: 100,
    estimatedCost: 0,
    estimatedCostCurrency: 'CNY',
    actualCost: 0,
    createdAt: '2026-08-11T00:00:00',
    updatedAt: '2026-08-11T00:00:00',
    createdBy: 'tester',
    ...overrides
  }
}

describe('SkuView', () => {
  it('shows product line code and finished product code instead of PRD code', async () => {
    productApi.getProductList.mockImplementation((params: { productType?: string }) => {
      if (params.productType === 'product_line') {
        return Promise.resolve([product({})])
      }
      if (params.productType === 'sku') {
        return Promise.resolve([
          product({
            productId: 2,
            parentProductId: 1,
            productCode: 'PRD-SUPER-0001-02',
            productName: '超队 4.0 SM S281 Negro',
            productType: 'sku',
            model: 'SM S281',
            color: 'Negro',
            phoneModelCode: '1291',
            colorCode: '02',
            finishedProductCode: 'NHA4030129102'
          })
        ])
      }
      return Promise.resolve([])
    })

    const wrapper = mount(SkuView, {
      global: {
        plugins: [ElementPlus],
        stubs: {
          PageContainer: { template: '<main><slot /></main>' },
          FixedTableViewport: { template: '<div><slot :table-height="480" /></div>' },
          StatusTag: { template: '<span />' },
          FilePreview: { template: '<div />' },
          ProjectFlowPanel: { template: '<div />' }
        }
      }
    })
    await flushPromises()

    expect(wrapper.text()).toContain('NHA4030')

    await wrapper.find('button.sku-product-card').trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('NHA4030129102')
    expect(wrapper.text()).not.toContain('PRD-SUPER-0001-02')
  })
})
