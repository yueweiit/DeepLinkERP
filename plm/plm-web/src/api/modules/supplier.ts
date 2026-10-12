import type { SupplierCenterSnapshot, SupplierDetail } from '@/types/supplier'

import request, { unwrapResponse } from '../request'

export interface SupplierSupplySidePayload {
  supplierCode?: string
  supplierName: string
  shortName: string
  contactPerson: string
  contactPhone: string
  contactEmail: string
  region: string
  supplyCategories: string[]
  paymentTerm: string
  cooperationLevel: string
  deliveryRisk: string
  status: 'draft' | 'active' | 'inactive'
}

export async function getSupplierCenterSnapshot(): Promise<SupplierCenterSnapshot> {
  return unwrapResponse<SupplierCenterSnapshot>(await request.get('/inventories/suppliers/snapshot'))
}

export async function createInventorySupplier(payload: SupplierSupplySidePayload): Promise<SupplierDetail> {
  return unwrapResponse<SupplierDetail>(await request.post('/inventories/suppliers', payload))
}

export async function updateInventorySupplier(
  supplierCode: string,
  payload: SupplierSupplySidePayload
): Promise<SupplierDetail> {
  return unwrapResponse<SupplierDetail>(
    await request.put(`/inventories/suppliers/${encodeURIComponent(supplierCode)}`, payload)
  )
}
