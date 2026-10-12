import request, { unwrapPage, unwrapResponse, type PageResponse } from '../request'
import type { AssignmentSettings, CollaborationOptions, CollaborationRow, ImportDecision, ImportPreview, MoldCodeOption, PlanHistory, PlanQuery, PlanView, ProjectOption, RowPatch, RowResult } from '@/types/collaboration'
const root = '/collaboration-plans'
export async function getCollaborationPage(query: PlanQuery): Promise<PageResponse<CollaborationRow>> { return unwrapPage(await request.get(root, { params: query })) }
export async function getCollaborationOptions(): Promise<CollaborationOptions> { return unwrapResponse(await request.get(`${root}/options`)) }
export async function getCollaborationItem(id: number): Promise<CollaborationRow> { return unwrapResponse(await request.get(`${root}/items/${id}`)) }
export async function createCollaborationItem(data: { styleName: string; compatibleModels: string; productLineId: number | null; brand?: string; phoneModelCode?: string | null; notes?: string }): Promise<CollaborationRow> { return unwrapResponse(await request.post(`${root}/items`, data)) }
export async function createCollaborationMold(id: number, data: { setName?: string; pcMoldCodeId?: number | null; tpuMoldCodeId?: number | null } = {}): Promise<CollaborationRow> { return unwrapResponse(await request.post(`${root}/items/${id}/mold-sets`, data)) }
export async function saveCollaborationRows(rows: RowPatch[]): Promise<RowResult[]> { return unwrapResponse(await request.post(`${root}/batch-save`, { rows })) }
export async function getCollaborationHistory(id: number, page = 1): Promise<PageResponse<PlanHistory>> { return unwrapPage(await request.get(`${root}/items/${id}/history`, { params: { page, size: 20 } })) }
export async function getCollaborationReferences(id: number): Promise<{ item: CollaborationRow; expressRecords: { projectId: number; timelineNodeKey: string; trackingNo: string; shippedAt: string | null; latestStatusText: string | null }[] }> { return unwrapResponse(await request.get(`${root}/items/${id}/references`)) }
export async function getCollaborationProjects(productLineId?: number, keyword?: string): Promise<ProjectOption[]> { return unwrapResponse(await request.get(`${root}/project-options`, { params: { productLineId, keyword } })) }
export async function linkCollaborationProjects(id: number, projectIds: number[], confirmCompatibility = false, beforeProjectIds?: number[], append = false): Promise<CollaborationRow> { return unwrapResponse(await request.put(`${root}/items/${id}/projects`, { projectIds, confirmCompatibility, beforeProjectIds, append })) }
export async function getCollaborationMoldCodes(itemId: number): Promise<MoldCodeOption[]> { return unwrapResponse(await request.get(`${root}/mold-code-options`, { params: { itemId } })) }
export async function getCollaborationAssignments(): Promise<AssignmentSettings> { return unwrapResponse(await request.get(`${root}/assignments`)) }
export async function saveCollaborationAssignments(groups: AssignmentSettings['groups'], before: AssignmentSettings['groups']): Promise<AssignmentSettings> { return unwrapResponse(await request.put(`${root}/assignments`, { groups, before })) }
export async function previewCollaborationImport(kind: PlanView, file: File): Promise<ImportPreview> { const data = new FormData(); data.append('file', file); return unwrapResponse(await request.post(`${root}/imports/${kind}/preview`, data)) }
export async function commitCollaborationImport(token: string, rows: ImportDecision[]): Promise<{ saved: number; skipped: number; duplicate: boolean }> { return unwrapResponse(await request.post(`${root}/imports/${token}/commit`, { rows })) }
export async function downloadCollaborationTemplate(kind: PlanView, query?: PlanQuery) {
  const response = await request.get(`${root}/templates/${kind}`, { responseType: 'blob', params: { ...query, blank: !query } })
  const url = URL.createObjectURL(response.data); const link = document.createElement('a'); link.href = url; link.download = `协作计划-${kind}.xlsx`; link.click(); URL.revokeObjectURL(url)
}
