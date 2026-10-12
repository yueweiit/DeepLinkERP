import type {
  BomCenterSnapshot,
  BomHistoryMergeResult,
  BomImportPreview,
  BomLedgerRow,
  BomProductRow,
  BomRoute,
  BomSkuRow,
  BomSummary,
  BomWorkbench,
  ProductionRouteSelection
} from '@/types/bom'
import { notConnected } from '../notConnected'
import request, { unwrapPage, unwrapResponse, type PageResponse } from '../request'

export interface BomLedgerPageQuery { page: number; size: number; keyword?: string }
export async function getBomProductPage(params: BomLedgerPageQuery): Promise<PageResponse<BomProductRow>> {
  return unwrapPage(await request.get('/bom-ledger/products', { params }))
}
export async function getProductBomPage(query: BomLedgerPageQuery & { productId: number }): Promise<PageResponse<BomLedgerRow>> {
  const { productId, ...params } = query
  return unwrapPage(await request.get(`/bom-ledger/products/${productId}/boms`, { params }))
}

/* ========== BOM 中心 ========== */

export function getBomCenterSnapshot(): Promise<BomCenterSnapshot> {
  return notConnected('BOM 中心快照')
}

/* ========== 项目级 BOM（文档 7.4） ========== */

export type ProductBomStatus = 'draft' | 'reviewing' | 'released' | 'archived' | 'frozen'

export interface ProductBomItemVO {
  productBomItemId: number
  productBomId: number
  inventoryId?: number | null
  itemCode?: string | null
  itemName: string
  specification?: string | null
  lineNo: number
  quantity: number
  unit: string
  lossRate?: number | null
  unitCost?: number | null
  lineCost?: number | null
  supplierCode?: string | null
  supplierName?: string | null
  currencyCode?: string | null
  materialSource?: string | null
  unmatchedFlag?: number | null
  lookupMessage?: string | null
  substituteFlag?: number | null
  remark?: string | null
  status: ProductBomStatus
}

export interface ProductBomVO {
  productBomId: number
  productId: number
  bomCode: string
  bomName: string
  bomType: string
  bomScope?: 'candidate' | 'formal' | 'test'
  versionNo: string
  status: ProductBomStatus
  productBomRouteId?: number | null
  processId?: number | null
  routeCode?: string | null
  routeName?: string | null
  candidateStatus?: string | null
  currentFormal?: boolean | null
  materialCount?: number | null
  totalCost?: number | null
  frozenFlag?: number | null
  frozenAt?: string | null
  frozenBy?: string | null
  remark?: string | null
  items: ProductBomItemVO[]
}

export interface ProductBomSavePayload {
  bomName: string
  bomType: string
  versionNo: string
  remark?: string
}

export interface ProductBomCreatePayload extends ProductBomSavePayload {
  processId: number
}

export interface ProductBomItemSavePayload {
  inventoryId?: number | null
  itemCode?: string
  itemName: string
  specification?: string
  lineNo: number
  quantity: number
  unit: string
  lossRate?: number | null
  unitCost?: number | null
  lineCost?: number | null
  supplierCode?: string | null
  supplierName?: string | null
  currencyCode?: string | null
  materialSource?: string | null
  unmatchedFlag?: number | null
  lookupMessage?: string | null
  substituteFlag?: number | null
  remark?: string
}

export interface BomRouteSavePayload {
  productBomRouteId?: number
  sourceProductBomRouteId?: number | null
  sharedBomGroupCode?: string
  routeVariantNo?: string
  variantName?: string
  processId: number
  routeCode: string
  routeName: string
  colors: string[]
  colorItems?: Array<{ codeItemId: number; codeValue: string; codeName: string }>
  items: ProductBomItemSavePayload[]
  processCost?: number
  packageCost?: number
  laborCost?: number
  toolingCost?: number
  otherCost?: number
}

export interface BomSaveOptions { moneyEditable: boolean }

function toBomItemSavePayload(item: BomRoute['items'][number], options: BomSaveOptions): ProductBomItemSavePayload {
  return {
    inventoryId: item.inventoryId ?? null,
    itemCode: item.itemCode || undefined,
    itemName: item.itemName,
    specification: item.specification || undefined,
    lineNo: item.lineNo,
    quantity: item.quantity,
    unit: item.unit,
    lossRate: item.lossRate ?? null,
    ...(options.moneyEditable ? { unitCost: item.unitCost ?? null, lineCost: item.lineCost ?? null, currencyCode: item.currencyCode ?? null } : {}),
    supplierCode: item.supplierCode ?? null,
    supplierName: item.supplierName ?? null,
    materialSource: item.materialSource ?? null,
    unmatchedFlag: item.unmatchedFlag ?? null,
    lookupMessage: item.lookupMessage ?? null,
    substituteFlag: item.substituteFlag ?? null,
    remark: item.remark || undefined
  }
}

