import type { ApprovalTask, WorkflowTemplate } from '@/types/common'

import request, { unwrapResponse } from '../request'

export interface ApprovalTemplateOptions {
  flowTypes: Array<{ label: string; value: WorkflowTemplate['flowType'] }>
  statuses: Array<{ label: string; value: WorkflowTemplate['status'] }>
  fileCategories: Array<{ label: string; value: string }>
}

export type WorkflowTemplateSavePayload = Omit<WorkflowTemplate, 'workflowTemplateId' | 'activeFlag' | 'updatedAt'>

export async function getApprovalTasks(): Promise<ApprovalTask[]> {
  const response = await request.get('/approval-center/tasks')
  return unwrapResponse<ApprovalTask[]>(response)
}

export async function getWorkflowTemplates(params?: {
  flowType?: WorkflowTemplate['flowType'] | ''
  status?: WorkflowTemplate['status'] | ''
}): Promise<WorkflowTemplate[]> {
  const response = await request.get('/approval-center/workflow-templates', { params })
  return unwrapResponse<WorkflowTemplate[]>(response)
}

export async function getWorkflowTemplate(workflowTemplateId: number): Promise<WorkflowTemplate> {
  const response = await request.get(`/approval-center/workflow-templates/${workflowTemplateId}`)
  return unwrapResponse<WorkflowTemplate>(response)
}

export async function createWorkflowTemplate(payload: WorkflowTemplateSavePayload): Promise<WorkflowTemplate> {
  const response = await request.post('/approval-center/workflow-templates', payload)
  return unwrapResponse<WorkflowTemplate>(response)
}

export async function updateWorkflowTemplate(
  workflowTemplateId: number,
  payload: WorkflowTemplateSavePayload
): Promise<WorkflowTemplate> {
  const response = await request.put(`/approval-center/workflow-templates/${workflowTemplateId}`, payload)
  return unwrapResponse<WorkflowTemplate>(response)
}

export async function activateWorkflowTemplate(workflowTemplateId: number): Promise<WorkflowTemplate> {
  const response = await request.post(`/approval-center/workflow-templates/${workflowTemplateId}/activate`)
  return unwrapResponse<WorkflowTemplate>(response)
}

export async function copyWorkflowTemplate(
  workflowTemplateId: number,
  targetFlowType?: WorkflowTemplate['flowType']
): Promise<WorkflowTemplate> {
  const response = await request.post(`/approval-center/workflow-templates/${workflowTemplateId}/copy`, null, {
    params: { targetFlowType }
  })
  return unwrapResponse<WorkflowTemplate>(response)
}

export async function getApprovalTemplateOptions(): Promise<ApprovalTemplateOptions> {
  const response = await request.get('/approval-center/template-options')
  return unwrapResponse<ApprovalTemplateOptions>(response)
}

export const getApprovalTemplates = getWorkflowTemplates
