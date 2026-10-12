import type { CommonStatus } from './common'

export interface SupplierMetric {
  label: string
  value: string
  hint: string
  targetPath: string
}

export interface SupplierSummary {
  supplierId: number
  supplierCode: string
  supplierName: string
  shortName: string
  contactPerson: string
  contactPhone: string
  contactEmail: string
  supplyCategories: string[]
  region: string
  status: CommonStatus
  updatedAt: string
}

export interface SupplierSupplyRecord {
  recordId: number
  supplyType: 'material' | 'tooling' | 'packaging'
  itemCode: string
  itemName: string
  relatedProduct: string
  unitPrice: number
  currency: string
  lastDeliveryDate: string
  status: CommonStatus
  targetPath: string
}

export interface SupplierProjectItem {
  projectCode: string
  projectName: string
  roleSummary: string
  stage: string
  targetPath: string
}

export interface SupplierQualificationItem {
  fileName: string
  fileType: string
  validUntil: string
  statusLabel: string
}

export interface SupplierDetail extends SupplierSummary {
  cooperationLevel: string
  paymentTerm: string
  deliveryRisk: string
  supplyRecords: SupplierSupplyRecord[]
  relatedProjects: SupplierProjectItem[]
  qualificationFiles: SupplierQualificationItem[]
}

export interface SupplierRiskItem {
  title: string
  level: 'high' | 'medium' | 'low'
  owner: string
  action: string
  targetPath: string
}

export interface SupplierCenterSnapshot {
  metrics: SupplierMetric[]
  suppliers: SupplierDetail[]
  risks: SupplierRiskItem[]
}
