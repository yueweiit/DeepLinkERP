import type { CommonStatus, ObjectType } from '@/types/common'
import { getStatusActions, getStatusColor, getStatusLabel } from '@/utils/status'

export function useStatus(objectType: ObjectType) {
  return {
    getStatusLabel: (status: CommonStatus) => getStatusLabel(status, objectType),
    getStatusColor,
    getAllowedActions: (status: CommonStatus) => getStatusActions(status)
  }
}
