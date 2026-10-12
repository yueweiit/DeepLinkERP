import request, { unwrapPage, unwrapResponse, type PageResponse } from '../request'
import type { MarketWatchConfig, MarketWatchItem, MarketWatchKind, MarketWatchQuery, MarketWatchSummary, PromotionCommand, PromotionOptions } from '@/types/marketWatch'

const root = '/market-watch'

export async function getMarketWatchConfig(): Promise<MarketWatchConfig> { return unwrapResponse(await request.get(`${root}/config`)) }
export async function getMarketWatchSummary(): Promise<MarketWatchSummary> { return unwrapResponse(await request.get(`${root}/summary`)) }
export async function getMarketWatchItems(query: MarketWatchQuery): Promise<PageResponse<MarketWatchItem>> { return unwrapPage(await request.get(`${root}/items`, { params: query })) }
export async function getMarketWatchItem(kind: MarketWatchKind, id: number): Promise<MarketWatchItem> { return unwrapResponse(await request.get(`${root}/items/${kind}/${id}`)) }
export async function updateMarketWatchItem(kind: MarketWatchKind, id: number, data: { status?: string; badge?: string; saleStatus?: string }): Promise<MarketWatchItem> { return unwrapResponse(await request.patch(`${root}/items/${kind}/${id}`, data)) }
export async function bulkUpdateMarketWatch(data: { kind: MarketWatchKind; ids: number[]; status?: string; badge?: string; saleStatus?: string }): Promise<{ kind: MarketWatchKind; updated: number }> { return unwrapResponse(await request.post(`${root}/items/bulk`, data)) }
export async function getPromotionOptions(kind: MarketWatchKind, id: number): Promise<PromotionOptions> { return unwrapResponse(await request.get(`${root}/promotion-options`, { params: { kind, id } })) }
export async function promoteMarketWatch(data: PromotionCommand): Promise<{ itemId: number; alreadyPromoted: boolean }> { return unwrapResponse(await request.post(`${root}/promotions`, data)) }

export async function exportMarketWatch(query: MarketWatchQuery) {
  const response = await request.get(`${root}/export.csv`, { params: query, responseType: 'blob' })
  const url = URL.createObjectURL(response.data)
  const link = document.createElement('a')
  link.href = url
  link.download = `手机新品监控-${query.kind}.csv`
  link.click()
  URL.revokeObjectURL(url)
}
