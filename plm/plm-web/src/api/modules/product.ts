import type { ProductDetail, ProductFormPayload, ProductSummary } from '@/types/product'
import request, { unwrapPage, unwrapResponse, type PageResponse } from '../request'
import { notConnected } from '../notConnected'



export interface ProductCreatePayload {
  customerId?: number | null
  parentProductId?: number | null
  productName: string
  productType: 'product_line' | 'model_variant'
  seriesName?: string
  model?: string
  color?: string
  productSpecificCode?: string
  phoneModelCode?: string
  colorCode?: string
  finishedProductCode?: string
  importShortCode?: string
  material?: string
  packageType?: string
  surfaceProcess?: string
  coreProcess?: string
  composition?: string
  ownerUserId?: number | null
  versionNo: string
  createdBy: string
  remark?: string
}

export interface ProductQuery {
  keyword?: string
  status?: string
  productType?: 'product_line' | 'model_variant' | 'sku'
  parentProductId?: number
  page?: number
  size?: number
}

export interface ProductCreateResult {
  productId: number
  productCode: string
  versionNo: string
  status: ProductSummary['status']
}

interface ProductUpdatePayload {
  updatedBy: string
  productName?: string
  productSpecificCode?: string | null
  phoneModelCode?: string | null
  colorCode?: string | null
  finishedProductCode?: string | null
  importShortCode?: string | null
  seriesName?: string
  model?: string
  color?: string
  material?: string
  packageType?: string
  surfaceProcess?: string
  coreProcess?: string
  composition?: string
  expectedDeliveryDate?: string | null
  expectedArrivalAt?: string | null
  actualArrivalAt?: string | null
  networkType?: string | null
  holeType?: string | null
  mobileFunction?: string | null
  tipo?: string | null
  priority?: string | null
  manufacturingLocation?: string | null
  moldMarking?: string | null
  referenceUrl?: string | null
  requirementType?: string | null
  customerRequirement?: string | null
  remark?: string
}

export interface ProductProductionColor {
  codeItemId?: number | null
  colorCode?: string | null
  colorName: string
  confirmedAt?: string | null
}

function toCreatePayload(payload: ProductCreatePayload | Partial<ProductFormPayload>): ProductCreatePayload {
  const productType = payload.productType === 'model_variant' ? 'model_variant' : 'product_line'
  const explicitPayload = payload as ProductCreatePayload
  const formPayload = payload as Partial<ProductFormPayload>
  return {
    customerId: explicitPayload.customerId ?? null,
    parentProductId: productType === 'model_variant' ? payload.parentProductId ?? null : null,
    productName: payload.productName?.trim() || '',
    productType,
    seriesName: productType === 'model_variant' ? undefined : payload.seriesName?.trim() || '',
    model: productType === 'model_variant' ? formPayload.model?.trim() || '' : formPayload.model?.trim() || '--',
    color: productType === 'model_variant' ? undefined : formPayload.color?.trim() || '--',
    productSpecificCode: formPayload.productSpecificCode?.trim().toUpperCase() || undefined,
    phoneModelCode: formPayload.phoneModelCode?.trim().toUpperCase() || undefined,
    colorCode: formPayload.colorCode?.trim().toUpperCase() || undefined,
    finishedProductCode: formPayload.finishedProductCode?.trim().toUpperCase() || undefined,
    importShortCode: formPayload.importShortCode?.trim().toUpperCase() || undefined,
    material: formPayload.material?.trim() || '',
    packageType: formPayload.packageType?.trim() || '',
    surfaceProcess: formPayload.surfaceProcess?.trim() || '',
    coreProcess: formPayload.coreProcess?.trim() || '',
    composition: formPayload.composition?.trim() || '',
    ownerUserId: explicitPayload.ownerUserId ?? null,
    versionNo: payload.versionNo?.trim() || 'A',
    createdBy: explicitPayload.createdBy?.trim() || formPayload.ownerUserName?.trim() || 'system',
    remark: explicitPayload.remark?.trim() || ''
  }
}

