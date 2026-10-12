import ElementPlus, { ElMessage, ElMessageBox } from 'element-plus'
import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useUserStore } from '@/stores/user'

const bomApi = vi.hoisted(() => ({
  getProjectBoms: vi.fn(),
  getBomWorkbench: vi.fn(),
  getBomDetail: vi.fn(),
  createProjectBom: vi.fn(),
  updateBom: vi.fn(),
  addBomItem: vi.fn(),
  updateBomItem: vi.fn(),
  deleteBomItem: vi.fn(),
  freezeBom: vi.fn(),
  confirmTestBom: vi.fn(),
  copyBomVersion: vi.fn(),
  publishBom: vi.fn(),
  recalculateBomCosts: vi.fn(),
  saveBomRoutes: vi.fn(),
  submitBomReview: vi.fn()
}))

const codeApi = vi.hoisted(() => ({
  getEnabledColorCodes: vi.fn()
}))

const processApi = vi.hoisted(() => ({
  getProcessRouteTemplates: vi.fn(),
  getProcessOperationMasters: vi.fn(),
  getProjectProcessRoutes: vi.fn(),
  getProcessRouteDetail: vi.fn(),
  createProcessRoute: vi.fn(),
  updateProcessRoute: vi.fn(),
  freezeProcessRoute: vi.fn()
}))

const attachmentApi = vi.hoisted(() => ({
  getTimelineAttachments: vi.fn(),
  getFileCenterAttachments: vi.fn(),
  uploadTimelineAttachment: vi.fn(),
  uploadProjectAttachment: vi.fn(),
  downloadAttachment: vi.fn(),
  deleteAttachment: vi.fn()
}))

const foundationApi = vi.hoisted(() => ({
  getProductPresentation: vi.fn()
}))

const projectApi = vi.hoisted(() => ({
  getProjects: vi.fn(),
  getProjectDetail: vi.fn(),
  getProjectTimeline: vi.fn(),
  confirmTimelineNode: vi.fn(),
  advanceTimelineNode: vi.fn(),
  returnTimelineNode: vi.fn(),
  saveMoldTransferExpress: vi.fn()
}))

const routeState = vi.hoisted(() => ({
  query: {} as Record<string, unknown>
}))

const routerPush = vi.hoisted(() => vi.fn())

vi.mock('@/api/modules/bom', () => bomApi)
vi.mock('@/api/modules/code', () => codeApi)
vi.mock('@/api/modules/process', () => processApi)
vi.mock('@/api/modules/attachment', () => attachmentApi)
vi.mock('@/api/modules/foundation', () => foundationApi)
vi.mock('@/api/modules/project', () => projectApi)
vi.mock('vue-router', () => ({
  useRoute: () => routeState,
  useRouter: () => ({ push: routerPush })
}))

import ProjectCenterView from '../ProjectCenterView.vue'
import ProjectBomPanel from '../components/ProjectBomPanel.vue'
import ProjectProcessRoutePanel from '../components/ProjectProcessRoutePanel.vue'
import TimelineAttachmentPanel from '../components/TimelineAttachmentPanel.vue'

const mountOptions = {
  global: {
    plugins: [ElementPlus]
  }
}

function createProductSummary(overrides: Record<string, unknown> = {}) {
  return {
    productId: 9,
    productCode: 'PRD-9',
    productName: '测试产品',
    productType: 'product_line',
    seriesName: 'S',
    model: 'M',
    color: '黑色',
    material: 'TPU',
    ownerUserName: '工程',
    versionNo: 'A',
    status: 'archived',
    currentStage: '设计确认',
    currentStepNo: 2,
    customerName: '内部立项',
    frozenFlag: false,
    releasedAt: '2026-07-01',
    completionRate: 1,
    estimatedCost: 0,
    estimatedCostCurrency: 'CNY',
    activeBomVersion: 'A',
    testItemCount: 0,
    ...overrides
  }
}

function createPresentation(productId = 9, nodeKey = 'PRODUCT_LINE_DESIGN_CONFIRM') {
  return {
    productId,
    title: '测试产品',
    flowLabel: '新产品线',
    currentNode: '设计确认',
    nextNode: '推进下一节点',
    summary: '测试摘要',
    costPanel: { showEstimated: false, actualTotal: 0, actualLines: [] },
    timeline: [{
      nodeKey,
      nodeName: '设计确认',
      status: 'current',
      ownerRole: '工程',
      summary: '当前节点'
    }],
    bomCompareRows: [],
    bomItems: [],
    bomItemsByVersion: {},
    toolingSummary: { totalCount: 0, availableCount: 0, trialCount: 0, toolingNames: [] },
    materialCategories: [],
    suppliers: [],
    documents: [],
    qualityRecords: [],
    processRoutes: []
  }
}

function createTimeline(projectId = 9, nodeKey = 'PRODUCT_LINE_DESIGN_CONFIRM') {
  return {
    projectId,
    productId: projectId,
    productType: 'product_line',
    currentNode: '设计确认',
    currentStepNo: 2,
    currentConfirmed: false,
    nodes: [{
      nodeKey,
      nodeName: '设计确认',
      phaseName: '设计验证阶段',
      stepNo: 2,
      status: 'current',
      nodeStatus: 'current',
      summary: '当前节点',
      ownerRole: '工程',
      documentCount: 0,
      confirmed: false
    }]
  }
}

