import request, { unwrapPage, unwrapResponse, type PageResponse } from '../request'
import type { CollaborationOptions, CollaborationRow, PlanHistory, PlanQuery, RowPatch, RowResult } from '@/types/collaboration'
const root = '/molds'
export async function getMolds(query: PlanQuery): Promise<PageResponse<CollaborationRow>> { return unwrapPage(await request.get(root, { params: query })) }
export async function getMoldOptions(): Promise<CollaborationOptions> { return unwrapResponse(await request.get(`${root}/options`)) }
export async function getMold(id: number): Promise<CollaborationRow> { return unwrapResponse(await request.get(`${root}/${id}`)) }
export async function createMold(itemId: number, setName: string): Promise<CollaborationRow> { return unwrapResponse(await request.post(root, { itemId, setName })) }
export async function copyMold(id: number, setName: string): Promise<CollaborationRow> { return unwrapResponse(await request.post(`${root}/${id}/copies`, { setName })) }
export async function saveMolds(rows: RowPatch[]): Promise<RowResult[]> { return unwrapResponse(await request.post(`${root}/batch-save`, { rows })) }
export async function getMoldHistory(id: number, page = 1): Promise<PageResponse<PlanHistory>> { return unwrapPage(await request.get(`${root}/${id}/history`, { params: { page, size: 20 } })) }
export async function getMoldReferences(id: number): Promise<{ item: CollaborationRow; expressRecords: { projectId: number; trackingNo: string; shippedAt: string | null; latestStatusText: string | null }[] }> { return unwrapResponse(await request.get(`${root}/${id}/references`)) }
export interface MoldInventoryOption { inventoryId: number; inventoryCode: string; inventoryName: string; inventoryType: string; specification: string | null }
export async function getMoldInventoryOptions(keyword: string): Promise<MoldInventoryOption[]> { return unwrapResponse(await request.get(`${root}/inventory-options`, { params: { keyword } })) }
