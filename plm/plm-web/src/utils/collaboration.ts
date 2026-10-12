import dayjs from 'dayjs'
import type { CellValue, CollaborationRow, FieldGroup, PlanField, RowPatch, RowResult } from '@/types/collaboration'
import { acknowledgeDraftChanges } from './draftChanges'

export const groupNames: Record<FieldGroup, string> = { market: '市场资料', engineering: '中国工程', logistics: '物流负责人', mexico: '墨西哥负责人', production: '工厂产量' }
export const statusNames: Record<string, string> = { candidate: '市场候选', linked: '已关联项目', pending: '待开模', making: '制作中', ready: '待发模', shipped: '已发出', mexico_arrived: '抵达墨西哥', recorded: '已填写', missing: '未填写', partially_arrived:'部分到厂', awaiting_acceptance:'已到厂，待验收', partially_accepted:'部分验收', acceptance_failed:'验收不通过', delivered:'交付完成' }
export const moldStatuses = ['pending','making','ready','shipped','mexico_arrived','partially_arrived','awaiting_acceptance','partially_accepted','acceptance_failed','delivered']
export const locationNames: Record<string,string> = { unknown:'未知', china_maker:'中国制模厂', china_dispatch:'中国待发区', in_transit:'国际运输中', mexico_transit:'墨西哥待转运', mexico_factory:'墨西哥工厂', other:'其他' }
export const acceptanceNames: Record<string,string> = { pending:'待验收', passed:'验收通过', failed:'验收不通过' }
export const productionFields = ['pcTotal', 'tpuTotal', 'finishedTotal', 'productionNotes']
export function rowKey(row: CollaborationRow) { return row.moldSetId ? `mold_set:${row.moldSetId}` : `item:${row.itemId}` }
export function isCollaborationEntry(path: string) { return ['/collaboration-plans','/molds','/mold-schedules'].includes(path) }
export function equalCell(a: CellValue, b: CellValue) { return a === b || (a != null && b != null && String(a) === String(b)) }
export function suggestedArrivalDate(plannedDelivery: CellValue) { return plannedDelivery ? dayjs(String(plannedDelivery)).add(7, 'day').format('YYYY-MM-DD') : null }
export function brandFromModel(model:string) {
  return ['Apple','Samsung','Motorola','HONOR','Xiaomi','OPPO','ZTE','HUAWEI','vivo','realme','OnePlus','TECNO','Infinix','Nokia'].find(brand => new RegExp(`^${brand}(?:[\\s:/-]|$)`,'i').test(model.trim())) || null
}
export function parseCell(field: PlanField, text: string): CellValue {
  const value = text.trim()
  if (!value) { if (['required','part_status','acceptance'].includes(field.kind)) throw new Error(`${field.label}不能为空`); return null }
  if (field.kind === 'location') { const key = Object.keys(locationNames).find(k => k === value || locationNames[k] === value); if (!key) throw new Error('模具位置无效'); return key === 'unknown' ? null : key }
  if (field.kind === 'acceptance') { const key = Object.keys(acceptanceNames).find(k => k === value || acceptanceNames[k] === value) || ({'通过':'passed','不通过':'failed'} as Record<string,string>)[value]; if (!key) throw new Error('验收结果无效'); return key }
  if (field.kind === 'part_status' && !['pending','making','ready'].includes(value)) throw new Error('制作状态无效')
  if (field.kind === 'count' || field.kind === 'money' || field.kind === 'id') {
    const clean = /^\d{1,3}(,\d{3})+(\.\d{1,2})?$/.test(value) ? value.replace(/,/g, '') : value
    if (!(field.kind === 'money' ? /^\d+(\.\d{1,2})?$/ : /^\d+$/).test(clean) || !Number.isSafeInteger(Number(clean)) && field.kind !== 'money') throw new Error(`${field.label}须为${field.kind === 'money' ? '非负数字，最多两位小数' : '非负整数'}`)
    if (field.kind === 'id' && Number(clean) < 1) throw new Error('关联 ID 无效')
    return Number(clean)
  }
  if (field.kind === 'date') {
    let iso = value
    const slash = value.match(/^(\d{1,2})\/(\d{1,2})\/(\d{4})$/)
    if (slash) iso = `${slash[3]}-${slash[2].padStart(2, '0')}-${slash[1].padStart(2, '0')}`
    const yearFirst = value.match(/^(\d{4})[\/年](\d{1,2})[\/月](\d{1,2})日?$/)
    if (yearFirst) iso = `${yearFirst[1]}-${yearFirst[2].padStart(2,'0')}-${yearFirst[3].padStart(2,'0')}`
    if (!/^\d{4}-\d{2}-\d{2}$/.test(iso) || dayjs(iso).format('YYYY-MM-DD') !== iso) throw new Error(`${field.label}须为完整年月日`)
    return iso
  }
  if (field.kind === 'code' && !/^\d{4}$/.test(value)) throw new Error('手机型号编码须为四位字符串')
  if (field.kind === 'url' && value.split(/\s+/).some(link => { try { return !['http:','https:'].includes(new URL(link).protocol) } catch { return true } })) throw new Error('参考链接只支持完整 HTTP/HTTPS 地址')
  if (field.maxLength && value.length > field.maxLength) throw new Error(`${field.label}长度超出限制`)
  return value
}
/** Excel's quoted tab-separated clipboard format, including multiline cells. */
export function parseClipboard(text: string): string[][] {
  const rows: string[][] = []; let row: string[] = []; let cell = ''; let quoted = false
  for (let i = 0; i < text.length; i++) {
    const c = text[i]
    if (c === '"') { if (quoted && text[i + 1] === '"') { cell += '"'; i++ } else if (quoted || !cell) quoted = !quoted; else cell += c }
    else if (!quoted && (c === '\t' || c === '\n' || c === '\r')) { row.push(cell); cell = ''; if (c !== '\t') { rows.push(row); row = []; if (c === '\r' && text[i + 1] === '\n') i++ } }
    else cell += c
  }
  if (quoted) throw new Error('粘贴内容的引号不完整')
  if (cell || row.length) { row.push(cell); rows.push(row) }
  return rows
}
export interface DraftRow { source: CollaborationRow; changes: Map<string, { before: CellValue; after: CellValue; confirm: boolean }>; reason: string; result?: RowResult }
export function validateMoldRow(row: CollaborationRow, value: (field: string) => CellValue): string | null {
  for (const part of ['pc','tpu']) {
    const name = part.toUpperCase(), status = value(part+'AcceptanceStatus'), arrived = value(part+'FactoryArrivalDate'), accepted = value(part+'AcceptanceDate')
    if (status === 'passed' && (!arrived || !accepted)) return `${name} 验收通过须填写实际到厂日期和验收日期`
    if (arrived && accepted && String(accepted) < String(arrived)) return `${name} 验收日期不能早于实际到厂日期`
    if (status === 'failed' && !String(value(part+'AcceptanceIssues') || '').trim()) return `${name} 验收不通过须填写问题说明`
  }
  return null
}
export class CollaborationDrafts {
  rows = new Map<string, DraftRow>()
  set(row: CollaborationRow, field: string, after: CellValue, confirm = false) {
    const key = rowKey(row); let draft = this.rows.get(key)
    if (!draft) { draft = { source: { ...row }, changes: new Map(), reason: '' }; this.rows.set(key, draft) }
    const original = draft.changes.get(field)
    const before = original ? original.before : (draft.source[field] as CellValue) ?? null
    if (equalCell(before, after) && !confirm) draft.changes.delete(field)
    else draft.changes.set(field, { before, after, confirm })
    draft.result = undefined
    if (!draft.changes.size) this.rows.delete(key)
  }
  value(row: CollaborationRow, field: string): CellValue { const c = this.rows.get(rowKey(row))?.changes.get(field); return c ? c.after : (row[field] as CellValue) ?? null }
  patches(): RowPatch[] { return [...this.rows.values()].map(d => ({ entityType: d.source.moldSetId ? 'mold_set' : 'item', id: d.source.moldSetId || d.source.itemId, changes: [...d.changes].map(([field, c]) => ({ field, before: c.before, after: c.after, reason: d.reason || undefined })) })) }
  apply(result: RowResult, submitted?: RowPatch) {
    const key = `${result.entityType}:${result.id}`; const draft = this.rows.get(key); if (!draft) return
    if (result.status !== 'saved') { draft.result = result; return }
    acknowledgeDraftChanges(draft.changes, submitted?.changes, result.row as Record<string, CellValue | undefined> | null, equalCell)
    if (result.row) draft.source = { ...result.row }
    draft.result = undefined
    if (!draft.changes.size) this.rows.delete(key)
  }
  resolve(key: string, field: string, keepMine: boolean) {
    const draft = this.rows.get(key); const conflict = draft?.result?.conflicts.find(c => c.field === field)
    if (!draft || !conflict) return
    if (!keepMine) draft.changes.delete(field)
    else { const change = draft.changes.get(field); if (change) change.before = conflict.current }
    draft.source[field] = conflict.current
    draft.result!.conflicts = draft.result!.conflicts.filter(c => c.field !== field)
    if (!draft.result!.conflicts.length) draft.result = undefined
    if (!draft.changes.size) this.rows.delete(key)
  }
  clear() { this.rows.clear() }
}
