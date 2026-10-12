export type MarketWatchKind = 'phone' | 'candidate'

export interface MarketWatchSummary {
  phones: number
  candidates: number
  pending_candidates: number
  unreviewed_candidates: number
  ignored_phones: number
  by_country: Record<string, number>
}

export interface MarketWatchLink {
  sourceKind: MarketWatchKind
  sourceId: number
  itemId: number
  promotedById: number
  promotedByName: string
  promotedAt: string
}

export interface MarketWatchItem {
  [key: string]: unknown
  id: number
  kind: MarketWatchKind
  brand: string
  country?: string
  source_country?: string
  missing_country?: string
  model: string
  normalized_model: string
  image_url?: string
  price?: string
  priceAmount?: number | null
  priceCurrency?: string | null
  badge?: string
  sale_status?: string
  sampling_status: string
  source_name?: string
  source_url?: string
  reason?: string
  first_seen_at: string
  last_seen_at: string
  collaborationLink?: MarketWatchLink | null
}

export interface MarketWatchQuery {
  kind: MarketWatchKind
  page: number
  size: number
  keyword?: string
  country?: string
  brand?: string
  source?: string
  status?: string
  dateFrom?: string
  dateTo?: string
}

export interface MarketWatchConfig { enabled: boolean; writable: boolean; administrator: boolean }
export interface MarketWatchMatch { itemId: number; productLineId: number | null; styleName: string; brand: string | null; compatibleModels: string; phoneModelCode: string | null }
export interface PromotionOptions { source: MarketWatchItem; matches: MarketWatchMatch[]; link: MarketWatchLink | null }
export interface PromotionCommand {
  sourceKind: MarketWatchKind
  sourceId: number
  mode: 'create' | 'link'
  itemId?: number | null
  productLineId?: number | null
  styleName?: string
  compatibleModels?: string
  phoneModelCode?: string | null
  notes?: string
}
