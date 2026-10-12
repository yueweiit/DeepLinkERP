import { beforeEach, describe, expect, it, vi } from 'vitest'

const requestMock = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  put: vi.fn()
}))

vi.mock('../../request', () => ({
  default: requestMock,
  unwrapResponse: <T>(response: { data: { data: T } }) => response.data.data
}))

import { createInventorySupplier, getSupplierCenterSnapshot, updateInventorySupplier } from '../supplier'

function apiResponse<T>(data: T) {
  return Promise.resolve({ data: { code: 0, message: 'success', data } })
}

describe('supplier API', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('uses Inventory supplier snapshot endpoint instead of frontend mock data', async () => {
    const snapshot = { metrics: [], suppliers: [], risks: [] }
    requestMock.get.mockReturnValue(apiResponse(snapshot))

    await expect(getSupplierCenterSnapshot()).resolves.toEqual(snapshot)
    expect(requestMock.get).toHaveBeenCalledWith('/inventories/suppliers/snapshot')
  })

  it('creates supplier through Inventory supply-side endpoint', async () => {
    const supplier = { supplierCode: 'SUP-A', supplierName: '东莞塑胶 A' }
    const payload = {
      supplierName: '东莞塑胶 A',
      shortName: '塑胶 A',
      contactPerson: '李采',
      contactPhone: '13800000000',
      contactEmail: '',
      region: '东莞',
      supplyCategories: ['原材料'],
      paymentTerm: '月结 30 天',
      cooperationLevel: '核心',
      deliveryRisk: 'low',
      status: 'active' as const
    }
    requestMock.post.mockReturnValue(apiResponse(supplier))

    await expect(createInventorySupplier(payload)).resolves.toEqual(supplier)
    expect(requestMock.post).toHaveBeenCalledWith('/inventories/suppliers', payload)
  })

  it('updates supplier through Inventory supply-side endpoint', async () => {
    const supplier = { supplierCode: 'SUP-A', supplierName: '东莞塑胶 A' }
    const payload = {
      supplierCode: 'SUP-A',
      supplierName: '东莞塑胶 A',
      shortName: '塑胶 A',
      contactPerson: '李采',
      contactPhone: '13800000000',
      contactEmail: '',
      region: '东莞',
      supplyCategories: ['原材料'],
      paymentTerm: '月结 30 天',
      cooperationLevel: '核心',
      deliveryRisk: 'low',
      status: 'active' as const
    }
    requestMock.put.mockReturnValue(apiResponse(supplier))

    await expect(updateInventorySupplier('SUP-A', payload)).resolves.toEqual(supplier)
    expect(requestMock.put).toHaveBeenCalledWith('/inventories/suppliers/SUP-A', payload)
  })
})