export function toBomRouteSavePayload(route: BomRoute, options: BomSaveOptions = { moneyEditable: true }): BomRouteSavePayload {
  const payload: BomRouteSavePayload = {
    productBomRouteId: route.productBomRouteId,
    sourceProductBomRouteId: route.sourceProductBomRouteId ?? null,
    sharedBomGroupCode: route.sharedBomGroupCode,
    routeVariantNo: route.routeVariantNo,
    variantName: route.variantName,
    processId: route.processId,
    routeCode: route.routeCode,
    routeName: route.routeName,
    colors: route.colors,
    colorItems: route.colorItems?.map(color => ({
      codeItemId: color.codeItemId,
      codeValue: color.codeValue,
      codeName: color.codeName
    })),
    items: route.items.map(item => toBomItemSavePayload(item, options))
  }
  if (options.moneyEditable) {
    if (route.processCost !== undefined) payload.processCost = route.processCost
    if (route.packageCost !== undefined) payload.packageCost = route.packageCost
    if (route.laborCost !== undefined) payload.laborCost = route.laborCost
    if (route.toolingCost !== undefined) payload.toolingCost = route.toolingCost
    if (route.otherCost !== undefined) payload.otherCost = route.otherCost
  }
  return payload
}

export function toBomRoutesSavePayload(routes: BomRoute[], options: BomSaveOptions = { moneyEditable: true }): BomRouteSavePayload[] {
  return routes.map(route => toBomRouteSavePayload(route, options))
}

/** GET /api/v1/projects/{projectId}/boms */
export async function getProjectBoms(projectId: number): Promise<ProductBomVO[]> {
  const response = await request.get(`/projects/${projectId}/boms`)
  return unwrapResponse<ProductBomVO[]>(response)
}

/** GET /api/v1/boms/{bomId} */
export async function getBomDetail(bomId: number): Promise<ProductBomVO> {
  const response = await request.get(`/boms/${bomId}`)
  return unwrapResponse<ProductBomVO>(response)
}

/** POST /api/v1/projects/{projectId}/boms */
export async function createProjectBom(projectId: number, payload: ProductBomCreatePayload) {
  const response = await request.post(`/projects/${projectId}/boms`, payload)
  return unwrapResponse<ProductBomVO>(response)
}

/** PUT /api/v1/boms/{bomId} */
export async function updateBom(bomId: number, payload: ProductBomSavePayload) {
  const response = await request.put(`/boms/${bomId}`, payload)
  return unwrapResponse<ProductBomVO>(response)
}

/** POST /api/v1/boms/{bomId}/items */
export async function addBomItem(bomId: number, payload: ProductBomItemSavePayload) {
  const response = await request.post(`/boms/${bomId}/items`, payload)
  return unwrapResponse<ProductBomVO>(response)
}

/** PUT /api/v1/boms/{bomId}/items/{itemId} */
export async function updateBomItem(bomId: number, itemId: number, payload: ProductBomItemSavePayload) {
  const response = await request.put(`/boms/${bomId}/items/${itemId}`, payload)
  return unwrapResponse<ProductBomVO>(response)
}

/** DELETE /api/v1/boms/{bomId}/items/{itemId} */
export async function deleteBomItem(bomId: number, itemId: number) {
  const response = await request.delete(`/boms/${bomId}/items/${itemId}`)
  return unwrapResponse<ProductBomVO>(response)
}

/** DELETE /api/v1/boms/{bomId} */
export async function deleteBomVersion(bomId: number): Promise<void> {
  await request.delete(`/boms/${bomId}`)
}

/** POST /api/v1/boms/{bomId}/freeze */
export async function freezeBom(bomId: number) {
  const response = await request.post(`/boms/${bomId}/freeze`)
  return unwrapResponse<ProductBomVO>(response)
}

/** POST /api/v1/boms/{bomId}/confirm-current-version */
export async function confirmCurrentBomVersion(bomId: number) {
  return unwrapResponse<ProductBomVO>(await request.post(`/boms/${bomId}/confirm-current-version`))
}

/** POST /api/v1/boms/{bomId}/cancel-confirmation */
export async function cancelCurrentBomConfirmation(bomId: number) {
  return unwrapResponse<ProductBomVO>(await request.post(`/boms/${bomId}/cancel-confirmation`))
}

export interface BomCopyVersionPayload {
  versionNo: string
  selectedColors: string[]
}

export interface BomInheritancePayload {
  sourceBomId: number
  selectedColors: string[]
}

export interface TestBomPayload {
  versionNo: string
  items: ProductBomItemSavePayload[]
}

export async function getBomLedger(): Promise<BomLedgerRow[]> {
  return unwrapResponse<BomLedgerRow[]>(await request.get('/bom-ledger'))
}

export async function getBomWorkbench(bomId: number): Promise<BomWorkbench> {
  return unwrapResponse<BomWorkbench>(await request.get(`/boms/${bomId}/workbench`))
}

export async function getBomSkus(bomId: number): Promise<BomSkuRow[]> {
  return unwrapResponse<BomSkuRow[]>(await request.get(`/boms/${bomId}/skus`))
}

export async function getProcessRouteSkus(routeId: number): Promise<BomSkuRow[]> {
  return unwrapResponse<BomSkuRow[]>(await request.get(`/process-routes/${routeId}/skus`))
}

