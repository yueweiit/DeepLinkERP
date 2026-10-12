import dayjs from 'dayjs'

export function formatDate(value: string | Date | null | undefined, pattern = 'YYYY-MM-DD') {
  if (!value) {
    return '--'
  }

  return dayjs(value).format(pattern)
}

export function formatDateTime(value: string | Date | null | undefined) {
  if (!value) {
    return '--'
  }

  return dayjs(value).format('YYYY-MM-DD HH:mm')
}

export function formatAmount(amount: number | null | undefined, currency = 'CNY') {
  if (amount == null) {
    return '--'
  }

  return new Intl.NumberFormat('zh-CN', {
    style: 'currency',
    currency,
    minimumFractionDigits: 2
  }).format(amount)
}

export function formatRate(rate: number | null | undefined) {
  if (rate == null) {
    return '--'
  }

  return `${(rate * 100).toFixed(0)}%`
}

export function formatFileSize(bytes: number) {
  if (bytes < 1024) {
    return `${bytes} B`
  }

  if (bytes < 1024 * 1024) {
    return `${(bytes / 1024).toFixed(1)} KB`
  }

  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}
