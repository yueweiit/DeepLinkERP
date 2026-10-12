import request, { unwrapPage, unwrapResponse, type PageResponse } from '../request'

/* ========== 时间轴节点附件（文档 7.6） ========== */

export interface AttachmentVO {
  attachmentId: number
  ownerObjectType: string
  ownerObjectId: number
  projectId?: number | null
  projectCode?: string | null
  projectName?: string | null
  timelineNodeKey?: string | null
  timelineStageCode?: string | null
  timelineStageName?: string | null
  timelineStepCode?: string | null
  timelineStepName?: string | null
  fileCategory: string
  fileName: string
  originalFileName: string
  fileExt: string
  contentType?: string | null
  fileSize: number
  checksum: string
  storageType: string
  storageKey: string
  previewable?: boolean
  previewType?: string | null
  previewStatus?: string | null
  previewUrl?: string | null
  downloadUrl?: string | null
  previewErrorMessage?: string | null
  versionNo: string
  status: string
  remark?: string | null
  familyId?: number | null
  changeReason?: string | null
  releasedAt?: string | null
  releasedBy?: string | number | null
  releasedByUserId?: number | null
  collaborationItemId?: number | null
  moldSetId?: number | null
  derivedPdfAttachmentId?: number | null
  createdAt: string
  createdBy: string
}

export interface AttachmentPreviewVO {
  attachmentId: number
  previewable: boolean
  previewType: string
  previewStatus: string
  previewUrl: string
  downloadUrl: string
  message?: string | null
}

export interface TimelineAttachmentMetadata {
  fileCategory: string
  versionNo?: string
  remark?: string
}

export interface FileCenterQuery {
  keyword?: string
  projectId?: number
  nodeKey?: string
  fileCategory?: string
  page?: number
  size?: number
}

/** POST /api/v1/projects/{projectId}/timeline/{nodeKey}/attachments */
export function uploadTimelineAttachment(
  projectId: number,
  nodeKey: string,
  file: File,
  metadata: TimelineAttachmentMetadata
) {
  const formData = new FormData()
  formData.append('file', file)
  formData.append('fileCategory', metadata.fileCategory)
  if (metadata.versionNo) formData.append('versionNo', metadata.versionNo)
  if (metadata.remark) formData.append('remark', metadata.remark)

  return request
    .post(`/projects/${projectId}/timeline/${nodeKey}/attachments`, formData)
    .then((response) => unwrapResponse<AttachmentVO>(response))
}

/** POST /api/v1/projects/{projectId}/attachments */
export function uploadProjectAttachment(
  projectId: number,
  file: File,
  metadata: TimelineAttachmentMetadata
) {
  const formData = new FormData()
  formData.append('file', file)
  formData.append('fileCategory', metadata.fileCategory)
  if (metadata.versionNo) formData.append('versionNo', metadata.versionNo)
  if (metadata.remark) formData.append('remark', metadata.remark)

  return request
    .post(`/projects/${projectId}/attachments`, formData)
    .then((response) => unwrapResponse<AttachmentVO>(response))
}


/** POST /api/v1/products/{productId}/attachments */
export function uploadProductAttachment(
  productId: number,
  file: File,
  metadata: TimelineAttachmentMetadata
) {
  const formData = new FormData()
  formData.append('file', file)
  formData.append('fileCategory', metadata.fileCategory)
  if (metadata.versionNo) formData.append('versionNo', metadata.versionNo)
  if (metadata.remark) formData.append('remark', metadata.remark)

  return request
    .post(`/products/${productId}/attachments`, formData)
    .then((response) => unwrapResponse<AttachmentVO>(response))
}

/** GET /api/v1/products/{productId}/attachments */
export async function getProductAttachments(productId: number, fileCategory?: string): Promise<AttachmentVO[]> {
  const response = await request.get(`/products/${productId}/attachments`, {
    params: fileCategory ? { fileCategory } : undefined
  })
  return unwrapResponse<AttachmentVO[]>(response)
}
/** GET /api/v1/projects/{projectId}/timeline/{nodeKey}/attachments */
export async function getTimelineAttachments(projectId: number, nodeKey: string): Promise<AttachmentVO[]> {
  const response = await request.get(`/projects/${projectId}/timeline/${nodeKey}/attachments`)
  return unwrapResponse<AttachmentVO[]>(response)
}

/** GET /api/v1/file-center/attachments */
export async function getFileCenterAttachments(params: FileCenterQuery = {}): Promise<PageResponse<AttachmentVO>> {
  const response = await request.get('/file-center/attachments', { params })
  return unwrapPage<AttachmentVO>(response)
}

/** GET /api/v1/attachments/{attachmentId} */
export async function getAttachmentDetail(attachmentId: number): Promise<AttachmentVO> {
  const response = await request.get(`/attachments/${attachmentId}`)
  return unwrapResponse<AttachmentVO>(response)
}

/** GET /api/v1/attachments/{attachmentId}/preview/metadata */
export async function getAttachmentPreviewMetadata(attachmentId: number): Promise<AttachmentPreviewVO> {
  const response = await request.get(`/attachments/${attachmentId}/preview/metadata`)
  return unwrapResponse<AttachmentPreviewVO>(response)
}

/** GET /api/v1/attachments/{attachmentId}/preview */
export async function previewAttachment(attachmentId: number): Promise<Blob> {
  const response = await request.get<Blob>(`/attachments/${attachmentId}/preview`, { responseType: 'blob' })
  return response.data
}

/** GET /api/v1/attachments/{attachmentId}/download */
export async function downloadAttachment(attachmentId: number): Promise<Blob> {
  const response = await request.get<Blob>(`/attachments/${attachmentId}/download`, { responseType: 'blob' })
  return response.data
}

/** DELETE /api/v1/attachments/{attachmentId} */
export async function deleteAttachment(attachmentId: number) {
  const response = await request.delete(`/attachments/${attachmentId}`)
  return unwrapResponse<void>(response)
}

export interface AttachmentPublication {
  reason: string
  itemId: number | null
  moldSetId: number | null
  pdfAttachmentId: number | null
}
export async function getAttachmentVersions(id: number): Promise<AttachmentVO[]> {
  return unwrapResponse(await request.get(`/attachments/${id}/versions`))
}
export async function uploadAttachmentVersion(id: number, file: File, versionNo: string, reason: string): Promise<AttachmentVO> {
  const form = new FormData(); form.append('file', file); form.append('versionNo', versionNo); form.append('reason', reason)
  return unwrapResponse(await request.post(`/attachments/${id}/versions`, form))
}
export async function publishAttachmentVersion(id: number, payload: AttachmentPublication): Promise<AttachmentVO> {
  return unwrapResponse(await request.post(`/attachments/${id}/release`, payload))
}

