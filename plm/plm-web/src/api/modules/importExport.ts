import request, { unwrapResponse } from '../request'

export type ImportExportObjectType = 'product' | 'inventory' | 'process' | 'attachment'

export interface ImportPreviewRowVO {
  rowNo: number
  businessKey: string
  status: 'ready' | 'error' | 'warning'
  message: string
  values: Record<string, string>
}

export interface ImportErrorVO {
  rowNo: number
  businessKey: string
  fieldName: string
  rawValue: string
  errorMessage: string
}

export interface ImportPreviewVO {
  importToken: string
  objectType: ImportExportObjectType
  fileName: string
  totalCount: number
  successCount: number
  failCount: number
  rows: ImportPreviewRowVO[]
  errors: ImportErrorVO[]
}

export interface ImportBatchVO {
  importBatchId: number
  objectType: ImportExportObjectType
  fileName: string
  totalCount: number
  successCount: number
  failCount: number
  status: string
  remark?: string | null
  createdAt: string
  createdBy: string
}

export async function downloadImportTemplate(objectType: ImportExportObjectType): Promise<Blob> {
  const response = await request.get<Blob>(`/import-export/templates/${objectType}`, { responseType: 'blob' })
  return response.data
}

export async function previewImport(objectType: ImportExportObjectType, file: File): Promise<ImportPreviewVO> {
  const formData = new FormData()
  formData.append('file', file)
  const response = await request.post(`/import-export/${objectType}/preview`, formData)
  return unwrapResponse<ImportPreviewVO>(response)
}

export async function commitImport(importToken: string): Promise<ImportPreviewVO> {
  const response = await request.post(`/import-export/${importToken}/commit`)
  return unwrapResponse<ImportPreviewVO>(response)
}

export async function getImportErrors(importToken: string): Promise<ImportErrorVO[]> {
  const response = await request.get(`/import-export/${importToken}/errors`)
  return unwrapResponse<ImportErrorVO[]>(response)
}

export async function exportMasterData(
  objectType: ImportExportObjectType,
  params: { keyword?: string; status?: string; full?: boolean } = {}
): Promise<Blob> {
  const response = await request.get<Blob>(`/import-export/${objectType}/export`, {
    params,
    responseType: 'blob'
  })
  return response.data
}

export async function getImportBatches(objectType?: ImportExportObjectType): Promise<ImportBatchVO[]> {
  const response = await request.get('/import-export/batches', {
    params: objectType ? { objectType } : undefined
  })
  return unwrapResponse<ImportBatchVO[]>(response)
}
