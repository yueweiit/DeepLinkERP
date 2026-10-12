// Existing system routes now use real APIs, not a second local fake account store.
export { getPilotUsers as getSystemUsers, getPilotRoles as getSystemRoles, savePilotUser as saveSystemUser, getPilotScopeOptions as getSystemScopeOptions } from './pilot'
import request, { unwrapPage, type PageResponse } from '../request'

export interface OperationLogQuery {
  page: number; size: number; operatorUserId?: number; action?: string
  createdFrom?: string; createdTo?: string
}
export interface OperationLogItem {
  logId: number; requestId: string | null; operatorUserId: number | null; operatorUserName: string | null
  action: string; businessType: string | null; businessId: string | null
  businessCode: string | null; businessName: string | null; result: string; createdAt: string
  detailJson?: string | null
}
export async function getOperationLogs(query: OperationLogQuery): Promise<PageResponse<OperationLogItem>> {
  return unwrapPage(await request.get('/operation-logs', { params: query }))
}
