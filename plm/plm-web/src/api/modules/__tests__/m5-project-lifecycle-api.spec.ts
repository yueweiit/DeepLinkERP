import { beforeEach, describe, expect, it, vi } from 'vitest'

const requestMock = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn()
}))

vi.mock('../../request', () => ({
  default: requestMock,
  unwrapResponse: <T>(response: { data: { data: T } }) => response.data.data
}))

import {
  abandonProject,
  archiveProject,
  checkProjectReleaseGate,
  freezeProject,
  publishProject
} from '../project'

function apiResponse<T>(data: T) {
  return Promise.resolve({ data: { code: 0, message: 'success', data } })
}

describe('M5 project lifecycle API contract', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('checks release gate through the project lifecycle endpoint', async () => {
    const gate = {
      projectId: 7,
      productId: 7,
      passed: false,
      currentStatus: 'developing',
      currentNodeKey: 'PRODUCT_LINE_PRODUCTION_DECISION',
      currentNodeConfirmed: true,
      frozenBomCount: 1,
      lockedProcessRouteCount: 0,
      drawingFileCount: 1,
      sopFileCount: 0,
      sipFileCount: 1,
      testingFileCount: 0,
      missingItems: [{ code: 'PROCESS_ROUTE_NOT_LOCKED', message: '缺少已锁定或已冻结工艺路线' }]
    }
    requestMock.get.mockReturnValue(apiResponse(gate))

    await expect(checkProjectReleaseGate(7)).resolves.toEqual(gate)

    expect(requestMock.get).toHaveBeenCalledWith('/projects/7/release-gate')
  })

  it('uses project lifecycle action endpoints with explicit reasons', async () => {
    const product = {
      productId: 7,
      productCode: 'PRD-7',
      productName: '测试产品',
      status: 'released'
    }
    requestMock.post.mockReturnValue(apiResponse(product))

    await freezeProject(7, { reason: '资料冻结' })
    await publishProject(7, { reason: '资料齐备，允许发布' })
    await archiveProject(7, { reason: '版本归档' })
    await abandonProject(8, { reason: '客户取消' })

    expect(requestMock.post).toHaveBeenNthCalledWith(1, '/projects/7/freeze', { reason: '资料冻结' })
    expect(requestMock.post).toHaveBeenNthCalledWith(2, '/projects/7/publish', { reason: '资料齐备，允许发布' })
    expect(requestMock.post).toHaveBeenNthCalledWith(3, '/projects/7/archive', { reason: '版本归档' })
    expect(requestMock.post).toHaveBeenNthCalledWith(4, '/projects/8/abandon', { reason: '客户取消' })
  })

  it('rejects abandon when the reason is blank before sending a request', async () => {
    await expect(abandonProject(8, { reason: '   ' })).rejects.toThrow('请填写停止原因')

    expect(requestMock.post).not.toHaveBeenCalled()
  })
})
