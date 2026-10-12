package com.yuewei.plm.module.workflow.service;

import com.yuewei.plm.module.workflow.dto.WorkflowTemplateSaveDTO;
import com.yuewei.plm.module.workflow.entity.WorkflowTemplate;
import com.yuewei.plm.module.workflow.vo.WorkflowTemplateVO;
import com.yuewei.plm.repository.entity.Product;
import java.util.List;

public interface WorkflowTemplateService {

    List<WorkflowTemplateVO> list(String flowType, String status);

    WorkflowTemplateVO detail(Long workflowTemplateId);

    WorkflowTemplateVO create(WorkflowTemplateSaveDTO dto);

    WorkflowTemplateVO update(Long workflowTemplateId, WorkflowTemplateSaveDTO dto);

    WorkflowTemplateVO activate(Long workflowTemplateId);

    WorkflowTemplateVO copy(Long workflowTemplateId, String targetFlowType);

    WorkflowTemplate findActiveTemplate(String flowType);

    WorkflowTemplate findTemplateForProduct(Product product);
}