export async function getProductBomSummary(productId: number): Promise<BomSummary> {
  return unwrapResponse<BomSummary>(await request.get(`/products/${productId}/bom-summary`))
}

export async function saveBomRoutes(bomId: number, routes: BomRoute[], options: BomSaveOptions = { moneyEditable: true }): Promise<void> {
  await request.put(`/boms/${bomId}/routes`, toBomRoutesSavePayload(routes, options))
}

export async function recalculateBomCosts(bomId: number, routes: BomRoute[]) {
  return unwrapResponse(await request.post(`/boms/${bomId}/costs/recalculate`, toBomRoutesSavePayload(routes)))
}

export async function submitBomReview(bomId: number) {
  return unwrapResponse<ProductBomVO>(await request.post(`/boms/${bomId}/submit-review`))
}

export async function publishBom(bomId: number) {
  return unwrapResponse(await request.post(`/boms/${bomId}/publish`))
}

export async function copyBomVersion(bomId: number, payload: BomCopyVersionPayload) {
  return unwrapResponse<ProductBomVO>(await request.post(`/boms/${bomId}/copy-version`, payload))
}

export async function inheritBom(productId: number, payload: BomInheritancePayload) {
  return unwrapResponse(await request.post(`/products/${productId}/boms/inherit`, payload))
}

export async function saveTestBom(productId: number, payload: TestBomPayload) {
  return unwrapResponse(await request.post(`/products/${productId}/test-bom`, payload))
}

export async function confirmTestBom(productId: number) {
  return unwrapResponse(await request.post(`/products/${productId}/test-bom/confirm`))
}

export async function previewBomImport(productId: number, bomId: number, file: File): Promise<BomImportPreview> {
  const form = new FormData()
  form.append('bomId', String(bomId))
  form.append('file', file)
  return unwrapResponse<BomImportPreview>(await request.post(`/products/${productId}/boms/import/preview`, form))
}

export async function commitBomImport(importToken: string) {
  return unwrapResponse(await request.post(`/boms/import/${importToken}/commit`))
}

export async function downloadBomImportTemplate(): Promise<Blob> {
  const response = await request.get('/boms/import/template', { responseType: 'blob' })
  return response.data
}

export async function downloadBomImportErrors(importToken: string): Promise<Blob> {
  const response = await request.get(`/boms/import/${importToken}/errors`, { responseType: 'blob' })
  return response.data
}

export interface ProductionConfirmation {
  productId: number
  selectedOperationCount: number
  selectedColorCount: number
  createdSkuCount: number
  operationProcessIds: number[]
  routeSelections: ProductionRouteSelection[]
  colors: string[]
}

export interface ProductionRouteConfirmPayload {
  routes: Array<{
    processId: number
    productBomId: number
    productBomRouteId: number
    operationProcessIds: number[]
    applicableColors: Array<{
      codeItemId: number
      colorCode: string
      colorName: string
    }>
  }>
  remark?: string
}

export async function previewHistoricalBomImport(file: File): Promise<BomImportPreview> {
  const form = new FormData()
  form.append('file', file)
  return unwrapResponse<BomImportPreview>(await request.post('/boms/history/import/preview', form))
}

export async function commitHistoricalBomImport(importToken: string) {
  return unwrapResponse(await request.post(`/boms/history/import/${importToken}/commit`))
}

export async function downloadHistoricalBomTemplate(): Promise<Blob> {
  const response = await request.get('/boms/history/import/template', { responseType: 'blob' })
  return response.data
}

export async function analyzeHistoricalBomMerge(productId?: number): Promise<BomHistoryMergeResult> {
  return unwrapResponse<BomHistoryMergeResult>(await request.get('/boms/history/merge/analysis', { params: { productId } }))
}

export async function autoMergeHistoricalBoms(productId?: number): Promise<BomHistoryMergeResult> {
  return unwrapResponse<BomHistoryMergeResult>(await request.post('/boms/history/merge/auto', null, { params: { productId } }))
}

export async function getProductionConfirmation(projectId: number): Promise<ProductionConfirmation> {
  return unwrapResponse<ProductionConfirmation>(await request.get(`/projects/${projectId}/production-confirmation`))
}

export async function confirmProductionOperations(projectId: number, payload: { productBomRouteId: number; operationProcessIds: number[] }) {
  return unwrapResponse<ProductionConfirmation>(await request.post(`/projects/${projectId}/production-operations/confirm`, payload))
}

export async function confirmProductionRoutes(projectId: number, payload: ProductionRouteConfirmPayload) {
  return unwrapResponse<ProductionConfirmation>(await request.post(`/projects/${projectId}/production-routes/confirm`, payload))
}

export async function confirmProductionColors(projectId: number, payload: { colors: Array<{ codeItemId: number; colorCode: string; colorName: string; productBomId: number; productBomRouteId: number }> }) {
  return unwrapResponse<ProductionConfirmation>(await request.post(`/projects/${projectId}/production-colors/confirm`, payload))
}
