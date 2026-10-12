import type { FinanceChange, FinanceRow, FinanceValue } from '@/api/modules/development'
import { acknowledgeDraftChanges } from '@/utils/draftChanges'
export interface FinanceDraft { source: FinanceRow; changes: Map<string, FinanceChange>; error: string }
export const sameFinanceValue = (a: FinanceValue | undefined, b: FinanceValue | undefined) => a == null && b == null || a === b || a != null && b != null && String(a) === String(b)
export function editFinanceCell(drafts: Map<number, FinanceDraft>, id: number, row: FinanceRow, field: string, after: FinanceValue) {
  let draft = drafts.get(id)
  if (!draft) { draft = { source: { ...row }, changes: new Map(), error: '' }; drafts.set(id, draft) }
  const before = draft.changes.has(field) ? draft.changes.get(field)!.before : draft.source[field] ?? null
  if (sameFinanceValue(before, after)) draft.changes.delete(field)
  else draft.changes.set(field, { field, before, after })
  draft.error = ''
  if (!draft.changes.size) drafts.delete(id)
}
/** A late receipt may acknowledge only the cells that were actually submitted. */
export function acceptFinanceSave(drafts: Map<number, FinanceDraft>, id: number, submitted: FinanceChange[], row: FinanceRow | null) {
  const draft = drafts.get(id)
  if (!draft) return
  acknowledgeDraftChanges(draft.changes, submitted, row, sameFinanceValue)
  if (row) draft.source = { ...row }
  draft.error = ''
  if (!draft.changes.size) drafts.delete(id)
}
export function parseFinancePaste(text: string) { return text.replace(/\r/g, '').replace(/\n$/, '').split('\n').map(line => line.split('\t')) }
export function financeValue(text: string, numeric: boolean): FinanceValue { const value = text.trim(); if (!value) return null; if (!numeric) return value; if (!/^\d+(?:\.\d+)?$/.test(value)) throw new Error('金额须为非负数字，未知留空'); return value }
export function previewFormula(row: FinanceRow) {
  if (row.calculationMode === 'manual') return row.budgetAmount == null || row.budgetAmount === '' || !Number.isFinite(Number(row.budgetAmount)) || Number(row.budgetAmount)<0 ? null : Number(row.budgetAmount)
  const fields = ['moldCost', 'moldWeight', 'transportRate', 'fuelRate', 'customsCost']
  if (fields.some(k => row[k] == null || row[k] === '' || !Number.isFinite(Number(row[k])) || Number(row[k]) < 0)) return null
  const round = (n: number) => Math.round((n + Number.EPSILON) * 100) / 100
  return round(Number(row.moldCost) + round(Number(row.moldWeight) * Number(row.transportRate)) + round(Number(row.moldWeight) * Number(row.fuelRate)) + Number(row.customsCost))
}
export function previewBreakEvenQuantity(row: FinanceRow) {
  const total=previewFormula(row)
  if(total==null||!Number.isFinite(total)||['salePrice','unitProductionCost'].some(k=>row[k]==null||row[k]===''||!Number.isFinite(Number(row[k]))||Number(row[k])<0))return null
  const margin=Number(row.salePrice)-Number(row.unitProductionCost)
  return margin>0?Math.ceil(total/margin):null
}
