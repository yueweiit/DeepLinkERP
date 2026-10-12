import ElementPlus, { ElMessage, ElMessageBox } from 'element-plus'
import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const projectApi = vi.hoisted(() => ({
  getWorkbenchInProgressProjects: vi.fn(),
  getProjects: vi.fn(),
  getProjectDetail: vi.fn(),
  getProjectTimeline: vi.fn(),
  confirmTimelineNode: vi.fn(),
  advanceTimelineNode: vi.fn(),
  returnTimelineNode: vi.fn()
}))

const productApi = vi.hoisted(() => ({
  createProduct: vi.fn(),
  getProductProductionColors: vi.fn()
}))

const attachmentApi = vi.hoisted(() => ({
  uploadTimelineAttachment: vi.fn()
}))

const orderApi = vi.hoisted(() => ({
  getRequirementForm: vi.fn(),
  saveRequirementForm: vi.fn(),
  confirmRequirementForm: vi.fn()
}))

const routerPush = vi.hoisted(() => vi.fn())

vi.mock('@/api/modules/project', () => projectApi)
vi.mock('@/api/modules/product', () => productApi)
vi.mock('@/api/modules/attachment', () => attachmentApi)
vi.mock('@/api/modules/order', () => orderApi)
vi.mock('@/stores/user', () => ({
  useUserStore: () => ({
    profile: { userName: '工程' }
  })
}))
vi.mock('vue-router', () => ({
  useRouter: () => ({ push: routerPush })
}))

import DashboardView from '../DashboardView.vue'

function createProject(overrides: Record<string, unknown> = {}) {
  return {
    productId: 9,
    productName: 'M2 测试产品线',
    productCode: 'PRD-M2-0002',
    seriesName: 'M2 测试产品线',
    currentStage: '立项确认',
    ownerUserName: '工程',
    activeBomVersion: '--',
    completionRate: 0.17,
    status: 'developing',
    productType: 'product_line',
    currentStepNo: 1,
    ...overrides
  }
}

function createTimeline(overrides: Record<string, unknown> = {}) {
  return {
    projectId: 9,
    productId: 9,
    productType: 'product_line',
    currentNode: '产品立项',
    currentStepNo: 1,
    currentConfirmed: false,
    currentStageCode: 'PRODUCT_LINE_INIT_CONFIRM',
    currentStageName: '立项确认',
    currentStepCode: 'PRODUCT_LINE_INITIATION_CONFIRM',
    currentStepName: '产品立项',
    nodes: [{
      nodeKey: 'PRODUCT_LINE_INITIATION_CONFIRM',
      nodeName: '产品立项',
      phaseName: '第 1 步',
      stageCode: 'PRODUCT_LINE_INIT_CONFIRM',
      stageName: '立项确认',
      requiredFileCategory: 'other',
      stepNo: 1,
      status: 'current',
      nodeStatus: 'current',
      summary: '等待节点处理',
      ownerRole: '项目经理',
      documentCount: 0,
      confirmed: false
    }],
    ...overrides
  }
}

function mountDashboard() {
  return mount(DashboardView, {
    global: {
      plugins: [ElementPlus],
      stubs: {
        Teleport: true,
        PageContainer: { template: '<main><slot /></main>' },
        StatusTag: { props: ['status'], template: '<span>{{ status }}</span>' },
        ElDialog: { props: ['modelValue'], template: '<section v-if="modelValue"><slot /><slot name="footer" /></section>' },
        ElSelect: { template: '<div><slot /></div>' },
        ElOption: { props: ['label', 'value'], template: '<span>{{ label }}</span>' },
        ElSegmented: { props: ['modelValue', 'options'], template: '<div><button v-for="option in options" :key="option.value" type="button">{{ option.label }}</button></div>' },
        ElDatePicker: { template: '<input />' },
        ProductionConfirmationDialog: {
          props: ['modelValue', 'projectId', 'mode'],
          emits: ['confirmed'],
          template: '<section v-if="modelValue" data-test="dashboard-production-confirmation-dialog"><span>{{ projectId }} {{ mode }}</span><button data-test="dashboard-production-confirmation-confirmed" type="button" @click="$emit(\'confirmed\')">confirmed</button></section>'
        }
      }
    }
  })
}

