import { beforeEach, describe, expect, it, vi } from 'vitest'

const requestMock = vi.hoisted(() => ({
  get: vi.fn(),
  patch: vi.fn(),
  post: vi.fn()
}))

vi.mock('../../request', () => ({
  default: requestMock,
  unwrapResponse: <T>(response: { data: { data: T } }) => response.data.data,
  unwrapPage: <T>(response: { data: { data: T } }) => response.data.data
}))

import {
  bulkUpdateMarketWatch,
  getMarketWatchItems,
  getPromotionOptions,
  promoteMarketWatch,
  updateMarketWatchItem
} from '../marketWatch'

function apiResponse<T>(data: T) {
  return Promise.resolve({ data: { code: 0, message: 'success', data } })
}

describe('market watch API', () => {
  beforeEach(() => vi.clearAllMocks())

  it('passes paging and filters to the native PLM proxy', async () => {
    const query = { kind: 'candidate' as const, page: 3, size: 20, keyword: 'pixel', country: 'MX' }
    const page = { content: [], page: 3, size: 20, totalElements: 0, totalPages: 0 }
    requestMock.get.mockReturnValue(apiResponse(page))

    await expect(getMarketWatchItems(query)).resolves.toEqual(page)
    expect(requestMock.get).toHaveBeenCalledWith('/market-watch/items', { params: query })
  })

  it('uses protected maintenance and batch endpoints', async () => {
    requestMock.patch.mockReturnValue(apiResponse({ id: 9, kind: 'phone' }))
    await updateMarketWatchItem('phone', 9, { status: 'sampled', badge: '重点' })
    expect(requestMock.patch).toHaveBeenCalledWith('/market-watch/items/phone/9', { status: 'sampled', badge: '重点' })

    requestMock.post.mockReturnValue(apiResponse({ kind: 'phone', updated: 2 }))
    await bulkUpdateMarketWatch({ kind: 'phone', ids: [9, 10], saleStatus: '在售' })
    expect(requestMock.post).toHaveBeenCalledWith('/market-watch/items/bulk', {
      kind: 'phone', ids: [9, 10], saleStatus: '在售'
    })
  })

  it('supports duplicate review and explicit linking to an existing collaboration item', async () => {
    requestMock.get.mockReturnValue(apiResponse({ source: { id: 9 }, matches: [{ itemId: 41 }] }))
    await getPromotionOptions('phone', 9)
    expect(requestMock.get).toHaveBeenCalledWith('/market-watch/promotion-options', { params: { kind: 'phone', id: 9 } })

    requestMock.post.mockReturnValue(apiResponse({ itemId: 41, alreadyPromoted: false }))
    await promoteMarketWatch({ sourceKind: 'phone', sourceId: 9, mode: 'link', itemId: 41 })
    expect(requestMock.post).toHaveBeenCalledWith('/market-watch/promotions', {
      sourceKind: 'phone', sourceId: 9, mode: 'link', itemId: 41
    })
  })
})
