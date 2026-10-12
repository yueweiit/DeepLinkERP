import request, { unwrapPage, unwrapResponse, type PageResponse } from '../request'
import type { CellValue, CollaborationOptions, CollaborationRow, ImportDecision, ImportPreview, PlanField, PlanHistory, RowPatch, RowResult } from '@/types/collaboration'
const root = '/collaboration-plans/schedules'
export interface ScheduleQuery { page: number; size: number; keyword?: string; productLineId?: number; moldSetId?: number; status?: string; mineOnly?: boolean; overdueOnly?: boolean }
export interface ScheduleTask { moldSetId: number; assetNumber: string; styleName: string; compatibleModels: string; taskKey: string; title: string; group: string; ownerUserId: number | null; dueDate: string | null; overdue: boolean }
export interface ScheduleRow extends CollaborationRow { planVersion: number; baseline: Record<string, CellValue> | null; baselineNeedsReview: boolean; marketEligible: boolean; scheduleStatus: string; tasks: ScheduleTask[]; suggestedDeliveryDate: string | null; suggestedFactoryDate: string | null; suggestedAcceptanceDate: string | null; suggestedProductionDate: string | null }
export interface ScheduleOptions extends CollaborationOptions { scheduleFields: PlanField[]; styleDays: Record<string, number>; transportDays: number; acceptanceDays: number; productionDays: number; remindersExternalEnabled: boolean }
export async function getSchedulePage(query: ScheduleQuery): Promise<PageResponse<ScheduleRow>> { return unwrapPage(await request.get(root, { params: query })) }
export async function getScheduleOptions(): Promise<ScheduleOptions> { return unwrapResponse(await request.get(`${root}/options`)) }
export async function getSchedule(id: number): Promise<ScheduleRow> { return unwrapResponse(await request.get(`${root}/${id}`)) }
export async function saveScheduleRows(rows: RowPatch[]): Promise<RowResult[]> { return unwrapResponse(await request.post(`${root}/batch-save`, { rows })) }
export async function confirmSchedulePlan(id: number, before: Record<string, CellValue>, reason: string): Promise<ScheduleRow> { return unwrapResponse(await request.post(`${root}/${id}/plans`, { before, reason })) }
export async function getScheduleHistory(id: number, page = 1): Promise<PageResponse<PlanHistory>> { return unwrapPage(await request.get(`${root}/${id}/history`, { params: { page, size: 20 } })) }
export async function getScheduleTasks(query: ScheduleQuery): Promise<PageResponse<ScheduleTask>> { return unwrapPage(await request.get(`${root}/tasks`, { params: query })) }
export async function enqueueScheduleReminders(): Promise<{ created: number; unassigned: number; externalSent: number; externalEnabled: boolean }> { return unwrapResponse(await request.post(`${root}/reminders/enqueue`)) }
export async function previewScheduleImport(file: File): Promise<ImportPreview> { const data = new FormData(); data.append('file', file); return unwrapResponse(await request.post(`${root}/imports/preview`, data)) }
export async function commitScheduleImport(token: string, rows: ImportDecision[]): Promise<{ saved: number; skipped: number; duplicate: boolean }> { return unwrapResponse(await request.post(`${root}/imports/${token}/commit`, { rows })) }
export async function downloadScheduleTemplate(query?: ScheduleQuery) { const result = await request.get(`${root}/template`, { params: { ...query, blank: !query }, responseType: 'blob' }); const url = URL.createObjectURL(result.data); const link = document.createElement('a'); link.href = url; link.download = '开模时间管控.xlsx'; link.click(); URL.revokeObjectURL(url) }
