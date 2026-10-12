export const MAX_UPLOAD_FILE_SIZE_BYTES = 200 * 1024 * 1024

export const ENGINEERING_UPLOAD_ACCEPT = [
  '.pdf',
  '.doc',
  '.docx',
  '.xls',
  '.xlsx',
  '.ppt',
  '.pptx',
  '.txt',
  '.csv',
  '.jpg',
  '.jpeg',
  '.png',
  '.webp',
  '.zip',
  '.rar',
  '.7z',
  '.dwg',
  '.dxf',
  '.step',
  '.stp',
  '.igs',
  '.iges',
  '.stl',
  '.obj',
  '.3dm',
  '.prt',
  '.sldprt',
  '.sldasm'
].join(',')

export const FILE_CATEGORY_OPTIONS = [
  { label: '图纸', value: 'drawing' },
  { label: '工程文件', value: 'engineering' },
  { label: 'SOP', value: 'sop' },
  { label: 'SIP', value: 'sip' },
  { label: '测试资料', value: 'testing' },
  { label: '客户确认件', value: 'customer_confirm' },
  { label: '示例照片', value: 'sample_image' },
  { label: '其他', value: 'other' }
] as const

export function fileCategoryLabel(value: string) {
  return FILE_CATEGORY_OPTIONS.find((item) => item.value === value)?.label || value
}

export function formatFileSize(bytes: number) {
  if (!Number.isFinite(bytes) || bytes <= 0) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB']
  const unitIndex = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1)
  const value = bytes / 1024 ** unitIndex
  const precision = value >= 10 || unitIndex === 0 ? 0 : 1
  return `${Number(value.toFixed(precision))} ${units[unitIndex]}`
}

export function saveBlob(blob: Blob, fileName: string) {
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = fileName || 'download'
  document.body.appendChild(anchor)
  try {
    anchor.click()
  } finally {
    anchor.remove()
    URL.revokeObjectURL(url)
  }
}

export function openBlobPreview(blob: Blob) {
  const url = URL.createObjectURL(blob)
  const preview = window.open(url, '_blank', 'noopener,noreferrer')
  if (!preview) {
    URL.revokeObjectURL(url)
    throw new Error('浏览器阻止了预览窗口，请允许弹窗后重试')
  }
  window.setTimeout(() => URL.revokeObjectURL(url), 60_000)
}
