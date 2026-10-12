import request, { unwrapPage, unwrapResponse } from '../request'
import type { PilotRoleDefinition, PilotUser, PilotUserInput, PilotEntity, PilotTask, PilotFile } from '@/types/pilot'
import type { RowPatch, RowResult } from '@/types/collaboration'
export async function getPilotUsers(): Promise<PilotUser[]> { return unwrapResponse(await request.get('/pilot/users')) }
export async function getPilotRoles(): Promise<PilotRoleDefinition[]> { return unwrapResponse(await request.get('/pilot/roles')) }
export async function savePilotUser(id: number | null, data: PilotUserInput): Promise<{ userId: number; saved: boolean }> { return unwrapResponse(id ? await request.put(`/pilot/users/${id}`, data) : await request.post('/pilot/users', data)) }
export async function getPilotScopeOptions(type: PilotEntity, keyword = ''): Promise<{ id: number; label: string }[]> { return unwrapResponse(await request.get('/pilot/scope-options', { params: { type, keyword } })) }
export async function getPilotTasks(page = 1, keyword = '') { return unwrapPage<PilotTask>(await request.get('/pilot/tasks', { params: { page, size: 20, keyword } })) }
export async function savePilotTask(id: number, action: string, data: RowPatch): Promise<RowResult> { return unwrapResponse(await request.post(`/pilot/tasks/${id}/${action}`, data)) }
export async function getPilotTaskFiles(id: number): Promise<PilotFile[]> { return unwrapResponse(await request.get(`/pilot/tasks/${id}/files`)) }
export async function getPilotSsoStatus(): Promise<{ enabled: boolean; corpId: string; message: string }> { return unwrapResponse(await request.get('/pilot/dingtalk/status')) }
export async function downloadPilotFile(id: number, name: string) {
 const response = await request.get(`/attachments/${id}/download`, { responseType: 'blob' })
 const url = URL.createObjectURL(response.data); const link = document.createElement('a'); link.href = url; link.download = name; link.click(); URL.revokeObjectURL(url)
}
