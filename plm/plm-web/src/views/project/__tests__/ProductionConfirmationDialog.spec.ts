import { mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const bomApi = vi.hoisted(() => ({
  getProjectBoms: vi.fn(),
  getBomWorkbench: vi.fn(),
  getProductionConfirmation: vi.fn(),
  confirmProductionRoutes: vi.fn(),
  confirmProductionColors: vi.fn()
}))
const processApi = vi.hoisted(() => ({ getProjectProcessRoutes: vi.fn() }))
vi.mock('@/api/modules/bom', () => bomApi)
vi.mock('@/api/modules/process', () => processApi)

import ProductionConfirmationDialog from '../components/ProductionConfirmationDialog.vue'

describe('ProductionConfirmationDialog', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    bomApi.getProjectBoms.mockResolvedValue([
      { productBomId: 31, bomType: 'mbom', status: 'released' },
      { productBomId: 32, bomType: 'mbom', status: 'released' },
      { productBomId: 33, bomType: 'mbom', status: 'draft' }
    ])
    bomApi.getBomWorkbench.mockImplementation((bomId: number) => Promise.resolve({
      productBomId: bomId,
      productId: 7,
      versionNo: bomId === 31 ? 'V1' : bomId === 32 ? 'V2' : 'V3',
      status: bomId === 33 ? 'draft' : 'released',
      routes: [{
        productBomRouteId: bomId + 50,
        processId: 9,
        routeCode: 'DYE',
        routeName: '染色工艺路线',
        colors: ['Negro', 'Azul Rey'],
        colorItems: [
          { codeItemId: 2, codeValue: '02', codeName: 'Negro' },
          { codeItemId: 8, codeValue: '08', codeName: 'Azul Rey' }
        ],
        items: [{ lineNo: 1, itemName: 'TPU', quantity: 1, unit: 'pcs' }],
        costSnapshot: { totalCost: 12.5, currencyCode: 'CNY' }
      }]
    }))
    processApi.getProjectProcessRoutes.mockResolvedValue([{
      processId: 9,
      processName: '染色工艺路线',
      operations: [
        { processId: 91, sequenceNo: 1, processName: '喷涂', status: 'confirmed' },
        { processId: 92, sequenceNo: 2, processName: '包装', status: 'confirmed' }
      ]
    }])
    bomApi.getProductionConfirmation.mockResolvedValue({
      productId: 7,
      selectedOperationCount: 0,
      selectedColorCount: 0,
      createdSkuCount: 0,
      operationProcessIds: [],
      routeSelections: [{
        processId: 9,
        productBomId: 31,
        productBomRouteId: 81,
        routeName: '染色工艺路线',
        bomVersionNo: 'V1',
        operationProcessIds: [91],
        applicableColors: [
          { codeItemId: 2, colorCode: '02', colorName: 'Negro' }
        ]
      }],
      colors: []
    })
    bomApi.confirmProductionRoutes.mockResolvedValue({ selectedOperationCount: 2 })
    bomApi.confirmProductionColors.mockResolvedValue({ selectedColorCount: 2, createdSkuCount: 2 })
  })

  it('confirms one usage BOM and applicable colors per route', async () => {
    const wrapper = mount(ProductionConfirmationDialog, {
      props: { modelValue: true, projectId: 7, mode: 'operations' },
      global: { plugins: [ElementPlus], stubs: { teleport: true, transition: false } }
    })
    await vi.waitFor(() => expect(wrapper.text()).toContain('候选 BOM V1'))

    expect(wrapper.text()).toContain('染色工艺路线')
    expect(wrapper.text()).toContain('使用 BOM')
    expect(wrapper.text()).toContain('投产工序')
    expect(wrapper.text()).toContain('适用颜色')
    expect(wrapper.text()).toContain('02 · Negro')
    expect(wrapper.text()).toContain('喷涂')
    await wrapper.get('[data-test="confirm-production-operations"]').trigger('click')

    await vi.waitFor(() => expect(bomApi.confirmProductionRoutes).toHaveBeenCalled())
    expect(bomApi.confirmProductionRoutes.mock.calls[0][1]).toMatchObject({
      routes: [{
        processId: 9,
        productBomId: 31,
        productBomRouteId: 81,
        operationProcessIds: [91],
        applicableColors: [
          { codeItemId: 2, colorCode: '02', colorName: 'Negro' }
        ]
      }]
    })
  })

  it('falls back to route colors when confirmed colors are empty', async () => {
    bomApi.getProductionConfirmation.mockResolvedValue({
      productId: 7,
      selectedOperationCount: 0,
      selectedColorCount: 0,
      createdSkuCount: 0,
      operationProcessIds: [],
      routeSelections: [{
        processId: 9,
        productBomId: 31,
        productBomRouteId: 81,
        routeName: '染色工艺路线',
        bomVersionNo: 'V1',
        operationProcessIds: [91],
        applicableColors: []
      }],
      colors: []
    })
    const wrapper = mount(ProductionConfirmationDialog, {
      props: { modelValue: true, projectId: 7, mode: 'colors' },
      global: { plugins: [ElementPlus], stubs: { teleport: true, transition: false } }
    })
    await vi.waitFor(() => expect(wrapper.text()).toContain('02 · Negro'))

    expect(wrapper.text()).toContain('染色工艺路线')
    expect(wrapper.text()).toContain('CNY 12.5')
  })

  it('excludes draft BOM routes from production confirmation', async () => {
    const wrapper = mount(ProductionConfirmationDialog, {
      props: { modelValue: true, projectId: 7, mode: 'operations', defaultProductBomRouteId: 83 },
      global: { plugins: [ElementPlus], stubs: { teleport: true, transition: false } }
    })
    await vi.waitFor(() => expect(wrapper.text()).toContain('候选 BOM V1'))

    expect(wrapper.text()).not.toContain('候选 BOM V3')
    expect(bomApi.getBomWorkbench).toHaveBeenCalledTimes(2)
    expect(bomApi.getBomWorkbench).toHaveBeenCalledWith(31)
    expect(bomApi.getBomWorkbench).toHaveBeenCalledWith(32)

    await wrapper.get('[data-test="confirm-production-operations"]').trigger('click')

    await vi.waitFor(() => expect(bomApi.confirmProductionRoutes).toHaveBeenCalled())
    expect(bomApi.confirmProductionRoutes.mock.calls[0][1]).toMatchObject({
      routes: [{
        processId: 9,
        productBomId: 31,
        productBomRouteId: 81,
        operationProcessIds: [91],
        applicableColors: [
          { codeItemId: 2, colorCode: '02', colorName: 'Negro' }
        ]
      }]
    })
  })

  it('confirms multiple BOMs for the same process route', async () => {
    bomApi.getProductionConfirmation.mockResolvedValue({
      productId: 7,
      selectedOperationCount: 4,
      selectedColorCount: 2,
      createdSkuCount: 0,
      operationProcessIds: [91, 92],
      routeSelections: [
        {
          processId: 9,
          productBomId: 31,
          productBomRouteId: 81,
          routeName: '染色工艺路线',
          bomVersionNo: 'V1',
          operationProcessIds: [91, 92],
          applicableColors: [{ codeItemId: 2, colorCode: '02', colorName: 'Negro' }]
        },
        {
          processId: 9,
          productBomId: 32,
          productBomRouteId: 82,
          routeName: '染色工艺路线',
          bomVersionNo: 'V2',
          operationProcessIds: [91, 92],
          applicableColors: [{ codeItemId: 8, colorCode: '08', colorName: 'Azul Rey' }]
        }
      ],
      colors: []
    })
    const wrapper = mount(ProductionConfirmationDialog, {
      props: { modelValue: true, projectId: 7, mode: 'operations' },
      global: { plugins: [ElementPlus], stubs: { teleport: true, transition: false } }
    })
    await vi.waitFor(() => expect(wrapper.text()).toContain('候选 BOM V2'))

    await wrapper.get('[data-test="confirm-production-operations"]').trigger('click')

    await vi.waitFor(() => expect(bomApi.confirmProductionRoutes).toHaveBeenCalled())
    const routes = bomApi.confirmProductionRoutes.mock.calls[0][1].routes
    expect(routes).toHaveLength(2)
    expect(routes).toEqual(expect.arrayContaining([
      expect.objectContaining({ processId: 9, productBomId: 31, productBomRouteId: 81 }),
      expect.objectContaining({ processId: 9, productBomId: 32, productBomRouteId: 82 })
    ]))
    expect(routes.find((route: { productBomRouteId: number }) => route.productBomRouteId === 81).applicableColors)
      .toEqual([{ codeItemId: 2, colorCode: '02', colorName: 'Negro' }])
    expect(routes.find((route: { productBomRouteId: number }) => route.productBomRouteId === 82).applicableColors)
      .toEqual([{ codeItemId: 8, colorCode: '08', colorName: 'Azul Rey' }])
  })


  it('defaults colors only from confirmed formal route selections', async () => {
    const wrapper = mount(ProductionConfirmationDialog, {
      props: { modelValue: true, projectId: 7, mode: 'colors' },
      global: { plugins: [ElementPlus], stubs: { teleport: true, transition: false } }
    })
    await vi.waitFor(() => expect(wrapper.text()).toContain('02 · Negro'))

    expect(wrapper.text()).not.toContain('08 · Azul Rey')
    expect(wrapper.text()).toContain('已选择 1 个颜色')
    await wrapper.get('[data-test="confirm-production-colors"]').trigger('click')

    await vi.waitFor(() => expect(bomApi.confirmProductionColors).toHaveBeenCalled())
    expect(bomApi.confirmProductionColors.mock.calls[0][1].colors).toHaveLength(1)
    expect(bomApi.confirmProductionColors.mock.calls[0][1].colors[0]).toMatchObject({
      codeItemId: 2,
      colorCode: '02',
      colorName: 'Negro',
      productBomId: 31,
      productBomRouteId: 81
    })
  })
})