function cleanOptional(value?: string | null) {
  const text = value?.trim()
  return text ? text : undefined
}

function cleanOptionalCode(value?: string | null) {
  const text = value?.trim().toUpperCase()
  return text ? text : undefined
}

function toUpdatePayload(payload: Partial<ProductFormPayload>): ProductUpdatePayload {
  return {
    updatedBy: cleanOptional(payload.ownerUserName) || 'system',
    productName: cleanOptional(payload.productName),
    productSpecificCode: payload.productSpecificCode === null ? null : cleanOptionalCode(payload.productSpecificCode),
    phoneModelCode: payload.phoneModelCode === null ? null : cleanOptionalCode(payload.phoneModelCode),
    colorCode: payload.colorCode === null ? null : cleanOptionalCode(payload.colorCode),
    finishedProductCode: payload.finishedProductCode === null ? null : cleanOptionalCode(payload.finishedProductCode),
    importShortCode: payload.importShortCode === null ? null : cleanOptionalCode(payload.importShortCode),
    seriesName: cleanOptional(payload.seriesName),
    model: cleanOptional(payload.model),
    color: cleanOptional(payload.color),
    material: cleanOptional(payload.material),
    packageType: cleanOptional(payload.packageType),
    surfaceProcess: cleanOptional(payload.surfaceProcess),
    coreProcess: cleanOptional(payload.coreProcess),
    composition: payload.composition ?? undefined,
    expectedDeliveryDate: payload.expectedReleaseDate || null,
    expectedArrivalAt: payload.expectedArrivalAt || null,
    actualArrivalAt: payload.actualArrivalAt || null,
    networkType: payload.networkType ?? undefined,
    holeType: payload.holeType ?? undefined,
    mobileFunction: payload.mobileFunction ?? undefined,
    tipo: payload.tipo ?? undefined,
    priority: payload.priority ?? undefined,
    manufacturingLocation: payload.manufacturingLocation ?? undefined,
    moldMarking: payload.moldMarking ?? undefined,
    referenceUrl: payload.referenceUrl ?? undefined,
    requirementType: payload.requirementType ?? undefined,
    customerRequirement: payload.customerRequirement ?? undefined,
    remark: payload.coreProcess || payload.composition || ''
  }
}

export async function getProductPage(params: ProductQuery = {}): Promise<PageResponse<ProductSummary>> {
  const response = await request.get('/products', { params })
  return unwrapPage<ProductSummary>(response)
}

export async function getProductList(params: ProductQuery = {}): Promise<ProductSummary[]> {
  return (await getProductPage(params)).content
}

export async function getProductProductionColors(productId: number): Promise<ProductProductionColor[]> {
  const response = await request.get(`/products/${productId}/production-colors`)
  return unwrapResponse<ProductProductionColor[]>(response)
}

interface BackendProductVO extends ProductSummary {
  customerId?: number | null
  ownerUserId?: number | null
  productCodePrefix?: string | null
  moldCodePrefix?: string | null
  moldCodeDetails?: ProductDetail['basicInfo']['moldCodeDetails']
  packageType?: string | null
  surfaceProcess?: string | null
  coreProcess?: string | null
  composition?: string | null
  expectedDeliveryDate?: string | null
  networkType?: string | null
  holeType?: string | null
  mobileFunction?: string | null
  tipo?: string | null
  priority?: string | null
  manufacturingLocation?: string | null
  moldMarking?: string | null
  referenceUrl?: string | null
  requirementType?: string | null
  customerRequirement?: string | null
  createdAt?: string | null
  createdBy?: string | null
  updatedAt?: string | null
  updatedBy?: string | null
  remark?: string | null
}

export async function getProductDetail(productId: number): Promise<ProductDetail> {
  const response = await request.get(`/products/${productId}`)
  const product = unwrapResponse<BackendProductVO>(response)
  return toProductDetail(product)
}

