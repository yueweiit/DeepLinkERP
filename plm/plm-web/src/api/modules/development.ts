import request, { unwrapPage, unwrapResponse, type PageResponse } from '../request'

export type FinanceEntity = 'budget' | 'expense'
export type FinanceValue = string | number | null
export interface FinanceRow { budgetId?: number; expenseId?: number; budgetKind?: 'platform' | 'mold'; budgetName?: string; description?: string; currencyCode: string; versionNo?: number; sourceSystem?: string; state?: string; [key: string]: FinanceValue | undefined }
export interface FinanceQuery { page: number; size: number; keyword?: string; kind?: 'platform' | 'mold'; state?: string; productLineId?: number; productId?: number; itemId?: number; currency?: string; budgetId?: number }
export interface FinanceChange { field: string; before: FinanceValue; after: FinanceValue }
export interface FinancePatch { id: number; changes: FinanceChange[]; reason?: string }
export interface FinanceResult { id: number; status: 'saved' | 'invalid' | 'conflict' | 'forbidden'; message: string; conflicts: { field: string; before: FinanceValue; current: FinanceValue; attempted: FinanceValue }[]; row: FinanceRow | null }
export interface FinanceOptions { productLines: { productId: number; productName: string; productCode: string }[]; items: { itemId: number; productLineId: number | null; styleName: string; compatibleModels: string }[]; molds: { moldSetId: number; itemId: number; setNo: number; setName: string }[]; budgets: FinanceRow[]; writable: boolean; confirmable: boolean; exportable: boolean }
export interface FinanceHistory { historyId: number; fieldName: string; beforeJson: string | null; afterJson: string | null; reason: string | null; actorName: string; changedAt: string; versionNo: number | null }
export interface BudgetImportRow { rowNo: number; sheetName: string; name: string; kind: 'platform' | 'mold'; currency: string; budgetId: number | null; productLineId: number | null; itemId: number | null; moldSetId: number | null; parentBudgetId: number | null; raw: Record<string, string>; formulas: Record<string, string>; values: Record<string, FinanceValue>; before: Record<string, FinanceValue>; issues: string[]; calculatedTotal: number | null; breakEvenQuantity: number | null; skip?: boolean; reason?: string }
export interface ErpImportRow { rowNo: number; voucherId: string; lineId: string; description: string; currency: string; postedAmount: number; reversalOf: string | null; issues: string[]; skip?: boolean; productLineId?: number | null; itemId?: number | null; moldSetId?: number | null; budgetId?: number | null; mappingReason?: string }
export interface FinancePreview<T> { token: string; rows: T[]; total: number; note: string; fileHash: string }
const root = (entity: FinanceEntity) => entity === 'budget' ? '/development-budgets' : '/development-expenses'
export async function getFinanceRows(entity: FinanceEntity, query: FinanceQuery): Promise<PageResponse<FinanceRow>> { return unwrapPage(await request.get(root(entity), { params: query })) }
export async function getFinanceOptions(): Promise<FinanceOptions> { return unwrapResponse(await request.get('/development-budgets/options')) }
export async function getFinanceSummary(entity: FinanceEntity, query: FinanceQuery): Promise<{ currencyGroups: Record<string, FinanceValue>[]; rule: string }> { return unwrapResponse(await request.get(`${root(entity)}/summary`, { params: query })) }
export async function createFinanceRow(entity: FinanceEntity, payload: Record<string, unknown>): Promise<FinanceRow> { return unwrapResponse(await request.post(root(entity), payload)) }
export async function saveFinanceRows(entity: FinanceEntity, rows: FinancePatch[]): Promise<FinanceResult[]> { return unwrapResponse(await request.post(`${root(entity)}/batch-save`, { rows })) }
export async function getFinanceHistory(entity: FinanceEntity, id: number, page = 1): Promise<PageResponse<FinanceHistory>> { return unwrapPage(await request.get(`${root(entity)}/${id}/history`, { params: { page, size: 20 } })) }
export async function previewBudgetFile(file: File): Promise<FinancePreview<BudgetImportRow>> { const form = new FormData(); form.append('file', file); return unwrapResponse(await request.post('/development-budgets/import-preview', form)) }
export async function commitBudgetFile(token: string, rows: BudgetImportRow[]) { return unwrapResponse<{ saved: number; skipped: number; duplicate: boolean }>(await request.post('/development-budgets/import-commit', { token, rows })) }
export async function previewErpExpenses(rows: unknown[]): Promise<FinancePreview<ErpImportRow>> { return unwrapResponse(await request.post('/development-expenses/erp-preview', { rows })) }
export async function refreshErpExpenses(): Promise<(FinancePreview<ErpImportRow> & {status:'preview_ready'}) | {status:'not_configured';message:string}> { return unwrapResponse(await request.post('/development-expenses/erp-refresh')) }
export async function commitErpExpenses(token: string, rows: ErpImportRow[]) { return unwrapResponse<{ saved: number; skipped: number; duplicate: boolean }>(await request.post('/development-expenses/erp-commit', { token, rows })) }
export async function exportBudgetFile(query: FinanceQuery): Promise<Blob> { const response = await request.get('/development-budgets/export', { params: query, responseType: 'blob' }); return response.data }
