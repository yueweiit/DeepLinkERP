import request, { unwrapPage, unwrapResponse, type PageResponse } from '../request'

export interface CodeItem {
  codeItemId: number
  codeType: string
  codeValue: string
  codeName: string
  codeNameZh?: string
  status: 'enabled' | 'disabled'
  sortOrder: number
  updatedAt?: string
}

export interface CodeItemQuery {
  codeType?: string
  keyword?: string
  status?: string
  page?: number
  size?: number
}

export interface CodeItemPayload {
  codeType: string
  codeValue: string
  codeName: string
  codeNameZh?: string
  sortOrder: number
}

export type PhoneModelReviewKind = 'code_many_names' | 'name_many_codes'
export interface PhoneModelReviewRow {
  key: string
  codeValues: string[]
  modelNames: string[]
  sourceCount: number
}
export async function getPhoneModelReview(params: { kind: PhoneModelReviewKind; page: number; size: number; keyword?: string }): Promise<PageResponse<PhoneModelReviewRow>> {
  return unwrapPage(await request.get('/code-items/phone-model-review', { params }))
}

export interface CodeImportRow {
  rowNo: number
  codeValue: string
  codeName: string
  codeNameZh?: string
  status: 'enabled' | 'disabled'
  sortOrder: number
  action: 'create' | 'update' | 'unchanged'
}

export interface CodeImportError {
  rowNo: number
  codeValue: string
  field: string
  reason: string
}

export interface CodeImportPreview {
  importToken: string
  createCount: number
  updateCount: number
  unchangedCount: number
  errorCount: number
  committedCount: number
  rows: CodeImportRow[]
  errors: CodeImportError[]
}

export async function getCodeItems(params: CodeItemQuery = {}): Promise<PageResponse<CodeItem>> {
  return unwrapPage<CodeItem>(await request.get('/code-items', { params }))
}

export async function getEnabledColorCodes(): Promise<CodeItem[]> {
  return (await getCodeItems({ codeType: 'color', status: 'enabled', page: 1, size: 200 })).content
}

export async function createCodeItem(payload: CodeItemPayload): Promise<CodeItem> {
  return unwrapResponse<CodeItem>(await request.post('/code-items', payload))
}

export async function updateCodeItem(id: number, payload: CodeItemPayload): Promise<CodeItem> {
  return unwrapResponse<CodeItem>(await request.put(`/code-items/${id}`, payload))
}

export async function enableCodeItem(id: number): Promise<CodeItem> {
  return unwrapResponse<CodeItem>(await request.post(`/code-items/${id}/enable`))
}

export async function disableCodeItem(id: number): Promise<CodeItem> {
  return unwrapResponse<CodeItem>(await request.post(`/code-items/${id}/disable`))
}

export async function previewCodeImport(file: File): Promise<CodeImportPreview> {
  const form = new FormData(); form.append('file', file)
  return unwrapResponse<CodeImportPreview>(await request.post('/code-items/import/preview', form))
}

export async function commitCodeImport(token: string): Promise<CodeImportPreview> {
  return unwrapResponse<CodeImportPreview>(await request.post(`/code-items/import/${token}/commit`))
}