describe('Dashboard project progress actions', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    projectApi.getWorkbenchInProgressProjects.mockResolvedValue([createProject()])
    projectApi.getProjects.mockResolvedValue([createProject({ status: 'released' })])
    projectApi.getProjectDetail.mockResolvedValue(createProject())
    projectApi.getProjectTimeline.mockResolvedValue(createTimeline())
    projectApi.confirmTimelineNode.mockResolvedValue({})
    projectApi.advanceTimelineNode.mockResolvedValue({})
    projectApi.returnTimelineNode.mockResolvedValue({})
    productApi.createProduct.mockResolvedValue({ productId: 20, productCode: 'PRD-MV-0020', versionNo: 'A', status: 'draft' })
    productApi.getProductProductionColors.mockResolvedValue([{ codeItemId: 10, colorCode: '01', colorName: '黑色', confirmedAt: '2026-07-23T10:00:00' }])
    attachmentApi.uploadTimelineAttachment.mockResolvedValue({})
    orderApi.getRequirementForm.mockResolvedValue({
      projectId: 9,
      dingTalkApprovalNo: 'DT-001',
      productName: '精孔磁吸壳 iPhone 18',
      model: 'iPhone 18',
      requirementType: 'customer_requirement',
      customerRequirement: '客户要求',
      status: 'draft',
      colors: [{ variantColorId: 1, colorCode: '01', colorName: '黑色', selected: true }]
    })
    orderApi.saveRequirementForm.mockResolvedValue({})
    orderApi.confirmRequirementForm.mockResolvedValue({})
    vi.spyOn(ElMessageBox, 'confirm').mockImplementation(() => Promise.resolve('confirm') as ReturnType<typeof ElMessageBox.confirm>)
    vi.spyOn(ElMessageBox, 'prompt').mockImplementation(() => Promise.resolve({ value: '资料已确认', action: 'confirm' }) as ReturnType<typeof ElMessageBox.prompt>)
  })

  it('loads backend timeline and confirms the current node from dashboard', async () => {
    const wrapper = mountDashboard()
    await flushPromises()

    await wrapper.get('[data-test="dashboard-project-9"]').trigger('click')
    await flushPromises()
    await wrapper.get('[data-test="dashboard-progress-confirm"]').trigger('click')
    await flushPromises()

    expect(projectApi.getProjectTimeline).toHaveBeenCalledWith(9)
    expect(projectApi.confirmTimelineNode).toHaveBeenCalledWith(9, 'PRODUCT_LINE_INITIATION_CONFIRM', '资料已确认')
  })

  it('shows the requirement form before a model-variant timeline starts', async () => {
    projectApi.getWorkbenchInProgressProjects.mockResolvedValue([
      createProject({ productType: 'model_variant', productName: '精孔磁吸壳 iPhone 18' })
    ])
    projectApi.getProjectTimeline.mockResolvedValue(createTimeline({
      productType: 'model_variant',
      started: false,
      startBlockReason: '请先完成新型号项目信息完善表',
      nodes: []
    }))

    const wrapper = mountDashboard()
    await flushPromises()
    await wrapper.get('[data-test="dashboard-project-9"]').trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('新型号项目信息完善表')
    expect(wrapper.text()).toContain('请先完成新型号项目信息完善表')
    expect(wrapper.find('[data-test="dashboard-progress-confirm"]').exists()).toBe(false)
    expect(wrapper.find('.project-progress-layout').exists()).toBe(false)
  })

  it('replaces the form with the first formal timeline node after confirmation', async () => {
    projectApi.getWorkbenchInProgressProjects.mockResolvedValue([
      createProject({ productType: 'model_variant', productName: '精孔磁吸壳 iPhone 18' })
    ])
    projectApi.getProjectTimeline
      .mockResolvedValueOnce(createTimeline({
        productType: 'model_variant',
        started: false,
        nodes: []
      }))
      .mockResolvedValueOnce(createTimeline({
        productType: 'model_variant',
        started: true,
        currentNode: '产品立项',
        currentStepCode: 'MODEL_VARIANT_INIT_CREATE',
        currentStepName: '产品立项',
        nodes: [{
          nodeKey: 'MODEL_VARIANT_INIT_CREATE',
          nodeName: '产品立项',
          phaseName: '立项阶段',
          stageCode: 'MODEL_VARIANT_INIT_CONFIRM',
          stageName: '立项确认',
          requiredFileCategory: 'other',
          stepNo: 1,
          status: 'current',
          nodeStatus: 'current',
          summary: '等待节点处理',
          ownerRole: '工程',
          documentCount: 0,
          confirmed: false
        }]
      }))
    orderApi.confirmRequirementForm.mockResolvedValue({ status: 'confirmed' })

    const wrapper = mountDashboard()
    await flushPromises()
    await wrapper.get('[data-test="dashboard-project-9"]').trigger('click')
    await flushPromises()
    const confirmFormButton = wrapper.findAll('button').find((button) => button.text().includes('确认并进入下一步'))
    expect(confirmFormButton).toBeDefined()
    await confirmFormButton!.trigger('click')
    await flushPromises()

    expect(orderApi.confirmRequirementForm).toHaveBeenCalledWith(9, expect.objectContaining({
      selectedVariantColorIds: [1]
    }))
    expect(wrapper.text()).not.toContain('请先完成新型号项目信息完善表')
    expect(wrapper.text()).toContain('产品立项')
    expect(wrapper.find('[data-test="dashboard-progress-confirm"]').exists()).toBe(true)
  })

  it('opens create-project dialog without product series manual field', async () => {
    const wrapper = mountDashboard()
    await flushPromises()

    await wrapper.get('.quick-action-inline').trigger('click')
    await flushPromises()

    expect(projectApi.getProjects).toHaveBeenCalledWith({ page: 1, size: 200, productType: 'product_line' })
    expect(wrapper.text()).not.toContain('产品系列')
    expect(wrapper.text()).not.toContain('例如 黑色 / 蓝色')
  })

  it('shows the simplified current-step actions from dashboard', async () => {
    const wrapper = mountDashboard()
    await flushPromises()

    await wrapper.get('[data-test="dashboard-project-9"]').trigger('click')
    await flushPromises()

    expect(wrapper.find('[data-test="dashboard-progress-advance"]').exists()).toBe(false)
    expect(wrapper.find('[data-test="dashboard-progress-hold"]').exists()).toBe(false)
    expect(wrapper.get('[data-test="dashboard-progress-return"]').text()).toContain('返回上一步')
  })

  it('shows current small step and uploaded materials with visual status', async () => {
    projectApi.getWorkbenchInProgressProjects.mockResolvedValue([createProject({ currentStepNo: 7 })])
    projectApi.getProjectTimeline.mockResolvedValue(createTimeline({
      currentNode: '测试模具',
      currentStepNo: 7,
      currentStepName: '测试模具',
      nodes: [{
        nodeKey: 'PRODUCT_LINE_MOLD_APPLY',
        nodeName: '申请开模',
        phaseName: '第 5 步',
        stageCode: 'PRODUCT_LINE_MOLD',
        stageName: '开模试模',
        requiredFileCategory: null,
        stepNo: 5,
        status: 'completed',
        nodeStatus: 'completed',
        summary: '已完成',
        ownerRole: '工程',
        documentCount: 0,
        confirmed: false
      }, {
        nodeKey: 'PRODUCT_LINE_MOLD_MAKE',
        nodeName: '制作模具',
        phaseName: '第 6 步',
        stageCode: 'PRODUCT_LINE_MOLD',
        stageName: '开模试模',
        requiredFileCategory: 'other',
        stepNo: 6,
        status: 'completed',
        nodeStatus: 'completed',
        summary: '已完成',
        ownerRole: '工程',
        documentCount: 1,
        confirmed: false
      }, {
        nodeKey: 'PRODUCT_LINE_MOLD_TEST',
        nodeName: '测试模具',
        phaseName: '第 7 步',
        stageCode: 'PRODUCT_LINE_MOLD',
        stageName: '开模试模',
        requiredFileCategory: 'testing',
        stepNo: 7,
        status: 'current',
        nodeStatus: 'current',
        summary: '等待测试模具资料确认',
        ownerRole: '工程 / 品质',
        documentCount: 3,
        confirmed: false
      }]
    }))
    const wrapper = mountDashboard()
    await flushPromises()

    await wrapper.get('[data-test="dashboard-project-9"]').trigger('click')
    await flushPromises()

    expect(wrapper.get('[data-test="dashboard-current-step-summary"]').text()).toContain('第 7 步')
    expect(wrapper.get('[data-test="dashboard-current-step-summary"]').text()).toContain('测试模具')
    expect(wrapper.get('[data-test="dashboard-child-step-6"]').classes()).toContain('is-confirmed')
    expect(wrapper.get('[data-test="dashboard-child-step-6"]').text()).toContain('已确认')
    expect(wrapper.get('[data-test="dashboard-child-step-7"]').classes()).toContain('is-current')
    expect(wrapper.get('[data-test="dashboard-child-step-7"]').text()).toContain('当前步骤')
    expect(wrapper.get('[data-test="dashboard-child-step-7"]').text()).toContain('已上传 3 个')
  })

  it('marks current required-upload small step as pending upload when no materials exist', async () => {
    projectApi.getWorkbenchInProgressProjects.mockResolvedValue([createProject({ currentStepNo: 7 })])
    projectApi.getProjectTimeline.mockResolvedValue(createTimeline({
      currentNode: '测试模具',
      currentStepNo: 7,
      currentStepName: '测试模具',
      nodes: [{
        nodeKey: 'PRODUCT_LINE_MOLD_TEST',
        nodeName: '测试模具',
        phaseName: '第 7 步',
        stageCode: 'PRODUCT_LINE_MOLD',
        stageName: '开模试模',
        requiredFileCategory: 'testing',
        stepNo: 7,
        status: 'current',
        nodeStatus: 'current',
        summary: '等待测试模具资料确认',
        ownerRole: '工程 / 品质',
        documentCount: 0,
        confirmed: false
      }]
    }))
    const wrapper = mountDashboard()
    await flushPromises()

    await wrapper.get('[data-test="dashboard-project-9"]').trigger('click')
    await flushPromises()

    expect(wrapper.get('[data-test="dashboard-child-step-7"]').classes()).toContain('is-missing-upload')
    expect(wrapper.get('[data-test="dashboard-child-step-7"]').text()).toContain('当前步骤')
    expect(wrapper.get('[data-test="dashboard-child-step-7"]').text()).toContain('待上传')
  })

  it('returns to previous small step from dashboard', async () => {
    const wrapper = mountDashboard()
    await flushPromises()

    await wrapper.get('[data-test="dashboard-project-9"]').trigger('click')
    await flushPromises()
    await wrapper.get('[data-test="dashboard-progress-return"]').trigger('click')
    await flushPromises()

    expect(projectApi.returnTimelineNode).toHaveBeenCalledWith(9, 'PRODUCT_LINE_INITIATION_CONFIRM', '资料已确认', true)
  })

  it('uploads current-stage materials from dashboard with selected step', async () => {
    const wrapper = mountDashboard()
    await flushPromises()

    await wrapper.get('[data-test="dashboard-project-9"]').trigger('click')
    await flushPromises()
    await wrapper.get('[data-test="dashboard-progress-upload-open"]').trigger('click')
    await flushPromises()

    await wrapper.get('[data-test="dashboard-progress-upload-step"]').setValue('PRODUCT_LINE_INITIATION_CONFIRM')
    const file = new File(['drawing'], 'drawing.txt', { type: 'text/plain' })
    const input = wrapper.get('[data-test="dashboard-progress-upload-file"]')
    Object.defineProperty(input.element, 'files', { value: [file] })
    await input.trigger('change')
    await wrapper.get('[data-test="dashboard-progress-upload-submit"]').trigger('click')
    await flushPromises()

    expect(attachmentApi.uploadTimelineAttachment).toHaveBeenCalledWith(
      9,
      'PRODUCT_LINE_INITIATION_CONFIRM',
      file,
      { fileCategory: 'other', remark: '工作台节点资料上传' }
    )
  })

  it('keeps material upload available on process-route small steps', async () => {
    projectApi.getWorkbenchInProgressProjects.mockResolvedValue([createProject({ currentStepNo: 9 })])
    projectApi.getProjectTimeline.mockResolvedValue(createTimeline({
      currentNode: '加工艺',
      currentStepNo: 9,
      currentStepName: '加工艺',
      nodes: [{
        nodeKey: 'PRODUCT_LINE_PROCESS_ADD',
        nodeName: '加工艺',
        phaseName: '第 9 步',
        stageCode: 'PRODUCT_LINE_SAMPLE_PROCESS',
        stageName: '样品与工艺',
        requiredFileCategory: null,
        stepNo: 9,
        status: 'current',
        nodeStatus: 'current',
        summary: '新建结构化工艺路线',
        ownerRole: '工程',
        documentCount: 0,
        confirmed: false
      }]
    }))
    const wrapper = mountDashboard()
    await flushPromises()

    await wrapper.get('[data-test="dashboard-project-9"]').trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('新建工艺路线')
    expect(wrapper.find('[data-test="dashboard-process-route-create"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="dashboard-production-confirmation-open"]').exists()).toBe(false)
    expect(wrapper.find('[data-test="dashboard-progress-upload-open"]').exists()).toBe(true)
    await wrapper.get('[data-test="dashboard-progress-upload-open"]').trigger('click')
    await flushPromises()
    await wrapper.get('[data-test="dashboard-progress-upload-step"]').setValue('PRODUCT_LINE_PROCESS_ADD')
    const file = new File(['process'], 'process.txt', { type: 'text/plain' })
    const input = wrapper.get('[data-test="dashboard-progress-upload-file"]')
    Object.defineProperty(input.element, 'files', { value: [file] })
    await input.trigger('change')
    await wrapper.get('[data-test="dashboard-progress-upload-submit"]').trigger('click')
    await flushPromises()

    expect(attachmentApi.uploadTimelineAttachment).toHaveBeenCalledWith(
      9,
      'PRODUCT_LINE_PROCESS_ADD',
      file,
      { fileCategory: 'other', remark: '工作台节点资料上传' }
    )
    await wrapper.get('[data-test="dashboard-process-route-create"]').trigger('click')

    expect(routerPush).toHaveBeenCalledWith({
      path: '/projects',
      query: { tab: 'in_progress', productId: '9', section: 'process_detail', createProcessRoute: '1' }
    })
  })

  it('opens production confirmation from process-confirm small step', async () => {
    projectApi.getWorkbenchInProgressProjects.mockResolvedValue([
      createProject({ currentStepNo: 10, productType: 'model_variant', productName: 'Alterna幻甲 SM S280' })
    ])
    projectApi.getProjectTimeline.mockResolvedValue(createTimeline({
      productType: 'model_variant',
      currentNode: '敲定工序',
      currentStepNo: 10,
      currentStepCode: 'MODEL_VARIANT_PROCESS_CONFIRM',
      currentStepName: '敲定工序',
      nodes: [{
        nodeKey: 'MODEL_VARIANT_PROCESS_CONFIRM',
        nodeName: '敲定工序',
        phaseName: '第 10 步',
        stageCode: 'MODEL_VARIANT_SAMPLE_PROCESS',
        stageName: '样品与工艺',
        requiredFileCategory: null,
        stepNo: 10,
        status: 'current',
        nodeStatus: 'current',
        summary: '确认有效投产工序',
        ownerRole: '工程',
        documentCount: 0,
        confirmed: false
      }]
    }))
    const wrapper = mountDashboard()
    await flushPromises()

    await wrapper.get('[data-test="dashboard-project-9"]').trigger('click')
    await flushPromises()

    expect(wrapper.find('[data-test="dashboard-production-confirmation-open"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="dashboard-process-route-create"]').exists()).toBe(false)

    await wrapper.get('[data-test="dashboard-production-confirmation-open"]').trigger('click')
    await flushPromises()

    expect(wrapper.get('[data-test="dashboard-production-confirmation-dialog"]').text()).toContain('9 operations')

    const timelineCallsBeforeConfirmed = projectApi.getProjectTimeline.mock.calls.length
    const workbenchCallsBeforeConfirmed = projectApi.getWorkbenchInProgressProjects.mock.calls.length
    await wrapper.get('[data-test="dashboard-production-confirmation-confirmed"]').trigger('click')
    await flushPromises()

    expect(projectApi.getProjectTimeline.mock.calls.length).toBe(timelineCallsBeforeConfirmed + 1)
    expect(projectApi.getWorkbenchInProgressProjects.mock.calls.length).toBe(workbenchCallsBeforeConfirmed + 1)
  })

  it('opens production color confirmation from final production step', async () => {
    projectApi.getWorkbenchInProgressProjects.mockResolvedValue([
      createProject({ currentStepNo: 22, productType: 'product_line', productName: '超队5.0', currentStage: '投产决策' })
    ])
    projectApi.getProjectTimeline.mockResolvedValue(createTimeline({
      currentNode: '投产决策',
      currentStepNo: 22,
      currentStepCode: 'PRODUCT_LINE_PRODUCTION_DECISION_STEP',
      currentStepName: '投产决策',
      nodes: [{
        nodeKey: 'PRODUCT_LINE_PRODUCTION_DECISION_STEP',
        nodeName: '投产决策',
        phaseName: '第 22 步',
        stageCode: 'PRODUCT_LINE_PRODUCTION_DECISION',
        stageName: '投产发布阶段',
        requiredFileCategory: null,
        stepNo: 22,
        status: 'current',
        nodeStatus: 'current',
        summary: '确认投产颜色',
        ownerRole: '工程',
        documentCount: 0,
        confirmed: false
      }]
    }))
    const wrapper = mountDashboard()
    await flushPromises()

    await wrapper.get('[data-test="dashboard-project-9"]').trigger('click')
    await flushPromises()

    expect(wrapper.find('[data-test="dashboard-production-colors-open"]').exists()).toBe(true)
    await wrapper.get('[data-test="dashboard-production-colors-open"]').trigger('click')
    await flushPromises()

    expect(wrapper.get('[data-test="dashboard-production-confirmation-dialog"]').text()).toContain('9 colors')
  })

  it('shows backend timeline action errors from dashboard actions', async () => {
    projectApi.confirmTimelineNode.mockRejectedValue(Object.assign(new Error('Request failed with status code 400'), {
      response: { data: { message: 'current stage documents are incomplete: PRODUCT_LINE_INITIATION_CONFIRM:other' } }
    }))
    const errorSpy = vi.spyOn(ElMessage, 'error').mockImplementation(() => undefined as never)
    const wrapper = mountDashboard()
    await flushPromises()

    await wrapper.get('[data-test="dashboard-project-9"]').trigger('click')
    await flushPromises()
    await wrapper.get('[data-test="dashboard-progress-confirm"]').trigger('click')
    await flushPromises()

    expect(errorSpy).toHaveBeenCalledWith('current stage documents are incomplete: PRODUCT_LINE_INITIATION_CONFIRM:other')
  })
})
