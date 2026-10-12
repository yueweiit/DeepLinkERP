import { mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const processApi = vi.hoisted(() => ({
  getProcessCenterSnapshot: vi.fn(),
  getProcessOperationMasters: vi.fn(),
  getProcessRouteTemplates: vi.fn(),
  getProcessRouteRelations: vi.fn(),
  confirmProcessOperationMaster: vi.fn(),
  createProcessOperationMaster: vi.fn()
}))

vi.mock('@/api/modules/process', () => processApi)
vi.mock('vue-router', () => ({
  useRoute: () => ({ query: {} }),
  useRouter: () => ({ push: vi.fn() })
}))

import ProcessCenterView from '../ProcessCenterView.vue'

describe('ProcessCenterView', () => {
  beforeEach(() => {
    processApi.getProcessOperationMasters.mockResolvedValue([])
    processApi.getProcessRouteTemplates.mockResolvedValue([])
    processApi.getProcessCenterSnapshot.mockResolvedValue({
      metrics: [], templates: [], routeDetails: {},
      routes: [{
        routeId: 81, processId: 81, routeCode: 'DYE', routeName: '染色工艺路线', productId: 7,
        productCode: 'NBA4030', productName: '亮甲 2.0', versionNo: 'V1',
        routeType: 'new_product_line', status: 'released', templateSource: 'standard',
        owner: '张工', operationCount: 5, totalCost: 2.3, currentGate: '已发布', riskLevel: 'low',
        hasExternalOperation: false, hasDifferenceOperation: false, targetPath: '/products/7',
        skuCount: 1,
        colors: [{ codeItemId: 2, colorCode: '02', colorName: '蓝色' }]
      }]
    })
    processApi.getProcessRouteRelations.mockResolvedValue({
      processId: 81,
      processCode: 'DYE',
      processName: '染色工艺路线',
      productId: 7,
      productCode: 'NBA4030',
      productName: '亮甲 2.0',
      versionNo: 'V1',
      status: 'released',
      colors: [{ codeItemId: 2, colorCode: '02', colorName: '蓝色' }],
      skus: [{
        productId: 9, skuCode: 'NBA4030112231', productName: '亮甲 2.0',
        phoneModel: 'Samsung A56', color: '蓝色', status: 'released', routeCode: 'DYE'
      }],
      operations: [{
        processId: 91,
        parentProcessId: 81,
        processCode: 'OP-DYE',
        operationCraftCode: '30',
        sequenceNo: 1,
        processName: '喷涂',
        qualityRequirement: '颜色一致',
        status: 'locked'
      }]
    })
  })

  it('opens the route relation drawer with colors skus and operations', async () => {
    const wrapper = mount(ProcessCenterView, { global: { plugins: [ElementPlus] }, attachTo: document.body })
    await wrapper.findAll('.el-segmented__item')[2].trigger('click')
    await vi.waitFor(() => expect(wrapper.text()).toContain('亮甲 2.0'))
    await wrapper.get('[data-test="process-route-skus"]').trigger('click')

    await vi.waitFor(() => expect(processApi.getProcessRouteRelations).toHaveBeenCalledWith(81))
    expect(document.body.textContent).toContain('工艺路线详情：染色工艺路线')
    expect(document.body.textContent).toContain('适用颜色')
    expect(document.body.textContent).toContain('NBA4030112231')
    expect(document.body.textContent).toContain('Samsung A56')
    expect(document.body.textContent).toContain('蓝色')
    expect(document.body.textContent).toContain('喷涂')
    wrapper.unmount()
  })
})
