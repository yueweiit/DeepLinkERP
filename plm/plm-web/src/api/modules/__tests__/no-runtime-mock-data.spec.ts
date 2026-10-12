import { describe, expect, it } from 'vitest'

import { getBomCenterSnapshot } from '@/api/modules/bom'
import { getCustomerDetail, getCustomerList } from '@/api/modules/customer'
import { getDashboardSnapshot } from '@/api/modules/dashboard'
import {
  getBomCenterRows,
  getFileSections,
  getFoundationProducts,
  getProductPresentation,
  getTestCenterSnapshot
} from '@/api/modules/foundation'

const runtimeMockBackedCalls = [
  ['dashboard snapshot', () => getDashboardSnapshot()],
  ['bom center snapshot', () => getBomCenterSnapshot()],
  ['foundation products', () => getFoundationProducts()],
  ['file sections', () => getFileSections()],
  ['test center snapshot', () => getTestCenterSnapshot()],
  ['bom center rows', () => getBomCenterRows()],
  ['product presentation', () => getProductPresentation(101)],
  ['customer list', () => getCustomerList()],
  ['customer detail', () => getCustomerDetail(101)],
] as const

describe('runtime mock data cleanup', () => {
  it.each(runtimeMockBackedCalls)('%s does not return frontend mock data at runtime', async (_name, callApi) => {
    await expect(callApi()).rejects.toThrow('整体测试阶段不展示前端假数据')
  })
})
