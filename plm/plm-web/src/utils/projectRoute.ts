import type { RouteLocationRaw } from 'vue-router'

const archivedProductQuery = {
  tab: 'archived',
  archiveView: 'product'
}

const archivedSkuQuery = {
  tab: 'archived',
  archiveView: 'sku'
}

export function toArchivedProductRoute(productId?: number | string): RouteLocationRaw {
  return {
    path: '/projects',
    query: {
      ...archivedProductQuery,
      ...(productId ? { productId: String(productId) } : {})
    }
  }
}

export function toArchivedSkuRoute(skuId?: number | string): RouteLocationRaw {
  return {
    path: '/projects',
    query: {
      ...archivedSkuQuery,
      ...(skuId ? { skuId: String(skuId) } : {})
    }
  }
}

export function toInProgressProjectRoute(extra: Record<string, string> = {}): RouteLocationRaw {
  return {
    path: '/projects',
    query: {
      tab: 'in_progress',
      ...extra
    }
  }
}

export function normalizeLegacyProductTarget(targetPath: string): RouteLocationRaw {
  if (!targetPath) return targetPath

  if (targetPath === '/sku-view') return toArchivedSkuRoute()
  if (targetPath === '/products') return toArchivedProductRoute()
  if (targetPath === '/products/create') return toInProgressProjectRoute()

  const editMatched = targetPath.match(/^\/products\/([^/]+)\/edit$/)
  if (editMatched) return toArchivedProductRoute(editMatched[1])

  const detailMatched = targetPath.match(/^\/products\/([^/?#]+)$/)
  if (detailMatched) return toArchivedProductRoute(detailMatched[1])

  if (targetPath.startsWith('/products?')) {
    const params = new URLSearchParams(targetPath.split('?')[1] || '')
    const lifecycle = params.get('lifecycle')
    const reportStatus = params.get('report_status')
    const status = params.get('status')

    if (status === 'developing' || lifecycle || reportStatus) {
      return toInProgressProjectRoute({
        ...(lifecycle ? { lifecycle } : {}),
        ...(reportStatus ? { report_status: reportStatus } : {})
      })
    }

    return {
      path: '/projects',
      query: {
        ...archivedProductQuery,
        ...(params.get('frozen') ? { filter: params.get('frozen') || '' } : {}),
        ...(params.get('risk') ? { risk: params.get('risk') || '' } : {})
      }
    }
  }

  return targetPath
}
