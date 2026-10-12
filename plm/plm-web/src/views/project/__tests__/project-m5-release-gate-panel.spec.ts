import ElementPlus from 'element-plus'
import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const projectApi = vi.hoisted(() => ({
  checkProjectReleaseGate: vi.fn(),
  freezeProject: vi.fn(),
  publishProject: vi.fn(),
  archiveProject: vi.fn(),
  abandonProject: vi.fn()
}))

vi.mock('@/api/modules/project', () => projectApi)

const messageBoxMock = vi.hoisted(() => ({
  confirm: vi.fn(),
  prompt: vi.fn()
}))

const messageMock = vi.hoisted(() => ({
  success: vi.fn(),
  error: vi.fn()
}))

vi.mock('element-plus', async (importOriginal) => {
  const actual = await importOriginal<typeof import('element-plus')>()
  return {
    ...actual,
    ElMessageBox: messageBoxMock,
    ElMessage: messageMock
  }
})

import ProjectReleaseGatePanel from '../components/ProjectReleaseGatePanel.vue'

function createGate(overrides: Record<string, unknown> = {}) {
  return {
    projectId: 7,
    productId: 7,
    passed: true,
    blocking: false,
    confirmRequired: true,
    currentStatus: 'developing',
    currentNodeKey: 'PRODUCT_LINE_PRODUCTION_DECISION',
    currentNodeConfirmed: true,
    frozenBomCount: 1,
    lockedProcessRouteCount: 0,
    drawingFileCount: 1,
    sopFileCount: 0,
    sipFileCount: 1,
    testingFileCount: 0,
    missingItems: [{ code: 'PROCESS_ROUTE_NOT_LOCKED', message: '缺少已锁定或已冻结工艺路线', severity: 'warning' }],
    ...overrides
  }
}

function mountPanel(productStatus = 'developing') {
  return mount(ProjectReleaseGatePanel, {
    props: { projectId: 7, productStatus },
    global: {
      plugins: [ElementPlus]
    }
  })
}

describe('ProjectReleaseGatePanel', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    projectApi.checkProjectReleaseGate.mockResolvedValue(createGate())
    messageBoxMock.confirm.mockResolvedValue('confirm')
    messageBoxMock.prompt.mockResolvedValue({ value: '业务取消' })
  })

  it('loads release risk data and keeps missing items collapsed by default', async () => {
    const wrapper = mountPanel()

    await flushPromises()

    expect(projectApi.checkProjectReleaseGate).toHaveBeenCalledWith(7)
    expect(wrapper.text()).toContain('存在非阻塞提醒')
    expect(wrapper.text()).toContain('待确认 1')
    expect(wrapper.find('[data-test="release-gate-risk-content"]').exists()).toBe(false)

    await wrapper.get('.el-collapse-item__header').trigger('click')
    await flushPromises()

    expect(wrapper.get('[data-test="release-gate-risk-content"]').text()).toContain('缺少已锁定或已冻结工艺路线')
    expect(wrapper.get('[data-test="release-gate-risk-content"]').text()).toContain('BOM：1')
    expect(wrapper.get('[data-test="release-gate-risk-content"]').text()).toContain('工艺路线：0')
  })

  it('publishes after confirming missing-material risks', async () => {
    projectApi.publishProject.mockResolvedValue({ status: 'released' })
    const wrapper = mountPanel()

    await flushPromises()
    await wrapper.get('[data-test="release-gate-publish"]').trigger('click')
    await flushPromises()

    expect(projectApi.publishProject).toHaveBeenCalledWith(7, {
      reason: '前端项目中心发布',
      riskConfirmed: true
    })
    expect(messageMock.success).toHaveBeenCalledWith('发布成功，当前状态：released')
  })

  it('disables publish for released products and keeps archive available', async () => {
    projectApi.checkProjectReleaseGate.mockResolvedValue(
      createGate({
        passed: false,
        currentStatus: 'released',
        missingItems: [{ code: 'TIMELINE_NODE_NOT_CONFIRMED', message: '当前门禁节点尚未确认' }]
      })
    )
    const wrapper = mountPanel('released')

    await flushPromises()

    const publishButton = wrapper.get('[data-test="release-gate-publish"]')
    expect((publishButton.element as HTMLButtonElement).disabled).toBe(true)
    expect(publishButton.text()).toContain('已发布')
    expect(wrapper.text()).toContain('产品已发布')
    expect(wrapper.text()).not.toContain('PRODUCT_STATUS_NOT_REVIEWING')
    expect((wrapper.get('[data-test="release-gate-archive"]').element as HTMLButtonElement).disabled).toBe(false)

    await publishButton.trigger('click')
    await flushPromises()

    expect(projectApi.publishProject).not.toHaveBeenCalled()
  })

  it('requires an abandon reason and emits changed after abandon succeeds', async () => {
    projectApi.abandonProject.mockResolvedValue({ productId: 7, productCode: 'PRD-7', productName: '测试产品', status: 'archived' })
    const wrapper = mountPanel()

    await flushPromises()
    await wrapper.get('[data-test="release-gate-abandon"]').trigger('click')
    await flushPromises()

    expect(projectApi.abandonProject).toHaveBeenCalledWith(7, { reason: '业务取消' })
    expect(wrapper.emitted('changed')).toHaveLength(1)
  })
})
