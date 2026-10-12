import request, { unwrapResponse } from '../request'

export interface MaterialLookupResult {
  matched: boolean
  inventoryId?: number | null
  inventoryCode?: string | null
  inventoryName?: string | null
  specification?: string | null
  unit?: string | null
  supplierName?: string | null
  unitCost?: number | null
  currencyCode?: string | null
  message?: string | null
}

export async function lookupMaterialByCode(inventoryCode: string): Promise<MaterialLookupResult> {
  return unwrapResponse<MaterialLookupResult>(await request.get('/inventories/material-lookup', {
    params: { inventoryCode }
  }))
}
