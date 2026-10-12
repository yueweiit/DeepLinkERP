import { describe, expect, it } from 'vitest'

import {
  findCurrentTimelineStep,
  mapTimelineStages,
  mapTimelineSteps
} from '../timelineAdapter'
import type { TimelineDetailVO } from '@/api/modules/project'

function createTimeline(): TimelineDetailVO {
  return {
    projectId: 9,
    productId: 9,
    productType: 'product_line',
    started: true,
    currentNode: '测试模具',
    currentStepNo: 7,
    currentStageCode: 'PRODUCT_LINE_MOLD',
    currentStageName: '开模试模',
    currentStepCode: 'PRODUCT_LINE_MOLD_TEST',
    currentStepName: '测试模具',
    currentConfirmed: false,
    nodes: [
      {
        nodeKey: 'PRODUCT_LINE_MOLD_APPLY',
        nodeName: '申请开模',
        stageCode: 'PRODUCT_LINE_MOLD',
        stageName: '开模试模',
        phaseName: '开模试模阶段',
        stepNo: 5,
        status: 'completed',
        nodeStatus: 'completed',
        summary: '已完成',
        ownerRole: '工程',
        requiredFileCategory: null,
        documentCount: 0,
        confirmed: false
      },
      {
        nodeKey: 'PRODUCT_LINE_MOLD_MAKE',
        nodeName: '制作模具',
        stageCode: 'PRODUCT_LINE_MOLD',
        stageName: '开模试模',
        phaseName: '开模试模阶段',
        stepNo: 6,
        status: 'completed',
        nodeStatus: 'completed',
        summary: '已完成',
        ownerRole: '工程',
        requiredFileCategory: 'other',
        documentCount: 1,
        confirmed: false
      },
      {
        nodeKey: 'PRODUCT_LINE_MOLD_TEST',
        nodeName: '测试模具',
        stageCode: 'PRODUCT_LINE_MOLD',
        stageName: '开模试模',
        phaseName: '开模试模阶段',
        stepNo: 7,
        status: 'current',
        nodeStatus: 'current',
        summary: '等待测试模具资料确认',
        ownerRole: '工程 / 品质',
        requiredFileCategory: 'testing',
        documentCount: 3,
        confirmed: false
      }
    ]
  }
}

describe('timelineAdapter', () => {
  it('maps backend timeline to stable per-step visual state', () => {
    const steps = mapTimelineSteps(createTimeline())

    expect(steps.map((step) => [step.stepNo, step.visualStatus])).toEqual([
      [5, 'confirmed'],
      [6, 'confirmed'],
      [7, 'current']
    ])
    expect(steps[1]).toMatchObject({
      nodeKey: 'PRODUCT_LINE_MOLD_MAKE',
      hasUploaded: true,
      documentCount: 1,
      isConfirmed: true
    })
    expect(steps[2]).toMatchObject({
      nodeKey: 'PRODUCT_LINE_MOLD_TEST',
      isCurrent: true,
      hasUploaded: true,
      documentCount: 3
    })
  })

  it('groups steps by stage and exposes the current step', () => {
    const timeline = createTimeline()
    const stages = mapTimelineStages(timeline)
    const current = findCurrentTimelineStep(timeline)

    expect(stages).toHaveLength(1)
    expect(stages[0]).toMatchObject({
      stageCode: 'PRODUCT_LINE_MOLD',
      stageName: '开模试模',
      status: 'current',
      documentCount: 4
    })
    expect(stages[0].steps.map((step) => step.nodeKey)).toEqual([
      'PRODUCT_LINE_MOLD_APPLY',
      'PRODUCT_LINE_MOLD_MAKE',
      'PRODUCT_LINE_MOLD_TEST'
    ])
    expect(current?.nodeKey).toBe('PRODUCT_LINE_MOLD_TEST')
  })

  it('treats the last confirmed step as completed when the backend marks the timeline complete', () => {
    const timeline: TimelineDetailVO = {
      ...createTimeline(),
      timelineCompleted: true,
      currentConfirmed: true,
      currentNode: '已完结',
      currentStepNo: 7,
      currentStepCode: 'PRODUCT_LINE_MOLD_TEST',
      currentStepName: '测试模具',
      currentStageCode: 'PRODUCT_LINE_MOLD',
      currentStageName: '开模试模',
      nodes: [
        { ...createTimeline().nodes[0], status: 'completed', nodeStatus: 'completed', confirmed: false },
        { ...createTimeline().nodes[1], status: 'completed', nodeStatus: 'completed', confirmed: false },
        { ...createTimeline().nodes[2], status: 'completed', nodeStatus: 'completed', confirmed: true }
      ]
    }

    const steps = mapTimelineSteps(timeline)
    const stages = mapTimelineStages(timeline)
    const current = findCurrentTimelineStep(timeline)

    expect(steps.map((step) => [step.stepNo, step.status, step.isCurrent, step.isConfirmed])).toEqual([
      [5, 'completed', false, true],
      [6, 'completed', false, true],
      [7, 'completed', false, true]
    ])
    expect(stages[0]).toMatchObject({
      stageCode: 'PRODUCT_LINE_MOLD',
      status: 'completed'
    })
    expect(current).toBeNull()
  })
})
