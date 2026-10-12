import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useUserStore } from '@/stores/user'

const codeApi = vi.hoisted(() => ({ getEnabledColorCodes: vi.fn() }))
const inventoryApi = vi.hoisted(() => ({ lookupMaterialByCode: vi.fn() }))
const supplierApi = vi.hoisted(() => ({ getSupplierCenterSnapshot: vi.fn() }))
vi.mock('@/api/modules/code', () => codeApi)
vi.mock('@/api/modules/inventory', () => inventoryApi)
vi.mock('@/api/modules/supplier', () => supplierApi)

import BomRouteEditor from '../components/BomRouteEditor.vue'
import { toBomRoutesSavePayload } from '@/api/modules/bom'
import type { BomRoute } from '@/types/bom'

const elementStubs = {
  teleport: true,
  ElSelect: {
    props: ['modelValue'],
    emits: ['update:modelValue', 'change'],
    template: `
      <select
        :data-test="$attrs['data-test']"
        :value="Array.isArray(modelValue) ? modelValue[0] : modelValue"
        @change="$emit('change', Number($event.target.value)); $emit('update:modelValue', Number($event.target.value))"
      >
        <slot />
      </select>
    `
  },
  ElOption: {
    props: ['label', 'value'],
    template: '<option :value="value">{{ label }}</option>'
  }
}

