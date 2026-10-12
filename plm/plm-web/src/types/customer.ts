import type { CommonStatus } from './common'

export interface CustomerSummary {
  customerId: number
  customerCode: string
  customerName: string
  customerShortName: string
  countryCode: string
  contactName: string
  contactPhone: string
  contactEmail: string
  status: CommonStatus
  updatedAt: string
}

export interface CustomerDetail extends CustomerSummary {
  address: string
  sourceType: string
  ownerUserName: string
  relatedOrders: Array<{
    orderCode: string
    orderTitle: string
    status: CommonStatus
    productName: string
  }>
  operationLogs: Array<{
    time: string
    operator: string
    action: string
    level: 'normal' | 'danger'
  }>
}
