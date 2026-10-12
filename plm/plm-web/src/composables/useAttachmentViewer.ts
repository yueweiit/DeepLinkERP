import { ElMessage } from 'element-plus'

import {
  downloadAttachment,
  getAttachmentPreviewMetadata,
  previewAttachment,
  type AttachmentVO
} from '@/api/modules/attachment'
import { openBlobPreview, saveBlob } from '@/utils/file'

function attachmentName(attachment: AttachmentVO) {
  return attachment.originalFileName || attachment.fileName || 'download'
}

function unsupportedMessage(attachment: AttachmentVO, message?: string | null) {
  return message || attachment.previewErrorMessage || '当前文件类型暂不支持在线预览，请下载后查看'
}

function isDirectPreviewStatus(status: string) {
  return !status || status === 'ready' || status === 'none'
}

export function useAttachmentViewer() {
  async function viewAttachment(attachment: AttachmentVO) {
    const metadata = await getAttachmentPreviewMetadata(attachment.attachmentId).catch(() => null)
    const previewable = metadata?.previewable ?? Boolean(attachment.previewable)
    const previewStatus = metadata?.previewStatus || attachment.previewStatus || ''

    if (!previewable || !isDirectPreviewStatus(previewStatus)) {
      ElMessage.warning(unsupportedMessage(attachment, metadata?.message))
      return
    }

    const blob = await previewAttachment(attachment.attachmentId)
    openBlobPreview(blob)
  }

  async function downloadFile(attachment: AttachmentVO) {
    const blob = await downloadAttachment(attachment.attachmentId)
    saveBlob(blob, attachmentName(attachment))
    ElMessage.success('文件已开始下载')
  }

  return {
    viewAttachment,
    downloadFile
  }
}
