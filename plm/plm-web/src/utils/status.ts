import type { CommonStatus, ObjectType } from '@/types/common'

export const STATUS_LABEL_MAP: Record<ObjectType, Partial<Record<CommonStatus, string>>> = {
  customer: {
    draft: '草稿',
    active: '启用',
    inactive: '停用'
  },
  product: {
    draft: '草稿',
    developing: '开发中',
    released: '已发布',
    archived: '已归档',
    confirmed: '已确认',
    pending: '待处理',
    approved: '已通过',
    rejected: '已驳回',
    blocked: '已阻塞',
    skipped: '已跳过'
  },
  order: {
    draft: '草稿',
    confirmed: '已确认',
    in_production: '生产中',
    completed: '已完成',
    closed: '已关闭'
  },
  'production-order': {
    draft: '草稿',
    scheduled: '已排产',
    in_progress: '进行中',
    completed: '已完成',
    closed: '已关闭'
  },
  process: {
    draft: '草稿',
    confirmed: '已确认',
    locked: '已锁定',
    changed: '已变更',
    archived: '已归档',
    pending: '待确认',
    approved: '已通过',
    blocked: '已阻塞',
    skipped: '已跳过'
  },
  inventory: {
    draft: '草稿',
    available: '可用',
    reserved: '已预留',
    consumed: '已消耗',
    closed: '已关闭',
    in_use: '使用中'
  },
  workstation: {
    draft: '草稿',
    available: '可用',
    in_use: '使用中',
    maintenance: '维护中',
    inactive: '停用'
  }
}

export const STATUS_COLOR_MAP: Partial<Record<CommonStatus, string>> = {
  draft: 'info',
  active: 'success',
  inactive: 'info',
  developing: 'primary',
  released: 'success',
  archived: 'info',
  confirmed: 'primary',
  in_production: 'warning',
  completed: 'success',
  closed: 'info',
  scheduled: 'primary',
  in_progress: 'warning',
  locked: 'danger',
  changed: 'warning',
  available: 'success',
  reserved: 'warning',
  consumed: 'info',
  in_use: 'primary',
  maintenance: 'danger',
  pending: 'warning',
  approved: 'success',
  rejected: 'danger',
  blocked: 'danger',
  skipped: 'info'
}

export function getStatusLabel(status: CommonStatus, objectType: ObjectType = 'product') {
  return STATUS_LABEL_MAP[objectType][status] || status
}

export function getStatusColor(status: CommonStatus) {
  return STATUS_COLOR_MAP[status] || 'info'
}

export function getStatusActions(status: CommonStatus) {
  const map: Partial<Record<CommonStatus, string[]>> = {
    draft: ['edit', 'submit'],
    developing: ['edit'],
    released: ['archive', 'copy'],
    active: ['edit'],
    pending: ['approve', 'reject']
  }

  return map[status] || []
}