describe('project M4 panels', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    setActivePinia(createPinia())
    useUserStore().permissions = ['*']
    codeApi.getEnabledColorCodes.mockResolvedValue([])
    document.body.innerHTML = ''
    routeState.query = {}
    bomApi.getProjectBoms.mockResolvedValue([])
    bomApi.getBomWorkbench.mockResolvedValue(null)
    processApi.getProcessRouteTemplates.mockResolvedValue([])
    processApi.getProcessOperationMasters.mockResolvedValue([])
    processApi.getProjectProcessRoutes.mockResolvedValue([])
    attachmentApi.getTimelineAttachments.mockResolvedValue([])
    foundationApi.getProductPresentation.mockResolvedValue(createPresentation())
    projectApi.getProjects.mockResolvedValue([])
    projectApi.getProjectDetail.mockRejectedValue(new Error('detail unavailable in default test fixture'))
    projectApi.getProjectTimeline.mockResolvedValue(createTimeline())
    projectApi.saveMoldTransferExpress.mockResolvedValue({
      moldTransferExpressId: 1,
      projectId: 9,
      timelineNodeKey: 'PRODUCT_LINE_MOLD_TRANSFER',
      trackingNo: 'YW-TEST-001',
      shippedAt: '2026-08-10T10:00:00',
      status: 'active'
    })
    attachmentApi.getFileCenterAttachments.mockResolvedValue({ content: [], page: 1, size: 100, totalElements: 0, totalPages: 0 })
    vi.spyOn(ElMessageBox, 'prompt').mockImplementation(() => Promise.resolve({ value: '确认备注', action: 'confirm' }) as ReturnType<typeof ElMessageBox.prompt>)
  })

  it('loads project BOMs and distinguishes a successful empty result', async () => {
    const wrapper = mount(ProjectBomPanel, { ...mountOptions, props: { projectId: 7 } })

    await flushPromises()

    expect(bomApi.getProjectBoms).toHaveBeenCalledWith(7)
    expect(wrapper.text()).toContain('当前项目还没有 BOM')
    expect(wrapper.get('[data-test="bom-create"]').attributes('disabled')).toBeUndefined()
  })

  it('keeps a frozen BOM immutable and allows copying a new correction version', async () => {
    bomApi.getProjectBoms.mockResolvedValue([{
      productBomId: 31,
      productId: 7,
      bomCode: 'BOM-31',
      bomName: '冻结 BOM',
      bomType: 'ebom',
      versionNo: 'A',
      status: 'frozen',
      items: []
    }])
    bomApi.getBomWorkbench.mockResolvedValue({
      productBomId: 31,
      productId: 7,
      bomCode: 'BOM-31',
      bomName: '冻结 BOM',
      bomScope: 'formal',
      versionNo: 'A',
      status: 'frozen',
      testItems: [],
      routes: []
    })

    const wrapper = mount(ProjectBomPanel, { ...mountOptions, props: { projectId: 7 } })
    await flushPromises()

    expect(wrapper.text()).toContain('冻结 BOM')
    expect(wrapper.get('[data-test="bom-edit"]').attributes('disabled')).toBeDefined()
    expect(wrapper.get('[data-test="bom-item-add"]').attributes('disabled')).toBeDefined()
    expect(wrapper.get('[data-test="bom-copy-version"]').attributes('disabled')).toBeUndefined()
  })

  it('loads process routes and shows the successful empty state', async () => {
    const wrapper = mount(ProjectProcessRoutePanel, { ...mountOptions, props: { projectId: 7 } })

    await flushPromises()

    expect(processApi.getProjectProcessRoutes).toHaveBeenCalledWith(7)
    expect(wrapper.text()).toContain('当前项目还没有工艺路线')
  })

  it('renders imported confirmed process routes as confirmed instead of draft', async () => {
    processApi.getProjectProcessRoutes.mockResolvedValue([{
      processId: 81,
      productId: 7,
      processCode: 'ROUTE-NFB4020-IMPORT-14',
      processName: 'titanio 骑士2.0 工艺路线',
      processType: 'routing',
      versionNo: 'A',
      status: 'confirmed',
      operations: []
    }])
    const wrapper = mount(ProjectProcessRoutePanel, { ...mountOptions, props: { projectId: 7 } })

    await flushPromises()

    expect(wrapper.text()).toContain('已确认')
    expect(wrapper.text()).not.toContain('草稿')
    expect(wrapper.get('[data-test="process-edit"]').attributes('disabled')).toBeUndefined()
    expect(wrapper.get('[data-test="process-delete"]').attributes('disabled')).toBeUndefined()
    expect(wrapper.find('[data-test="process-create-version"]').exists()).toBe(false)
  })

  it('opens process route creation with template operations and a node check table', async () => {
    processApi.getProcessRouteTemplates.mockResolvedValue([{
      routeTemplateCode: 'ROUTE-STD-INJECTION',
      routeTemplateName: '标准注塑组装路线',
      versionNo: 'V1',
      defaultTemplate: true,
      operations: [{
        operationCode: 'PROC_INJECTION',
        sequenceNo: 10,
        processName: '注塑成型',
        processParamJson: '{"temperature":82}',
        standardTimeMins: 0,
        qualityRequirement: '外观无缩印'
      }]
    }])
    const wrapper = mount(ProjectProcessRoutePanel, {
      ...mountOptions,
      props: { projectId: 7, productCode: 'PRD-7' }
    })
    await flushPromises()

    await wrapper.get('[data-test="process-create"]').trigger('click')
    await flushPromises()

    expect(processApi.getProcessRouteTemplates).toHaveBeenCalledWith({ productCode: 'PRD-7' })
    expect(document.body.textContent).toContain('标准注塑组装路线')
    expect(document.body.textContent).toContain('注塑成型')
    expect(document.body.textContent).toContain('节点配置核对表')
  })

  it('hides model and free color fields when creating a product process route', async () => {
    processApi.getProcessRouteTemplates.mockResolvedValue([{
      routeTemplateCode: 'ROUTE-STD-INJECTION',
      routeTemplateName: '标准注塑组装路线',
      versionNo: 'V1',
      defaultTemplate: true,
      operations: []
    }])
    const wrapper = mount(ProjectProcessRoutePanel, {
      ...mountOptions,
      props: { projectId: 7, productCode: 'PRD-7' }
    })
    await flushPromises()

    await wrapper.get('[data-test="process-create"]').trigger('click')
    await flushPromises()

    expect(document.body.textContent).not.toContain('适用型号')
    expect(document.body.textContent).not.toContain('适用颜色')
  })

  it('submits manual operation name and code without selecting operation master', async () => {
    processApi.getProcessRouteTemplates.mockResolvedValue([])
    processApi.createProcessRoute.mockResolvedValue({
      processId: 100,
      productId: 7,
      processCode: 'PRD-7-CUSTOM-V1',
      processName: '手工路线',
      processType: 'routing',
      versionNo: 'V1',
      status: 'draft',
      operations: []
    })
    const wrapper = mount(ProjectProcessRoutePanel, {
      ...mountOptions,
      props: { projectId: 7, productCode: 'PRD-7', productType: 'product_line', productSpecificCode: 'HD' }
    })
    await flushPromises()

    await wrapper.get('[data-test="process-create"]').trigger('click')
    await flushPromises()

    const routeNameInput = document.body.querySelector('[data-test="process-route-name-input"] input') as HTMLInputElement
    routeNameInput.value = '手工路线'
    routeNameInput.dispatchEvent(new Event('input'))
    const operationNameInput = document.body.querySelector('[data-test="operation-name-input"] input') as HTMLInputElement
    operationNameInput.value = '手工注塑成型'
    operationNameInput.dispatchEvent(new Event('input'))
    const operationCodeInput = document.body.querySelector('[data-test="operation-craft-code-input"] input') as HTMLInputElement
    operationCodeInput.value = '1010'
    operationCodeInput.dispatchEvent(new Event('input'))
    operationCodeInput.dispatchEvent(new Event('change'))
    const businessCodeInput = document.body.querySelector('[data-test="business-operation-code-input"] input') as HTMLInputElement
    businessCodeInput.value = 'NHD1010'
    businessCodeInput.dispatchEvent(new Event('input'))
    businessCodeInput.dispatchEvent(new Event('change'))
    const qualityInput = document.body.querySelector('.operation-row [placeholder="填写该工序的质量要求"]') as HTMLInputElement
    qualityInput.value = '外观无缩水、无明显披锋'
    qualityInput.dispatchEvent(new Event('input'))
    await flushPromises()
    ;(document.body.querySelector('[data-test="process-route-save"]') as HTMLButtonElement).click()
    await flushPromises()

    const payload = processApi.createProcessRoute.mock.calls[0][1]
    expect(payload.operations[0]).toMatchObject({
      operationMasterProcessId: null,
      operationSource: 'manual_snapshot',
      processName: '手工注塑成型',
      operationCraftCode: '1010',
      businessOperationCode: 'NHD1010',
      businessOperationCodeManualFlag: true,
      codeGenerationContext: 'product_line_route'
    })
  })

  it('shows operation detail column titles in the route dialog', async () => {
    processApi.getProcessRouteTemplates.mockResolvedValue([{
      routeTemplateCode: 'ROUTE-STD-INJECTION',
      routeTemplateName: '标准注塑组装路线',
      versionNo: 'V1',
      defaultTemplate: true,
      operations: [{
        operationCode: 'PROC_INJECTION',
        sequenceNo: 10,
        processName: '注塑成型',
        processParamJson: '{"temperature":82}',
        standardTimeMins: 12,
        qualityRequirement: '外观无缩水'
      }]
    }])
    const wrapper = mount(ProjectProcessRoutePanel, {
      ...mountOptions,
      props: { projectId: 7, productCode: 'PRD-7' }
    })
    await flushPromises()

    await wrapper.get('[data-test="process-create"]').trigger('click')
    await flushPromises()

    const header = document.body.querySelector('[data-test="operation-editor-columns"]')
    const editor = document.body.querySelector('[data-test="operation-editor"]')
    expect(editor?.querySelector('[data-test="operation-editor-columns"]')).not.toBeNull()
    expect(editor?.querySelectorAll('.operation-row')).toHaveLength(1)
    expect(header?.textContent).toContain('顺序')
    expect(header?.textContent).toContain('产品工序编码')
    expect(header?.textContent).toContain('基础工序编码')
    expect(header?.textContent).toContain('工序名称')
    expect(header?.textContent).toContain('标准工时')
    expect(header?.textContent).toContain('工艺参数')
    expect(header?.textContent).toContain('质量要求')
    expect(header?.textContent).toContain('操作')
  })

  it('keeps product line business operation code pending until model and color are known', async () => {
    processApi.getProcessRouteTemplates.mockResolvedValue([{
      routeTemplateCode: 'ROUTE-STD-INJECTION',
      routeTemplateName: 'Standard injection route',
      versionNo: 'V1',
      defaultTemplate: true,
      operations: [{
        operationCode: 'PROC_INJECTION',
        operationCraftCode: '1020',
        materialStatusCode: '10',
        sequenceNo: 10,
        processName: 'Injection molding',
        processParamJson: '{}',
        standardTimeMins: 12,
        qualityRequirement: 'No burrs'
      }]
    }])
    const wrapper = mount(ProjectProcessRoutePanel, {
      ...mountOptions,
      props: { projectId: 7, productCode: 'FA' }
    })
    await flushPromises()

    await wrapper.get('[data-test="process-create"]').trigger('click')
    await flushPromises()

    const businessCodeInput = document.body.querySelector('[data-test="business-operation-code-input"] input') as HTMLInputElement
    expect(businessCodeInput?.value).toBe('')
    expect(document.body.textContent).toContain('TPU / 10')
    expect(document.body.textContent).toContain('PC / 20')
    expect(document.body.textContent).toContain('半成品 / 30')
    expect(document.body.textContent).not.toContain('成品 / 40')
  })

  it('does not regenerate a fake product line code when material status changes', async () => {
    processApi.getProcessRouteTemplates.mockResolvedValue([{
      routeTemplateCode: 'ROUTE-STD-INJECTION',
      routeTemplateName: 'Standard injection route',
      versionNo: 'V1',
      defaultTemplate: true,
      operations: [{
        operationCode: 'PROC_INJECTION',
        operationCraftCode: '1020',
        sequenceNo: 10,
        processName: 'Injection molding',
        processParamJson: '{}',
        standardTimeMins: 12,
        qualityRequirement: 'No burrs'
      }]
    }])
    const wrapper = mount(ProjectProcessRoutePanel, {
      ...mountOptions,
      props: { projectId: 7, productCode: 'FA' }
    })
    await flushPromises()

    await wrapper.get('[data-test="process-create"]').trigger('click')
    await flushPromises()

    const businessCodeInput = document.body.querySelector('[data-test="business-operation-code-input"] input') as HTMLInputElement
    expect(businessCodeInput?.value).toBe('')

    const materialSelect = document.body.querySelector('[data-test="material-status-select"] .el-select') as HTMLElement
    materialSelect.click()
    await flushPromises()
    const tpuOption = [...document.body.querySelectorAll('.el-select-dropdown__item')]
      .find((item) => item.textContent?.includes('TPU / 10')) as HTMLElement
    tpuOption.click()
    await flushPromises()

    expect(businessCodeInput.value).toBe('')
  })

  it('submits manual business code and finished product flag without changing material status', async () => {
    processApi.getProcessRouteTemplates.mockResolvedValue([{
      routeTemplateCode: 'ROUTE-STD-INJECTION',
      routeTemplateName: 'Standard injection route',
      versionNo: 'V1',
      defaultTemplate: true,
      operations: [{
        operationCode: 'PROC_INJECTION',
        operationCraftCode: '10',
        materialStatusCode: '20',
        sequenceNo: 10,
        operationMasterProcessId: 900,
        processName: 'Injection molding',
        processParamJson: '{}',
        standardTimeMins: 12,
        qualityRequirement: 'No burrs'
      }]
    }])
    processApi.createProcessRoute.mockResolvedValue({
      processId: 100,
      productId: 7,
      processCode: 'BA-ROUTE-STD-INJECTION-V1',
      processName: 'Standard injection route',
      processType: 'routing',
      versionNo: 'V1',
      status: 'draft',
      operations: []
    })
    const wrapper = mount(ProjectProcessRoutePanel, {
      ...mountOptions,
      props: {
        projectId: 7,
        productCode: 'BA',
        productType: 'sku',
        productSpecificCode: 'BA',
        phoneModelCode: '1291',
        colorCode: '01'
      }
    })
    await flushPromises()

    await wrapper.get('[data-test="process-create"]').trigger('click')
    await flushPromises()
    const businessCodeInput = document.body.querySelector('[data-test="business-operation-code-input"] input') as HTMLInputElement
    businessCodeInput.value = 'NBA10A1'
    businessCodeInput.dispatchEvent(new Event('input'))
    businessCodeInput.dispatchEvent(new Event('change'))
    const finishedCheckbox = document.body.querySelector('[data-test="finished-product-checkbox"] input') as HTMLInputElement
    finishedCheckbox.click()
    await flushPromises()
    ;(document.body.querySelector('[data-test="process-route-save"]') as HTMLButtonElement).click()
    await flushPromises()

    const payload = processApi.createProcessRoute.mock.calls[0][1]
    expect(payload.operations[0]).toMatchObject({
      operationCraftCode: '1010',
      materialStatusCode: '20',
      finishedProductFlag: true,
      businessOperationCode: 'NBA10A1129101',
      businessOperationCodeManualFlag: true
    })
  })

  it('allows repeated system operation codes when product operation codes differ', async () => {
    processApi.getProcessRouteTemplates.mockResolvedValue([{
      routeTemplateCode: 'ROUTE-STD-INJECTION',
      routeTemplateName: 'Standard injection route',
      versionNo: 'V1',
      defaultTemplate: true,
      operations: [
        {
          operationCode: 'PROC_INJECTION',
          operationCraftCode: '20',
          materialStatusCode: '10',
          sequenceNo: 10,
          operationMasterProcessId: 900,
          processName: 'Injection molding',
          processParamJson: '{}',
          standardTimeMins: 12,
          qualityRequirement: 'No burrs'
        },
        {
          operationCode: 'PROC_INJECTION',
          operationCraftCode: '10',
          materialStatusCode: '20',
          sequenceNo: 20,
          operationMasterProcessId: 900,
          processName: 'Injection molding again',
          processParamJson: '{}',
          standardTimeMins: 12,
          qualityRequirement: 'No burrs'
        }
      ]
    }])
    processApi.createProcessRoute.mockResolvedValue({
      processId: 100,
      productId: 7,
      processCode: 'BA-ROUTE-STD-INJECTION-V1',
      processName: 'Standard injection route',
      processType: 'routing',
      versionNo: 'V1',
      status: 'draft',
      operations: []
    })
    const wrapper = mount(ProjectProcessRoutePanel, {
      ...mountOptions,
      props: { projectId: 7, productCode: 'BA', productSpecificCode: 'BA' }
    })
    await flushPromises()

    await wrapper.get('[data-test="process-create"]').trigger('click')
    await flushPromises()
    ;(document.body.querySelector('[data-test="process-route-save"]') as HTMLButtonElement).click()
    await flushPromises()

    expect(processApi.createProcessRoute).toHaveBeenCalled()
    const payload = processApi.createProcessRoute.mock.calls[0][1]
    expect(payload.operations).toMatchObject([
      { operationCode: 'PROC_INJECTION', operationCraftCode: '1020', businessOperationCode: 'NBA1020' },
      { operationCode: 'PROC_INJECTION', operationCraftCode: '1010', businessOperationCode: 'NBA1010' }
    ])
  })

  it('renders predecessor and successor nodes with operation names', async () => {
    processApi.getProcessRouteTemplates.mockResolvedValue([{
      routeTemplateCode: 'ROUTE-STD-INJECTION',
      routeTemplateName: '标准注塑组装路线',
      versionNo: 'V1',
      defaultTemplate: true,
      operations: [
        {
          operationCode: 'PROC_INJECTION',
          sequenceNo: 10,
          processName: '注塑成型',
          processParamJson: '{}',
          standardTimeMins: 12,
          qualityRequirement: '外观无缩水'
        },
        {
          operationCode: 'PROC_TRIMMING',
          sequenceNo: 20,
          processName: '修边去披锋',
          processParamJson: '{}',
          standardTimeMins: 4,
          qualityRequirement: '边缘平顺'
        },
        {
          operationCode: 'PROC_ASSEMBLY',
          sequenceNo: 30,
          processName: '组装',
          processParamJson: '{}',
          standardTimeMins: 6,
          qualityRequirement: '装配牢固'
        }
      ]
    }])
    const wrapper = mount(ProjectProcessRoutePanel, {
      ...mountOptions,
      props: { projectId: 7, productCode: 'PRD-7' }
    })
    await flushPromises()

    await wrapper.get('[data-test="process-create"]').trigger('click')
    await flushPromises()

    const predecessors = [...document.body.querySelectorAll('[data-test="node-check-predecessor"]')]
    const successors = [...document.body.querySelectorAll('[data-test="node-check-successor"]')]
    expect(predecessors).toHaveLength(3)
    expect(successors).toHaveLength(3)
    expect(successors[0].textContent).toBe('修边去披锋')
    expect(successors[0].textContent).not.toContain('PROC_TRIMMING')
    expect(predecessors[1].textContent).toBe('注塑成型')
    expect(successors[1].textContent).toBe('组装')
    expect(predecessors[1].textContent).not.toContain('PROC_INJECTION')
    expect(successors[1].textContent).not.toContain('PROC_ASSEMBLY')
  })

  it('queries project attachments without requiring a current timeline node', async () => {
    const wrapper = mount(TimelineAttachmentPanel, {
      ...mountOptions,
      props: { projectId: 7 }
    })

    await flushPromises()

    expect(attachmentApi.getFileCenterAttachments).toHaveBeenCalledWith({ projectId: 7, page: 1, size: 100 })
    expect(wrapper.text()).toContain('项目文件')
    expect(wrapper.get('[data-test="attachment-upload"]').attributes()).toHaveProperty('disabled')
  })

  it('uploads project files without selecting a timeline step', async () => {
    attachmentApi.uploadProjectAttachment.mockResolvedValue({
      attachmentId: 92,
      originalFileName: '项目资料.txt',
      fileCategory: 'other'
    })
    const wrapper = mount(TimelineAttachmentPanel, {
      global: {
        plugins: [ElementPlus],
        stubs: {
          ElUpload: {
            props: ['onChange', 'onRemove'],
            template: '<button data-test="stub-select-file" @click="onChange({ raw: { name: \'项目资料.txt\', size: 7, type: \'text/plain\' } })"><slot /></button>'
          }
        }
      },
      props: { projectId: 7 }
    })

    await flushPromises()
    await wrapper.get('[data-test="stub-select-file"]').trigger('click')
    await wrapper.get('[data-test="attachment-upload"]').trigger('click')
    await flushPromises()

    expect(attachmentApi.uploadProjectAttachment).toHaveBeenCalled()
    expect(attachmentApi.uploadTimelineAttachment).not.toHaveBeenCalled()
    const [projectId, file, metadata] = attachmentApi.uploadProjectAttachment.mock.calls[0]
    expect(projectId).toBe(7)
    expect(file.name).toBe('项目资料.txt')
    expect(metadata).toMatchObject({ fileCategory: 'testing', versionNo: 'V1' })
  })

  it('queries project attachments for the material detail area', async () => {
    attachmentApi.getFileCenterAttachments.mockResolvedValue({
      content: [{
        attachmentId: 91,
        ownerObjectType: 'Product',
        ownerObjectId: 7,
        projectId: 7,
        projectCode: 'PRD-7',
        projectName: '测试产品',
        timelineNodeKey: 'PRODUCT_LINE_INITIATION_CONFIRM',
        timelineStageName: '立项阶段',
        timelineStepName: '确认立项',
        fileCategory: 'drawing',
        fileName: 'drawing.pdf',
        originalFileName: 'drawing.pdf',
        fileExt: 'pdf',
        fileSize: 1024,
        checksum: 'abc',
        storageType: 'local',
        storageKey: 'projects/7/PRODUCT_LINE_INITIATION_CONFIRM/drawing.pdf',
        versionNo: 'V1',
        status: 'draft',
        createdAt: '2026-07-22 10:00:00',
        createdBy: '工程'
      }],
      page: 1,
      size: 100,
      totalElements: 1,
      totalPages: 1
    })
    const wrapper = mount(TimelineAttachmentPanel, {
      ...mountOptions,
      props: { projectId: 7 }
    })

    await flushPromises()

    expect(attachmentApi.getFileCenterAttachments).toHaveBeenCalledWith({ projectId: 7, page: 1, size: 100 })
    expect(wrapper.text()).toContain('drawing.pdf')
    expect(wrapper.text()).toContain('确认立项')
  })

  it('does not mount hidden attachment panels before the attachment tab is active', async () => {
    routeState.query = { tab: 'archived', archiveView: 'product', productId: '9', section: 'basic' }
    projectApi.getProjects.mockResolvedValue([createProductSummary()])

    const wrapper = mount(ProjectCenterView, {
      global: {
        plugins: [ElementPlus],
        stubs: {
          Teleport: true,
          PageContainer: { template: '<main><slot /></main>' },
          StatusTag: { template: '<span />' },
          FilePreview: { template: '<div />' },
          ElDialog: { props: ['modelValue'], template: '<div v-if="modelValue"><slot /><slot name="footer" /></div>' },
          ElDropdown: { template: '<div><slot /><slot name="dropdown" /></div>' },
          ElDropdownMenu: { template: '<div><slot /></div>' },
          ElDropdownItem: { template: '<button><slot /></button>' },
          ElTable: { template: '<div><slot /></div>' },
          ElTableColumn: { template: '<div />' },
          ProjectBomPanel: { template: '<div />' },
          ProjectProcessRoutePanel: { template: '<div />' },
          ProjectReleaseGatePanel: { template: '<div />' },
          TimelineAttachmentPanel: {
            props: ['projectId'],
            template: '<div data-test="timeline-attachment-panel">{{ projectId }}</div>'
          }
        }
      }
    })

    await flushPromises()
    await flushPromises()

    expect(wrapper.find('[data-test="timeline-attachment-panel"]').exists()).toBe(false)
  })

  it('keeps product detail navigation for BOM, process, and materials sections', async () => {
    routeState.query = { tab: 'archived', archiveView: 'product', productId: '9', section: 'project_flow' }
    projectApi.getProjects.mockResolvedValue([createProductSummary()])

    const wrapper = mount(ProjectCenterView, {
      global: {
        plugins: [ElementPlus],
        stubs: {
          Teleport: true,
          PageContainer: { template: '<main><slot /></main>' },
          StatusTag: { template: '<span />' },
          FilePreview: { template: '<div />' },
          ElDialog: { props: ['modelValue'], template: '<div v-if="modelValue"><slot /><slot name="footer" /></div>' },
          ElDropdown: { template: '<div><slot /><slot name="dropdown" /></div>' },
          ElDropdownMenu: { template: '<div><slot /></div>' },
          ElDropdownItem: { template: '<button><slot /></button>' },
          ElTable: { template: '<div><slot /></div>' },
          ElTableColumn: { template: '<div />' },
          ProjectBomPanel: { template: '<div />' },
          ProjectProcessRoutePanel: { template: '<div />' },
          ProjectReleaseGatePanel: { template: '<div />' },
          TimelineAttachmentPanel: { template: '<div />' }
        }
      }
    })

    await flushPromises()
    await flushPromises()

    const sectionLabels = wrapper.findAll('.detail-breadcrumb__item').map((item) => item.text())
    expect(sectionLabels).toEqual(expect.arrayContaining(['BOM管理', '工序明细', '资料区']))
  })

  it('renders mold transfer express as tracking number registration without trace controls', async () => {
    routeState.query = { tab: 'archived', archiveView: 'product', productId: '9', section: 'project_flow' }
    projectApi.getProjects.mockResolvedValue([createProductSummary({ status: 'developing', currentStage: '运模' })])
    projectApi.getProjectTimeline.mockResolvedValue({
      ...createTimeline(9, 'PRODUCT_LINE_MOLD_TRANSFER'),
      currentNode: '运模',
      moldTransferExpress: {
        moldTransferExpressId: 1,
        projectId: 9,
        timelineNodeKey: 'PRODUCT_LINE_MOLD_TRANSFER',
        trackingNo: 'YW-EXP-001',
        shippedAt: '2026-08-10T10:00:00',
        status: 'active'
      },
      nodes: [{
        nodeKey: 'PRODUCT_LINE_MOLD_TRANSFER',
        nodeName: '运模',
        phaseName: '开模阶段',
        stepNo: 5,
        status: 'current',
        nodeStatus: 'current',
        summary: '当前运模节点',
        ownerRole: '工程',
        documentCount: 0,
        confirmed: false
      }]
    })

    const wrapper = mount(ProjectCenterView, {
      global: {
        plugins: [ElementPlus],
        stubs: {
          Teleport: true,
          PageContainer: { template: '<main><slot /></main>' },
          StatusTag: { template: '<span />' },
          FilePreview: { template: '<div />' },
          ElDialog: { props: ['modelValue'], template: '<div v-if="modelValue"><slot /><slot name="footer" /></div>' },
          ElDropdown: { template: '<div><slot /><slot name="dropdown" /></div>' },
          ElDropdownMenu: { template: '<div><slot /></div>' },
          ElDropdownItem: { template: '<button><slot /></button>' },
          ElTable: { template: '<div><slot /></div>' },
          ElTableColumn: { template: '<div />' },
          ProjectBomPanel: { template: '<div />' },
          ProjectProcessRoutePanel: { template: '<div />' },
          ProjectReleaseGatePanel: { template: '<div />' },
          TimelineAttachmentPanel: { template: '<div />' }
        }
      }
    })

    await flushPromises()
    await flushPromises()

    const panelText = wrapper.get('.mold-transfer-panel').text()
    expect(panelText).toContain('运模快递登记')
    expect(panelText).toContain('快递单号')
    expect(panelText).toContain('发运时间')
    expect(panelText).toContain('YW-EXP-001')
    expect(panelText).not.toContain('刷新轨迹')
    expect(panelText).not.toContain('DHL 运模进度')
    expect(panelText).not.toContain('承运商')
    expect(panelText).not.toContain('最新状态')
    expect(panelText).not.toContain('最近刷新')
    expect(wrapper.find('.mold-transfer-traces').exists()).toBe(false)
  })

  it('shows the final timeline node as completed after backend completion', async () => {
    routeState.query = { tab: 'archived', archiveView: 'product', productId: '9', section: 'project_flow' }
    projectApi.getProjects.mockResolvedValue([createProductSummary({ status: 'released', currentStage: '运模', currentStepNo: 18 })])
    projectApi.getProjectTimeline.mockResolvedValue({
      ...createTimeline(9, 'MODEL_VARIANT_MOLD_TRANSFER'),
      timelineCompleted: true,
      currentNode: '运模',
      currentStepNo: 18,
      currentConfirmed: true,
      currentStepCode: 'MODEL_VARIANT_MOLD_TRANSFER',
      currentStepName: '运模',
      currentStageCode: 'MODEL_VARIANT_SMALL_BATCH_MX',
      currentStageName: '小批与 MX 验证',
      nodes: createTimeline(9, 'MODEL_VARIANT_MOLD_TRANSFER').nodes.map((node, index, nodes) => ({
        ...node,
        status: 'completed',
        nodeStatus: 'completed',
        confirmed: index === nodes.length - 1
      }))
    })

    const wrapper = mount(ProjectCenterView, {
      global: {
        plugins: [ElementPlus],
        stubs: {
          Teleport: true,
          PageContainer: { template: '<main><slot /></main>' },
          StatusTag: { template: '<span />' },
          FilePreview: { template: '<div />' },
          ElDialog: { props: ['modelValue'], template: '<div v-if="modelValue"><slot /><slot name="footer" /></div>' },
          ElDropdown: { template: '<div><slot /><slot name="dropdown" /></div>' },
          ElDropdownMenu: { template: '<div><slot /></div>' },
          ElDropdownItem: { template: '<button><slot /></button>' },
          ElTable: { template: '<div><slot /></div>' },
          ElTableColumn: { template: '<div />' },
          ProjectBomPanel: { template: '<div />' },
          ProjectProcessRoutePanel: { template: '<div />' },
          ProjectReleaseGatePanel: { template: '<div />' },
          TimelineAttachmentPanel: { template: '<div />' }
        }
      }
    })

    await flushPromises()
    await flushPromises()

    expect(wrapper.get('.timeline-action-panel__status').text()).toContain('已完成')
    expect(wrapper.find('[data-test="project-timeline-confirm"]').exists()).toBe(false)
    expect(wrapper.find('[data-test="project-timeline-advance"]').exists()).toBe(false)
  })

  it('shows the final product-line timeline node as completed after backend completion', async () => {
    routeState.query = { tab: 'archived', archiveView: 'product', productId: '9', section: 'project_flow' }
    projectApi.getProjects.mockResolvedValue([createProductSummary({ status: 'released', currentStage: '投产决策', currentStepNo: 22 })])
    projectApi.getProjectTimeline.mockResolvedValue({
      ...createTimeline(9, 'PRODUCT_LINE_PRODUCTION_DECISION_STEP'),
      timelineCompleted: true,
      currentNode: '投产决策',
      currentStepNo: 22,
      currentConfirmed: true,
      currentStepCode: 'PRODUCT_LINE_PRODUCTION_DECISION_STEP',
      currentStepName: '投产决策',
      currentStageCode: 'PRODUCT_LINE_PRODUCTION_DECISION',
      currentStageName: '投产决策',
      nodes: [{
        ...createTimeline(9, 'PRODUCT_LINE_PRODUCTION_DECISION_STEP').nodes[0],
        nodeName: '投产决策',
        phaseName: '投产发布阶段',
        stepNo: 22,
        status: 'completed',
        nodeStatus: 'completed',
        confirmed: true
      }]
    })

    const wrapper = mount(ProjectCenterView, {
      global: {
        plugins: [ElementPlus],
        stubs: {
          Teleport: true,
          PageContainer: { template: '<main><slot /></main>' },
          StatusTag: { template: '<span />' },
          FilePreview: { template: '<div />' },
          ElDialog: { props: ['modelValue'], template: '<div v-if="modelValue"><slot /><slot name="footer" /></div>' },
          ElDropdown: { template: '<div><slot /><slot name="dropdown" /></div>' },
          ElDropdownMenu: { template: '<div><slot /></div>' },
          ElDropdownItem: { template: '<button><slot /></button>' },
          ElTable: { template: '<div><slot /></div>' },
          ElTableColumn: { template: '<div />' },
          ProjectBomPanel: { template: '<div />' },
          ProjectProcessRoutePanel: { template: '<div />' },
          ProjectReleaseGatePanel: { template: '<div />' },
          TimelineAttachmentPanel: { template: '<div />' }
        }
      }
    })

    await flushPromises()
    await flushPromises()

    expect(wrapper.get('.timeline-action-panel__status').text()).toContain('已完成')
    expect(wrapper.text()).toContain('投产决策')
    expect(wrapper.find('[data-test="project-timeline-confirm"]').exists()).toBe(false)
    expect(wrapper.find('[data-test="project-timeline-advance"]').exists()).toBe(false)
  })

  it('mounts the M5 release gate panel in the current node section', async () => {
    routeState.query = { tab: 'archived', archiveView: 'product', productId: '9' }
    projectApi.getProjects.mockResolvedValue([createProductSummary({ status: 'developing' })])

    const wrapper = mount(ProjectCenterView, {
      global: {
        plugins: [ElementPlus],
        stubs: {
          Teleport: true,
          PageContainer: { template: '<main><slot /></main>' },
          StatusTag: { template: '<span />' },
          FilePreview: { template: '<div />' },
          ElDialog: { props: ['modelValue'], template: '<div v-if="modelValue"><slot /><slot name="footer" /></div>' },
          ElDropdown: { template: '<div><slot /><slot name="dropdown" /></div>' },
          ElDropdownMenu: { template: '<div><slot /></div>' },
          ElDropdownItem: { template: '<button><slot /></button>' },
          ElTable: { template: '<div><slot /></div>' },
          ElTableColumn: { template: '<div />' },
          ProjectBomPanel: { template: '<div />' },
          ProjectProcessRoutePanel: { template: '<div />' },
          ProjectReleaseGatePanel: {
            props: ['projectId', 'productStatus'],
            template: '<div data-test="release-gate-panel">{{ projectId }}:{{ productStatus }}</div>'
          },
          TimelineAttachmentPanel: { template: '<div />' }
        }
      }
    })

    await flushPromises()
    await flushPromises()

    expect(wrapper.get('[data-test="release-gate-panel"]').text()).toBe('9:developing')
  })

  it('renders abandoned projects from backend summaries instead of hardcoded static rows', async () => {
    routeState.query = { tab: 'abandoned' }
    projectApi.getProjects.mockResolvedValue([
      createProductSummary({
        productId: 88,
        productCode: 'PRD-REAL-ABN-088',
        productName: '后端真实放弃项目',
        status: 'archived',
        lockStatus: 'abandoned',
        abandonedAt: '2026-07-15T09:30:00',
        abandonedBy: 'engineer01'
      })
    ])

    const wrapper = mount(ProjectCenterView, {
      global: {
        plugins: [ElementPlus],
        stubs: {
          Teleport: true,
          PageContainer: { template: '<main><slot /></main>' },
          StatusTag: { template: '<span />' },
          FilePreview: { template: '<div />' },
          ElDialog: { props: ['modelValue'], template: '<div v-if="modelValue"><slot /><slot name="footer" /></div>' },
          ElDropdown: { template: '<div><slot /><slot name="dropdown" /></div>' },
          ElDropdownMenu: { template: '<div><slot /></div>' },
          ElDropdownItem: { template: '<button><slot /></button>' },
          ElTable: {
            props: ['data'],
            template: '<div><span v-for="row in data" :key="row.productId">{{ row.productCode }} {{ row.productName }} {{ row.abandonedAt }}</span><slot /></div>'
          },
          ElTableColumn: { template: '<div />' },
          ProjectBomPanel: { template: '<div />' },
          ProjectProcessRoutePanel: { template: '<div />' },
          ProjectReleaseGatePanel: { template: '<div />' },
          TimelineAttachmentPanel: { template: '<div />' }
        }
      }
    })

    await flushPromises()
    await flushPromises()

    expect(wrapper.text()).toContain('PRD-REAL-ABN-088')
    expect(wrapper.text()).toContain('后端真实放弃项目')
    expect(wrapper.text()).not.toContain('PRD-SC29-ABN-001')
    expect(wrapper.text()).not.toContain('PRD-LJ29-ABN-003')
  })

  it('shows backend timeline action errors instead of generic axios errors', async () => {
    routeState.query = { tab: 'archived', archiveView: 'product', productId: '9' }
    projectApi.getProjects.mockResolvedValue([createProductSummary({ status: 'developing' })])
    projectApi.confirmTimelineNode.mockRejectedValue(Object.assign(new Error('Request failed with status code 400'), {
      response: { data: { message: '只能操作当前时间轴节点' } }
    }))
    const errorSpy = vi.spyOn(ElMessage, 'error').mockImplementation(() => undefined as never)

    const wrapper = mount(ProjectCenterView, {
      global: {
        plugins: [ElementPlus],
        stubs: {
          Teleport: true,
          PageContainer: { template: '<main><slot /></main>' },
          StatusTag: { template: '<span />' },
          FilePreview: { template: '<div />' },
          ElDialog: { props: ['modelValue'], template: '<div v-if="modelValue"><slot /><slot name="footer" /></div>' },
          ElDropdown: { template: '<div><slot /><slot name="dropdown" /></div>' },
          ElDropdownMenu: { template: '<div><slot /></div>' },
          ElDropdownItem: { template: '<button><slot /></button>' },
          ElTable: { template: '<div><slot /></div>' },
          ElTableColumn: { template: '<div />' },
          ProjectBomPanel: { template: '<div />' },
          ProjectProcessRoutePanel: { template: '<div />' },
          ProjectReleaseGatePanel: { template: '<div />' },
          TimelineAttachmentPanel: { template: '<div />' }
        }
      }
    })

    await flushPromises()
    await flushPromises()
    await wrapper.get('[data-test="project-timeline-confirm"]').trigger('click')
    await flushPromises()

    expect(errorSpy).toHaveBeenCalledWith('只能操作当前时间轴节点')
  })
})