function toProductDetail(product: BackendProductVO): ProductDetail {
  const productTypeLabel = product.productType === 'model_variant' ? '新型号线' : product.productType === 'sku' ? 'SKU' : '新产品线'
  return {
    productId: product.productId,
    basicInfo: {
      productCode: product.productCode || '',
      productName: product.productName || '',
      moldCodes: product.moldCodes || null,
      moldCodeDetails: product.moldCodeDetails || [],
      productSpecificCode: product.productSpecificCode || null,
      phoneModelCode: product.phoneModelCode || null,
      colorCode: product.colorCode || null,
      finishedProductCode: product.finishedProductCode || null,
      importShortCode: product.importShortCode || null,
      seriesName: product.seriesName || '',
      productType: product.productType,
      productFlowMode: product.productType === 'model_variant' ? 'new_model_variant' : 'new_product_line',
      ownerUserName: product.ownerUserName || product.updatedBy || product.createdBy || 'system',
      status: product.status,
      versionNo: product.versionNo || 'A',
      material: product.material || '',
      packageType: product.packageType || '',
      surfaceProcess: product.surfaceProcess || '',
      coreProcess: product.coreProcess || '',
      composition: product.composition || '',
      moldTransferAt: product.moldTransferAt || null,
      expectedArrivalAt: product.expectedArrivalAt || null,
      actualArrivalAt: product.actualArrivalAt || null,
      networkType: product.networkType || null,
      holeType: product.holeType || null,
      mobileFunction: product.mobileFunction || null,
      tipo: product.tipo || null,
      priority: product.priority || null,
      manufacturingLocation: product.manufacturingLocation || null,
      moldMarking: product.moldMarking || null,
      referenceUrl: product.referenceUrl || null,
      requirementType: product.requirementType || null,
      customerRequirement: product.customerRequirement || null,
      customerName: product.customerName || '',
      currentStage: product.currentStage || '',
      currentStepNo: product.currentStepNo || 1,
      expectedReleaseDate: product.expectedDeliveryDate || null,
      model: product.model || '',
      color: product.color || '',
      estimatedCost: product.estimatedCost || 0,
      estimatedCostCurrency: product.estimatedCostCurrency || 'CNY',
      actualCost: product.actualCost || 0,
      rdCost: product.rdCost || 0,
      productCost: product.productCost || 0,
      totalCost: product.totalCost || product.estimatedCost || 0,
      productTypeLabel,
      parentProductName: null,
      inheritedSummary: product.remark || '',
      moldAction: product.moldAction || null,
      nextAction: product.nextAction || null,
      gateSummary: product.gateSummary || null
    },
    statusTimeline: [],
    approvalTimeline: [],
    bomItems: [],
    attachments: [],
    qualityRecords: [],
    operationLogs: [],
    versionHistory: [],
    costBreakdown: [],
    testItems: []
  }
}

export async function createProduct(payload: ProductCreatePayload | Partial<ProductFormPayload>): Promise<ProductCreateResult> {
  const response = await request.post('/products', toCreatePayload(payload))
  return unwrapResponse<ProductCreateResult>(response)
}

export async function updateProduct(productId: number, payload: Partial<ProductFormPayload>): Promise<ProductDetail> {
  const response = await request.put(`/products/${productId}`, toUpdatePayload(payload))
  return toProductDetail(unwrapResponse<BackendProductVO>(response))
}

export async function updateProductBasicInfo(productId: number, payload: Partial<ProductFormPayload>): Promise<ProductDetail> {
  const response = await request.patch(`/products/${productId}/basic-info`, toUpdatePayload(payload))
  return toProductDetail(unwrapResponse<BackendProductVO>(response))
}

export function publishProduct(_productId: number): Promise<ProductDetail> {
  return notConnected('产品发布')
}

export function freezeProduct(_productId: number): Promise<ProductDetail> {
  return notConnected('产品冻结')
}



