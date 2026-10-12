import request, { unwrapPage, unwrapResponse, type PageResponse } from '../request'
export interface MoldSourceCode {
  sourceCodeId: number; sourceSystem: 'erp' | 'dingtalk'; moldCode: string; moldName: string
  itemGroup: string | null; specifications: string | null; originalAlias: string | null; disabled: boolean
  styleCode: string | null; phoneModelCode: string | null; partType: 'PC' | 'TPU' | null
  archiveCount: number; itemId: number | null; styleName: string | null; compatibleModels: string | null
  pcCount: number; tpuCount: number; nameCount: number; sourceNameCount: number; approvalInstanceId: string | null
  approvalStatus: string | null; receivedBy: string; receivedAt: string; sourceModifiedAt: string | null
}
export interface MoldSourceQuery { page: number; size: number; keyword?: string; source?: string; part?: string; review?: string }
export interface MoldSourceSummary { total: number; erp: number; dingtalk: number; nonstandard: number; paired: number; name_conflicts: number; source_conflicts: number }
export async function getMoldSourceCodes(params: MoldSourceQuery): Promise<PageResponse<MoldSourceCode>> { return unwrapPage(await request.get('/molds/source-codes', { params })) }
export async function getMoldSourceSummary(): Promise<MoldSourceSummary> { return unwrapResponse(await request.get('/molds/source-codes/summary')) }
