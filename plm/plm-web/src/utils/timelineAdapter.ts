import type { TimelineDetailVO, TimelineNodeVO } from '@/api/modules/project'

export type TimelineVisualStatus =
  | 'confirmed'
  | 'current'
  | 'uploaded'
  | 'missing-upload'
  | 'pending'
  | 'rejected'

export interface TimelineStepView {
  nodeKey: string
  stepNo: number
  stepName: string
  stageCode?: string | null
  stageName?: string | null
  phaseName: string
  status: TimelineNodeVO['status']
  confirmed: boolean
  documentCount: number
  requiredFileCategory?: string | null
  isCurrent: boolean
  isConfirmed: boolean
  hasUploaded: boolean
  visualStatus: TimelineVisualStatus
  source: TimelineNodeVO
}

export interface TimelineStageView {
  stageCode: string
  stageName: string
  phaseName: string
  status: TimelineNodeVO['status']
  currentStepNo: number
  documentCount: number
  steps: TimelineStepView[]
}

function resolveStepVisualStatus(node: TimelineNodeVO, currentStepNo: number): TimelineVisualStatus {
  const isConfirmed = Boolean(node.confirmed) || node.stepNo < currentStepNo || node.status === 'completed'
  const hasUploaded = Number(node.documentCount || 0) > 0

  if (node.status === 'rejected') return 'rejected'
  if (node.status === 'current') return hasUploaded ? 'current' : 'missing-upload'
  if (isConfirmed) return 'confirmed'
  if (hasUploaded) return 'uploaded'
  return 'pending'
}

export function mapTimelineSteps(timeline: TimelineDetailVO | null | undefined): TimelineStepView[] {
  if (!timeline?.nodes?.length) return []
  const currentStepNo = Number(timeline.currentStepNo || 1)

  return timeline.nodes.map((node) => {
    const documentCount = Number(node.documentCount || 0)
    const isCurrent = node.status === 'current'
    const isConfirmed = Boolean(node.confirmed) || node.stepNo < currentStepNo || node.status === 'completed'

    return {
      nodeKey: node.nodeKey,
      stepNo: node.stepNo,
      stepName: node.nodeName,
      stageCode: node.stageCode,
      stageName: node.stageName,
      phaseName: node.phaseName,
      status: node.status,
      confirmed: Boolean(node.confirmed),
      documentCount,
      requiredFileCategory: node.requiredFileCategory,
      isCurrent,
      isConfirmed,
      hasUploaded: documentCount > 0,
      visualStatus: resolveStepVisualStatus(node, currentStepNo),
      source: node
    }
  })
}

export function mapTimelineStages(timeline: TimelineDetailVO | null | undefined): TimelineStageView[] {
  const steps = mapTimelineSteps(timeline)
  const groups = new Map<string, TimelineStepView[]>()

  steps.forEach((step) => {
    const key = step.stageCode || step.nodeKey
    groups.set(key, [...(groups.get(key) || []), step])
  })

  return Array.from(groups.entries()).map(([stageCode, groupSteps]) => {
    const current = groupSteps.find((step) => step.isCurrent)
    const rejected = groupSteps.some((step) => step.status === 'rejected')
    const allConfirmed = groupSteps.every((step) => step.isConfirmed)

    return {
      stageCode,
      stageName: current?.stageName || groupSteps[0]?.stageName || groupSteps[0]?.stepName || stageCode,
      phaseName: current?.phaseName || groupSteps[0]?.phaseName || '',
      status: rejected ? 'rejected' : current ? 'current' : allConfirmed ? 'completed' : 'pending',
      currentStepNo: Number(timeline?.currentStepNo || current?.stepNo || groupSteps[0]?.stepNo || 1),
      documentCount: groupSteps.reduce((sum, step) => sum + step.documentCount, 0),
      steps: groupSteps
    }
  })
}

export function findCurrentTimelineStep(timeline: TimelineDetailVO | null | undefined): TimelineStepView | null {
  return mapTimelineSteps(timeline).find((step) => step.isCurrent) || null
}