describe('BomRouteEditor', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    setActivePinia(createPinia())
    useUserStore().permissions = ['*']
    supplierApi.getSupplierCenterSnapshot.mockResolvedValue({ metrics: [], suppliers: [], risks: [] })
  })

  it('renders a single existing route selector, color select and automatic line numbers', async () => {
    codeApi.getEnabledColorCodes.mockResolvedValue([
      { codeItemId: 1, codeType: 'color', codeValue: '01', codeName: 'Morado', status: 'enabled', sortOrder: 1 },
      { codeItemId: 2, codeType: 'color', codeValue: '02', codeName: 'Negro', status: 'enabled', sortOrder: 2 }
    ])
    const wrapper = mount(BomRouteEditor, {
      global: { plugins: [ElementPlus], stubs: elementStubs },
      props: {
        modelValue: true,
        processRoutes: [{
          processId: 58,
          productId: 9,
          processCode: 'RD-M2-0002-ROL',
          processName: '表面处理喷涂路线',
          processType: 'routing',
          versionNo: 'A',
          status: 'draft',
          operations: []
        }],
        routes: [{
          processId: 58,
          routeCode: 'RD-M2-0002-ROL',
          routeName: '表面处理喷涂路线',
          colors: ['Morado'],
          colorItems: [{ codeItemId: 1, codeValue: '01', codeName: 'Morado' }],
          items: []
        }]
      }
    })

    await flushPromises()

    expect(wrapper.find('[data-test="route-add"]').exists()).toBe(false)
    expect(wrapper.find('[data-test="route-delete"]').exists()).toBe(false)
    expect(wrapper.find('[data-test="route-process-id"]').exists()).toBe(false)
    expect(wrapper.find('[data-test="route-color-select"]').exists()).toBe(true)

    await wrapper.get('[data-test="route-item-add"]').trigger('click')
    expect(wrapper.find('[data-test="route-item-line-no-input"]').exists()).toBe(false)
    expect(wrapper.find('[data-test="route-item-line-no"]').text()).toBe('1')
  })

  it('loads active Inventory suppliers into the route item supplier selector', async () => {
    codeApi.getEnabledColorCodes.mockResolvedValue([{ codeItemId: 8, codeType: 'color', codeValue: '08', codeName: 'Azul Rey', status: 'enabled', sortOrder: 8 }])
    supplierApi.getSupplierCenterSnapshot.mockResolvedValue({
      metrics: [],
      suppliers: [
        { supplierId: 1, supplierCode: 'SUP-001', supplierName: '新增供应商A', shortName: '', contactPerson: '', contactPhone: '', contactEmail: '', supplyCategories: ['原材料'], region: '', status: 'active', updatedAt: '', cooperationLevel: '', paymentTerm: '', deliveryRisk: '', supplyRecords: [], relatedProjects: [], qualificationFiles: [] },
        { supplierId: 2, supplierCode: 'SUP-002', supplierName: '停用供应商B', shortName: '', contactPerson: '', contactPhone: '', contactEmail: '', supplyCategories: ['原材料'], region: '', status: 'inactive', updatedAt: '', cooperationLevel: '', paymentTerm: '', deliveryRisk: '', supplyRecords: [], relatedProjects: [], qualificationFiles: [] }
      ],
      risks: []
    })

    const wrapper = mount(BomRouteEditor, {
      global: { plugins: [ElementPlus], stubs: elementStubs },
      props: {
        modelValue: true,
        routes: [{ processId: 9, routeCode: 'DYE', routeName: '染色路线', colors: ['Azul Rey'], colorItems: [{ codeItemId: 8, codeValue: '08', codeName: 'Azul Rey' }], items: [] }]
      }
    })

    await flushPromises()
    await wrapper.get('[data-test="route-item-add"]').trigger('click')

    const supplierSelect = wrapper.get('[data-test="route-item-supplier"]')
    expect(supplierApi.getSupplierCenterSnapshot).toHaveBeenCalled()
    expect(supplierSelect.text()).toContain('新增供应商A')
    expect(supplierSelect.text()).not.toContain('停用供应商B')
  })

  it('adds and saves route BOM material details', async () => {
    codeApi.getEnabledColorCodes.mockResolvedValue([{ codeItemId: 8, codeType: 'color', codeValue: '08', codeName: 'Azul Rey', status: 'enabled', sortOrder: 8 }])
    inventoryApi.lookupMaterialByCode.mockResolvedValue({
      matched: true,
      inventoryId: 88,
      inventoryCode: 'MAT-001',
      inventoryName: '蓝色色母',
      specification: '25kg / 包',
      unit: 'kg',
      supplierName: '东莞塑胶 A',
      unitCost: 3.5,
      currencyCode: 'CNY'
    })
    const wrapper = mount(BomRouteEditor, {
      global: { plugins: [ElementPlus], stubs: elementStubs },
      props: {
        modelValue: true,
        routes: [{ processId: 9, routeCode: 'DYE', routeName: '染色路线', colors: ['Azul Rey'], colorItems: [{ codeItemId: 8, codeValue: '08', codeName: 'Azul Rey' }], items: [] }]
      }
    })

    await flushPromises()
    expect(codeApi.getEnabledColorCodes).toHaveBeenCalled()
    expect(wrapper.text()).toContain('08 - Azul Rey')
    await wrapper.get('[data-test="route-item-add"]').trigger('click')
    await wrapper.get('[data-test="route-item-code"]').setValue('MAT-001')
    await wrapper.get('[data-test="route-item-code"]').trigger('blur')
    await flushPromises()
    await wrapper.get('[data-test="route-item-quantity"] input').setValue('2')
    await wrapper.get('[data-test="route-item-loss-rate"] input').setValue('0.05')
    await wrapper.get('[data-test="route-editor-save"]').trigger('click')

    const saved = wrapper.emitted('save')?.[0]?.[0] as Array<{ colorItems: Array<Record<string, unknown>>; items: Array<Record<string, unknown>> }>
    expect(saved[0].colorItems[0]).toMatchObject({ codeItemId: 8, codeValue: '08', codeName: 'Azul Rey' })
    expect(saved[0].items[0]).toMatchObject({
      inventoryId: 88,
      itemCode: 'MAT-001',
      itemName: '蓝色色母',
      specification: '25kg / 包',
      quantity: 2,
      unit: 'kg',
      supplierName: '东莞塑胶 A',
      lossRate: 0.05,
      unitCost: 3.5,
      lineCost: 7,
      materialSource: 'inventory',
      unmatchedFlag: 0
    })
  })

  it('preserves route identity and variant lineage but removes response-only identifiers', async () => {
    codeApi.getEnabledColorCodes.mockResolvedValue([{ codeItemId: 8, codeType: 'color', codeValue: '08', codeName: 'Azul Rey', status: 'enabled', sortOrder: 8 }])
    const wrapper = mount(BomRouteEditor, {
      global: { plugins: [ElementPlus], stubs: elementStubs },
      props: {
        modelValue: true,
        routes: [{
          productBomRouteId: 12,
          sourceProductBomRouteId: 10,
          sharedBomGroupCode: 'GROUP-9',
          routeVariantNo: 'ALT-2',
          variantName: 'Alternative material',
          productBomId: 31,
          processId: 9,
          routeCode: 'DYE',
          routeName: 'Dye route',
          status: 'active',
          colors: ['Azul Rey'],
          colorItems: [{ codeItemId: 8, codeValue: '08', codeName: 'Azul Rey' }],
          items: [{
            productBomItemId: 99,
            inventoryId: 88,
            itemCode: 'MAT-001',
            itemName: 'PC shell',
            lineNo: 1,
            quantity: 1,
            unit: 'PCS',
            supplierName: 'Supplier A',
            unitCost: 2.5,
            lineCost: 2.5
          }]
        }]
      }
    })

    await flushPromises()
    await wrapper.get('[data-test="route-editor-save"]').trigger('click')

    const drafts = wrapper.emitted('save')?.[0]?.[0] as BomRoute[]
    expect(drafts[0]).toMatchObject({ productBomRouteId: 12, sourceProductBomRouteId: 10, routeVariantNo: 'ALT-2' })
    const saved = toBomRoutesSavePayload(drafts)
    expect(saved[0]).not.toHaveProperty('productBomId')
    expect(saved[0]).not.toHaveProperty('status')
    expect(saved[0].items[0]).not.toHaveProperty('productBomItemId')
    expect(saved[0]).toMatchObject({
      productBomRouteId: 12,
      sourceProductBomRouteId: 10,
      sharedBomGroupCode: 'GROUP-9',
      routeVariantNo: 'ALT-2',
      variantName: 'Alternative material',
      processId: 9,
      routeCode: 'DYE',
      routeName: 'Dye route',
      colors: ['Azul Rey']
    })
  })

  it('keeps unmatched material as manual row and saves supplier and line cost', async () => {
    codeApi.getEnabledColorCodes.mockResolvedValue([{ codeItemId: 8, codeType: 'color', codeValue: '08', codeName: 'Azul Rey', status: 'enabled', sortOrder: 8 }])
    inventoryApi.lookupMaterialByCode.mockResolvedValue({
      matched: false,
      inventoryCode: 'MAT-404',
      message: '物料编码未匹配到物料库，可先人工录入候选 BOM，正式发布前请确认物料资料。'
    })
    const wrapper = mount(BomRouteEditor, {
      global: { plugins: [ElementPlus], stubs: elementStubs },
      props: {
        modelValue: true,
        routes: [{ processId: 9, routeCode: 'DYE', routeName: '染色路线', colors: ['Azul Rey'], colorItems: [{ codeItemId: 8, codeValue: '08', codeName: 'Azul Rey' }], items: [] }]
      }
    })

    await flushPromises()
    await wrapper.get('[data-test="route-item-add"]').trigger('click')
    await wrapper.get('[data-test="route-item-code"]').setValue('MAT-404')
    await wrapper.get('[data-test="route-item-code"]').trigger('blur')
    await flushPromises()
    await wrapper.get('[data-test="route-item-name"]').setValue('人工录入辅料')
    await wrapper.get('[data-test="route-item-unit"]').setValue('PCS')
    await wrapper.get('[data-test="route-item-unit-cost"] input').setValue('2.5')
    await wrapper.get('[data-test="route-editor-save"]').trigger('click')

    expect(wrapper.text()).toContain('未匹配')
    const saved = wrapper.emitted('save')?.[0]?.[0] as Array<{ items: Array<Record<string, unknown>> }>
    expect(saved[0].items[0]).toMatchObject({
      itemCode: 'MAT-404',
      itemName: '人工录入辅料',
      unitCost: 2.5,
      lineCost: 2.5,
      materialSource: 'manual',
      unmatchedFlag: 1
    })
  })

  it('lets engineering change quantities without exposing or zeroing protected money', async () => {
    const user = useUserStore()
    user.permissions = ['bom:write', 'finance:read']
    codeApi.getEnabledColorCodes.mockResolvedValue([{ codeItemId: 8, codeType: 'color', codeValue: '08', codeName: 'Blue', status: 'enabled', sortOrder: 8 }])
    const wrapper = mount(BomRouteEditor, {
      global: { plugins: [ElementPlus], stubs: elementStubs },
      props: { modelValue: true, moneyReadable: true, moneyEditable: false, routes: [{
        productBomRouteId: 12, sourceProductBomRouteId: 10, processId: 9, routeCode: 'DYE', routeName: 'Dye',
        colors: ['Blue'], colorItems: [{ codeItemId: 8, codeValue: '08', codeName: 'Blue' }], processCost: 7,
        items: [{ lineNo: 1, inventoryId: 88, itemName: 'PC shell', quantity: 1, unit: 'PCS', unitCost: 2.5, lineCost: 2.5, currencyCode: 'CNY' }]
      }] }
    })
    await flushPromises()
    expect(wrapper.get('[data-test="route-item-unit-cost"] input').attributes('disabled')).toBeDefined()
    expect(wrapper.get('[data-test="route-item-line-cost"] input').attributes('disabled')).toBeDefined()
    await wrapper.get('[data-test="route-item-quantity"] input').setValue('2')
    await wrapper.get('[data-test="route-item-add"]').trigger('click')
    await wrapper.findAll('[data-test="route-item-name"]')[1].setValue('New component')
    await wrapper.get('[data-test="route-editor-save"]').trigger('click')
    const drafts = wrapper.emitted('save')?.[0]?.[0] as BomRoute[]
    expect(drafts[0].items[0]).toMatchObject({ quantity: 2, unitCost: 2.5, lineCost: 2.5 })
    expect(drafts[0].items[1].unitCost).toBeUndefined()
    expect(drafts[0].items[1].lineCost).toBeUndefined()
    const saved = toBomRoutesSavePayload(drafts, { moneyEditable: false })
    expect(saved[0]).toMatchObject({ productBomRouteId: 12, sourceProductBomRouteId: 10 })
    expect(saved[0]).not.toHaveProperty('processCost')
    saved[0].items.forEach(item => {
      expect(item).not.toHaveProperty('unitCost')
      expect(item).not.toHaveProperty('lineCost')
      expect(item).not.toHaveProperty('currencyCode')
    })
    expect(saved[0].items.map(item => item.lineNo)).toEqual([1, 2])
    user.permissions = ['bom:write']
    await flushPromises()
    expect(wrapper.find('[data-test="route-item-unit-cost"]').exists()).toBe(false)
    expect(wrapper.find('[data-test="route-item-line-cost"]').exists()).toBe(false)
    expect(wrapper.text()).toContain('当前账号无内部金额查看与编辑权限')
    wrapper.unmount()
  })
})
