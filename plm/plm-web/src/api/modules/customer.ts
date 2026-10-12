import type { CustomerDetail, CustomerSummary } from '@/types/customer'

import { notConnected } from '../notConnected'

export function getCustomerList(): Promise<CustomerSummary[]> {
  return notConnected('客户列表')
}

export function getCustomerDetail(_customerId: number): Promise<CustomerDetail> {
  return notConnected('客户详情')
}

export function createCustomer(_payload: Partial<CustomerDetail>): Promise<CustomerDetail> {
  return notConnected('客户创建')
}

export function updateCustomer(_customerId: number, _payload: Partial<CustomerDetail>): Promise<CustomerDetail> {
  return notConnected('客户编辑')
}
