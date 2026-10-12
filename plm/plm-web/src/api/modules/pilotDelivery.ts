import request, { unwrapResponse } from '../request'
export interface Trial { trial_id: number; name: string; status: string; revision: number; platform_ids?: number[]; new_platform_id?: number | null; project_ids?: number[]; started_on?: string | null; review_on?: string | null; baseline?: Record<string, unknown> }
export interface TrialOptions { platforms: { product_id: number; product_name: string; product_code: string; status: string }[]; projects: { product_id: number; parent_product_id: number; product_name: string; model: string; status: string }[]; message: string }
export interface IntegrationConfiguration { enabled: boolean; erpConfigured: boolean; erpExpensesConfigured: boolean; dingtalkConfigured: boolean; message: string }
export interface DeliveryTask { task_id: number; kind: string; event_id: string; status: string; attempts: number; last_error: string | null; created_at: string; updated_at: string }
export async function getTrials(): Promise<Trial[]> { return unwrapResponse(await request.get('/pilot-delivery/trials')) }
export async function getTrialOptions(): Promise<TrialOptions> { return unwrapResponse(await request.get('/pilot-delivery/options')) }
export async function getTrial(id: number): Promise<Trial> { return unwrapResponse(await request.get(`/pilot-delivery/trials/${id}`)) }
export async function saveTrial(id: number | null, payload: Record<string, unknown>): Promise<Trial> { return unwrapResponse(await (id ? request.put(`/pilot-delivery/trials/${id}`, payload) : request.post('/pilot-delivery/trials', payload))) }
export async function startTrial(id: number, payload: Record<string, unknown>): Promise<Trial> { return unwrapResponse(await request.post(`/pilot-delivery/trials/${id}/start`, payload)) }
export async function reviewTrial(id: number, payload: Record<string, unknown>): Promise<Trial> { return unwrapResponse(await request.post(`/pilot-delivery/trials/${id}/review`, payload)) }
export async function getTrialMetrics(id: number): Promise<Record<string, unknown>> { return unwrapResponse(await request.get(`/pilot-delivery/trials/${id}/metrics`)) }
export async function getIntegrationConfiguration(): Promise<IntegrationConfiguration> { return unwrapResponse(await request.get('/pilot-delivery/configuration')) }
export async function getDeliveryTasks(page = 1, status?: string): Promise<{ content: DeliveryTask[]; totalElements: number }> { return unwrapResponse(await request.get('/pilot-delivery/tasks', { params: { page, size: 50, status } })) }
export async function retryDeliveryTask(id: number): Promise<void> { unwrapResponse(await request.post(`/pilot-delivery/tasks/${id}/retry`)) }
export async function exportTrial(id: number) { const response = await request.get(`/pilot-delivery/trials/${id}/export`, { responseType: 'blob' }); const url = URL.createObjectURL(response.data); const link = document.createElement('a'); link.href = url; link.download = `DeepLinkPLM试点${id}.zip`; link.click(); URL.revokeObjectURL(url) }
