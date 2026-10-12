import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import ElementPlus, { ElMessageBox } from 'element-plus'
import { createPinia, setActivePinia } from 'pinia'

const api = vi.hoisted(() => ({
  getProjectBoms: vi.fn(),
  getBomWorkbench: vi.fn(),
  createProjectBom: vi.fn(),
  saveBomRoutes: vi.fn(),
  recalculateBomCosts: vi.fn(),
  submitBomReview: vi.fn(),
  confirmCurrentBomVersion: vi.fn(),
  cancelCurrentBomConfirmation: vi.fn(),
  copyBomVersion: vi.fn(),
  confirmTestBom: vi.fn()
}))

const processApi = vi.hoisted(() => ({
  getProjectProcessRoutes: vi.fn()
}))

vi.mock('@/api/modules/bom', () => api)
vi.mock('@/api/modules/process', () => processApi)

import ProjectBomPanel from '../components/ProjectBomPanel.vue'
import { useUserStore } from '@/stores/user'

describe('ProjectBomPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    setActivePinia(createPinia());useUserStore().permissions=['*']
    document.body.innerHTML = ''
    processApi.getProjectProcessRoutes.mockResolvedValue([
      { processId: 9, processCode: 'ROUTE-DYE', processName: '染色工艺路线', operations: [] }
    ])
    api.createProjectBom.mockResolvedValue({
      productBomId: 32,
      productId: 7,
      bomName: '候选 BOM V2',
      bomType: 'mbom',
      versionNo: 'V2',
      status: 'draft',
      processId: 9
    })
    api.confirmCurrentBomVersion.mockResolvedValue({})
    api.cancelCurrentBomConfirmation.mockResolvedValue({})
    api.getProjectBoms.mockResolvedValue([{
      productBomId: 31,
      productId: 7,
      bomCode: 'BOM-31',
      bomName: '候选 BOM',
      bomType: 'mbom',
      bomScope: 'candidate',
      versionNo: 'V1',
      status: 'draft',
      processId: 9,
      routeName: '染色工艺路线',
      candidateStatus: 'draft',
      currentFormal: true,
      materialCount: 2,
      totalCost: 12.5,
      items: []
    }])
    api.getBomWorkbench.mockResolvedValue({
      productBomId: 31,
      productId: 7,
      bomCode: 'BOM-31',
      bomName: '候选 BOM',
      bomScope: 'candidate',
      versionNo: 'V1',
      status: 'draft',
      testItems: [],
      routes: [{
        productBomRouteId: 81,
        processId: 9,
        routeCode: 'DYE',
        routeName: '染色工艺路线',
        status: 'active',
        colors: ['黑色', '蓝色'],
        items: [
          {
            lineNo: 1,
            itemCode: 'MAT-404',
            itemName: '人工录入辅料',
            quantity: 1,
            unit: 'PCS',
            materialSource: 'manual',
            unmatchedFlag: 1,
            supplierName: '',
            unitCost: null,
            lineCost: null
          }
        ]
      }]
    })
  })

  it('shows candidate BOMs with route and current formal status', async () => {
    const wrapper = mount(ProjectBomPanel, {
      props: { projectId: 7 },
      global: { plugins: [ElementPlus], stubs: { transition: false } }
    })
    await vi.waitFor(() => expect(api.getBomWorkbench).toHaveBeenCalledWith(31))

    expect(wrapper.text()).toContain('新建 BOM')
    expect(wrapper.text()).toContain('候选 BOM')
    expect(wrapper.text()).toContain('染色工艺路线')
    expect(wrapper.text()).toContain('当前正式')
    expect(wrapper.text()).toContain('导入 XLSX')
    expect(wrapper.text()).toContain('人工物料 1')
    expect(wrapper.text()).toContain('供应商缺失 1')
    expect(wrapper.text()).toContain('成本缺失 1')
    expect(wrapper.text()).toContain('提交审核')
    expect(wrapper.text()).not.toContain('冻结')
    expect(wrapper.text()).not.toContain('发布当前 BOM 版本')
    expect(wrapper.text()).toContain('取消确认')
    expect(wrapper.find('[data-test="bom-create"]').exists()).toBe(true)
    useUserStore().permissions = ['bom:write']
    await flushPromises()
    expect(wrapper.find('[data-test="bom-refresh-cost"]').exists()).toBe(false)
    expect(wrapper.find('.cost-metric-grid').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('成本缺失 1')
    expect(wrapper.text()).not.toContain('试算成本')
  })

  it('opens candidate BOM creation with required process route selection', async () => {
    const wrapper = mount(ProjectBomPanel, {
      props: { projectId: 7 },
      global: { plugins: [ElementPlus], stubs: { transition: false } }
    })
    await vi.waitFor(() => expect(processApi.getProjectProcessRoutes).toHaveBeenCalledWith(7))

    await wrapper.get('[data-test="bom-create"]').trigger('click')
    await vi.waitFor(() => expect(`${wrapper.text()}${document.body.textContent}`).toContain('关联工艺路线'))

    expect(document.body.textContent).toContain('染色工艺路线')
    expect(wrapper.find('[data-test="bom-create-submit"]').exists()).toBe(true)
  })

  it('explicitly publishes and confirms a reviewed BOM, never an unreviewed draft', async () => {
    vi.spyOn(ElMessageBox,'confirm').mockResolvedValue('confirm' as never)
    api.getProjectBoms.mockResolvedValue([{
      productBomId: 31,
      productId: 7,
      bomCode: 'BOM-31',
      bomName: '候选 BOM',
      bomType: 'mbom',
      bomScope: 'candidate',
      versionNo: 'V1',
      status: 'reviewing',
      processId: 9,
      routeName: '染色工艺路线',
      candidateStatus: 'reviewing',
      currentFormal: false,
      materialCount: 2,
      totalCost: 12.5,
      items: []
    }])
    const wrapper = mount(ProjectBomPanel, {
      props: { projectId: 7 },
      global: { plugins: [ElementPlus], stubs: { transition: false } }
    })
    await vi.waitFor(() => expect(api.getBomWorkbench).toHaveBeenCalledWith(31))

    expect(wrapper.text()).toContain('发布并确认当前 BOM')
    await wrapper.get('[data-test="bom-confirm-current"]').trigger('click')

    await vi.waitFor(() => expect(api.confirmCurrentBomVersion).toHaveBeenCalledWith(31))
  })

  it('released formal versions are read-only and must copy a new version instead of cancelling into edits', async () => {
    vi.spyOn(ElMessageBox, 'confirm').mockResolvedValue({ action: 'confirm' } as never)
    api.getProjectBoms.mockResolvedValue([{
      productBomId: 31,
      productId: 7,
      bomCode: 'BOM-31',
      bomName: '候选 BOM',
      bomType: 'mbom',
      bomScope: 'formal',
      versionNo: 'V1',
      status: 'released',
      processId: 9,
      routeName: '染色工艺路线',
      candidateStatus: 'released',
      currentFormal: true,
      materialCount: 2,
      totalCost: 12.5,
      items: []
    }])
    const wrapper = mount(ProjectBomPanel, {
      props: { projectId: 7 },
      global: { plugins: [ElementPlus], stubs: { transition: false } }
    })
    await vi.waitFor(() => expect(api.getBomWorkbench).toHaveBeenCalledWith(31))

    expect(wrapper.find('[data-test="bom-cancel-confirmation"]').exists()).toBe(false)
    expect(wrapper.get('[data-test="bom-edit"]').attributes('disabled')).toBeDefined()
    expect(wrapper.get('[data-test="bom-item-add"]').attributes('disabled')).toBeDefined()
    expect(wrapper.get('[data-test="bom-submit-review"]').attributes('disabled')).toBeDefined()
    expect(wrapper.get('[data-test="bom-copy-version"]').attributes('disabled')).toBeUndefined()
    expect(api.cancelCurrentBomConfirmation).not.toHaveBeenCalled()
  })
  it('submitting review changes only review state and does not publish or confirm',async()=>{
    api.submitBomReview.mockResolvedValue({status:'reviewing'});const wrapper=mount(ProjectBomPanel,{props:{projectId:7},global:{plugins:[ElementPlus]}});await vi.waitFor(()=>expect(api.getBomWorkbench).toHaveBeenCalledWith(31));await wrapper.get('[data-test="bom-submit-review"]').trigger('click');await vi.waitFor(()=>expect(api.submitBomReview).toHaveBeenCalledWith(31));expect(api.confirmCurrentBomVersion).not.toHaveBeenCalled();expect(wrapper.text()).toContain('提交审核不等于正式发布')
  })
  it('frozen candidates are immutable but remain eligible for explicit publication',async()=>{
    const old=await api.getProjectBoms();api.getProjectBoms.mockResolvedValue(old.map((b:Record<string,unknown>)=>({...b,status:'frozen',candidateStatus:'frozen',currentFormal:false})));const wrapper=mount(ProjectBomPanel,{props:{projectId:7},global:{plugins:[ElementPlus]}});await vi.waitFor(()=>expect(api.getBomWorkbench).toHaveBeenCalledWith(31));expect(wrapper.get('[data-test="bom-edit"]').attributes('disabled')).toBeDefined();expect(wrapper.get('[data-test="bom-confirm-current"]').attributes('disabled')).toBeUndefined()
  })
})
